"""Regression suite for PineRatioZRevRuleZCross.exit_fill_timing (2026-06-10).

Closes a doctrine gap: the opt-in `exit_fill_timing` param shipped without
tests. The param controls WHEN the zero-cross EQUILIBRIUM exit fills:

  "bar_close" (DEFAULT) -- legacy / current. The zcross is DETECTED on bar M's
      close (sign(z[M]) != sign(z[M-1])) and ALSO FILLS on bar M's close. This
      is a same-bar detect+fill lookahead (unattainable live), kept as the
      default for byte-parity with the pre-2026-06-10 corpus.

  "next_open" -- realistic / no-lookahead. The zcross detected on bar M sets a
      pending-exit and KEEPS holding; the liquidation fills at bar M+1's OPEN
      (symmetric with the entry's next-bar-open fill). At end-of-data (no bar
      M+1) it force-closes at the last bar's CLOSE so the basket cannot hang.

Harness mirrors tests/test_basket_runner_streaming_parity.py: deterministic
(no RNG / wall-clock) 2-leg OHLC driven through the REAL engine path
(BasketRunner.run(fast_path=False)) so entries fill next-bar-open exactly as
in research/live. The only deviation from that helper is a GAPPED open
(open[t] != close[t-1]) so that the next_open assertion "exit_price == bar
M+1's OPEN and != bar M's close and != bar M+1's close" is discriminating
rather than vacuous (the streaming-parity helper builds open[t] == close[t-1],
which would make open[M+1] == close[M] by construction and mask a lookahead).

Cases:
  1. test_default_equals_bar_close_parity         -- UNSET == explicit bar_close
  2. test_bar_close_exits_same_bar                -- bar_close fills at M close
  3. test_next_open_exits_one_bar_later_at_open   -- next_open fills at M+1 open
  4. test_next_open_eof_force_close               -- terminal-bar zcross EOF close
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0
WARMUP = 2 * N_WINDOW
# +3bp open gap: distinct from BOTH the prior bar's close and this bar's close,
# so the next_open fill price is provably bar M+1's own OPEN (not a same-bar
# close lookahead and not the prior close).
_OPEN_GAP = 0.0003


def _ohlc_gapped(close, idx):
    """Deterministic OHLC with a GAPPED open. open[t] = close[t] * (1 + gap)
    (bar 0 excepted), so open[t] differs from both close[t-1] and close[t].
    This is the single deviation from the streaming-parity helper -- it makes
    the next_open exit-price assertion discriminating (a same-bar close fill
    would land on close[M] != open[M+1], and is thus detectable)."""
    close = np.asarray(close, dtype=float)
    openp = close * (1.0 + _OPEN_GAP)
    openp[0] = close[0]
    high = np.maximum(openp, close) * 1.00050
    low = np.minimum(openp, close) * 0.99950
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close,
         "volume": 1000.0, "spread": 0.00002}, index=idx,
    )


def _synthetic_legs(n: int = N_BARS):
    """Deterministic 2-leg OHLC whose A/B ratio mean-reverts with enough
    amplitude to drive several z-cross cycles (entry at |z|>=z_entry, exit at
    the next zero-cross). Same oscillator as the streaming-parity helper, with
    the gapped-open OHLC builder."""
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    t = np.arange(n)
    osc = (0.60 * np.sin(2 * np.pi * t / 41)
           + 0.40 * np.sin(2 * np.pi * t / 17 + 0.7)
           + 0.25 * np.sin(2 * np.pi * t / 9 + 1.9)
           + 0.15 * np.sin(2 * np.pi * t / 5 + 0.3))
    return (_ohlc_gapped(1.1000 * (1.0 + 0.004 * osc), idx),
            _ohlc_gapped(1.2700 * (1.0 + 0.0005 * np.sin(2 * np.pi * t / 53)), idx))


def _run(exit_fill_timing=None, n: int = N_BARS):
    """Fresh construction + full engine-path run. Returns (rule, legA, legB).

    `exit_fill_timing=None` leaves the param UNSET (exercises the dataclass
    default) -- distinct from passing the explicit string, which is the point
    of the parity test."""
    dfA, dfB = _synthetic_legs(n)
    shared = PineZRevArmedState()
    legA = BasketLeg(SYM_A, 0.01, +1, dfA.copy(),
                     PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    legB = BasketLeg(SYM_B, 0.01, -1, dfB.copy(),
                     PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    kwargs = dict(
        n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute",
        shared_armed_state=shared, run_id="EFT", directive_id="EFT", basket_id="EFT",
    )
    if exit_fill_timing is not None:
        kwargs["exit_fill_timing"] = exit_fill_timing
    rule = PineRatioZRevRuleZCross(**kwargs)
    BasketRunner([legA, legB], [rule],
                 warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    return rule, legA, legB


def _equilibrium_exits(rule):
    """LIQUIDATE events tagged EQUILIBRIUM (the zero-cross exit), in order."""
    return [e for e in rule.recycle_events
            if e.get("action") == "LIQUIDATE" and e.get("reason") == "EQUILIBRIUM"]


def _exit_loc(rule, leg, event) -> int:
    """Aligned-bar integer location of an exit event's bar_ts."""
    return leg.df.index.get_loc(event["bar_ts"])


