"""Tests for the analysis-layer liquidation floor (leverage_liquidation_adjust).

Locks the contract: negative intra-run equity => liquidated (total loss of
stake); otherwise metrics pass through unchanged; missing artifact => no floor.
The floor is the agreed remedy for the FROZEN-engine no-liquidation finding
(2026-06-04) -- applied in analysis, never in the engine."""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from tools.leverage_liquidation_adjust import liquidation_adjusted  # noqa: E402


def test_negative_equity_is_liquidated_to_total_loss():
    out = liquidation_adjusted(net_pct=5299.0, max_dd_pct=94.5, ret_dd=56.1, min_equity_usd=-29880.0)
    assert out["liquidated"] is True
    assert out["net_pct"] == -100.0
    assert out["max_dd_pct"] == 100.0
    assert out["ret_dd"] == -1.0


def test_recovered_from_negative_still_liquidated():
    # SZVP pattern: blew to -$30k then "recovered" to +5299%. min_equity<0 is the
    # discriminant -> liquidated regardless of the (fictitious) positive net.
    out = liquidation_adjusted(net_pct=5299.0, max_dd_pct=94.5, ret_dd=56.1, min_equity_usd=-1.0)
    assert out["liquidated"] is True and out["net_pct"] == -100.0


def test_granular_blowup_capped_at_minus_100():
    # granular run that ended -132% with min equity -$544 -> capped to -100%.
    out = liquidation_adjusted(net_pct=-132.0, max_dd_pct=151.4, ret_dd=-0.87, min_equity_usd=-544.0)
    assert out["liquidated"] is True
    assert out["net_pct"] == -100.0 and out["max_dd_pct"] == 100.0


def test_nonnegative_equity_passes_through():
    out = liquidation_adjusted(net_pct=12.0, max_dd_pct=8.0, ret_dd=1.5, min_equity_usd=437.0)
    assert out["liquidated"] is False
    assert out["net_pct"] == 12.0 and out["max_dd_pct"] == 8.0 and out["ret_dd"] == 1.5


def test_zero_min_equity_is_not_liquidated():
    # exactly 0 == bust but not negative; floor triggers strictly below 0.
    out = liquidation_adjusted(net_pct=-99.0, max_dd_pct=99.0, ret_dd=-1.0, min_equity_usd=0.0)
    assert out["liquidated"] is False and out["net_pct"] == -99.0


def test_missing_artifact_passes_through():
    out = liquidation_adjusted(net_pct=50.0, max_dd_pct=20.0, ret_dd=2.5, min_equity_usd=None)
    assert out["liquidated"] is False and out["net_pct"] == 50.0


def test_notional_run_is_noop():
    # production/notional runs are bounded (min equity well above 0) -> no-op.
    out = liquidation_adjusted(net_pct=6.83, max_dd_pct=4.35, ret_dd=1.57, min_equity_usd=958.0)
    assert out["liquidated"] is False and out["ret_dd"] == 1.57


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
