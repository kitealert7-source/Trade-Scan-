"""Regression — `tools/utils/research/simulators._simulate` must not crash
when a trade has identical entry_timestamp and exit_timestamp.

Background
----------
The function sorts events with key `(time, 0 if exit else 1)`. The
tiebreaker is correct for the cross-trade case (a trade A exiting at
time T must commit its PnL into equity BEFORE trade B's entry at the
same T, so B's entry_equity reflects A's PnL).

It is wrong for the intra-trade case: if a single trade has
`entry_timestamp == exit_timestamp` (intra-bar fill — happens
legitimately on 30M/4H/1D bars and any future tick-fill case), the
exit event sorts BEFORE its own entry event. The dict
`trade_entry_eq[idx]` is empty at that point and the lookup raised
KeyError, aborting the entire simulation.

Production blast radius
-----------------------
`simulate_percent_path` is reached transitively from
`tools.utils.research.robustness.early_late_split`, which is imported
by `tools/family_report.py`. The KeyError took down the entire
family report for any family containing an intra-bar trade.
Today's family stress test (2026-05-12) found two such families:
`28_PA_XAUUSD_30M_ENGULF` and `53_MR_FX_4H_CMR`.

Fix
---
Defensive dict lookup: `trade_entry_eq.get(idx, equity)`. When the
entry has not been recorded yet, fall back to current equity — which
is mathematically the entry equity for an intra-bar trade because
zero time has passed between the would-be entry and the exit.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tools.utils.research.simulators import (
    _simulate,
    _trade_pcts,
    simulate_percent_path,
)


def _build_trades(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal trade DataFrame with the columns _simulate expects."""
    df = pd.DataFrame(rows)
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"])
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"])
    return df


# ---------------------------------------------------------------------------
# 1. Intra-bar trade — the bug
# ---------------------------------------------------------------------------

def test_simulate_does_not_crash_on_intra_bar_trade():
    """A trade with entry_timestamp == exit_timestamp must not raise
    KeyError. Crash predecessor: `28_PA_XAUUSD_30M_ENGULF` trade #309
    on 2026-03-31 23:30:00.
    """
    trades = _build_trades([
        {"entry_timestamp": "2026-01-01 09:00", "exit_timestamp": "2026-01-01 10:00", "pnl_usd": 50.0},
        # The intra-bar trade — entry and exit collide.
        {"entry_timestamp": "2026-01-02 23:30", "exit_timestamp": "2026-01-02 23:30", "pnl_usd": 10.0},
        {"entry_timestamp": "2026-01-03 09:00", "exit_timestamp": "2026-01-03 10:00", "pnl_usd": -20.0},
    ])
    # Must not raise.
    pcts = _trade_pcts(trades, start_cap=10_000.0)
    result = _simulate(trades, pcts, 10_000.0)
    assert "final_equity" in result
    assert result["final_equity"] > 0  # sanity


def test_simulate_intra_bar_pnl_applied_correctly():
    """The intra-bar fallback uses current equity as entry equity. With
    one trade, entry_eq = start_cap; final_equity = start_cap + PnL.
    """
    trades = _build_trades([
        {"entry_timestamp": "2026-01-01 12:00", "exit_timestamp": "2026-01-01 12:00", "pnl_usd": 100.0},
    ])
    pcts = _trade_pcts(trades, start_cap=10_000.0)
    res = _simulate(trades, pcts, 10_000.0)
    # entry_eq fallback = 10_000; pcts[0] = 100/10_000 = 0.01;
    # final = 10_000 + 10_000 * 0.01 = 10_100.
    assert res["final_equity"] == pytest.approx(10_100.0, abs=0.5)


