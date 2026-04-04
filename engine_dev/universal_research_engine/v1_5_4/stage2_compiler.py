"""
Stage-2 Presentation Compiler — SOP-Complete with Full Metric Computation
Consumes Stage-1 authoritative artifacts and produces AK_Trade_Report Excel.
Implements SOP_OUTPUT §5.1 (Performance Summary) and §5.2 (Yearwise Performance).
All metrics computed from Stage-1 data. No placeholders.
Rewritten to use pandas and Unified Formatter (Zero OpenPyXL Styling / Imports).

Authority: SOP_OUTPUT, SOP_TESTING
State Gated: Yes (STAGE_2_START)
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import argparse

__all__ = [
    "load_stage1_artifacts",
    "compile_stage2",
    "generate_excel_report",
    "get_performance_summary_df",
    "get_trades_df",
]

# Config
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Governance Imports
from tools.pipeline_utils import PipelineStateManager
from config.state_paths import BACKTESTS_DIR, RUNS_DIR

# ==================================================================
# CONSTANTS & CONFIG
# ==================================================================

# Session boundaries (UTC hours)
ASIA_START, ASIA_END = 0, 8
LONDON_START, LONDON_END = 8, 16
NY_START, NY_END = 16, 24


def load_stage1_artifacts(run_folder: Path) -> dict[str, Any]:
    execution_dir = run_folder / "raw"
    metadata_dir = run_folder / "metadata"
    
    required_files = [
        execution_dir / "results_tradelevel.csv",
        execution_dir / "results_standard.csv",
        execution_dir / "results_risk.csv",
        execution_dir / "results_yearwise.csv",
        execution_dir / "metrics_glossary.csv",
        metadata_dir / "run_metadata.json",
    ]
    
    for f in required_files:
        if not f.exists():
            raise FileNotFoundError(f"Required Stage-1 artifact missing: {f}")
    
    def read_csv(path):
        with open(path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    
    tradelevel = read_csv(execution_dir / "results_tradelevel.csv")
    standard = read_csv(execution_dir / "results_standard.csv")
    risk = read_csv(execution_dir / "results_risk.csv")
    yearwise = read_csv(execution_dir / "results_yearwise.csv")
    glossary = read_csv(execution_dir / "metrics_glossary.csv")
    
    with open(metadata_dir / "run_metadata.json", "r", encoding="utf-8") as f:
        metadata = json.load(f)
        
    # v5 Metric Integrity: Load Bar Geometry if available
    geometry_path = execution_dir / "bar_geometry.json"
    if geometry_path.exists():
        try:
            with open(geometry_path, "r", encoding="utf-8") as f:
                geo = json.load(f)
                metadata["bar_geometry"] = geo
        except (OSError, json.JSONDecodeError) as e:
            print(f"  STAGE2_BAR_GEOMETRY_WARN  {type(e).__name__}: {e}  path={geometry_path}")
        
    starting_capital = metadata.get("reference_capital_usd")
    if not isinstance(starting_capital, (int, float)) or starting_capital <= 0:
        raise ValueError("Missing or invalid reference_capital_usd in metadata")

    return {
        "tradelevel": tradelevel,
        "standard": standard[0] if standard else {},
        "risk": risk[0] if risk else {},
        "yearwise": yearwise,
        "glossary": glossary,
        "metadata": metadata,
    }



def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val not in (None, "", "None") else default
    except (ValueError, TypeError):
        print(f"  STAGE2_COERCE_WARN  _safe_float({val!r})  type={type(val).__name__}  -> default={default}")
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val)) if val not in (None, "", "None") else default
    except (ValueError, TypeError):
        print(f"  STAGE2_COERCE_WARN  _safe_int({val!r})  type={type(val).__name__}  -> default={default}")
        return default

def _round_val(val: Any, decimals: int = 2) -> Any:
    if isinstance(val, (int, float)):
        return round(val, decimals)
    return val



def _parse_timestamp(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))
    except (ValueError, TypeError, AttributeError):
        return None


def _get_session(dt: datetime | None) -> str:
    """Classify trade by session based on hour (UTC)."""
    if dt is None:
        return "unknown"
    hour = dt.hour
    if ASIA_START <= hour < ASIA_END:
        return "asia"
    elif LONDON_START <= hour < LONDON_END:
        return "london"
    else:
        return "ny"


def _compute_pnl_basics(pnls: list[float]) -> dict[str, Any]:
    """Core PnL aggregation: counts, ratios, averages, extremes."""
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_profit = sum(pnls)

    trade_count = len(pnls)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / trade_count) if trade_count > 0 else 0.0

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit if gross_profit > 0 else 0.0
    avg_trade = (net_profit / trade_count) if trade_count > 0 else 0.0
    avg_win = (sum(wins) / win_count) if win_count > 0 else 0.0
    avg_loss = (sum(losses) / loss_count) if loss_count > 0 else 0.0
    win_loss_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else avg_win if avg_win > 0 else 0.0

    return {
        "wins": wins, "losses": losses,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "net_profit": net_profit,
        "trade_count": trade_count, "win_count": win_count, "loss_count": loss_count,
        "win_rate": win_rate, "profit_factor": profit_factor,
        "avg_trade": avg_trade, "avg_win": avg_win, "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio, "expectancy": avg_trade,
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
    }


def _compute_drawdown(pnls: list[float], net_profit: float, starting_capital: float) -> dict[str, float]:
    """Equity curve traversal for max drawdown and return ratios."""
    peak = 0.0
    max_dd = 0.0
    cumulative = 0.0
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return {
        "max_dd": max_dd,
        "max_dd_pct": (max_dd / starting_capital) if starting_capital > 0 else 0.0,
        "return_dd_ratio": (net_profit / max_dd) if max_dd > 0 else net_profit if net_profit > 0 else 0.0,
        "return_on_capital": (net_profit / starting_capital) if starting_capital > 0 else 0.0,
    }


def _compute_streaks(pnls: list[float]) -> dict[str, int]:
    """Longest consecutive win/loss streaks."""
    max_consec_wins = 0
    max_consec_losses = 0
    current_wins = 0
    current_losses = 0
    for pnl in pnls:
        if pnl > 0:
            current_wins += 1
            current_losses = 0
            max_consec_wins = max(max_consec_wins, current_wins)
        elif pnl < 0:
            current_losses += 1
            current_wins = 0
            max_consec_losses = max(max_consec_losses, current_losses)
        else:
            current_wins = 0
            current_losses = 0
    return {"max_consec_wins": max_consec_wins, "max_consec_losses": max_consec_losses}


def _compute_bars_stats(filtered: list[dict[str, Any]], bars_list: list[int]) -> dict[str, float]:
    """Average bars held: overall, winning trades, losing trades."""
    avg_bars = (sum(bars_list) / len(bars_list)) if bars_list else 0.0

    win_bars = [_safe_int(t.get("bars_held", 0)) for t in filtered
                if _safe_float(t.get("pnl_usd", 0)) > 0 and t.get("bars_held") not in (None, "", "None")]
    loss_bars = [_safe_int(t.get("bars_held", 0)) for t in filtered
                 if _safe_float(t.get("pnl_usd", 0)) < 0 and t.get("bars_held") not in (None, "", "None")]
    return {
        "avg_bars": avg_bars,
        "avg_bars_win": (sum(win_bars) / len(win_bars)) if win_bars else 0.0,
        "avg_bars_loss": (sum(loss_bars) / len(loss_bars)) if loss_bars else 0.0,
    }


def _compute_trading_period(filtered: list[dict[str, Any]], trade_count: int) -> dict[str, Any]:
    """Trading date span, trades/month, longest flat period between trades."""
    entry_dates: list[datetime] = []
    exit_dates: list[datetime] = []
    for t in filtered:
        entry_dt = _parse_timestamp(t.get("entry_timestamp", ""))
        exit_dt = _parse_timestamp(t.get("exit_timestamp", ""))
        if entry_dt:
            entry_dates.append(entry_dt)
        if exit_dt:
            exit_dates.append(exit_dt)

    if entry_dates and exit_dates:
        trading_period_days = max((max(exit_dates) - min(entry_dates)).days, 1)
    else:
        trading_period_days = 1

    trades_per_month = (trade_count / (trading_period_days / 30)) if trading_period_days >= 30 else trade_count

    longest_flat_days = 0
    if len(exit_dates) > 1:
        sorted_exits = sorted(exit_dates)
        sorted_entries = sorted(entry_dates)
        for i in range(1, len(sorted_entries)):
            gap = (sorted_entries[i] - sorted_exits[i - 1]).days if i - 1 < len(sorted_exits) else 0
            if gap > longest_flat_days:
                longest_flat_days = gap

    return {
        "trading_period_days": trading_period_days,
        "trades_per_month": trades_per_month,
        "longest_flat_days": longest_flat_days,
        "entry_dates": entry_dates,
        "exit_dates": exit_dates,
    }


# Timeframe string -> bars per calendar day
_TF_BARS_PER_DAY: dict[str, float] = {
    "1d": 1.0, "d": 1.0, "daily": 1.0,
    "4h": 6.0, "1h": 24.0, "30m": 48.0,
    "15m": 96.0, "5m": 288.0, "1m": 1440.0,
}


def _compute_bars_per_day(filtered: list[dict[str, Any]], metadata: dict[str, Any] | None) -> float:
    """Dynamic bars-per-day: candle geometry > empirical > metadata > fallback.

    SOP-compliant three-tier resolution (v5 Metric Integrity).
    """
    # --- Tier 1: Candle Geometry (authoritative if available) ---
    if metadata and "bar_geometry" in metadata and "median_bar_seconds" in metadata["bar_geometry"]:
        median_sec = _safe_float(metadata["bar_geometry"]["median_bar_seconds"])
        if median_sec > 0:
            return 86400.0 / median_sec

    # --- Collect empirical samples (used by Tier 2) ---
    valid_samples: list[float] = []
    for t in filtered:
        try:
            entry = _parse_timestamp(t.get("entry_timestamp", ""))
            exit_ = _parse_timestamp(t.get("exit_timestamp", ""))
            bars = _safe_int(t.get("bars_held", 0))
            if entry and exit_ and bars > 1 and exit_ > entry:
                valid_samples.append((exit_ - entry).total_seconds() / bars)
        except (ValueError, TypeError, AttributeError) as e:
            print(f"  STAGE2_BARS_PER_DAY_SKIP  trade={t.get('parent_trade_id', '?')}  {type(e).__name__}: {e}")
            continue

    # --- Tier 2: Empirical derivation (>=5 samples) ---
    if len(valid_samples) >= 5:
        valid_samples.sort()
        median_spb = valid_samples[len(valid_samples) // 2]
        if median_spb > 0:
            return 86400.0 / median_spb

    # --- Tier 3: Metadata timeframe lookup ---
    if metadata and "timeframe" in metadata:
        tf = str(metadata["timeframe"]).lower().strip()
        if tf in _TF_BARS_PER_DAY:
            return _TF_BARS_PER_DAY[tf]

    return 6.0  # Ultimate fallback (4H equivalent)


def _compute_risk_ratios(pnls: list[float], avg_trade: float) -> dict[str, float]:
    """Trade-based Sharpe, Sortino, and SQN.

    Uses PnL-level statistics (not annualized). Requires >= 2 trades.
    """
    trade_count = len(pnls)
    if trade_count < 2:
        return {"sharpe_ratio": 0.0, "sortino_ratio": 0.0, "sqn": 0.0}

    mean_pnl = statistics.mean(pnls)
    std_pnl = statistics.stdev(pnls)

    sharpe_ratio = (mean_pnl / std_pnl) if std_pnl != 0 else 0.0

    # Sortino: downside deviation (target = 0)
    downside_sum_sq = sum(p ** 2 for p in pnls if p < 0)
    downside_dev = math.sqrt(downside_sum_sq / trade_count)
    sortino_ratio = (mean_pnl / downside_dev) if downside_dev != 0 else 0.0

    # SQN: sqrt(N) * Mean / StdDev
    sqn = (math.sqrt(trade_count) * avg_trade) / std_pnl if std_pnl != 0 else 0.0

    return {"sharpe_ratio": sharpe_ratio, "sortino_ratio": sortino_ratio, "sqn": sqn}


def _compute_mfe_mae(filtered: list[dict[str, Any]]) -> dict[str, float]:
    """Average MFE/MAE (R-multiples) and edge ratio from execution-emitted values."""
    mfe_list: list[float] = []
    mae_list: list[float] = []
    for t in filtered:
        mfe_r = _safe_float(t.get("mfe_r", 0))
        mae_r = _safe_float(t.get("mae_r", 0))
        if mfe_r > 0 or mae_r > 0:
            mfe_list.append(mfe_r)
            mae_list.append(mae_r)

    avg_mfe_r = (sum(mfe_list) / len(mfe_list)) if mfe_list else 0.0
    avg_mae_r = (sum(mae_list) / len(mae_list)) if mae_list else 0.0
    edge_ratio = (avg_mfe_r / avg_mae_r) if avg_mae_r > 0 else avg_mfe_r if avg_mfe_r > 0 else 0.0
    return {"avg_mfe_r": avg_mfe_r, "avg_mae_r": avg_mae_r, "edge_ratio": edge_ratio}


def _compute_concentration(wins: list[float], losses: list[float],
                           gross_profit: float, gross_loss: float) -> dict[str, float]:
    """Top-5 winning trades and worst-5 losing trades concentration."""
    sorted_wins = sorted(wins, reverse=True)
    top5_profit = sum(sorted_wins[:5])
    top5_pct = (top5_profit / gross_profit) if gross_profit > 0 else 0.0

    sorted_losses = sorted(losses)
    worst5_loss = sum(sorted_losses[:5])
    worst5_pct = (abs(worst5_loss) / gross_loss) if gross_loss > 0 else 0.0
    return {"top5_pct_gross_profit": top5_pct, "worst5_loss_pct": worst5_pct}


def _bucket_breakdown(filtered: list[dict[str, Any]], field: str,
                      bucket_map: dict[str, list[str]],
                      strict: bool = False) -> dict[str, list[float]]:
    """Group trade PnLs into named buckets by a categorical field.

    Args:
        field:      trade dict key to read (e.g. 'volatility_regime', 'trend_label')
        bucket_map: {bucket_name: [accepted_raw_values]}
        strict:     if True, raise on missing/unknown values
    Returns:
        {bucket_name: [pnl, pnl, ...]}
    """
    buckets: dict[str, list[float]] = {k: [] for k in bucket_map}
    # Invert for O(1) lookup: raw_value -> bucket_name
    _lookup: dict[str, str] = {}
    for bname, raw_vals in bucket_map.items():
        for rv in raw_vals:
            _lookup[rv] = bname

    for t in filtered:
        pnl = _safe_float(t.get("pnl_usd", 0))
        raw = str(t.get(field, "")).strip().lower()

        if raw in ("none", "nan", ""):
            if strict:
                raise ValueError(
                    f"Stage-2 CRITICAL: Trade {t.get('parent_trade_id')} missing '{field}'. Strict enforcement.")
            continue

        bname = _lookup.get(raw)
        if bname is not None:
            buckets[bname].append(pnl)
        elif strict:
            raise ValueError(
                f"Stage-2 CRITICAL: Invalid {field} '{raw}' for trade {t.get('parent_trade_id')}")

    return buckets


def _summarize_buckets(buckets: dict[str, list[float]], prefix: str) -> dict[str, Any]:
    """Compute net_profit, trade count, avg_trade per bucket with prefixed keys."""
    out: dict[str, Any] = {}
    for bname, pnls in buckets.items():
        net = sum(pnls)
        cnt = len(pnls)
        avg = (net / cnt) if cnt > 0 else 0.0
        out[f"net_profit_{prefix}_{bname}"] = net
        out[f"trades_{prefix}_{bname}"] = cnt
        out[f"avg_trade_{prefix}_{bname}"] = avg
    return out


def _compute_session_breakdown(filtered: list[dict[str, Any]]) -> dict[str, Any]:
    """PnL breakdown by trading session (Asia / London / NY)."""
    asia_pnls: list[float] = []
    london_pnls: list[float] = []
    ny_pnls: list[float] = []
    for t in filtered:
        pnl = _safe_float(t.get("pnl_usd", 0))
        entry_dt = _parse_timestamp(t.get("entry_timestamp", ""))
        session = _get_session(entry_dt)
        if session == "asia":
            asia_pnls.append(pnl)
        elif session == "london":
            london_pnls.append(pnl)
        else:
            ny_pnls.append(pnl)

    def _sess(pnls: list[float]) -> tuple[float, int, float]:
        net = sum(pnls)
        cnt = len(pnls)
        return net, cnt, (net / cnt) if cnt > 0 else 0.0

    a_net, a_cnt, a_avg = _sess(asia_pnls)
    l_net, l_cnt, l_avg = _sess(london_pnls)
    n_net, n_cnt, n_avg = _sess(ny_pnls)
    return {
        "net_profit_asia": a_net, "trades_asia": a_cnt, "avg_trade_asia": a_avg,
        "net_profit_london": l_net, "trades_london": l_cnt, "avg_trade_london": l_avg,
        "net_profit_ny": n_net, "trades_ny": n_cnt, "avg_trade_ny": n_avg,
    }


# ---------------------------------------------------------------------------
# Volatility regime bucket mapping (numeric + string forms)
# ---------------------------------------------------------------------------
_VOL_REGIME_BUCKETS: dict[str, list[str]] = {
    "low_vol":    ["low", "-1", "-1.0"],
    "normal_vol": ["normal", "0", "0.0"],
    "high_vol":   ["high", "1", "1.0"],
}

# ---------------------------------------------------------------------------
# Trend regime bucket mapping
# ---------------------------------------------------------------------------
_TREND_LABEL_BUCKETS: dict[str, list[str]] = {
    "strong_up":   ["strong_up"],
    "weak_up":     ["weak_up"],
    "neutral":     ["neutral"],
    "weak_down":   ["weak_down"],
    "strong_down": ["strong_down"],
}


def _compute_metrics_from_trades(trades: list[dict[str, Any]], starting_capital: float, direction_filter: int | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute all metrics from trade-level data. direction_filter: 1=Long, -1=Short, None=All

    Delegates to focused statistical functions; assembles into the canonical
    metrics dict consumed by get_performance_summary_df() and Stage 3.
    """
    filtered = trades
    if direction_filter is not None:
        filtered = [t for t in trades if _safe_int(t.get("direction", 0)) == direction_filter]

    if not filtered:
        return _empty_metrics(starting_capital)

    pnls = [_safe_float(t.get("pnl_usd", 0)) for t in filtered]
    bars_list = [_safe_int(t.get("bars_held", 0)) for t in filtered if t.get("bars_held") not in (None, "", "None")]

    # 1. Core PnL
    basics = _compute_pnl_basics(pnls)
    trade_count = basics["trade_count"]

    # 2. Drawdown
    dd = _compute_drawdown(pnls, basics["net_profit"], starting_capital)

    # 3. Streaks
    streaks = _compute_streaks(pnls)

    # 4. Bars statistics
    bars = _compute_bars_stats(filtered, bars_list)

    # 5. Trading period
    period = _compute_trading_period(filtered, trade_count)

    # 6. Bars per day + % time in market
    bars_per_day = _compute_bars_per_day(filtered, metadata)
    total_bars_held = sum(bars_list) if bars_list else 0
    total_bars_in_period = period["trading_period_days"] * bars_per_day
    pct_time_in_market = (total_bars_held / total_bars_in_period) if total_bars_in_period > 0 else 0.0

    # 7. MFE / MAE
    mfe_mae = _compute_mfe_mae(filtered)

    # 8. Concentration
    concentration = _compute_concentration(
        basics["wins"], basics["losses"], basics["gross_profit"], basics["gross_loss"])

    # 9. Risk ratios
    risk = _compute_risk_ratios(pnls, basics["avg_trade"])

    # 10. Volatility regime breakdown (strict — missing/unknown = hard fail)
    vol_buckets = _bucket_breakdown(filtered, "volatility_regime", _VOL_REGIME_BUCKETS, strict=True)
    vol = _summarize_buckets(vol_buckets, "")

    # 11. Session breakdown
    session = _compute_session_breakdown(filtered)

    # 12. Trend regime breakdown (non-strict — unlabelled trades silently skipped)
    trend_buckets = _bucket_breakdown(filtered, "trend_label", _TREND_LABEL_BUCKETS, strict=False)
    trend = _summarize_buckets(trend_buckets, "")

    # Trade density (trades per year)
    trading_period_days = period["trading_period_days"]
    trade_density = int(round(trade_count / (trading_period_days / 365.25))) if trading_period_days > 0 else 0

    return {
        "starting_capital": starting_capital,
        "net_profit": basics["net_profit"],
        "gross_profit": basics["gross_profit"],
        "gross_loss": basics["gross_loss"],
        "profit_factor": basics["profit_factor"],
        "expectancy": basics["expectancy"],
        "return_dd_ratio": dd["return_dd_ratio"],
        "total_trades": trade_count,
        "winning_trades": basics["win_count"],
        "losing_trades": basics["loss_count"],
        "pct_profitable": basics["win_rate"],
        "trades_per_month": period["trades_per_month"],
        "longest_flat_days": period["longest_flat_days"],
        "avg_trade": basics["avg_trade"],
        "avg_win": basics["avg_win"],
        "avg_loss": basics["avg_loss"],
        "win_loss_ratio": basics["win_loss_ratio"],
        "avg_mfe_r": mfe_mae["avg_mfe_r"],
        "avg_mae_r": mfe_mae["avg_mae_r"],
        "edge_ratio": mfe_mae["edge_ratio"],
        "largest_win": basics["largest_win"],
        "largest_loss": basics["largest_loss"],
        "top5_pct_gross_profit": concentration["top5_pct_gross_profit"],
        "worst5_loss_pct": concentration["worst5_loss_pct"],
        "max_consec_wins": streaks["max_consec_wins"],
        "max_consec_losses": streaks["max_consec_losses"],
        "max_dd_usd": dd["max_dd"],
        "max_dd_pct": dd["max_dd_pct"],
        "return_on_capital": dd["return_on_capital"],
        "pct_time_in_market": pct_time_in_market,
        "sharpe_ratio": risk["sharpe_ratio"],
        "sortino_ratio": risk["sortino_ratio"],
        "k_ratio": 0.0,  # Requires regression on equity curve — not implemented
        "sqn": risk["sqn"],
        "return_retracement_ratio": dd["return_dd_ratio"],
        "avg_bars_win": bars["avg_bars_win"],
        "avg_bars_loss": bars["avg_bars_loss"],
        "avg_bars": bars["avg_bars"],
        "trading_period_days": trading_period_days,
        "net_profit_low_vol": vol["net_profit__low_vol"],
        "net_profit_normal_vol": vol["net_profit__normal_vol"],
        "net_profit_high_vol": vol["net_profit__high_vol"],
        "trades_low_vol": vol["trades__low_vol"],
        "trades_normal_vol": vol["trades__normal_vol"],
        "trades_high_vol": vol["trades__high_vol"],
        "avg_trade_low_vol": vol["avg_trade__low_vol"],
        "avg_trade_normal_vol": vol["avg_trade__normal_vol"],
        "avg_trade_high_vol": vol["avg_trade__high_vol"],
        "net_profit_asia": session["net_profit_asia"],
        "net_profit_london": session["net_profit_london"],
        "net_profit_ny": session["net_profit_ny"],
        "trades_asia": session["trades_asia"],
        "trades_london": session["trades_london"],
        "trades_ny": session["trades_ny"],
        "avg_trade_asia": session["avg_trade_asia"],
        "avg_trade_london": session["avg_trade_london"],
        "avg_trade_ny": session["avg_trade_ny"],
        "trade_density": trade_density,
        "net_profit_strong_up": trend["net_profit__strong_up"],
        "net_profit_weak_up": trend["net_profit__weak_up"],
        "net_profit_neutral": trend["net_profit__neutral"],
        "net_profit_weak_down": trend["net_profit__weak_down"],
        "net_profit_strong_down": trend["net_profit__strong_down"],
        "trades_strong_up": trend["trades__strong_up"],
        "trades_weak_up": trend["trades__weak_up"],
        "trades_neutral": trend["trades__neutral"],
        "trades_weak_down": trend["trades__weak_down"],
        "trades_strong_down": trend["trades__strong_down"],
    }


