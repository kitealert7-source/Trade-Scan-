"""Backtest + profile metric readers.

Source files:
    portfolio_summary.json     — aggregate backtest metrics
    profile_comparison.json    — per-profile metrics (accepted, rejection, PF, recovery)
"""

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import STRATEGIES_DIR


def _read_backtest_metrics(strategy_id: str) -> dict:
    """Read aggregate metrics from portfolio_summary.json."""
    ps = STRATEGIES_DIR / strategy_id / "portfolio_evaluation" / "portfolio_summary.json"
    if ps.exists():
        data = json.loads(ps.read_text(encoding="utf-8"))
        return {
            "trades":      data.get("total_trades", "?"),
            "pf":          round(data.get("profit_factor", 0), 2),
            "sharpe":      round(data.get("sharpe_ratio", 0), 2),
            "max_dd_pct":  round(data.get("max_drawdown_pct", 0), 2),
            "pnl":         round(data.get("total_pnl", 0), 2),
            "ret_dd":      round(data.get("return_dd_ratio", 0), 2),
            "expectancy":  round(data.get("expectancy", 0), 4),
        }
    return {"trades": "?", "pf": "?", "sharpe": "?", "max_dd_pct": "?", "pnl": "?", "ret_dd": "?", "expectancy": "?"}


def _read_profile_metrics(strategy_id: str, profile: str) -> dict:
    """Read profile-specific metrics from profile_comparison.json."""
    pc = STRATEGIES_DIR / strategy_id / "deployable" / "profile_comparison.json"
    if not pc.exists():
        return {}
    data = json.loads(pc.read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    if profile in profiles:
        p = profiles[profile]
        return {
            "accepted":       p.get("accepted_trades", "?"),
            "rejected_pct":   round(p.get("rejection_pct", 0), 2),
            "profile_pf":     round(p.get("profit_factor", 0), 2),
            "recovery":       round(p.get("recovery_factor", 0), 2),
        }
    available = list(profiles.keys())
    if available:
        print(f"[WARN] Profile '{profile}' not in profile_comparison.json. Available: {available}")
    return {}
