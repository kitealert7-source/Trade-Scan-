"""
Metrics Core — Single Source of Truth for Trade-Level Metric Computation.

Extracted from stage2_compiler.py to enable reuse by:
  - stage2_compiler (AK Trade Report)
  - shadow_filter (what-if analysis)
  - report_generator (future direct computation)

All functions are pure: no I/O, no global state, no side effects beyond
diagnostic prints on invalid data. Every function preserves the original
stage2_compiler behavior exactly.

Authority: SOP_OUTPUT (metric definitions)
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any

__all__ = [
    # Public metric functions
    "compute_pnl_basics",
    "compute_drawdown",
    "compute_streaks",
    "compute_bars_stats",
    "compute_trading_period",
    "compute_bars_per_day",
    "compute_risk_ratios",
    "compute_k_ratio",
    "compute_mfe_mae",
    "compute_concentration",
    "bucket_breakdown",
    "summarize_buckets",
    "compute_session_breakdown",
    "compute_regime_age_breakdown",
    # Orchestrator
    "compute_metrics_from_trades",
    "empty_metrics",
    # Constants
    "ASIA_START",
    "ASIA_END",
    "LONDON_START",
    "LONDON_END",
    "NY_START",
    "NY_END",
    "TF_BARS_PER_DAY",
    "VOL_REGIME_BUCKETS",
    "TREND_LABEL_BUCKETS",
    "REGIME_AGE_BUCKETS",
]


# ==================================================================
# CONSTANTS
# ==================================================================

# Session boundaries (UTC hours)
ASIA_START, ASIA_END = 0, 8
LONDON_START, LONDON_END = 8, 16
NY_START, NY_END = 16, 24

# Timeframe string -> bars per calendar day
TF_BARS_PER_DAY: dict[str, float] = {
    "1d": 1.0, "d": 1.0, "daily": 1.0,
    "4h": 6.0, "1h": 24.0, "30m": 48.0,
    "15m": 96.0, "5m": 288.0, "1m": 1440.0,
}

# Volatility regime bucket mapping (numeric + string forms)
VOL_REGIME_BUCKETS: dict[str, list[str]] = {
    "low_vol":    ["low", "-1", "-1.0"],
    "normal_vol": ["normal", "0", "0.0"],
    "high_vol":   ["high", "1", "1.0"],
}

# Trend regime bucket mapping
TREND_LABEL_BUCKETS: dict[str, list[str]] = {
    "strong_up":   ["strong_up"],
    "weak_up":     ["weak_up"],
    "neutral":     ["neutral"],
    "weak_down":   ["weak_down"],
    "strong_down": ["strong_down"],
}

# Regime age bucket definitions: (display_label, min_age_inclusive, max_age_inclusive_or_None)
REGIME_AGE_BUCKETS: list[tuple[str, int, int | None]] = [
    ("Age 0",    0,  0),
    ("Age 1",    1,  1),
    ("Age 2",    2,  2),
    ("Age 3-5",  3,  5),
    ("Age 6-10", 6, 10),
    ("Age 11+", 11, None),
]


# ==================================================================
# UTILITIES
# ==================================================================

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


# ==================================================================
# CORE METRIC FUNCTIONS
# ==================================================================

def compute_pnl_basics(pnls: list[float]) -> dict[str, Any]:
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


def compute_drawdown(pnls: list[float], net_profit: float, starting_capital: float) -> dict[str, float]:
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


def compute_streaks(pnls: list[float]) -> dict[str, int]:
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


def compute_bars_stats(filtered: list[dict[str, Any]], bars_list: list[int]) -> dict[str, float]:
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


def compute_trading_period(filtered: list[dict[str, Any]], trade_count: int) -> dict[str, Any]:
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


def compute_bars_per_day(filtered: list[dict[str, Any]], metadata: dict[str, Any] | None) -> float:
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
        if tf in TF_BARS_PER_DAY:
            return TF_BARS_PER_DAY[tf]

    return 6.0  # Ultimate fallback (4H equivalent)


def compute_risk_ratios(pnls: list[float], avg_trade: float) -> dict[str, float]:
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


def compute_mfe_mae(filtered: list[dict[str, Any]]) -> dict[str, float]:
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


def compute_k_ratio(pnls: list[float]) -> float:
    """K-Ratio: OLS slope of cumulative equity curve / standard error of slope."""
    n = len(pnls)
    if n < 3:
        return 0.0

    cum = []
    s = 0.0
    for p in pnls:
        s += p
        cum.append(s)

    x_mean = (n - 1) / 2.0
    y_mean = sum(cum) / n

    ss_xx = sum((i - x_mean) ** 2 for i in range(n))
    ss_xy = sum((i - x_mean) * (cum[i] - y_mean) for i in range(n))

    slope = ss_xy / ss_xx if ss_xx > 0 else 0.0
    intercept = y_mean - slope * x_mean

    residuals_sq = sum((cum[i] - (slope * i + intercept)) ** 2 for i in range(n))
    mse = residuals_sq / max(1, (n - 2))

    se_slope = math.sqrt(mse / ss_xx) if ss_xx > 0 and mse > 0 else 0.0

    return (slope / se_slope) if se_slope > 0 else 0.0


def compute_concentration(wins: list[float], losses: list[float],
                          gross_profit: float, gross_loss: float) -> dict[str, float]:
    """Top-5 winning trades and worst-5 losing trades concentration."""
    sorted_wins = sorted(wins, reverse=True)
    top5_profit = sum(sorted_wins[:5])
    top5_pct = (top5_profit / gross_profit) if gross_profit > 0 else 0.0

    sorted_losses = sorted(losses)
    worst5_loss = sum(sorted_losses[:5])
    worst5_pct = (abs(worst5_loss) / gross_loss) if gross_loss > 0 else 0.0
    return {"top5_pct_gross_profit": top5_pct, "worst5_loss_pct": worst5_pct}


def bucket_breakdown(filtered: list[dict[str, Any]], field: str,
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


def summarize_buckets(buckets: dict[str, list[float]], prefix: str) -> dict[str, Any]:
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


def compute_session_breakdown(filtered: list[dict[str, Any]]) -> dict[str, Any]:
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


def compute_regime_age_breakdown(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-bucket statistics grouped by regime_age numeric ranges.

    Uses REGIME_AGE_BUCKETS for range definitions. Trades with missing or
    non-parseable regime_age are silently skipped (non-strict, consistent
    with trend_label handling). Metrics per bucket via compute_pnl_basics().

    Returns a list of records in REGIME_AGE_BUCKETS order with keys:
        label, trades, net_pnl, profit_factor, win_rate, avg_trade
    """
    bucket_pnls: list[list[float]] = [[] for _ in REGIME_AGE_BUCKETS]

    for t in trades:
        raw = t.get("regime_age")
        if raw in (None, "", "None", "nan"):
            continue
        try:
            age = int(float(raw))
        except (ValueError, TypeError):
            continue

        for idx, (_label, lo, hi) in enumerate(REGIME_AGE_BUCKETS):
            if age >= lo and (hi is None or age <= hi):
                bucket_pnls[idx].append(_safe_float(t.get("pnl_usd", 0)))
                break

    rows: list[dict[str, Any]] = []
    for (label, _lo, _hi), pnls in zip(REGIME_AGE_BUCKETS, bucket_pnls):
        if pnls:
            b = compute_pnl_basics(pnls)
            rows.append({
                "label":         label,
                "trades":        b["trade_count"],
                "net_pnl":       round(b["net_profit"], 2),
                "profit_factor": round(b["profit_factor"], 3),
                "win_rate":      round(b["win_rate"] * 100, 1),
                "avg_trade":     round(b["avg_trade"], 2),
            })
        else:
            rows.append({
                "label":         label,
                "trades":        0,
                "net_pnl":       0.0,
                "profit_factor": 0.0,
                "win_rate":      0.0,
                "avg_trade":     0.0,
            })
    return rows