def test_simulate_cross_trade_ordering_still_correct():
    """The fix must NOT change the cross-trade ordering: if trade A
    exits at time T and trade B enters at the same time T, A's PnL
    must flow into B's entry equity (exits-before-entries at equal
    time still holds).
    """
    trades = _build_trades([
        # Trade A: enters 09:00, exits 10:00 with +100 PnL.
        {"entry_timestamp": "2026-01-01 09:00", "exit_timestamp": "2026-01-01 10:00", "pnl_usd": 100.0},
        # Trade B: enters 10:00 (same time as A's exit), exits 11:00.
        {"entry_timestamp": "2026-01-01 10:00", "exit_timestamp": "2026-01-01 11:00", "pnl_usd": 50.0},
    ])
    pcts = _trade_pcts(trades, start_cap=10_000.0)
    res = _simulate(trades, pcts, 10_000.0)
    # A: entry_eq=10_000, pct=100/10_000=0.01, exit grows equity to 10_100.
    # B: at time T=10:00, A's exit fires first (existing rule), so B's
    # entry_eq=10_100. pct=50/10_100~=0.00495, exit grows equity to
    # 10_100 + 10_100*0.00495 = 10_150.
    assert res["final_equity"] == pytest.approx(10_150.0, abs=0.5)


def test_simulate_multiple_intra_bar_trades():
    """Three trades, all intra-bar — each chained correctly. Pin the
    multi-occurrence case so a future refactor doesn't accidentally
    only handle the first one.

    Math note: trades with constant absolute PnL ($100 each) are
    additive, not compound. The percent-path representation scales
    PnL by entry_eq then unscales on the exit, so the simulator
    reproduces the absolute PnL. Three trades × $100 = +$300.
    """
    trades = _build_trades([
        {"entry_timestamp": "2026-01-01 09:00", "exit_timestamp": "2026-01-01 09:00", "pnl_usd": 100.0},
        {"entry_timestamp": "2026-01-02 09:00", "exit_timestamp": "2026-01-02 09:00", "pnl_usd": 100.0},
        {"entry_timestamp": "2026-01-03 09:00", "exit_timestamp": "2026-01-03 09:00", "pnl_usd": 100.0},
    ])
    pcts = _trade_pcts(trades, start_cap=10_000.0)
    res = _simulate(trades, pcts, 10_000.0)
    assert res["final_equity"] == pytest.approx(10_300.0, abs=0.5)


def test_simulate_intra_bar_compound_returns():
    """Three intra-bar trades with constant *percent* returns (each
    +1% of entry equity) — confirm the simulator does compound the
    growth correctly when the underlying signal is percent-based.
    Distinguished from the additive-absolute test above.
    """
    # PnL = 1% of entry equity. Trade 1 enters at 10_000 → PnL=100.
    # Trade 2 enters at 10_100 → PnL=101. Trade 3 enters at 10_201 → PnL=102.01.
    # Final: 10_303.01.
    trades = _build_trades([
        {"entry_timestamp": "2026-01-01 09:00", "exit_timestamp": "2026-01-01 09:00", "pnl_usd": 100.0},
        {"entry_timestamp": "2026-01-02 09:00", "exit_timestamp": "2026-01-02 09:00", "pnl_usd": 101.0},
        {"entry_timestamp": "2026-01-03 09:00", "exit_timestamp": "2026-01-03 09:00", "pnl_usd": 102.01},
    ])
    pcts = _trade_pcts(trades, start_cap=10_000.0)
    res = _simulate(trades, pcts, 10_000.0)
    assert res["final_equity"] == pytest.approx(10_303.01, abs=0.5)


# ---------------------------------------------------------------------------
# 2. Real-data regression — the two families that crashed today
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_path", [
    pytest.param(
        "../TradeScan_State/backtests/28_PA_XAUUSD_30M_ENGULF_S02_V1_P00_XAUUSD/raw/results_tradelevel.csv",
        id="28_PA_XAUUSD_30M_ENGULF_S02_V1_P00",
    ),
    pytest.param(
        "../TradeScan_State/backtests/53_MR_FX_4H_CMR_S01_V1_P00_AUDJPY/raw/results_tradelevel.csv",
        id="53_MR_FX_4H_CMR_S01_V1_P00",
    ),
])
def test_real_failing_data_now_simulates(fixture_path):
    """Run simulate_percent_path on the actual trade logs that crashed
    the family stress test. Both must now complete without KeyError.
    Skips if the backtest data is not present (e.g., in a fresh
    checkout) — the unit tests above cover the contract.
    """
    from pathlib import Path
    p = Path(fixture_path)
    if not p.exists():
        pytest.skip(f"Backtest fixture not present at {fixture_path}")
    df = pd.read_csv(p)
    # Must not raise.
    res = simulate_percent_path(df, 10_000.0)
    assert res["final_equity"] > 0
    assert "cagr" in res
    assert "max_dd_pct" in res
