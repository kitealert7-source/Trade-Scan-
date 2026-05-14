"""Phase 5b.4b acceptance test — engine-bypass fast path parity gate.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.4 (basket runner optimization).

The fast path skips per-bar `evaluate_bar` for trivial leg strategies
(ContinuousHoldStrategy with `_basket_fast_path = True`). It is only
correct under the contract documented on `BasketRunner._run_fast_path`:
the strategy signals once on bar 0, never again, and never asks the
engine to exit.

This test locks parity between the two paths against the canonical H2
basket on a real 4-week window of data:
  * Per-leg trade lists match in count, order, and meaningful fields.
  * Recycle event counts match exactly.
  * Harvest outcome (TARGET / FLOOR / BLOWN / nothing) matches.
  * Realized + harvested totals match within float epsilon.

Headline guarantee: dropping the fast path into production never changes
basket_sim parity. If this test fails, the fast path has drifted from
the engine path's behaviour and the production matrix run cannot trust
the speed-up — fix the fast path or revert.

Why the smaller window: the canonical 10-window matrix is 2y per window
(~150k bars × 2 legs); a parity test that exercises the full window
takes minutes per run. A 4-week window (~5800 bars) hits the same
recycle / harvest / freeze code paths in seconds — sufficient because
the rule is bar-state-driven, not bar-count-driven.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Tunable: a window long enough to exercise harvest/recycle paths under
# realistic compression conditions. 2024-09 → 2024-12 catches a mix of
# regimes per USD_SYNTH compression_5d in the historical record.
_WINDOW_START = "2024-09-02"
_WINDOW_END = "2024-12-30"


def _make_runner(fast_path_eligible: bool):
    """Build a BasketRunner against the H2 spec on a small real-data window.

    fast_path_eligible=True  -> ContinuousHoldStrategy on every leg
    fast_path_eligible=False -> wrap each strategy in a class that strips
                                the marker so auto-detect picks engine path
    """
    from tools.basket_data_loader import load_basket_leg_data
    from tools.basket_runner import BasketLeg, BasketRunner
    from tools.recycle_rules.h2_recycle import H2RecycleRule
    from tools.recycle_strategies import ContinuousHoldStrategy

    leg_data = load_basket_leg_data(["EURUSD", "USDJPY"], _WINDOW_START, _WINDOW_END)

    eur_strat = ContinuousHoldStrategy(symbol="EURUSD", direction=+1)
    jpy_strat = ContinuousHoldStrategy(symbol="USDJPY", direction=+1)

    if not fast_path_eligible:
        # Wrap to hide the marker without changing behaviour. Same .name,
        # same callbacks, same STRATEGY_SIGNATURE — but engine path forced.
        for s in (eur_strat, jpy_strat):
            # Detach the class-level marker by setting an instance attr to False;
            # getattr precedence picks up the instance value.
            s._basket_fast_path = False

    legs = [
        BasketLeg(
            symbol="EURUSD",
            lot=0.02,
            direction=+1,
            df=leg_data["EURUSD"].copy(),
            strategy=eur_strat,
        ),
        BasketLeg(
            symbol="USDJPY",
            lot=0.01,
            direction=+1,
            df=leg_data["USDJPY"].copy(),
            strategy=jpy_strat,
        ),
    ]

    rule = H2RecycleRule(
        trigger_usd=10.0,
        add_lot=0.01,
        starting_equity=1000.0,
        harvest_target_usd=2000.0,
        dd_freeze_frac=0.10,
        margin_freeze_frac=0.15,
        leverage=1000.0,
        factor_column="compression_5d",
        factor_min=10.0,
    )
    runner = BasketRunner(legs=legs, rules=[rule])
    return runner, rule


def _trade_signature(t: dict) -> tuple:
    """Comparable shape across both paths.

    Reads the small set of fields the rule populates on synthetic
    BASKET_RECYCLE_WINNER / BASKET_HARVEST_* trades — exit_source +
    exit_reason + entry/exit prices + pnl_usd. DATA_END trades emitted
    by `finalize_force_close` lack pnl_usd, so we tolerate a None there.
    Trade_high / trade_low / atr_entry are intentionally NOT compared:
    the engine path tracks them through pre-position high/low logic
    that does not run pre-entry on bar 0; the fast path opens at bar 1
    with both equal to entry_open. These are display-only fields the
    rule never reads.
    """
    return (
        t.get("exit_source"),
        t.get("exit_reason"),
        round(float(t.get("entry_price", 0.0) or 0.0), 6),
        round(float(t.get("exit_price", 0.0) or 0.0), 6),
        round(float(t.get("pnl_usd", 0.0) or 0.0), 2),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_continuous_hold_carries_fast_path_marker():
    """Sanity: the marker is present on the class, not just on instances."""
    from tools.recycle_strategies import ContinuousHoldStrategy
    assert getattr(ContinuousHoldStrategy, "_basket_fast_path", False) is True


def test_can_use_fast_path_detects_continuous_hold():
    """Auto-detect returns True iff every leg's strategy carries the marker."""
    runner, _ = _make_runner(fast_path_eligible=True)
    assert runner._can_use_fast_path() is True
    runner, _ = _make_runner(fast_path_eligible=False)
    assert runner._can_use_fast_path() is False


