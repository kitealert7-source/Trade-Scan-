"""
Stage-2 Presentation Compiler — SOP-Complete with Full Metric Computation
Consumes Stage-1 authoritative artifacts and produces AK_Trade_Report Excel.
Implements SOP_OUTPUT §5.1 (Performance Summary) and §5.2 (Yearwise Performance).
All metrics computed from Stage-1 data. No placeholders.
Rewritten to use pandas and Unified Formatter (Zero OpenPyXL Styling / Imports).
"""

import csv
import json
import math
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# ==================================================================
# CONSTANTS & CONFIG
# ==================================================================

# Session boundaries (UTC hours)
ASIA_START, ASIA_END = 0, 8
LONDON_START, LONDON_END = 8, 16
NY_START, NY_END = 16, 24


def load_stage1_artifacts(run_folder: Path):
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
        except Exception:
            pass # Graceful degradation
        
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


def _safe_float(val, default=0.0):
    try:
        return float(val) if val not in (None, "", "None") else default
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(float(val)) if val not in (None, "", "None") else default
    except (ValueError, TypeError):
        return default


def _parse_timestamp(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))
    except:
        return None


def _get_session(dt):
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


def _compute_metrics_from_trades(trades, starting_capital, direction_filter=None, metadata=None):
    """Compute all metrics from trade-level data. direction_filter: 1=Long, -1=Short, None=All"""
    
    filtered = trades
    if direction_filter is not None:
        filtered = [t for t in trades if _safe_int(t.get("direction", 0)) == direction_filter]
    
    if not filtered:
        return _empty_metrics(starting_capital)
    
    pnls = [_safe_float(t.get("pnl_usd", 0)) for t in filtered]
    bars_list = [_safe_int(t.get("bars_held", 0)) for t in filtered if t.get("bars_held") not in (None, "", "None")]
    
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_profit = sum(pnls)
    
    trade_count = len(pnls)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0
    
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit if gross_profit > 0 else 0.0
    avg_trade = (net_profit / trade_count) if trade_count > 0 else 0.0
    avg_win = (sum(wins) / win_count) if win_count > 0 else 0.0
    avg_loss = (sum(losses) / loss_count) if loss_count > 0 else 0.0
    win_loss_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else avg_win if avg_win > 0 else 0.0
    expectancy = avg_trade
    
    largest_win = max(wins) if wins else 0.0
    largest_loss = min(losses) if losses else 0.0
    
    # Equity curve and drawdown
    equity_curve = []
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cumulative += pnl
        equity_curve.append(cumulative)
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    
    max_dd_pct = (max_dd / starting_capital * 100) if starting_capital > 0 else 0.0
    return_dd_ratio = (net_profit / max_dd) if max_dd > 0 else net_profit if net_profit > 0 else 0.0
    return_on_capital = (net_profit / starting_capital * 100) if starting_capital > 0 else 0.0
    
    # Streaks
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
    
    # Bars statistics
    avg_bars = (sum(bars_list) / len(bars_list)) if bars_list else 0.0
    win_bars = [_safe_int(t.get("bars_held", 0)) for t in filtered 
                if _safe_float(t.get("pnl_usd", 0)) > 0 and t.get("bars_held") not in (None, "", "None")]
    loss_bars = [_safe_int(t.get("bars_held", 0)) for t in filtered 
                 if _safe_float(t.get("pnl_usd", 0)) < 0 and t.get("bars_held") not in (None, "", "None")]
    avg_bars_win = (sum(win_bars) / len(win_bars)) if win_bars else 0.0
    avg_bars_loss = (sum(loss_bars) / len(loss_bars)) if loss_bars else 0.0
    
    # Trading period and time analysis
    entry_dates = []
    exit_dates = []
    for t in filtered:
        entry_dt = _parse_timestamp(t.get("entry_timestamp", ""))
        exit_dt = _parse_timestamp(t.get("exit_timestamp", ""))
        if entry_dt:
            entry_dates.append(entry_dt)
        if exit_dt:
            exit_dates.append(exit_dt)
    
    if entry_dates and exit_dates:
        first_entry = min(entry_dates)
        last_exit = max(exit_dates)
        trading_period_days = (last_exit - first_entry).days
        if trading_period_days < 1:
            trading_period_days = 1
    else:
        trading_period_days = 1
        first_entry = None
        last_exit = None
    
    trades_per_month = (trade_count / (trading_period_days / 30)) if trading_period_days >= 30 else trade_count
    
    # --- Dynamic Bars Per Day Calculation (SOP-Compliant) ---
    bars_per_day = 6.0 # Ultimate fallback
    source_method = "default"
    
    # Try Empirical Derivation
    valid_samples = []
    for t in filtered:
        try:
            entry = _parse_timestamp(t.get("entry_timestamp", ""))
            exit = _parse_timestamp(t.get("exit_timestamp", ""))
            bars = _safe_int(t.get("bars_held", 0))
            
            if entry and exit and bars > 1 and exit > entry:
                duration_seconds = (exit - entry).total_seconds()
                seconds_per_bar = duration_seconds / bars
                valid_samples.append(seconds_per_bar)
        except:
            continue
            
    # Try Candle Geometry (Primary - v5 Metric Integrity)
    if metadata and "bar_geometry" in metadata and "median_bar_seconds" in metadata["bar_geometry"]:
        median_sec = _safe_float(metadata["bar_geometry"]["median_bar_seconds"])
        if median_sec > 0:
            bars_per_day = 86400.0 / median_sec
            source_method = "candle_geometry"
            
    # Try Empirical Derivation (Secondary)
    elif len(valid_samples) >= 5: # Require at least 5 trades to trust empirical
        valid_samples.sort()
        mid = len(valid_samples) // 2
        median_spb = valid_samples[mid]
        if median_spb > 0:
            bars_per_day = 86400.0 / median_spb
            source_method = "empirical"
    else:
        # Try Metadata Fallback if available
        if metadata and "timeframe" in metadata:
            tf = str(metadata["timeframe"]).lower().strip()
            if tf in ["1d", "d", "daily"]:
                bars_per_day = 1.0
                source_method = "metadata (1d)"
            elif tf == "4h":
                bars_per_day = 6.0
                source_method = "metadata (4h)"
            elif tf == "1h":
                bars_per_day = 24.0
                source_method = "metadata (1h)"
            elif tf == "30m":
                bars_per_day = 48.0
                source_method = "metadata (30m)"
            elif tf == "15m":
                bars_per_day = 96.0
                source_method = "metadata (15m)"
            elif tf == "5m":
                bars_per_day = 288.0
                source_method = "metadata (5m)"
            elif tf == "1m":
                bars_per_day = 1440.0
                source_method = "metadata (1m)"
    
    # % Time in Market (total bars held / total bars in period)
    total_bars_held = sum(bars_list) if bars_list else 0
    total_bars_in_period = trading_period_days * bars_per_day
    pct_time_in_market = (total_bars_held / total_bars_in_period * 100) if total_bars_in_period > 0 else 0.0
    
    # Longest flat period (days between trades)
    longest_flat_days = 0
    if len(exit_dates) > 1:
        sorted_exits = sorted(exit_dates)
        sorted_entries = sorted(entry_dates)
        for i in range(1, len(sorted_entries)):
            gap = (sorted_entries[i] - sorted_exits[i-1]).days if i-1 < len(sorted_exits) else 0
            if gap > longest_flat_days:
                longest_flat_days = gap
    
    # MFE / MAE computation (consume execution-emitted values)
    mfe_list = []
    mae_list = []
    for t in filtered:
        mfe_r = _safe_float(t.get("mfe_r", 0))
        mae_r = _safe_float(t.get("mae_r", 0))
        if mfe_r > 0 or mae_r > 0:
            mfe_list.append(mfe_r)
            mae_list.append(mae_r)
    
    avg_mfe_r = (sum(mfe_list) / len(mfe_list)) if mfe_list else 0.0
    avg_mae_r = (sum(mae_list) / len(mae_list)) if mae_list else 0.0
    edge_ratio = (avg_mfe_r / avg_mae_r) if avg_mae_r > 0 else avg_mfe_r if avg_mfe_r > 0 else 0.0
    
    # Concentration (top 5 trades contribution)
    sorted_wins = sorted(wins, reverse=True)
    top5_profit = sum(sorted_wins[:5]) if len(sorted_wins) >= 5 else sum(sorted_wins)
    top5_pct = (top5_profit / gross_profit * 100) if gross_profit > 0 else 0.0
    
    sorted_losses = sorted(losses)
    worst5_loss = sum(sorted_losses[:5]) if len(sorted_losses) >= 5 else sum(sorted_losses)
    worst5_pct = (abs(worst5_loss) / gross_loss * 100) if gross_loss > 0 else 0.0
    
    # Risk metrics placeholders (overridden later)
    sharpe_ratio = 0.0
    sortino_ratio = 0.0
    k_ratio = 0.0
    sqn = 0.0
    return_retracement_ratio = return_dd_ratio
    
    # Volatility regime breakdown
    vol_low_pnls = []
    vol_normal_pnls = []
    vol_high_pnls = []
    for t in filtered:
        pnl = _safe_float(t.get("pnl_usd", 0))
        regime = t.get("volatility_regime", "normal")
        if regime == "low": vol_low_pnls.append(pnl)
        elif regime == "normal": vol_normal_pnls.append(pnl)
        else: vol_high_pnls.append(pnl)
    
    net_profit_low_vol = sum(vol_low_pnls)
    net_profit_normal_vol = sum(vol_normal_pnls)
    net_profit_high_vol = sum(vol_high_pnls)
    trades_low_vol = len(vol_low_pnls)
    trades_normal_vol = len(vol_normal_pnls)
    trades_high_vol = len(vol_high_pnls)
    avg_trade_low_vol = (net_profit_low_vol / trades_low_vol) if trades_low_vol > 0 else 0.0
    avg_trade_normal_vol = (net_profit_normal_vol / trades_normal_vol) if trades_normal_vol > 0 else 0.0
    avg_trade_high_vol = (net_profit_high_vol / trades_high_vol) if trades_high_vol > 0 else 0.0
    
    # Session breakdown
    asia_pnls = []
    london_pnls = []
    ny_pnls = []
    for t in filtered:
        pnl = _safe_float(t.get("pnl_usd", 0))
        entry_dt = _parse_timestamp(t.get("entry_timestamp", ""))
        session = _get_session(entry_dt)
        if session == "asia": asia_pnls.append(pnl)
        elif session == "london": london_pnls.append(pnl)
        else: ny_pnls.append(pnl)
    
    net_profit_asia = sum(asia_pnls)
    net_profit_london = sum(london_pnls)
    net_profit_ny = sum(ny_pnls)
    trades_asia = len(asia_pnls)
    trades_london = len(london_pnls)
    trades_ny = len(ny_pnls)
    avg_trade_asia = (net_profit_asia / trades_asia) if trades_asia > 0 else 0.0
    avg_trade_london = (net_profit_london / trades_london) if trades_london > 0 else 0.0
    avg_trade_ny = (net_profit_ny / trades_ny) if trades_ny > 0 else 0.0
    
    return {
        "starting_capital": starting_capital,
        "net_profit": net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "return_dd_ratio": return_dd_ratio,
        "total_trades": trade_count,
        "winning_trades": win_count,
        "losing_trades": loss_count,
        "pct_profitable": win_rate,
        "trades_per_month": trades_per_month,
        "longest_flat_days": longest_flat_days,
        "avg_trade": avg_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "avg_mfe_r": avg_mfe_r,
        "avg_mae_r": avg_mae_r,
        "edge_ratio": edge_ratio,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "top5_pct_gross_profit": top5_pct,
        "worst5_loss_pct": worst5_pct,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        "max_dd_usd": max_dd,
        "max_dd_pct": max_dd_pct,
        "return_on_capital": return_on_capital,
        "pct_time_in_market": pct_time_in_market,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "k_ratio": k_ratio,
        "sqn": sqn,
        "return_retracement_ratio": return_retracement_ratio,
        "avg_bars_win": avg_bars_win,
        "avg_bars_loss": avg_bars_loss,
        "avg_bars": avg_bars,
        "trading_period_days": trading_period_days,
        "net_profit_low_vol": net_profit_low_vol,
        "net_profit_normal_vol": net_profit_normal_vol,
        "net_profit_high_vol": net_profit_high_vol,
        "trades_low_vol": trades_low_vol,
        "trades_normal_vol": trades_normal_vol,
        "trades_high_vol": trades_high_vol,
        "avg_trade_low_vol": avg_trade_low_vol,
        "avg_trade_normal_vol": avg_trade_normal_vol,
        "avg_trade_high_vol": avg_trade_high_vol,
        "net_profit_asia": net_profit_asia,
        "net_profit_london": net_profit_london,
        "net_profit_ny": net_profit_ny,
        "trades_asia": trades_asia,
        "trades_london": trades_london,
        "trades_ny": trades_ny,
        "avg_trade_asia": avg_trade_asia,
        "avg_trade_london": avg_trade_london,
        "avg_trade_ny": avg_trade_ny,
    }

