"""
Unit tests for burnin_evaluator.py — pure metric/gate logic, no I/O.

Covers:
  - _compute_metrics() with empty, winning, losing, mixed trades
  - _evaluate_gates() threshold logic, verdicts, inf handling
  - Tiny sample trap: no abort on insufficient data
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.burnin_evaluator import _compute_metrics, _evaluate_gates, GATES


def _make_exit(pnl_usd: float, event_utc: str = "2026-04-10T12:00:00") -> dict:
    """Build a minimal EXIT record for testing."""
    return {
        "event_type": "EXIT",
        "net_pnl_usd": pnl_usd,
        "event_utc": event_utc,
    }


# ===================================================================
# _compute_metrics()
# ===================================================================

class TestComputeMetrics:

    def test_empty_trades(self):
        m = _compute_metrics([], signal_count=0, fill_count=0)
        assert m["trades"] == 0
        assert m["pf"] is None
        assert m["wr_pct"] is None
        assert m["net_pnl"] == 0.0
        assert m["max_dd_pct"] == 0.0

    def test_all_winners(self):
        trades = [_make_exit(100), _make_exit(200), _make_exit(50)]
        m = _compute_metrics(trades, signal_count=3, fill_count=3)
        assert m["trades"] == 3
        assert m["pf"] == float("inf")
        assert m["wr_pct"] == 100.0
        assert m["net_pnl"] == 350.0
        assert m["max_dd_pct"] == 0.0

    def test_all_losers(self):
        trades = [_make_exit(-50), _make_exit(-30), _make_exit(-20)]
        m = _compute_metrics(trades, signal_count=3, fill_count=3)
        assert m["trades"] == 3
        assert m["pf"] == 0.0
        assert m["wr_pct"] == 0.0
        assert m["net_pnl"] == -100.0
        assert m["max_consec_losses"] == 3

    def test_mixed_trades(self):
        trades = [_make_exit(100), _make_exit(-40), _make_exit(60)]
        m = _compute_metrics(trades, signal_count=3, fill_count=3)
        assert m["trades"] == 3
        assert m["pf"] == 4.0  # 160 / 40
        assert m["wr_pct"] == pytest_approx(66.7, abs=0.1)
        assert m["net_pnl"] == 120.0

    def test_fill_rate(self):
        trades = [_make_exit(100)]
        m = _compute_metrics(trades, signal_count=10, fill_count=8)
        assert m["fill_rate"] == 80.0

    def test_fill_rate_no_signals(self):
        m = _compute_metrics([], signal_count=0, fill_count=0)
        assert m["fill_rate"] is None

    def test_drawdown_calculation(self):
        """Win, win, big loss — DD should be the loss from peak."""
        trades = [_make_exit(500), _make_exit(300), _make_exit(-600)]
        m = _compute_metrics(trades, signal_count=3, fill_count=3)
        # Peak = 800, then drops to 200 → DD = 600 USD
        # DD% = 600 / 10000 (notional) = 6.0%
        assert m["max_dd_usd"] == 600.0
        assert m["max_dd_pct"] == 6.0

    def test_consecutive_losing_weeks(self):
        """Two trades in different weeks, both losing."""
        trades = [
            _make_exit(-50, "2026-04-07T10:00:00"),  # Week 15
            _make_exit(-30, "2026-04-14T10:00:00"),  # Week 16
        ]
        m = _compute_metrics(trades, signal_count=2, fill_count=2)
        assert m["consec_losing_weeks"] == 2

    def test_lot_rescaling_to_target(self):
        """Trades with explicit lot_size are rescaled to GATES['target_lot'].

        Formula: pnl_norm = pnl_orig * (target_lot / lot_size).
        At target_lot=0.01 and lot_size=1.0, the rescaled PnL is 1% of original.
        Verifies that PF and DD scale by the same factor — uniform across trades.
        """
        target = GATES["target_lot"]  # 0.01
        # Two trades, both at lot_size=1.0. Original PnL: +200, -100.
        # Rescaled to 0.01 lot: +2.00, -1.00.
        trades = [
            {"event_type": "EXIT", "net_pnl_usd": 200.0, "lot_size": 1.0,
             "event_utc": "2026-04-10T12:00:00"},
            {"event_type": "EXIT", "net_pnl_usd": -100.0, "lot_size": 1.0,
             "event_utc": "2026-04-10T13:00:00"},
        ]
        m = _compute_metrics(trades, signal_count=2, fill_count=2)
        # Net PnL collapses: (200 - 100) * 0.01 = 1.00
        assert abs(m["net_pnl"] - 1.0) < 0.001
        # PF unchanged by uniform rescaling: 200 / 100 == 2.00 == 2.00 / 1.00
        assert abs(m["pf"] - 2.0) < 0.001
        assert m["wr_pct"] == 50.0

    def test_lot_rescaling_variable_lots(self):
        """Different lot sizes per trade rescale independently — PF and DD
        differ from the lot-uniform case because trades carry different weight
        in the rescaled equity curve."""
        # Trade A: +200 USD at lot=2.0 → rescaled +1.00 USD (200 * 0.01/2.0)
        # Trade B: -100 USD at lot=0.5 → rescaled -2.00 USD (-100 * 0.01/0.5)
        trades = [
            {"event_type": "EXIT", "net_pnl_usd": 200.0, "lot_size": 2.0,
             "event_utc": "2026-04-10T12:00:00"},
            {"event_type": "EXIT", "net_pnl_usd": -100.0, "lot_size": 0.5,
             "event_utc": "2026-04-10T13:00:00"},
        ]
        m = _compute_metrics(trades, signal_count=2, fill_count=2)
        assert abs(m["net_pnl"] - (-1.0)) < 0.001  # 1.0 + (-2.0) = -1.0
        assert abs(m["pf"] - 0.5) < 0.001          # 1.0 / 2.0 = 0.5

    def test_lot_rescaling_missing_lot_unchanged(self):
        """Records without lot_size fall through unrescaled — preserves
        backward compatibility for tests + edge-case records."""
        trades = [_make_exit(500), _make_exit(-300)]  # no lot_size set
        m = _compute_metrics(trades, signal_count=2, fill_count=2)
        # Falls through: pnls treated at face value
        assert m["net_pnl"] == 200.0
        assert abs(m["pf"] - (500.0 / 300.0)) < 0.001


# ===================================================================
# _evaluate_gates()
# ===================================================================

class TestEvaluateGates:

    def test_continue_on_zero_trades(self):
        m = _compute_metrics([], signal_count=0, fill_count=0)
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "CONTINUE"

    def test_on_track_all_pass(self):
        """Good metrics across the board → ON_TRACK."""
        m = {
            "trades": 60, "pf": 1.50, "wr_pct": 60.0, "net_pnl": 500.0,
            "max_dd_pct": 3.0, "max_dd_usd": 300.0,
            "consec_losing_weeks": 0, "max_consec_losses": 2,
            "fill_rate": 95.0, "signals": 60, "fills": 57,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "ON_TRACK"
        assert len(ev["abort_reasons"]) == 0

    def test_observe_pf_after_50_trades(self):
        """PF < 1.10 after 50+ trades → OBSERVE (formerly ABORT, demoted under
        observational burn-in policy). Fill rate is OK so no execution-safety
        ABORT fires; the PF gate surfaces as OBS for human review."""
        m = {
            "trades": 55, "pf": 1.05, "wr_pct": 55.0, "net_pnl": 50.0,
            "max_dd_pct": 5.0, "max_dd_usd": 500.0,
            "consec_losing_weeks": 1, "max_consec_losses": 4,
            "fill_rate": 90.0, "signals": 55, "fills": 50,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "OBSERVE"
        assert ev["abort_reasons"] == []
        pf_gate = [g for g in ev["gates"] if g["gate"] == "Profit Factor"][0]
        assert pf_gate["status"] == "OBS"

    def test_tiny_sample_no_abort(self):
        """CRITICAL: 3 trades with PF < 1.10 must NOT trigger abort.

        The PF abort gate only applies after abort_pf_min_trades (50).
        Early bad luck must not kill a strategy prematurely.
        """
        m = {
            "trades": 3, "pf": 0.50, "wr_pct": 33.3, "net_pnl": -50.0,
            "max_dd_pct": 0.5, "max_dd_usd": 50.0,
            "consec_losing_weeks": 1, "max_consec_losses": 2,
            "fill_rate": 100.0, "signals": 3, "fills": 3,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] != "ABORT", (
            f"Tiny sample (3 trades) should not trigger abort, got: {ev['verdict']}"
        )

    def test_observe_drawdown(self):
        """DD > 12% → OBSERVE (formerly ABORT, demoted under observational
        burn-in policy). Under RAW_MIN_LOT_V1 deployment a 13% DD is unreachable
        in normal operation — surfacing it indicates a sizing-regime mismatch
        or data anomaly, not a strategy-quality failure."""
        m = {
            "trades": 30, "pf": 1.30, "wr_pct": 55.0, "net_pnl": 200.0,
            "max_dd_pct": 13.0, "max_dd_usd": 1300.0,
            "consec_losing_weeks": 0, "max_consec_losses": 3,
            "fill_rate": 95.0, "signals": 30, "fills": 29,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "OBSERVE"
        assert ev["abort_reasons"] == []
        dd_gate = [g for g in ev["gates"] if g["gate"] == "Max Drawdown"][0]
        assert dd_gate["status"] == "OBS"

    def test_abort_fill_rate(self):
        """Fill rate < 80% → ABORT."""
        m = {
            "trades": 20, "pf": 1.40, "wr_pct": 55.0, "net_pnl": 150.0,
            "max_dd_pct": 2.0, "max_dd_usd": 200.0,
            "consec_losing_weeks": 0, "max_consec_losses": 1,
            "fill_rate": 75.0, "signals": 20, "fills": 15,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "ABORT"
        assert any("Fill rate" in r or "fill" in r.lower() for r in ev["abort_reasons"])

    def test_observe_consec_losing_weeks(self):
        """3+ consecutive losing weeks → OBSERVE (formerly ABORT, demoted under
        observational burn-in policy). Regime/temporal signal for human review,
        not an automated abort gate."""
        m = {
            "trades": 20, "pf": 1.15, "wr_pct": 55.0, "net_pnl": 30.0,
            "max_dd_pct": 4.0, "max_dd_usd": 400.0,
            "consec_losing_weeks": 3, "max_consec_losses": 5,
            "fill_rate": 90.0, "signals": 20, "fills": 18,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "OBSERVE"
        assert ev["abort_reasons"] == []
        clw_gate = [g for g in ev["gates"] if g["gate"] == "Consec Losing Weeks"][0]
        assert clw_gate["status"] == "OBS"

    def test_warn_low_wr(self):
        """WR below pass threshold but no abort trigger → WARN."""
        m = {
            "trades": 20, "pf": 1.25, "wr_pct": 40.0, "net_pnl": 100.0,
            "max_dd_pct": 3.0, "max_dd_usd": 300.0,
            "consec_losing_weeks": 0, "max_consec_losses": 3,
            "fill_rate": 95.0, "signals": 20, "fills": 19,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] == "WARN"

    def test_inf_pf_handled(self):
        """PF=inf (all winners) should be PASS, not crash."""
        m = {
            "trades": 5, "pf": float("inf"), "wr_pct": 100.0, "net_pnl": 500.0,
            "max_dd_pct": 0.0, "max_dd_usd": 0.0,
            "consec_losing_weeks": 0, "max_consec_losses": 0,
            "fill_rate": 100.0, "signals": 5, "fills": 5,
            "weekly_pnl": {},
        }
        ev = _evaluate_gates(m)
        assert ev["verdict"] in ("ON_TRACK", "CONTINUE")
        pf_gate = [g for g in ev["gates"] if g["gate"] == "Profit Factor"][0]
        assert pf_gate["status"] == "PASS"


# ===================================================================
# Helper for float comparison
# ===================================================================

def pytest_approx(expected, abs=0.01):
    """Standalone approx for float comparisons without importing pytest."""
    class _Approx:
        def __eq__(self, other):
            return builtins_abs(other - expected) <= abs
        def __repr__(self):
            return f"~{expected}"
    import builtins
    builtins_abs = builtins.abs
    return _Approx()