def test_run_force_fast_on_ineligible_legs_raises():
    """If the caller forces fast_path=True but a leg lacks the marker,
    fail loudly rather than silently produce divergent output."""
    runner, _ = _make_runner(fast_path_eligible=False)
    with pytest.raises(ValueError, match="_basket_fast_path = True"):
        runner.run(fast_path=True)


def test_fast_vs_engine_parity_on_h2_short_window():
    """Headline parity gate.

    Run the SAME basket spec twice — once forced to engine path, once
    forced to fast path — and assert the output matches on every
    semantically-meaningful axis.
    """
    runner_engine, rule_engine = _make_runner(fast_path_eligible=True)
    runner_fast,   rule_fast   = _make_runner(fast_path_eligible=True)

    out_engine = runner_engine.run(fast_path=False)
    out_fast   = runner_fast.run(fast_path=True)

    # Same legs returned
    assert set(out_engine.keys()) == set(out_fast.keys()) == {"EURUSD", "USDJPY"}

    # Trade lists same length per leg
    for sym in ("EURUSD", "USDJPY"):
        assert len(out_engine[sym]) == len(out_fast[sym]), (
            f"Trade-count mismatch on {sym}: engine={len(out_engine[sym])} "
            f"fast={len(out_fast[sym])}"
        )

    # Trade-by-trade signature match
    for sym in ("EURUSD", "USDJPY"):
        for idx, (te, tf) in enumerate(zip(out_engine[sym], out_fast[sym])):
            sig_e, sig_f = _trade_signature(te), _trade_signature(tf)
            assert sig_e == sig_f, (
                f"Trade signature mismatch on {sym}[{idx}]:\n"
                f"  engine: {sig_e}\n  fast:   {sig_f}\n"
                f"  engine raw: {te}\n  fast raw:   {tf}"
            )

    # Rule-level outcome matches
    assert rule_engine.harvested == rule_fast.harvested, (
        f"Harvested flag drift: engine={rule_engine.harvested} fast={rule_fast.harvested}"
    )
    assert rule_engine.exit_reason == rule_fast.exit_reason, (
        f"Exit-reason drift: engine={rule_engine.exit_reason} fast={rule_fast.exit_reason}"
    )
    assert len(rule_engine.recycle_events) == len(rule_fast.recycle_events), (
        f"Recycle-event-count drift: engine={len(rule_engine.recycle_events)} "
        f"fast={len(rule_fast.recycle_events)}"
    )
    assert abs(rule_engine.realized_total - rule_fast.realized_total) < 0.01, (
        f"Realized total drift: engine={rule_engine.realized_total} "
        f"fast={rule_fast.realized_total}"
    )
    assert abs(rule_engine.harvested_total_usd - rule_fast.harvested_total_usd) < 0.01, (
        f"Harvested total drift: engine={rule_engine.harvested_total_usd} "
        f"fast={rule_fast.harvested_total_usd}"
    )


def test_auto_detect_picks_fast_path_for_h2_basket():
    """The production caller (tools/basket_pipeline.py) calls runner.run()
    with no arguments. With the marker on ContinuousHoldStrategy, that
    must auto-select the fast path — otherwise the production speedup
    isn't actually engaged.

    We verify by patching the fast-path entrypoint to record a flag and
    checking it fires.
    """
    runner, _ = _make_runner(fast_path_eligible=True)
    seen = {"fast": 0, "engine": 0}
    orig_fast = runner._run_fast_path
    orig_engine = runner._run_engine_path

    def _wrapped_fast():
        seen["fast"] += 1
        return orig_fast()

    def _wrapped_engine():
        seen["engine"] += 1
        return orig_engine()

    runner._run_fast_path = _wrapped_fast      # type: ignore[method-assign]
    runner._run_engine_path = _wrapped_engine  # type: ignore[method-assign]
    runner.run()  # no args -> auto-detect

    assert seen["fast"] == 1 and seen["engine"] == 0, (
        f"Auto-detect did not select fast path for H2 basket; saw {seen!r}"
    )
