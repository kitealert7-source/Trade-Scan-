"""Phase A regression — verdict_risk section + per-section deletions/suppressions.

Pins the eight behavioral changes from the Phase A reporting upgrade:
  1. Verdict block renders at top of REPORT_*.md (after header, before key metrics).
  2. Risk flags surface tail / direction / body-deficit / flat-period.
  3. Parent Δ resolves when a parent pass exists in Master Filter.
  4. §4.3 standalone Volatility Edge + Trend Edge tables are gone.
  5. §4.2 Yearwise table carries dominance / partial / negative flags.
  6. §4.1 fill-age section is suppressed when bucket distribution matches regime-age.
  7. §4.1 exec-delta section is suppressed when ≥95% of trades land in one bucket.
  8. §4.8 K-Ratio is no longer in markdown Portfolio Key Metrics.

All tests run against the actual current PSBRK V4 P14 backtest output to keep the
verification close to production data. Hermetic unit tests for the suppression
predicates and verdict logic are below the integration test.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.report.report_sections.verdict_risk import (
    _build_verdict_risk_section,
    _compute_risk_flags,
    _compute_verdict,
    _tail_flag,
    _body_deficit_flag,
    _direction_imbalance_flag,
    _flat_period_flag,
    _loss_streak_flag,
    _wasted_edge_flag,
    _stall_decay_flag,
    _windows_compatible,
    _core_gates_missing,
    _fail_gates_violated,
    _verdict_rationale,
)
from tools.report.report_sections.session import (
    _bucket_distribution_matches,
    _exec_delta_single_bucket_dominates,
    _build_fill_age_section,
    _build_exec_delta_section,
)
from tools.report.report_sections.summary import _build_yearwise_section


# ---------------------------------------------------------------------------
# Helpers — synthetic payloads (no fixtures on disk required)
# ---------------------------------------------------------------------------

class _FakePL:
    """Stand-in for SymbolPayloads carrying just what verdict_risk reads."""
    def __init__(self, **kw):
        self.portfolio_pnl = kw.get("portfolio_pnl", 1000.0)
        self.portfolio_trades = kw.get("portfolio_trades", 100)
        self.symbols_data = kw.get("symbols_data", [{"Symbol": "XAUUSD"}])
        self.start_date = kw.get("start_date", "2024-05-11")
        self.end_date = kw.get("end_date", "2026-05-11")
        self.all_trades_dfs = kw.get("all_trades_dfs", [])


# ---------------------------------------------------------------------------
# 1. Verdict block placement + structure
# ---------------------------------------------------------------------------

def test_verdict_block_renders_with_required_keys():
    pl = _FakePL(portfolio_pnl=2830.45, portfolio_trades=1078)
    totals = {"max_dd_pct": 0.40, "ret_dd": 7.07, "sharpe": 1.39, "sqn": 2.87,
              "port_pf": 1.35, "k_ratio": 0.10}
    md = _build_verdict_risk_section("65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14", pl, totals)
    text = "\n".join(md)
    assert "## Verdict & Risk" in text
    assert "**Verdict:**" in text
    assert "**Risk flags:**" in text
    assert "**Δ vs parent" in text or "Δ vs parent:" in text


def test_verdict_status_is_one_of_known_values():
    pl = _FakePL(portfolio_pnl=2830.45, portfolio_trades=1078)
    totals = {"max_dd_pct": 0.40, "ret_dd": 7.07, "sharpe": 1.39, "sqn": 2.87,
              "port_pf": 1.35, "k_ratio": 0.10}
    v = _compute_verdict("65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14", pl, totals)
    assert v["status"] in {"CORE", "WATCH", "RESERVE", "FAIL", "LIVE", "UNKNOWN"}


# ---------------------------------------------------------------------------
# 2. Risk flag thresholds
# ---------------------------------------------------------------------------

def test_tail_flag_fires_when_top5_over_70pct():
    # 5 huge winners + 95 small losers → top-5 share dominates
    df = pd.DataFrame({
        "pnl_usd": [1000.0] * 5 + [-1.0] * 95,
        "direction": [1] * 100,
        "exit_timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
    })
    flags = _tail_flag(df)
    assert flags, "tail flag should fire when top-5 share is huge"
    assert "Tail concentration" in flags[0]


def test_tail_flag_silent_when_balanced():
    df = pd.DataFrame({
        "pnl_usd": [10.0] * 100,
        "direction": [1] * 100,
        "exit_timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
    })
    assert _tail_flag(df) == []


def test_body_deficit_flag_fires_when_below_threshold():
    # 20 huge winners + 80 small losers — body after Top-20 is heavily negative
    df = pd.DataFrame({
        "pnl_usd": [1000.0] * 20 + [-30.0] * 80,
        "direction": [1] * 100,
        "exit_timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
    })
    flags = _body_deficit_flag(df)
    assert flags, "body-deficit flag should fire when body PnL after Top-20 < -$500"


def test_direction_imbalance_fires_when_one_side_dominant():
    # All positive PnL is long
    df = pd.DataFrame({
        "pnl_usd": [10.0] * 90 + [-5.0] * 10,
        "direction": [1] * 100,
        "exit_timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
    })
    flags = _direction_imbalance_flag(df)
    assert flags, "direction-bias flag should fire when one side carries >85%"
    assert "longs carry" in flags[0]


def test_loss_streak_flag_fires_above_threshold():
    # 17 consecutive losses sandwiched between wins
    pnls = [1.0] * 5 + [-1.0] * 17 + [1.0] * 5
    df = pd.DataFrame({
        "pnl_usd": pnls,
        "direction": [1] * len(pnls),
        "entry_timestamp": pd.date_range("2024-01-01", periods=len(pnls), freq="D"),
    })
    flags = _loss_streak_flag(df)
    assert flags, "loss-streak flag should fire when run exceeds threshold"
    assert "16" in flags[0] or "17" in flags[0]


def test_loss_streak_flag_silent_below_threshold():
    # Max streak = 10 (below default threshold of 15)
    pnls = [1.0, -1.0] * 5 + [-1.0] * 10 + [1.0] * 5
    df = pd.DataFrame({
        "pnl_usd": pnls,
        "direction": [1] * len(pnls),
        "entry_timestamp": pd.date_range("2024-01-01", periods=len(pnls), freq="D"),
    })
    assert _loss_streak_flag(df) == []


def test_wasted_edge_flag_fires_when_mfe_unconverted():
    # 30 trades reached +3R MFE then closed at -0.5R; 70 normal trades
    n_wasted, n_normal = 30, 70
    df = pd.DataFrame({
        "pnl_usd": [-1.0] * n_wasted + [10.0] * n_normal,
        "direction": [1] * (n_wasted + n_normal),
        "mfe_r": [3.0] * n_wasted + [1.0] * n_normal,
        "r_multiple": [-0.5] * n_wasted + [1.0] * n_normal,
        "entry_timestamp": pd.date_range("2024-01-01", periods=n_wasted + n_normal, freq="D"),
    })
    flags = _wasted_edge_flag(df)
    assert flags, "wasted-edge flag should fire when >25% of trades hit +2R MFE then close <0R"
    assert "Wasted edge" in flags[0]


def test_wasted_edge_flag_silent_when_columns_missing():
    df = pd.DataFrame({
        "pnl_usd": [10.0, -5.0, 10.0],
        "direction": [1, 1, 1],
    })
    assert _wasted_edge_flag(df) == []


def test_stall_decay_flag_fires_when_h2_below_threshold():
    # First half PnL = +$1000, second half PnL = +$200 (20% of H1 — below 50%)
    n = 200
    pnls = [10.0] * (n // 2) + [2.0] * (n // 2)
    df = pd.DataFrame({
        "pnl_usd": pnls,
        "direction": [1] * n,
        "entry_timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
    })
    flags = _stall_decay_flag(df)
    assert flags, "stall-decay flag should fire when H2 < 50% of H1"


def test_stall_decay_flag_silent_when_h1_negative():
    # First half is loss-making — decay is ill-defined, must not fire
    pnls = [-10.0] * 100 + [5.0] * 100
    df = pd.DataFrame({
        "pnl_usd": pnls,
        "direction": [1] * 200,
        "entry_timestamp": pd.date_range("2024-01-01", periods=200, freq="D"),
    })
    assert _stall_decay_flag(df) == []


def test_flat_period_flag_fires_when_long_dormancy():
    # 1 big win, then 300 days of small losses
    dates = list(pd.date_range("2024-01-01", periods=1, freq="D")) + \
            list(pd.date_range("2024-01-02", periods=300, freq="D"))
    pnls = [1000.0] + [-1.0] * 300
    df = pd.DataFrame({
        "pnl_usd": pnls,
        "direction": [1] * 301,
        "exit_timestamp": dates,
    })
    flags = _flat_period_flag(df)
    assert flags, "flat-period flag should fire when no new high for > 250 days"


# ---------------------------------------------------------------------------
# 3. §4.1 auto-suppress predicates
# ---------------------------------------------------------------------------

def test_bucket_distribution_matches_byte_equal():
    a = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 20, "Age_2_T": 5}]
    b = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 20, "Age_2_T": 5}]
    assert _bucket_distribution_matches(a, b) is True


def test_bucket_distribution_diverges_when_one_bucket_differs():
    a = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 20, "Age_2_T": 5}]
    b = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 21, "Age_2_T": 5}]
    assert _bucket_distribution_matches(a, b) is False


def test_exec_delta_dominance_threshold():
    # 99% of trades in Δ=1 bucket — should dominate
    rows = [{"Symbol": "XAU", "Exec_Delta_leneg1_T": 1, "Exec_Delta_0_T": 1,
             "Exec_Delta_1_T": 198, "Exec_Delta_ge2_T": 0}]
    assert _exec_delta_single_bucket_dominates(rows, threshold=0.95) is True


def test_exec_delta_no_dominance_when_balanced():
    rows = [{"Symbol": "XAU", "Exec_Delta_leneg1_T": 50, "Exec_Delta_0_T": 50,
             "Exec_Delta_1_T": 50, "Exec_Delta_ge2_T": 50}]
    assert _exec_delta_single_bucket_dominates(rows, threshold=0.95) is False


def test_fill_age_section_suppressed_when_distribution_matches():
    fill = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 20}]
    age = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 20}]
    out = _build_fill_age_section(fill, age)
    text = "\n".join(out)
    assert "Suppressed" in text
    assert "T:10" not in text, "should NOT render the full bucket table"


def test_fill_age_section_renders_when_distribution_differs():
    fill = [{"Symbol": "XAU", "Age_0_T": 10, "Age_1_T": 20, "Age_0_PnL": 100,
             "Age_1_PnL": 200, "Age_0_PF": 1.0, "Age_1_PF": 1.5,
             "Age_0_WR": 50, "Age_1_WR": 60}]
    age = [{"Symbol": "XAU", "Age_0_T": 12, "Age_1_T": 18}]
    out = _build_fill_age_section(fill, age)
    text = "\n".join(out)
    assert "Suppressed" not in text


def test_exec_delta_section_suppressed_when_dominated():
    rows = [{"Symbol": "XAU", "Exec_Delta_leneg1_T": 0, "Exec_Delta_0_T": 0,
             "Exec_Delta_1_T": 1000, "Exec_Delta_ge2_T": 0,
             "Exec_Delta_1_PnL": 100, "Exec_Delta_1_PF": 1.2,
             "Exec_Delta_1_WR": 50}]
    meta = [{"Symbol": "XAU", "n_total": 1000, "n_delta_valid": 1000}]
    out = _build_exec_delta_section(rows, meta)
    text = "\n".join(out)
    assert "Suppressed" in text


# ---------------------------------------------------------------------------
# 4. §4.2 Yearwise flag composition
# ---------------------------------------------------------------------------

def test_yearwise_dominant_flag_fires_when_year_over_60pct_of_net():
    # 2024 carries 70%, 2025 carries 30%
    df = pd.DataFrame({
        "pnl_usd": [70.0] * 10 + [30.0] * 10,
        "entry_timestamp": (
            list(pd.date_range("2024-01-01", periods=10, freq="ME")) +
            list(pd.date_range("2025-01-01", periods=10, freq="ME"))
        ),
    })
    md = _build_yearwise_section([df])
    text = "\n".join(md)
    assert "dominant" in text or "% of net" in text


def test_yearwise_negative_flag_fires():
    df = pd.DataFrame({
        "pnl_usd": [-50.0] * 10 + [80.0] * 10,
        "entry_timestamp": (
            list(pd.date_range("2024-01-01", periods=10, freq="ME")) +
            list(pd.date_range("2025-01-01", periods=10, freq="ME"))
        ),
    })
    md = _build_yearwise_section([df])
    text = "\n".join(md)
    assert "negative" in text.lower()


def test_yearwise_partial_flag_fires_when_fewer_than_11_months():
    # 5 months only in 2026
    df = pd.DataFrame({
        "pnl_usd": [10.0] * 5,
        "entry_timestamp": pd.date_range("2026-01-01", periods=5, freq="ME"),
    })
    md = _build_yearwise_section([df])
    text = "\n".join(md)
    assert "partial" in text.lower()


# ---------------------------------------------------------------------------
# Fix 1: rationale names the binding CORE gate when WATCH
# ---------------------------------------------------------------------------

def test_rationale_names_binding_gate_when_sharpe_short():
    # P14-style row: SQN passes, Sharpe just below floor
    row = {
        "total_trades": 1078,
        "max_dd_pct": 0.40,
        "return_dd_ratio": 7.07,
        "sharpe_ratio": 1.39,
        "sqn": 2.87,
        "profit_factor": 1.35,
        "trade_density": 543,
    }
    assert _core_gates_missing(row) == ["Sharpe 1.39 < 1.5"]
    rationale = _verdict_rationale(row, "WATCH")
    assert "Sharpe 1.39 < 1.5" in rationale
    assert "binding gate" in rationale


def test_rationale_names_multiple_binding_gates():
    # Row that fails both SQN and Sharpe
    row = {
        "total_trades": 200,
        "max_dd_pct": 12.0,
        "return_dd_ratio": 3.0,
        "sharpe_ratio": 1.0,
        "sqn": 2.0,
        "profit_factor": 1.30,
        "trade_density": 100,
    }
    missing = _core_gates_missing(row)
    assert "SQN 2.00 < 2.5" in missing
    assert "Sharpe 1.00 < 1.5" in missing
    rationale = _verdict_rationale(row, "WATCH")
    assert "binding gates" in rationale  # plural


def test_rationale_for_fail_status_names_gate():
    row = {
        "total_trades": 30,           # FAILS trades < 50
        "max_dd_pct": 12.0,
        "return_dd_ratio": 1.0,
        "sharpe_ratio": 1.0,
        "sqn": 1.0,                   # FAILS sqn < 1.5
        "profit_factor": 0.9,
        "trade_density": 20,
    }
    assert "trades 30 < 50" in _fail_gates_violated(row)
    assert "SQN 1.00 < 1.5" in _fail_gates_violated(row)


def test_rationale_for_core_lists_all_gates_passed():
    row = {
        "total_trades": 1000,
        "max_dd_pct": 10.0,
        "return_dd_ratio": 5.0,
        "sharpe_ratio": 2.0,
        "sqn": 3.0,
        "profit_factor": 1.5,
        "trade_density": 200,
    }
    assert _core_gates_missing(row) == []
    rationale = _verdict_rationale(row, "CORE")
    # All six gate values must appear
    for token in ["SQN 3.00", "Sharpe 2.00", "R/DD 5.00", "DD 10.00%", "PF 1.50", "density 200"]:
        assert token in rationale


# ---------------------------------------------------------------------------
# Fix 2: parent Δ window-mismatch guard
# ---------------------------------------------------------------------------

def test_windows_compatible_within_tolerance():
    ok, _ = _windows_compatible("2024-05-11", "2026-05-11", "2024-05-09", "2026-05-13")
    assert ok is True


def test_windows_incompatible_when_start_drift_exceeds_tolerance():
    ok, reason = _windows_compatible("2024-05-11", "2026-05-11", "2024-07-19", "2026-05-04")
    assert ok is False
    assert "start" in reason.lower() or "Δ" in reason
    assert "tolerance" in reason


def test_windows_incompatible_when_end_drift_exceeds_tolerance():
    ok, reason = _windows_compatible("2024-05-11", "2026-05-11", "2024-05-09", "2025-08-21")
    assert ok is False


def test_windows_compatible_fail_open_on_parse_error():
    # When parent has no dates at all → don't block the comparison.
    ok, _ = _windows_compatible("2024-05-11", "2026-05-11", None, None)
    assert ok is True


# ---------------------------------------------------------------------------
# 5. End-to-end: regenerated PSBRK V4 P14 report carries Phase A markers
# ---------------------------------------------------------------------------

from config.path_authority import TRADE_SCAN_STATE

_P14_REPORT_PATH = (
    TRADE_SCAN_STATE / "backtests"
    / "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14_XAUUSD"
    / "REPORT_65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14.md"
)


@pytest.mark.skipif(not _P14_REPORT_PATH.exists(),
                    reason="V4 P14 backtest report missing — run pipeline first")
def test_p14_report_carries_phase_a_markers():
    text = _P14_REPORT_PATH.read_text(encoding="utf-8")

    # 1. Verdict block present, near the top (before Portfolio Key Metrics)
    verdict_idx = text.find("## Verdict & Risk")
    key_metrics_idx = text.find("## Portfolio Key Metrics")
    assert verdict_idx > 0
    assert key_metrics_idx > verdict_idx, "Verdict must precede key metrics"

    # 2. §4.3: standalone Volatility/Trend Edge sections removed
    assert "## Volatility Edge\n" not in text
    assert "## Trend Edge\n" not in text

    # 3. §4.2: Yearwise table has a Flags column
    assert "Yearwise Performance" in text
    # New column header marker
    assert "| Flags |" in text

    # 4. §4.8: K-Ratio not in Portfolio Key Metrics
    pkm_block = text[key_metrics_idx:key_metrics_idx + 2000]
    assert "K-Ratio" not in pkm_block

    # 5. §4.1: fill-age suppressed when redundant — present in current run
    assert "fill-age bucket distribution is identical to regime-age" in text \
        or "## Regime Lifecycle (Fill Age" in text  # rendered or suppressed


@pytest.mark.skipif(not _P14_REPORT_PATH.exists(),
                    reason="V4 P14 backtest report missing — run pipeline first")
def test_p14_report_fix1_rationale_names_binding_sharpe_gate():
    """Fix 1 regression — verdict rationale must name the binding CORE gate."""
    text = _P14_REPORT_PATH.read_text(encoding="utf-8")
    # WATCH because Sharpe 1.39 < 1.5 is the binding gate
    assert "Sharpe 1.39 < 1.5" in text, \
        "binding-gate Sharpe must be surfaced in the verdict rationale"
    assert "binding gate" in text


@pytest.mark.skipif(not _P14_REPORT_PATH.exists(),
                    reason="V4 P14 backtest report missing — run pipeline first")
def test_p14_report_fix2_parent_delta_suppressed_on_window_mismatch():
    """Fix 2 regression — when parent's window differs, Δ must show 'unavailable'."""
    text = _P14_REPORT_PATH.read_text(encoding="utf-8")
    # P14 currently runs on 2024-05-13..2026-05-08 (standardized) but parent
    # P13's Master Filter row is from a different (pre-recovery) window.
    assert "unavailable (window mismatch)" in text, \
        "parent Δ must declare window mismatch instead of rendering contaminated deltas"


@pytest.mark.skipif(not _P14_REPORT_PATH.exists(),
                    reason="V4 P14 backtest report missing — run pipeline first")
def test_p14_report_fix3_loss_streak_flag_surfaced():
    """Fix 3 regression — loss-streak flag must fire on P14 (streak = 16)."""
    text = _P14_REPORT_PATH.read_text(encoding="utf-8")
    # P14's longest loss streak = 16 (> 15 threshold)
    assert "Loss streak" in text, "loss-streak risk flag must be surfaced"
    # Risk block cannot say 'none surfaced' when a flag fires
    pkm_idx = text.find("## Portfolio Key Metrics")
    vr_block = text[text.find("## Verdict & Risk"):pkm_idx]
    assert "none surfaced" not in vr_block, \
        "risk block must NOT say 'none surfaced' when any flag fires"
