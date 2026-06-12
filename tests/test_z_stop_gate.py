"""Validation suite for the hard z-stop overlay (pine_ratio_zrev_v1_zstop, 2026-06-11).

The z-stop variant is the ZCRS champion (PineRatioZRevRuleZCross) PLUS a |z|>=z_stop
hard exit (next_open fill) and a re-entry latch (SET on the stop fill, RESET on a
zero-cross, gated in _maybe_approve). This suite is the CLEAN-TOGGLE gate the cohort run
depends on: it proves the variant differs from champion ONLY when the stop actually fires.

Harness mirrors tests/test_coint_regime_gate.py: deterministic (no RNG / wall-clock)
2-leg OHLC driven through the REAL engine path (BasketRunner.run(fast_path=False)).

Cases:
  PARITY -- z_stop beyond the data's reach (1e9) == the zcross champion, BYTE-IDENTICAL
            (recycle_events + per_bar_records), for BOTH exit_fill_timing modes. This is
            the property the experiment trusts.
  FIRES  -- z_stop inside the data's z range: >=1 LIQUIDATE_ZSTOP fires, leaves the basket
            flat, increments the counter, and the latch blocks any re-open until a
            zero-cross resets it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross
from tools.recycle_rules.pine_ratio_zrev_v1_zstop import PineRatioZRevRuleZStop
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy

SYM_A, SYM_B = "EURUSD", "GBPUSD"
N_BARS = 300
N_WINDOW = 30
Z_ENTRY = 1.0


def _ohlc(close, idx):
    close = np.asarray(close, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * 1.00008
    low = np.minimum(openp, close) * 0.99992
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close,
         "volume": 1000.0, "spread": 0.00002}, index=idx,
    )


def _synthetic_legs(n=N_BARS):
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    t = np.arange(n)
    osc = (0.60 * np.sin(2 * np.pi * t / 41)
           + 0.40 * np.sin(2 * np.pi * t / 17 + 0.7)
           + 0.25 * np.sin(2 * np.pi * t / 9 + 1.9)
           + 0.15 * np.sin(2 * np.pi * t / 5 + 0.3))
    return (_ohlc(1.1000 * (1.0 + 0.004 * osc), idx),
            _ohlc(1.2700 * (1.0 + 0.0005 * np.sin(2 * np.pi * t / 53)), idx))


def _normalize_nan(records):
    out = []
    for r in records:
        out.append({k: ("__NAN__" if isinstance(v, float) and math.isnan(v) else v)
                    for k, v in r.items()})
    return out


def _run(rule_cls, *, exit_fill_timing="next_open", **extra):
    """Fresh construction + full engine-path run. Returns (rule, legA, legB)."""
    dfA, dfB = _synthetic_legs()
    dfA, dfB = dfA.copy(), dfB.copy()
    dfA["coint_regime"] = "cointegrated"
    dfB["coint_regime"] = "cointegrated"
    shared = PineZRevArmedState()
    legA = BasketLeg(SYM_A, 0.01, +1, dfA, PineZRevLegStrategy(SYM_A, +1, armed_state=shared))
    legB = BasketLeg(SYM_B, 0.01, -1, dfB, PineZRevLegStrategy(SYM_B, -1, armed_state=shared))
    rule = rule_cls(
        n_window=N_WINDOW, z_entry=Z_ENTRY, entry_mode="absolute",
        exit_fill_timing=exit_fill_timing, shared_armed_state=shared,
        run_id="ZST", directive_id="ZST", basket_id="ZST", **extra,
    )
    BasketRunner([legA, legB], [rule],
                 warmup_bars=rule.required_warmup_bars()).run(fast_path=False)
    return rule, legA, legB


def _loc(leg, bar_ts):
    return leg.df.index.get_loc(bar_ts)


def _opens(rule, leg):
    return sorted(_loc(leg, e["bar_ts"]) for e in rule.recycle_events
                  if e.get("action") == "BASKET_OPEN")


# --------------------------------------------------------------------------- #
# PARITY: z_stop beyond reach (1e9) == the zcross champion, byte-identical.
# --------------------------------------------------------------------------- #

def _assert_parity(exit_fill_timing):
    r_z, _, _ = _run(PineRatioZRevRuleZStop, exit_fill_timing=exit_fill_timing, z_stop=1e9)
    r_c, _, _ = _run(PineRatioZRevRuleZCross, exit_fill_timing=exit_fill_timing)

    # The fixture must actually trade, else parity is vacuous.
    assert sum(1 for e in r_c.recycle_events if e["action"] == "BASKET_OPEN") >= 3
    # No z-stop ever fired and the latch never set.
    assert not any(e.get("reason") == "ZSTOP" for e in r_z.recycle_events), (
        "a z_stop beyond the data's reach must never fire")
    assert r_z._z_stop_latch is False and r_z._n_zstop_exits == 0

    assert r_z.recycle_events == r_c.recycle_events, (
        f"recycle_events diverged: z_stop=1e9 != zcross champion "
        f"(exit_fill_timing={exit_fill_timing})")
    assert _normalize_nan(r_z.per_bar_records) == _normalize_nan(r_c.per_bar_records), (
        f"per_bar_records diverged: z_stop=1e9 != zcross champion "
        f"(exit_fill_timing={exit_fill_timing})")


def test_parity_next_open():
    """exit_fill_timing='next_open' (the experiment's config): the inert z-stop is
    byte-identical to the zcross champion."""
    _assert_parity("next_open")


def test_parity_bar_close():
    """exit_fill_timing='bar_close' (the default): parity holds here too -- the z-stop
    overlay is inert regardless of fill timing when the stop never triggers."""
    _assert_parity("bar_close")


# --------------------------------------------------------------------------- #
# FIRES: z_stop inside the z range -> stop fires, flat, latch blocks re-entry.
# --------------------------------------------------------------------------- #

def test_zstop_fires_flat_and_latches():
    """Pick a z_stop the fixture's z actually reaches. Assert: >=1 LIQUIDATE_ZSTOP
    fires; each leaves the basket flat + is tagged; the counter matches; and after the
    first stop NO basket re-opens until a zero-cross resets the latch."""
    # Probe the fixture's z range to choose a reachable z_stop (> z_entry).
    _, legA, _ = _run(PineRatioZRevRuleZCross)
    z = legA.df["pine_zrev_z"].abs()
    zmax = float(z[~z.isna()].max())
    assert zmax > Z_ENTRY + 0.5, f"fixture z range too tight to exercise z_stop (zmax={zmax})"
    z_stop = round(Z_ENTRY + 0.4 * (zmax - Z_ENTRY), 3)  # strictly > z_entry, inside range

    rule, legA2, _ = _run(PineRatioZRevRuleZStop, z_stop=z_stop)
    zstop_liqs = [e for e in rule.recycle_events
                  if e.get("action") == "LIQUIDATE" and e.get("reason") == "ZSTOP"]
    assert zstop_liqs, f"expected >=1 LIQUIDATE_ZSTOP at z_stop={z_stop} (zmax={zmax})"
    assert rule._n_zstop_exits == len(zstop_liqs)

    # Each z-stop exit leaves the basket flat and carries the LIQUIDATE_ZSTOP tag.
    for e in zstop_liqs:
        loc = _loc(legA2, e["bar_ts"])
        rec = next(r for r in rule.per_bar_records if _loc(legA2, r["timestamp"]) == loc)
        assert rec["skip_reason"] == "LIQUIDATE_ZSTOP", rec["skip_reason"]
        assert rec["active_legs"] == 0, f"basket must be flat on the z-stop bar {loc}"

    # LATCH: after the first z-stop exit, no re-open until a zero-cross resets it.
    first_exit = min(_loc(legA2, e["bar_ts"]) for e in zstop_liqs)
    zcross_col = legA2.df["pine_zrev_zcross_exit"].to_numpy()
    nz = np.where(zcross_col[first_exit + 1:])[0]
    opens = _opens(rule, legA2)
    if len(nz):
        first_zcross = first_exit + 1 + int(nz[0])
        blocked = [o for o in opens if first_exit < o < first_zcross]
        assert blocked == [], (
            f"latch breached: re-open at {blocked} before the zero-cross reset "
            f"{first_zcross} (z-stop exit at {first_exit})")
    else:
        # No zero-cross after the stop -> latched for the rest of the run.
        assert [o for o in opens if o > first_exit] == [], (
            "latch breached: re-open after a z-stop with no subsequent zero-cross reset")