def _normalize_nan(records):
    """Replace NaN floats with a sentinel so dict == dict is well-defined.
    Per-bar records carry NaN fields (gate_factor_value, margin_level_pct when
    flat); raw == fails on identical structures because nan != nan. Every other
    field is compared verbatim, so this only neutralizes the NaN pathology --
    it does not loosen the parity assertion."""
    out = []
    for r in records:
        d = {}
        for k, v in r.items():
            d[k] = "__NAN__" if isinstance(v, float) and math.isnan(v) else v
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# Guard the guard: the fixture must actually exercise equilibrium exits, else
# the parity / timing assertions below would pass vacuously.
# --------------------------------------------------------------------------- #

def test_fixture_exercises_equilibrium_exits():
    rule, legA, _ = _run("bar_close")
    eq = _equilibrium_exits(rule)
    opens = sum(1 for e in rule.recycle_events if e.get("action") == "BASKET_OPEN")
    assert opens >= 3 and len(eq) >= 2, (
        f"fixture must drive several zcross cycles; got {opens} opens, {len(eq)} "
        f"equilibrium exits"
    )
    # And the zcross flag is genuinely True on each bar_close exit bar M.
    zc = legA.df["pine_zrev_zcross_exit"]
    assert all(bool(zc.iloc[_exit_loc(rule, legA, e)]) for e in eq), (
        "every bar_close EQUILIBRIUM exit must coincide with a zcross-flag bar"
    )


# --------------------------------------------------------------------------- #
# 1. Default (UNSET) == explicit "bar_close": byte-identical events + records.
# --------------------------------------------------------------------------- #

def test_default_equals_bar_close_parity():
    """exit_fill_timing UNSET must be byte-identical to explicit "bar_close"
    for BOTH recycle_events and per_bar_records on a basket that produces >=1
    EQUILIBRIUM exit. This pins the parity gate: the pending-exit branch is
    never entered in bar_close mode, so the default path is unchanged from the
    pre-2026-06-10 corpus."""
    r_default, _, _ = _run(exit_fill_timing=None)            # dataclass default
    r_explicit, _, _ = _run(exit_fill_timing="bar_close")    # explicit string

    assert r_default.exit_fill_timing == "bar_close", "default must be bar_close"
    assert len(_equilibrium_exits(r_default)) >= 1, "parity gate needs an EQ exit"

    # recycle_events: no NaN fields -> direct equality.
    assert r_default.recycle_events == r_explicit.recycle_events, (
        "recycle_events diverged between UNSET and explicit bar_close"
    )
    # per_bar_records: NaN-normalized equality (raw == fails only on nan != nan).
    assert _normalize_nan(r_default.per_bar_records) == _normalize_nan(r_explicit.per_bar_records), (
        "per_bar_records diverged between UNSET and explicit bar_close"
    )