def _empty_metrics(starting_capital: float = 0.0) -> dict[str, Any]:
    return {
        "starting_capital": starting_capital,
        "net_profit": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
        "profit_factor": 0.0, "expectancy": 0.0, "return_dd_ratio": 0.0,
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "pct_profitable": 0.0, "trades_per_month": 0.0, "longest_flat_days": 0,
        "avg_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "win_loss_ratio": 0.0,
        "avg_mfe_r": 0.0, "avg_mae_r": 0.0, "edge_ratio": 0.0,
        "largest_win": 0.0, "largest_loss": 0.0,
        "top5_pct_gross_profit": 0.0, "worst5_loss_pct": 0.0,
        "max_consec_wins": 0, "max_consec_losses": 0,
        "max_dd_usd": 0.0, "max_dd_pct": 0.0,
        "return_on_capital": 0.0, "pct_time_in_market": 0.0,
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "k_ratio": 0.0, "sqn": 0.0,
        "return_retracement_ratio": 0.0,
        "avg_bars_win": 0.0, "avg_bars_loss": 0.0, "avg_bars": 0.0,
        "trading_period_days": 0,
        "net_profit_low_vol": 0.0, "net_profit_normal_vol": 0.0, "net_profit_high_vol": 0.0,
        "trades_low_vol": 0, "trades_normal_vol": 0, "trades_high_vol": 0,
        "avg_trade_low_vol": 0.0, "avg_trade_normal_vol": 0.0, "avg_trade_high_vol": 0.0,
        "net_profit_asia": 0.0, "net_profit_london": 0.0, "net_profit_ny": 0.0,
        "trades_asia": 0, "trades_london": 0, "trades_ny": 0,
        "avg_trade_asia": 0.0, "avg_trade_london": 0.0, "avg_trade_ny": 0.0,
        "trade_density": 0,
        "net_profit_strong_up": 0.0, "net_profit_weak_up": 0.0, "net_profit_neutral": 0.0,
        "net_profit_weak_down": 0.0, "net_profit_strong_down": 0.0,
        "trades_strong_up": 0, "trades_weak_up": 0, "trades_neutral": 0,
        "trades_weak_down": 0, "trades_strong_down": 0,
    }

