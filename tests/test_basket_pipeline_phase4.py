"""Phase 4 acceptance test — basket_pipeline adapter wiring.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 4.

Gate per the migration risk table:
  > "Per-symbol directives unchanged; basket produces expected row"
  > Mitigation: "Feature flag; default off"

This module tests the basket-side glue:
  - basket_pipeline.run_basket_pipeline() correctly parses a basket directive
  - The right RecycleRule is instantiated with directive params
  - Legs are constructed in the correct shape from directive + caller-supplied data
  - BasketRunResult renders an MPS-row-compatible dict via .to_mps_row()

Per-symbol directives remain unchanged because no existing pipeline tool
is modified by Phase 4 — basket_pipeline.py is a parallel adapter, not a
patch to stage3/portfolio_evaluator. Regression coverage for per-symbol
flow is provided by the existing test suite which we DO NOT touch.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.basket_pipeline import (
    BasketRunResult,
    _instantiate_rule,
    _legs_from_directive,
    run_basket_pipeline,
)
from tools.recycle_rules import H2CompressionRecycleRule, H2RecycleRule


REPO_ROOT = Path(__file__).resolve().parent.parent
RECYCLE_REGISTRY = REPO_ROOT / "governance" / "recycle_rules" / "registry.yaml"


# --- fixtures ------------------------------------------------------------


class _NoSignalStrategy:
    name = "phase4_nosignal"
    timeframe = "5m"

    def prepare_indicators(self, df):
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


def _h2_directive():
    return {
        "test": {"name": "90_PORT_H2_5M_RECYCLE_S01_V1_P00",
                 "strategy": "90_PORT_H2_5M_RECYCLE_S01_V1_P00"},
        "basket": {
            "basket_id": "H2",
            "legs": [
                {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
                {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
            ],
            "initial_stake_usd": 1000.0,
            "harvest_threshold_usd": 2000.0,
            "recycle_rule": {
                "name": "H2_recycle", "version": 1,
                "params": {
                    "trigger_usd": 10.0,
                    "add_lot": 0.01,
                    "starting_equity": 1000.0,
                    "harvest_target_usd": 2000.0,
                    "factor_column": "compression_5d",
                    "factor_min": 10.0,
                    "dd_freeze_frac": 0.10,
                    "margin_freeze_frac": 0.15,
                    "leverage": 1000.0,
                },
            },
            "regime_gate": {"factor": "USD_SYNTH.compression_5d",
                            "operator": ">=", "value": 10},
        },
    }


def _leg_df(seed: int, n: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-09-02", periods=n, freq="5min")
    base = 1.10 + np.cumsum(rng.normal(0.0, 0.0005, n))
    return pd.DataFrame(
        {"open": base, "high": base, "low": base, "close": base,
         "volume": 1000.0, "compression_5d": 5.0},  # gate closed
        index=idx,
    )


# --- unit: _instantiate_rule ---------------------------------------------


def test_instantiate_rule_h2_recycle():
    """H2_recycle@1 instantiates with directive params overriding registry defaults."""
    cfg = {"name": "H2_recycle", "version": 1,
           "params": {"trigger_usd": 12.5, "add_lot": 0.02,
                      "starting_equity": 750.0, "harvest_target_usd": 1500.0,
                      "factor_column": "compression_5d", "factor_min": 8.0,
                      "dd_freeze_frac": 0.08, "margin_freeze_frac": 0.12,
                      "leverage": 500.0}}
    rule = _instantiate_rule(cfg)
    assert isinstance(rule, H2RecycleRule)
    assert rule.name == "H2_recycle"
    assert rule.version == 1
    assert rule.trigger_usd == 12.5
    assert rule.add_lot == 0.02
    assert rule.starting_equity == 750.0
    assert rule.harvest_target_usd == 1500.0
    assert rule.factor_min == 8.0
    assert rule.factor_column == "compression_5d"


def test_instantiate_rule_deprecated_v7_compression_raises():
    """H2_v7_compression@1 is deprecated; instantiation must FAIL-CLOSED with a
    clear migration message."""
    cfg = {"name": "H2_v7_compression", "version": 1, "params": {}}
    with pytest.raises(NotImplementedError, match="DEPRECATED"):
        _instantiate_rule(cfg)


def test_instantiate_rule_unknown_raises():
    with pytest.raises(NotImplementedError, match="not wired yet"):
        _instantiate_rule({"name": "GBPJPY_AnotherRule", "version": 1, "params": {}})


# --- unit: _legs_from_directive ------------------------------------------


def test_legs_from_directive_shape():
    d = _h2_directive()
    leg_data = {"EURUSD": _leg_df(1), "USDJPY": _leg_df(2)}
    leg_strategies = {"EURUSD": _NoSignalStrategy(), "USDJPY": _NoSignalStrategy()}
    legs = _legs_from_directive(d, leg_data, leg_strategies)
    assert [l.symbol for l in legs] == ["EURUSD", "USDJPY"]
    assert legs[0].direction == +1   # long
    assert legs[1].direction == -1   # short
    assert legs[0].lot == 0.02
    assert legs[1].lot == 0.01


def test_legs_from_directive_missing_data_raises():
    d = _h2_directive()
    with pytest.raises(KeyError, match="missing OHLC data"):
        _legs_from_directive(d, {"EURUSD": _leg_df(1)}, {"EURUSD": _NoSignalStrategy(),
                                                          "USDJPY": _NoSignalStrategy()})


def test_legs_from_directive_missing_strategy_raises():
    d = _h2_directive()
    with pytest.raises(KeyError, match="missing strategy"):
        _legs_from_directive(d,
                             {"EURUSD": _leg_df(1), "USDJPY": _leg_df(2)},
                             {"EURUSD": _NoSignalStrategy()})


# --- end-to-end (no-signal -> no trades, but result shape verified) ------


def test_run_basket_pipeline_produces_basket_row_shape():
    d = _h2_directive()
    leg_data = {"EURUSD": _leg_df(1), "USDJPY": _leg_df(2)}
    leg_strategies = {"EURUSD": _NoSignalStrategy(), "USDJPY": _NoSignalStrategy()}
    result = run_basket_pipeline(d, leg_data, leg_strategies,
                                 recycle_registry_path=RECYCLE_REGISTRY)
    assert isinstance(result, BasketRunResult)
    assert result.basket_id == "H2"
    assert result.execution_mode == "basket"
    assert result.rule_name == "H2_recycle"
    assert result.rule_version == 1
    # No-signal strategies + flat compression_5d=5.0 -> gate closed -> no recycles.
    # Positions never open via the no-signal strategy, so per-leg trades are empty.
    assert all(t == [] for t in result.per_leg_trades.values())
    assert result.recycle_events == []
    assert result.harvested_total_usd == 0.0

    row = result.to_mps_row()
    assert row["execution_mode"] == "basket"
    assert row["basket_id"] == "H2"
    assert row["rule_name"] == "H2_recycle"
    assert row["trades_total"] == 0
    assert row["recycle_event_count"] == 0
    assert isinstance(row["basket_legs"], list) and len(row["basket_legs"]) == 2


def test_per_symbol_hot_path_untouched_post_phase5b():
    """Phase 5b update: per-symbol HOT path still unchanged.

    Phase 4 originally asserted that NO basket references existed in
    run_pipeline.py / stage3_compiler.py / portfolio_evaluator.py. Phase 5b
    deliberately threaded basket dispatch into run_pipeline.py and basket
    CSV writing into portfolio_evaluator.py — those are now legal additions
    (Phase 5b feature wiring per the locked plan).

    The structural invariant that remains: stage3_compiler.py — the
    per-symbol aggregator — must stay basket-free. Per-symbol pipeline
    stages are not changed by Phase 5b; baskets early-return BEFORE
    BootstrapController and StageRunner (see _try_basket_dispatch in
    run_pipeline.py). So stage3_compiler can never see a basket directive.

    If a future change adds basket-aware logic into stage3, that's a
    separate phase that needs its own audit; this test guards the
    boundary.
    """
    p = REPO_ROOT / "tools" / "stage3_compiler.py"
    assert p.is_file(), f"expected {p} to still exist"
    text = p.read_text(encoding="utf-8")
    assert "basket_pipeline" not in text, (
        "stage3_compiler.py must stay basket-free — baskets early-return "
        "from run_pipeline.py before any stage runs. If you need basket "
        "support in stage3, open a new phase."
    )
    assert "RecycleRule" not in text, (
        "stage3_compiler.py must stay basket-free — see comment above."
    )