# --------------------------------------------------------------------------- #
# 2. bar_close: EQUILIBRIUM exit fills on the zcross detection bar M's CLOSE.
# --------------------------------------------------------------------------- #

def test_bar_close_exits_same_bar():
    """Under "bar_close": for an EQUILIBRIUM exit, exit_index == the zcross
    detection bar M (zcross flag True at M) and exit_price == bar M's CLOSE for
    every leg. This is the legacy same-bar detect+fill the next_open mode
    removes."""
    rule, legA, legB = _run("bar_close")
    eq = _equilibrium_exits(rule)
    assert eq, "need at least one EQUILIBRIUM exit"

    for leg in (legA, legB):
        zc = leg.df["pine_zrev_zcross_exit"]
        for e in eq:
            M = _exit_loc(rule, leg, e)
            assert bool(zc.iloc[M]), (
                f"bar_close exit at loc {M} is not a zcross detection bar"
            )
            # Event fill mark == bar M close.
            assert e["exit_prices"][leg.symbol] == float(leg.df.iloc[M]["close"]), (
                f"{leg.symbol}: bar_close exit_price must be bar M's close"
            )

    # Per-leg trade record: exit_index == M, exit_price == M close.
    for leg in (legA, legB):
        eq_trades = [t for t in leg.trades
                     if str(t.get("exit_source", "")).startswith("PINE_ZREV_EQUILIBRIUM")]
        assert eq_trades, f"{leg.symbol}: expected EQUILIBRIUM trades"
        for t in eq_trades:
            M = t["exit_index"]
            assert t["exit_price"] == float(leg.df.iloc[M]["close"]), (
                f"{leg.symbol}: trade exit_price must be the M-close at exit_index"
            )


# --------------------------------------------------------------------------- #
# 3. next_open: EQUILIBRIUM exit defers one bar and fills at bar M+1's OPEN.
#    THE CORE NO-LOOKAHEAD ASSERTION.
# --------------------------------------------------------------------------- #

def test_next_open_exits_one_bar_later_at_open():
    """Under "next_open": the FIRST EQUILIBRIUM exit is deferred one aligned
    bar relative to bar_close -- it fills at bar M+1's OPEN, not bar M's close.

    We anchor on the FIRST exit because both modes share byte-identical history
    up to and including bar M (no earlier deferral has perturbed the
    trajectory): bar_close exits at M, next_open exits at M+1. Specifically:

      * exit_index == M + 1 (one aligned bar after the zcross detection bar M)
      * exit_price == bar M+1's OPEN for every leg
      * exit_price != bar M's CLOSE  (no same-bar lookahead)
      * exit_price != bar M+1's CLOSE (it is the open, not the close)
      * on bar M the basket is still OPEN / HOLDING (no same-bar fill)
    """
    r_bc, legA_bc, _ = _run("bar_close")
    r_no, legA_no, legB_no = _run("next_open")

    eq_bc = _equilibrium_exits(r_bc)
    eq_no = _equilibrium_exits(r_no)
    assert eq_bc and eq_no, "both modes must produce at least one EQUILIBRIUM exit"

    # bar_close fills on the zcross detection bar M (shared first cycle).
    M = _exit_loc(r_bc, legA_bc, eq_bc[0])
    # next_open fills one aligned bar later, at M+1.
    Mp1 = _exit_loc(r_no, legA_no, eq_no[0])
    assert Mp1 == M + 1, (
        f"next_open first EQUILIBRIUM exit must be one bar after bar_close: "
        f"bar_close M={M}, next_open M+1={Mp1}"
    )

    idx = legA_no.df.index
    assert idx[Mp1] == eq_no[0]["bar_ts"], "exit bar_ts must be the M+1 aligned bar"

    for leg in (legA_no, legB_no):
        open_mp1 = float(leg.df.iloc[Mp1]["open"])
        close_mp1 = float(leg.df.iloc[Mp1]["close"])
        close_m = float(leg.df.iloc[M]["close"])
        fill = eq_no[0]["exit_prices"][leg.symbol]
        assert fill == open_mp1, (
            f"{leg.symbol}: next_open exit must fill at bar M+1's OPEN "
            f"({open_mp1}), got {fill}"
        )
        assert fill != close_m, (
            f"{leg.symbol}: next_open exit must NOT fill at bar M's close "
            f"(same-bar lookahead) -- {fill} == {close_m}"
        )
        assert fill != close_mp1, (
            f"{leg.symbol}: next_open exit fills at M+1's OPEN, not its close "
            f"-- {fill} == {close_mp1}"
        )
        # Per-leg trade record agrees: exit_index == M+1, exit_price == M+1 open.
        eq_trade = next(t for t in leg.trades
                        if str(t.get("exit_source", "")).startswith("PINE_ZREV_EQUILIBRIUM"))
        assert eq_trade["exit_index"] == Mp1
        assert eq_trade["exit_price"] == open_mp1

    # The event carries the next_open provenance tag.
    assert eq_no[0].get("exit_fill_timing") == "next_open"

    # On bar M the basket is still OPEN (no same-bar fill): the per-bar record
    # at M is HOLDING with both legs active; the fill lands on M+1.
    recs = {r["bar_index"]: r for r in r_no.per_bar_records}
    assert recs[M]["skip_reason"] == "HOLDING", (
        f"next_open must keep holding on bar M; skip_reason={recs[M]['skip_reason']}"
    )
    assert recs[M]["active_legs"] == 2, "both legs must still be open on bar M"
    assert recs[Mp1]["skip_reason"] == "EQUILIBRIUM_EXIT_BAR"
    assert recs[Mp1]["active_legs"] == 0, "basket flat on the M+1 fill bar"