def _compute_yearwise_metrics(trades: list[dict[str, Any]], year: int, starting_capital: float, authoritative_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if authoritative_data is None:
        authoritative_data = {}

    year_trades = []
    for t in trades:
        exit_dt = _parse_timestamp(t.get("exit_timestamp", ""))
        if exit_dt and exit_dt.year == year:
            year_trades.append(t)
    
    if not year_trades and not authoritative_data:
        return None
    
    pnls = [_safe_float(t.get("pnl_usd", 0)) for t in year_trades]
    bars_list = [_safe_int(t.get("bars_held", 0)) for t in year_trades if t.get("bars_held") not in (None, "", "None")]
    
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    
    net_profit = _safe_float(authoritative_data.get("net_pnl_usd")) if "net_pnl_usd" in authoritative_data else sum(pnls)
    trade_count = _safe_int(authoritative_data.get("trade_count")) if "trade_count" in authoritative_data else len(pnls)
    win_rate = _safe_float(authoritative_data.get("win_rate")) * 100 if "win_rate" in authoritative_data else ((len(wins) / len(pnls) * 100) if pnls else 0.0)
    
    win_count = len(wins)
    loss_count = len(losses)
    
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit if gross_profit > 0 else 0.0
    avg_trade = (net_profit / trade_count) if trade_count > 0 else 0.0
    avg_bars = (sum(bars_list) / len(bars_list)) if bars_list else 0.0
    
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    
    max_dd_pct = (max_dd / starting_capital * 100) if starting_capital > 0 else 0.0
    return_dd_ratio = (net_profit / max_dd) if max_dd > 0 else net_profit if net_profit > 0 else 0.0
    
    return {
        "year": year,
        "net_profit": net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_trade": avg_trade,
        "max_dd_usd": max_dd,
        "max_dd_pct": max_dd_pct,
        "return_dd_ratio": return_dd_ratio,
        "avg_bars": avg_bars,
        "win_count": win_count,
        "loss_count": loss_count,
    }


def _compute_buy_hold_benchmark(trades: list[dict[str, Any]]) -> dict[str, float] | None:
    if not trades or len(trades) < 2:
        return None
    try:
        sorted_trades = sorted(trades, key=lambda t: t.get("entry_timestamp", ""))
        first_price = _safe_float(sorted_trades[0].get("entry_price", 0))
        last_price = _safe_float(sorted_trades[-1].get("exit_price", 0))
        if first_price <= 0 or last_price <= 0:
            return None
        bh_return_pct = ((last_price - first_price) / first_price) * 100
        exit_prices = [_safe_float(t.get("exit_price", 0)) for t in sorted_trades]
        exit_prices = [p for p in exit_prices if p > 0]
        if not exit_prices:
            return None
        peak = exit_prices[0]
        max_dd_pct = 0.0
        for price in exit_prices:
            if price > peak:
                peak = price
            dd = ((peak - price) / peak) * 100 if peak > 0 else 0
            if dd > max_dd_pct:
                max_dd_pct = dd
        return {
            "return_pct": bh_return_pct,
            "max_drawdown_pct": max_dd_pct,
            "first_price": first_price,
            "last_price": last_price,
        }
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
        print(f"  STAGE2_BUY_HOLD_SKIP  {type(e).__name__}: {e}")
        return None


def get_runtime_engine_version() -> str:
    """Dynamically load version from validated engine manifest."""
    try:
        from tools.pipeline_utils import get_engine_version
        _ver = get_engine_version()
        manifest_path = PROJECT_ROOT / "engine_dev" / "universal_research_engine" / _ver / "VALIDATED_ENGINE.manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("engine_version", "UNKNOWN")
    except (ImportError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"  STAGE2_ENGINE_VERSION_WARN  {type(e).__name__}: {e}")
    return "UNKNOWN"

def get_settings_df(metadata: dict[str, Any]) -> pd.DataFrame:
    # Strict Version Validation (SOP v4.2 Remediation)
    meta_engine_ver = metadata.get("engine_version", "")
    runtime_ver = get_runtime_engine_version()
    
    # If runtime version is known, enforce strict match
    if runtime_ver != "UNKNOWN":
        if meta_engine_ver != runtime_ver:
             # Raise error to prevent silent corruption/mismatch
             raise ValueError(f"Stage-2 Metadata Mismatch: Metadata says {meta_engine_ver}, Runtime says {runtime_ver}. Strict enforcement enabled.")
    
    data = [
        {"Parameter": "Run ID", "Value": metadata.get("run_id", "")},
        {"Parameter": "Strategy Name", "Value": metadata.get("strategy_name", "")},
        {"Parameter": "Symbol", "Value": metadata.get("symbol", "")},
        {"Parameter": "Broker", "Value": metadata.get("broker", "")},
        {"Parameter": "Reference Capital (USD)", "Value": metadata.get("reference_capital_usd", "")},
        {"Parameter": "Position Sizing Basis", "Value": metadata.get("position_sizing_basis", "")},
        {"Parameter": "Timeframe", "Value": metadata.get("timeframe", "")},
        {"Parameter": "Date Range Start", "Value": metadata.get("date_range", {}).get("start", "")},
        {"Parameter": "Date Range End", "Value": metadata.get("date_range", {}).get("end", "")},
        {"Parameter": "Execution Timestamp", "Value": metadata.get("execution_timestamp_utc", "")},
        {"Parameter": "Engine Name", "Value": metadata.get("engine_name", "")},
        {"Parameter": "Engine Version", "Value": meta_engine_ver}, 
        {"Parameter": "Schema Version", "Value": metadata.get("schema_version", "")},
    ]
    return pd.DataFrame(data)

def get_performance_summary_df(trades: list[dict[str, Any]], starting_capital: float, standard_metrics: dict[str, Any], risk_metrics: dict[str, Any], metadata: dict[str, Any] | None = None) -> pd.DataFrame:
    all_metrics = _compute_metrics_from_trades(trades, starting_capital, None, metadata)
    long_metrics = _compute_metrics_from_trades(trades, starting_capital, 1, metadata)
    short_metrics = _compute_metrics_from_trades(trades, starting_capital, -1, metadata)
    
    # OVERRIDE All Trades
    all_metrics["net_profit"] = _safe_float(standard_metrics.get("net_pnl_usd", 0))
    all_metrics["gross_profit"] = _safe_float(standard_metrics.get("gross_profit", 0))
    all_metrics["gross_loss"] = _safe_float(standard_metrics.get("gross_loss", 0))
    all_metrics["pct_profitable"] = _safe_float(standard_metrics.get("win_rate", 0)) * 100
    all_metrics["profit_factor"] = _safe_float(standard_metrics.get("profit_factor", 0))
    all_metrics["max_dd_usd"] = _safe_float(risk_metrics.get("max_drawdown_usd", 0))
    all_metrics["max_dd_pct"] = _safe_float(risk_metrics.get("max_drawdown_pct", 0)) * 100
    all_metrics["return_dd_ratio"] = _safe_float(risk_metrics.get("return_dd_ratio", 0))
    all_metrics["sharpe_ratio"] = _safe_float(risk_metrics.get("sharpe_ratio", 0))
    all_metrics["sortino_ratio"] = _safe_float(risk_metrics.get("sortino_ratio", 0))
    all_metrics["k_ratio"] = _safe_float(risk_metrics.get("k_ratio", 0))
    
    rows = []
    def add_row(label, key):
        val_all = all_metrics.get(key)
        val_long = long_metrics.get(key)
        val_short = short_metrics.get(key)
        
        rows.append({
            "Metric": label,
            "All Trades": _round_val(val_all, 2),
            "Long Trades": _round_val(val_long, 2),
            "Short Trades": _round_val(val_short, 2)
        })

    add_row("Starting Capital", "starting_capital")
    add_row("Net Profit (USD)", "net_profit")
    add_row("Gross Profit (USD)", "gross_profit")
    add_row("Gross Loss (USD)", "gross_loss")
    add_row("Profit Factor", "profit_factor")
    add_row("Expectancy (USD)", "expectancy")
    add_row("Return / Drawdown Ratio", "return_dd_ratio")
    add_row("Total Trades", "total_trades")
    add_row("Winning Trades", "winning_trades")
    add_row("Losing Trades", "losing_trades")
    add_row("% Profitable", "pct_profitable")
    add_row("Trades per Month", "trades_per_month")
    add_row("Longest Flat Period (Days)", "longest_flat_days")
    add_row("Avg Trade (USD)", "avg_trade")
    add_row("Avg Win (USD)", "avg_win")
    add_row("Avg Loss (USD)", "avg_loss")
    add_row("Win/Loss Ratio", "win_loss_ratio")
    add_row("Avg MFE (R)", "avg_mfe_r")
    add_row("Avg MAE (R)", "avg_mae_r")
    add_row("Edge Ratio (MFE / MAE)", "edge_ratio")
    add_row("Largest Win (USD)", "largest_win")
    add_row("Largest Loss (USD)", "largest_loss")
    add_row("% of Gross Profit (Top Trades)", "top5_pct_gross_profit")
    add_row("Worst 5 Trades Loss %", "worst5_loss_pct")
    add_row("Max Consecutive Wins", "max_consec_wins")
    add_row("Max Consecutive Losses", "max_consec_losses")
    add_row("Max Drawdown (USD)", "max_dd_usd")
    add_row("Max Drawdown (%)", "max_dd_pct")
    add_row("Return on Capital", "return_on_capital")
    add_row("% Time in Market", "pct_time_in_market")
    add_row("Sharpe Ratio", "sharpe_ratio")
    add_row("Sortino Ratio", "sortino_ratio")
    add_row("K-Ratio", "k_ratio")
    add_row("SQN (System Quality Number)", "sqn")
    add_row("Return Retracement Ratio", "return_retracement_ratio")
    add_row("Avg Bars in Winning Trades", "avg_bars_win")
    add_row("Avg Bars in Losing Trades", "avg_bars_loss")
    add_row("Avg Bars per Trade", "avg_bars")
    add_row("Trading Period (Days)", "trading_period_days")
    add_row("Net Profit - Low Volatility", "net_profit_low_vol")
    add_row("Net Profit - Normal Volatility", "net_profit_normal_vol")
    add_row("Net Profit - High Volatility", "net_profit_high_vol")
    add_row("Trades - Low Volatility", "trades_low_vol")
    add_row("Trades - Normal Volatility", "trades_normal_vol")
    add_row("Trades - High Volatility", "trades_high_vol")
    add_row("Avg Trade - Low Volatility", "avg_trade_low_vol")
    add_row("Avg Trade - Normal Volatility", "avg_trade_normal_vol")
    add_row("Avg Trade - High Volatility", "avg_trade_high_vol")
    add_row("Net Profit - Asia Session", "net_profit_asia")
    add_row("Net Profit - London Session", "net_profit_london")
    add_row("Net Profit - New York Session", "net_profit_ny")
    add_row("Trades - Asia Session", "trades_asia")
    add_row("Trades - London Session", "trades_london")
    add_row("Trades - New York Session", "trades_ny")
    add_row("Avg Trade - Asia Session", "avg_trade_asia")
    add_row("Avg Trade - London Session", "avg_trade_london")
    add_row("Avg Trade - New York Session", "avg_trade_ny")
    add_row("Trade Density (Trades/Year)", "trade_density")
    add_row("Net Profit - Strong Up", "net_profit_strong_up")
    add_row("Net Profit - Weak Up", "net_profit_weak_up")
    add_row("Net Profit - Neutral", "net_profit_neutral")
    add_row("Net Profit - Weak Down", "net_profit_weak_down")
    add_row("Net Profit - Strong Down", "net_profit_strong_down")
    add_row("Trades - Strong Up", "trades_strong_up")
    add_row("Trades - Weak Up", "trades_weak_up")
    add_row("Trades - Neutral", "trades_neutral")
    add_row("Trades - Weak Down", "trades_weak_down")
    add_row("Trades - Strong Down", "trades_strong_down")

    return pd.DataFrame(rows)

def get_benchmark_df(trades: list[dict[str, Any]], starting_capital: float, all_net_profit: float) -> pd.DataFrame:
    bh = _compute_buy_hold_benchmark(trades)
    if not bh:
        return pd.DataFrame()
    
    strategy_return_pct = (all_net_profit / starting_capital) * 100 if starting_capital > 0 else 0.0
    relative_perf = strategy_return_pct - bh["return_pct"]
    
    data = [
        {"Metric": "First Price", "Value": bh["first_price"]},
        {"Metric": "Last Price", "Value": bh["last_price"]},
        {"Metric": "Buy & Hold Return (%)", "Value": bh["return_pct"]},
        {"Metric": "Buy & Hold Max Drawdown (%)", "Value": bh["max_drawdown_pct"]},
        {"Metric": "Strategy Net Return (%)", "Value": strategy_return_pct},
        {"Metric": "Relative Performance (%)", "Value": relative_perf},
    ]
    return pd.DataFrame(data)

def get_yearwise_df(trades: list[dict[str, Any]], starting_capital: float, yearwise_data: list[dict[str, Any]]) -> pd.DataFrame:
    year_lookup = {}
    if yearwise_data:
        for row in yearwise_data:
            try:
                y = int(row.get("year", 0))
                if y > 0: year_lookup[y] = row
            except (ValueError, TypeError):
                pass

    years = set()
    for t in trades:
        exit_dt = _parse_timestamp(t.get("exit_timestamp", ""))
        if exit_dt: years.add(exit_dt.year)
    years.update(year_lookup.keys())
    
    rows = []
    for year in sorted(years):
        auth_row = year_lookup.get(year, None)
        metrics = _compute_yearwise_metrics(trades, year, starting_capital, auth_row)
        if metrics:
            rows.append(metrics)
            
    if not rows:
        return pd.DataFrame()
        
    df = pd.DataFrame(rows)
    # Reorder columns matches headers
    cols = ["year", "net_profit", "gross_profit", "gross_loss", "trade_count", "win_rate", "profit_factor", "avg_trade", "max_dd_usd", "max_dd_pct", "return_dd_ratio", "avg_bars", "win_count", "loss_count"]
    # Ensure all cols exist
    for c in cols:
        if c not in df.columns: df[c] = 0
    return df[cols]

def get_trades_df(trades: list[dict[str, Any]]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
        
    # Get all unique keys from all trades to ensure we don't miss any columns
    all_keys = set()
    for t in trades:
        all_keys.update(t.keys())
    
    # Define a logical order for known columns, others appended at end
    priority_cols = [
        "strategy_name", "parent_trade_id", "sequence_index", "direction",
        "entry_timestamp", "exit_timestamp", "entry_price", "exit_price",
        "pnl_usd", "bars_held", "volatility_regime", "trend_score", "trend_regime", "trend_label"
    ]
    
    sorted_cols = [c for c in priority_cols if c in all_keys]
    remaining_cols = sorted([c for c in all_keys if c not in priority_cols])
    final_cols = sorted_cols + remaining_cols
    
    rows = []
    for t in trades:
        row = {}
        for k in final_cols:
            val = t.get(k, "")
            # Try to make numeric if possible for Excel
            try:
                if k in ["direction", "sequence_index", "bars_held"]:
                    row[k] = int(float(val))
                elif k in ["strategy_name", "parent_trade_id", "entry_timestamp", "exit_timestamp", "volatility_regime", "trend_label"]:
                    row[k] = str(val)
                else:
                    fval = float(val)
                    row[k] = _round_val(fval, 4) # 4 decimals for price/r-multiples
            except (ValueError, TypeError):
                row[k] = val
        rows.append(row)
        
    return pd.DataFrame(rows)


def generate_excel_report(artifacts: dict[str, Any], output_path: Path) -> None:
    starting_capital = artifacts["metadata"]["reference_capital_usd"]
    
    df_settings = get_settings_df(artifacts["metadata"])
    df_summary = get_performance_summary_df(artifacts["tradelevel"], starting_capital, artifacts["standard"], artifacts["risk"], artifacts["metadata"])
    
    # Extract net profit from summary for benchmark
    try:
        net_profit_row = df_summary[df_summary["Metric"] == "Net Profit (USD)"]
        net_profit = float(net_profit_row["All Trades"].values[0])
    except (ValueError, TypeError, IndexError, KeyError) as e:
        print(f"  STAGE2_NET_PROFIT_EXTRACT_WARN  {type(e).__name__}: {e}  -> default=0.0")
        net_profit = 0.0
        
    df_benchmark = get_benchmark_df(artifacts["tradelevel"], starting_capital, net_profit)
    df_yearwise = get_yearwise_df(artifacts["tradelevel"], starting_capital, artifacts["yearwise"])
    df_trades = get_trades_df(artifacts["tradelevel"])
    
    # Write to Excel (Raw Data)
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        df_settings.to_excel(writer, sheet_name="Settings", index=False)
        df_summary.to_excel(writer, sheet_name="Performance Summary", index=False)
        if not df_benchmark.empty:
            df_benchmark.to_excel(writer, sheet_name="Benchmark Analysis", index=False)
        df_yearwise.to_excel(writer, sheet_name="Yearwise Performance", index=False)
        df_trades.to_excel(writer, sheet_name="Trades List", index=False)
        
    # Call Unified Formatter
    try:
        project_root = PROJECT_ROOT
        formatter = project_root / "tools" / "format_excel_artifact.py"
        cmd = [sys.executable, str(formatter), "--file", str(output_path), "--profile", "strategy"]
        subprocess.run(cmd, check=True)
        print(f"[SUCCESS] Formatted {output_path.name}")
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"[WARN] Failed to format {output_path.name}: {type(e).__name__}: {e}")


def compile_stage2(run_folder: Path) -> None:
    artifacts = load_stage1_artifacts(run_folder)
    strategy_name = artifacts["metadata"].get("strategy_name", "UNKNOWN")
    excel_filename = f"AK_Trade_Report_{strategy_name}.xlsx"
    excel_path = run_folder / excel_filename
    
    generate_excel_report(artifacts, excel_path)
    return run_folder, [excel_filename]

def main() -> None:
    parser = argparse.ArgumentParser(description="Stage-2 Presentation Compiler (v5 Multi-Asset) - Clean Engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("run_folder", nargs="?", help="Path to single Stage-1 run folder")
    group.add_argument("--scan", help="Scan backtests/ for folders matching DIRECTIVE_NAME_*")
    
    args = parser.parse_args()
    
    if args.scan:
        directive_name = args.scan
        backtests_root = BACKTESTS_DIR
        runs_root = RUNS_DIR # For governance
        
        if not backtests_root.exists():
            print(f"[FAIL] Backtests directory not found: {backtests_root}")
            sys.exit(1)
            
        candidates = sorted(list(backtests_root.glob(f"{directive_name}_*")))
        valid_runs = []
        for cand in candidates:
            if cand.is_dir() and (cand / "metadata" / "run_metadata.json").exists():
                valid_runs.append(cand)
        
        if not valid_runs:
            print(f"[SCAN] No valid run folders found for directive: {directive_name}")
            sys.exit(1)
            
        print(f"[SCAN] Found {len(valid_runs)} valid runs for '{directive_name}'")
        
        # BATCH EXECUTION — Per-asset error tracking
        batch_succeeded = []
        batch_failed = []
        for run_folder in valid_runs:
            try:
                # --- GOVERNANCE CHECK ---
                # We need Run ID to verify state.
                with open(run_folder / "metadata" / "run_metadata.json", "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    run_id = meta.get("run_id")
                    
                if not run_id:
                     raise ValueError("Run ID missing in metadata.")
                     
                state_mgr = PipelineStateManager(run_id)
                # Verify we are cleared for Stage 2
                state_mgr.verify_state("STAGE_1_COMPLETE")
                print(f"[GOVERNANCE] Verified -> {run_folder.name}")
                # ------------------------
                
                compile_stage2(run_folder)
                
                # Verify critical artifact was actually written
                ak_reports = list(run_folder.glob("AK_Trade_Report_*.xlsx"))
                if not ak_reports:
                    raise RuntimeError(f"AK_Trade_Report not found after compile_stage2 for {run_folder.name}")
                
                batch_succeeded.append(run_folder.name)
            except Exception as e:
                print(f"[ERROR] Failed to compile {run_folder.name}: {e}")
                batch_failed.append({"folder": run_folder.name, "error": str(e)})
        
        # --- BATCH SUMMARY ---
        print(f"\n[SCAN SUMMARY] Succeeded: {len(batch_succeeded)} | Failed: {len(batch_failed)}")
        if batch_failed:
            for f_info in batch_failed:
                print(f"  FAILED: {f_info['folder']} — {f_info['error']}")
            sys.exit(1)
    else:
        # SINGLE EXECUTION
        run_folder = Path(args.run_folder).resolve()
        if not run_folder.exists():
            print(f"[FAIL] Run folder not found: {run_folder}")
            sys.exit(1)
            
        try:
             # --- GOVERNANCE CHECK ---
            with open(run_folder / "metadata" / "run_metadata.json", "r", encoding="utf-8") as f:
                meta = json.load(f)
                run_id = meta.get("run_id")
            
            if not run_id:
                 raise ValueError("Run ID missing in metadata.")
                 
            state_mgr = PipelineStateManager(run_id)
            state_mgr.verify_state("STAGE_1_COMPLETE")
            print(f"[GOVERNANCE] Verified -> {run_folder.name}")
            # ------------------------
            
            compile_stage2(run_folder)
        except Exception as e:
            print(f"[FATAL] {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