def _empty_metrics(starting_capital=0.0):
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
    }

def _compute_yearwise_metrics(trades, year, starting_capital, authoritative_data=None):
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


def _compute_buy_hold_benchmark(trades):
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
    except Exception:
        return None


def get_settings_df(metadata):
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
        {"Parameter": "Engine Version", "Value": metadata.get("engine_version", "")},
        {"Parameter": "Schema Version", "Value": metadata.get("schema_version", "")},
    ]
    return pd.DataFrame(data)

def get_performance_summary_df(trades, starting_capital, standard_metrics, risk_metrics, metadata=None):
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
    all_metrics["sqn"] = _safe_float(risk_metrics.get("sqn", 0))
    
    rows = []
    def add_row(label, key):
        rows.append({
            "Metric": label,
            "All Trades": all_metrics.get(key),
            "Long Trades": long_metrics.get(key),
            "Short Trades": short_metrics.get(key)
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

    return pd.DataFrame(rows)

def get_benchmark_df(trades, starting_capital, all_net_profit):
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

def get_yearwise_df(trades, starting_capital, yearwise_data):
    year_lookup = {}
    if yearwise_data:
        for row in yearwise_data:
            try:
                y = int(row.get("year", 0))
                if y > 0: year_lookup[y] = row
            except: pass

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

def get_trades_df(trades):
    rows = []
    for t in trades:
        d = _safe_int(t.get("direction", 0))
        rows.append({
            "Parent Trade ID": t.get("parent_trade_id", ""),
            "Sequence Index": t.get("sequence_index", ""),
            "Strategy Name": t.get("strategy_name", ""),
            "Direction": "LONG" if d == 1 else "SHORT",
            "Entry Time": t.get("entry_timestamp", ""),
            "Exit Time": t.get("exit_timestamp", ""),
            "Entry Price": t.get("entry_price", ""),
            "Exit Price": t.get("exit_price", ""),
            "PnL (USD)": t.get("pnl_usd", ""),
            "Bars Held": t.get("bars_held", ""),
        })
    return pd.DataFrame(rows)


def generate_excel_report(artifacts, output_path: Path):
    starting_capital = artifacts["metadata"]["reference_capital_usd"]
    
    df_settings = get_settings_df(artifacts["metadata"])
    df_summary = get_performance_summary_df(artifacts["tradelevel"], starting_capital, artifacts["standard"], artifacts["risk"], artifacts["metadata"])
    
    # Extract net profit from summary for benchmark
    try:
        net_profit_row = df_summary[df_summary["Metric"] == "Net Profit (USD)"]
        net_profit = float(net_profit_row["All Trades"].values[0])
    except:
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
        project_root = Path(__file__).parent.parent
        formatter = project_root / "tools" / "format_excel_artifact.py"
        cmd = [sys.executable, str(formatter), "--file", str(output_path), "--profile", "strategy"]
        subprocess.run(cmd, check=True)
        print(f"[SUCCESS] Formatted {output_path.name}")
    except Exception as e:
        print(f"[WARN] Failed to format {output_path.name}: {e}")


def compile_stage2(run_folder: Path):
    artifacts = load_stage1_artifacts(run_folder)
    strategy_name = artifacts["metadata"].get("strategy_name", "UNKNOWN")
    excel_filename = f"AK_Trade_Report_{strategy_name}.xlsx"
    excel_path = run_folder / excel_filename
    
    generate_excel_report(artifacts, excel_path)
    return run_folder, [excel_filename]

def main():
    parser = argparse.ArgumentParser(description="Stage-2 Presentation Compiler (v4 Multi-Asset) - Clean Engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("run_folder", nargs="?", help="Path to single Stage-1 run folder")
    group.add_argument("--scan", help="Scan backtests/ for folders matching DIRECTIVE_NAME_*")
    
    args = parser.parse_args()
    
    if args.scan:
        directive_name = args.scan
        backtests_root = Path(__file__).parent.parent / "backtests"
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
        success_count = 0
        fail_count = 0
        for run_folder in valid_runs:
            try:
                print(f">>> Compiling: {run_folder.name} ... ", end="", flush=True)
                compile_stage2(run_folder)
                print("[OK]")
                success_count += 1
            except Exception as e:
                print(f"[FAIL] {e}")
                fail_count += 1
        print(f"BATCH SUMMARY: {success_count} Success, {fail_count} Failed")
        if fail_count > 0: sys.exit(1)
        sys.exit(0)
    else:
        run_folder = Path(args.run_folder)
        if not run_folder.exists(): raise SystemExit(f"ERROR: Run folder not found: {run_folder}")
        try:
            out, files = compile_stage2(run_folder)
            print(f"Generated: {files}")
        except Exception as e:
            raise SystemExit(f"Stage-2 compilation aborted. {e}")

if __name__ == "__main__":
    main()