# --------------------------------------------------------------------------- #
# 4. next_open EOF: a zcross on the LAST bar still force-closes (no hang).
# --------------------------------------------------------------------------- #

def test_next_open_eof_force_close():
    """A zero-cross detected on the TERMINAL bar under "next_open" has no bar
    M+1 to defer to. The EOF force-finalize must still liquidate (no hang, no
    dropped exit) -- at that terminal bar's CLOSE, tagged
    "next_open_eof_close".

    We construct the EOF deterministically: find the first bar_close
    EQUILIBRIUM exit bar M on the full feed (shared history), then truncate the
    feed to n = M+1 so bar M is the last aligned bar. Under next_open there is
    no M+1, so the pending exit must force-close at M."""
    r_full, legA_full, _ = _run("bar_close")
    eq_full = _equilibrium_exits(r_full)
    assert eq_full, "need a bar_close EQUILIBRIUM exit to locate a zcross bar"
    M = _exit_loc(r_full, legA_full, eq_full[0])

    n_trunc = M + 1                       # bar M becomes the terminal aligned bar
    assert n_trunc > WARMUP + 3, "truncated feed must clear warmup + entry"

    r_eof, legA, legB = _run("next_open", n=n_trunc)
    eq_eof = _equilibrium_exits(r_eof)

    assert len(eq_eof) == 1, (
        f"terminal-bar zcross must produce exactly one (force-closed) "
        f"EQUILIBRIUM exit, got {len(eq_eof)}"
    )
    last_loc = len(legA.df.index) - 1
    exit_loc = _exit_loc(r_eof, legA, eq_eof[0])
    assert exit_loc == M == last_loc, (
        f"EOF force-close must land on the terminal bar M={M} "
        f"(last={last_loc}, exit={exit_loc})"
    )
    # No hang: basket is flat at the end of the run.
    assert r_eof._basket_open is False, "basket must not hang open past the data"
    # EOF semantics: fill at the terminal bar's CLOSE, tagged next_open_eof_close.
    assert eq_eof[0].get("exit_fill_timing") == "next_open_eof_close"
    for leg in (legA, legB):
        assert eq_eof[0]["exit_prices"][leg.symbol] == float(leg.df.iloc[M]["close"]), (
            f"{leg.symbol}: EOF force-close must fill at the terminal bar's close"
        )