# ==================================================================
# ORCHESTRATOR
# ==================================================================

def compute_metrics_from_trades(trades: list[dict[str, Any]], starting_capital: float, direction_filter: int | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute all metrics from trade-level data. direction_filter: 1=Long, -1=Short, None=All

    Delegates to focused statistical functions; assembles into the canonical
    metrics dict consumed by get_performance_summary_df() and Stage 3.
    """
    # --- Metadata presence guard (prevents silent bars_per_day drift) ---
    if metadata is None:
        print("  METRICS_CORE_WARN  metadata=None — bars_per_day will use empirical/fallback")

    filtered = trades
    if direction_filter is not None:
        filtered = [t for t in trades if _safe_int(t.get("direction", 0)) == direction_filter]

    if not filtered:
        return empty_metrics(starting_capital)

    pnls = [_safe_float(t.get("pnl_usd", 0)) for t in filtered]
    bars_list = [_safe_int(t.get("bars_held", 0)) for t in filtered if t.get("bars_held") not in (None, "", "None")]

    # 1. Core PnL
    basics = compute_pnl_basics(pnls)
    trade_count = basics["trade_count"]

    # 2. Drawdown
    dd = compute_drawdown(pnls, basics["net_profit"], starting_capital)

    # 3. Streaks
    streaks = compute_streaks(pnls)

    # 4. Bars statistics
    bars = compute_bars_stats(filtered, bars_list)

    # 5. Trading period
    period = compute_trading_period(filtered, trade_count)

    # 6. Bars per day + % time in market
    bars_per_day = compute_bars_per_day(filtered, metadata)
    total_bars_held = sum(bars_list) if bars_list else 0
    total_bars_in_period = period["trading_period_days"] * bars_per_day
    pct_time_in_market = (total_bars_held / total_bars_in_period) if total_bars_in_period > 0 else 0.0

    # 7. MFE / MAE
    mfe_mae = compute_mfe_mae(filtered)

    # 8. Concentration
    concentration = compute_concentration(
        basics["wins"], basics["losses"], basics["gross_profit"], basics["gross_loss"])

    # 9. Risk ratios
    risk = compute_risk_ratios(pnls, basics["avg_trade"])

    # 10. Volatility regime breakdown (strict — missing/unknown = hard fail)
    vol_buckets = bucket_breakdown(filtered, "volatility_regime", VOL_REGIME_BUCKETS, strict=True)
    vol = summarize_buckets(vol_buckets, "")

    # 11. Session breakdown
    session = compute_session_breakdown(filtered)

    # 12. Trend regime breakdown (non-strict — unlabelled trades silently skipped)
    trend_buckets = bucket_breakdown(filtered, "trend_label", TREND_LABEL_BUCKETS, strict=False)
    trend = summarize_buckets(trend_buckets, "")

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
        "k_ratio": compute_k_ratio(pnls),
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


def empty_metrics(starting_capital: float = 0.0) -> dict[str, Any]:
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
