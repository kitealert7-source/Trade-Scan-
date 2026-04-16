"""
Regression tests for _compute_portfolio_status().

Validates FAIL / WATCH / CORE classification boundaries including:
- Realized PnL gate (<= $0)
- Accepted trades gate (< 50)
- Trade density gate (< 50 per symbol)
- Expectancy asset-class gates (FX, XAU, BTC, INDEX, MIXED)
- CORE promotion thresholds
- Edge cases at exact boundaries
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.portfolio_evaluator import _compute_portfolio_status


# ── FAIL: Realized PnL ──────────────────────────────────────────────────────

def test_fail_negative_pnl():
    assert _compute_portfolio_status(-100.0, 200, 0.0, 1.0, "22_CONT_FX_15M") == "FAIL"


def test_fail_zero_pnl():
    assert _compute_portfolio_status(0.0, 200, 0.0, 1.0, "22_CONT_FX_15M") == "FAIL"


# ── FAIL: Accepted trades ───────────────────────────────────────────────────

def test_fail_accepted_below_50():
    assert _compute_portfolio_status(500.0, 49, 0.0, 1.0, "22_CONT_FX_15M") == "FAIL"


def test_pass_accepted_exactly_50():
    """accepted == 50 should NOT fail (gate is < 50)."""
    assert _compute_portfolio_status(500.0, 50, 0.0, 1.0, "22_CONT_FX_15M") == "WATCH"


# ── FAIL: Trade density ─────────────────────────────────────────────────────

def test_fail_low_trade_density():
    """Portfolio with 200 accepted trades but only 14 per symbol → FAIL."""
    assert _compute_portfolio_status(500.0, 200, 0.0, 1.0, "02_VOL_FX_1D_VOLEXP", trade_density_min=14) == "FAIL"


def test_pass_trade_density_exactly_50():
    """trade_density == 50 should NOT fail (gate is < 50)."""
    assert _compute_portfolio_status(500.0, 200, 0.0, 1.0, "22_CONT_FX_15M", trade_density_min=50) != "FAIL"


def test_pass_trade_density_none():
    """Missing trade_density (None) should not trigger FAIL — backwards compat."""
    assert _compute_portfolio_status(500.0, 200, 0.0, 1.0, "22_CONT_FX_15M", trade_density_min=None) != "FAIL"


# ── FAIL: Expectancy gates ──────────────────────────────────────────────────

def test_fail_fx_low_expectancy():
    """FX gate: expectancy < $0.15 → FAIL."""
    assert _compute_portfolio_status(500.0, 100, 0.0, 0.10, "22_CONT_FX_15M") == "FAIL"


def test_fail_xau_low_expectancy():
    """XAU gate: expectancy < $0.50 → FAIL."""
    assert _compute_portfolio_status(500.0, 100, 0.0, 0.40, "11_REV_XAUUSD_1H") == "FAIL"


def test_fail_btc_low_expectancy():
    """BTC gate: expectancy < $0.50 → FAIL."""
    assert _compute_portfolio_status(500.0, 100, 0.0, 0.30, "33_TREND_BTCUSD_1H") == "FAIL"


def test_fail_idx_low_expectancy():
    """INDEX gate: expectancy < $0.50 → FAIL."""
    assert _compute_portfolio_status(500.0, 100, 0.0, 0.40, "02_VOL_IDX_1D") == "FAIL"


def test_pass_mixed_no_exp_gate():
    """PF_ composites (MIXED) have no expectancy gate."""
    assert _compute_portfolio_status(500.0, 100, 0.0, 0.01, "PF_ABC123") == "WATCH"


# ── CORE: Portfolios (edge_quality gate) ─────────────────────────────────────

def test_core_portfolio_with_edge_quality():
    """CORE requires edge_quality >= 0.12 for Portfolios tab."""
    assert _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.15) == "CORE"


def test_core_portfolio_low_edge_quality():
    """Base CORE met but edge_quality < 0.12 → NOT CORE."""
    result = _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "22_CONT_FX_15M",
                                       edge_quality=0.10)
    assert result != "CORE"


def test_core_portfolio_edge_quality_boundary():
    """edge_quality == 0.12 exactly → CORE."""
    assert _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.12) == "CORE"


def test_core_portfolio_no_quality_metric():
    """No quality metric provided → backwards compat CORE."""
    assert _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "22_CONT_FX_15M") == "CORE"


# ── CORE: Single-Asset (SQN gate) ───────────────────────────────────────────

def test_core_single_asset_with_sqn():
    """CORE requires SQN >= 2.5 for Single-Asset tab."""
    assert _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "03_TREND_XAUUSD_1H",
                                     sqn=3.0) == "CORE"


def test_core_single_asset_low_sqn():
    """Base CORE met but SQN < 2.5 → NOT CORE."""
    result = _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "03_TREND_XAUUSD_1H",
                                       sqn=2.3)
    assert result != "CORE"


def test_core_single_asset_sqn_boundary():
    """SQN == 2.5 exactly → CORE."""
    assert _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "03_TREND_XAUUSD_1H",
                                     sqn=2.5) == "CORE"


# ── CORE: Base thresholds still required ─────────────────────────────────────

def test_core_boundary_realized():
    """realized == $1000 is NOT > $1000 → not CORE."""
    assert _compute_portfolio_status(1000.0, 250, 10.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.15) != "CORE"


def test_core_boundary_accepted():
    """accepted == 199 < 200 → not CORE."""
    assert _compute_portfolio_status(1500.0, 199, 10.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.15) != "CORE"


def test_core_boundary_rejection():
    """rejection == 31% > 30% → not CORE."""
    assert _compute_portfolio_status(1500.0, 250, 31.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.15) != "CORE"


def test_core_with_trade_density():
    """CORE with valid trade_density + edge_quality."""
    assert _compute_portfolio_status(1500.0, 250, 10.0, 1.0, "22_CONT_FX_15M",
                                     trade_density_min=100, edge_quality=0.15) == "CORE"


# ── WATCH: Quality floor required ────────────────────────────────────────────

def test_watch_portfolio_good_edge():
    """Profitable, edge_quality >= 0.08 → WATCH."""
    assert _compute_portfolio_status(500.0, 100, 5.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.10) == "WATCH"


def test_watch_portfolio_low_edge():
    """Profitable but edge_quality < 0.08 → FAIL."""
    assert _compute_portfolio_status(500.0, 100, 5.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.05) == "FAIL"


def test_watch_single_asset_good_sqn():
    """Profitable, SQN >= 2.0 → WATCH."""
    assert _compute_portfolio_status(500.0, 100, 5.0, 1.0, "03_TREND_XAUUSD_1H",
                                     sqn=2.2) == "WATCH"


def test_watch_single_asset_low_sqn():
    """Profitable but SQN < 2.0 → FAIL."""
    assert _compute_portfolio_status(500.0, 100, 5.0, 1.0, "03_TREND_XAUUSD_1H",
                                     sqn=1.5) == "FAIL"


def test_watch_high_rejection_with_edge():
    """High realized + trades but rejection > 30% → WATCH if edge good."""
    assert _compute_portfolio_status(5000.0, 500, 35.0, 1.0, "22_CONT_FX_15M",
                                     edge_quality=0.10) == "WATCH"


def test_watch_no_quality_metric():
    """No quality metric → backwards compat WATCH."""
    assert _compute_portfolio_status(500.0, 100, 5.0, 1.0, "22_CONT_FX_15M") == "WATCH"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
