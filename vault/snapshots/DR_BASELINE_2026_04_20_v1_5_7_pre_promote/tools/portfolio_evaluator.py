"""
Portfolio Evaluator - Multi-Instrument Portfolio Analysis + Snapshot Archival
Usage: python tools/portfolio_evaluator.py <STRATEGY_ID>
Example: python tools/portfolio_evaluator.py IDX23

Produces:
  - strategies/<STRATEGY_ID>/portfolio_evaluation/ (frozen snapshot)
  - Console executive summary + recommendation
"""

import sys
import json
import csv
import math
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')


# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ------------------------------------------------------------------
# IMPORTS (numpy/pandas/matplotlib)
# ------------------------------------------------------------------
import subprocess
from filelock import FileLock

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
from tools.pipeline_utils import get_engine_version, ensure_xlsx_writable
from config.state_paths import BACKTESTS_DIR, RUNS_DIR, STRATEGIES_DIR
from tools.portfolio_core import (
    compute_concurrency_series as core_compute_concurrency_series,
    load_trades_for_portfolio_evaluator as core_load_trades_for_portfolio_evaluator,
)

BACKTESTS_ROOT = BACKTESTS_DIR
STRATEGIES_ROOT = STRATEGIES_DIR
TOTAL_PORTFOLIO_CAPITAL = 10000.0
RISK_FREE_RATE = 0.0  # For Sharpe/Sortino
PORTFOLIO_ENGINE_VERSION = get_engine_version()
RELIABILITY_MIN_ACCEPTED = 50
RELIABILITY_MIN_SIM_YEARS = 1.0

SYMBOLS = ['AUS200', 'ESP35', 'EUSTX50', 'FRA40', 'GER40',
           'JPN225', 'NAS100', 'SPX500', 'UK100', 'US30']

# Color palette
COLORS = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
          '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9']

plt.rcParams.update({
    'figure.facecolor': '#1a1a2e',
    'axes.facecolor': '#16213e',
    'axes.edgecolor': '#0f3460',
    'axes.labelcolor': '#e0e0e0',
    'text.color': '#e0e0e0',
    'xtick.color': '#a0a0a0',
    'ytick.color': '#a0a0a0',
    'grid.color': '#0f3460',
    'grid.alpha': 0.3,
    'font.size': 10,
    'axes.titlesize': 13,
    'figure.titlesize': 15,
})


# ==================================================================
# DATA LOADING
# ==================================================================
def load_all_trades(run_ids):
    """
    Load trade-level results for explicit atomic runs.
    Bypasses auto-discovery and Excel UI parsing.
    Sourced purely from runs/<run_id>/data/ results.
    """
    return core_load_trades_for_portfolio_evaluator(run_ids, PROJECT_ROOT)


def load_symbol_metrics(strategy_id):
    """
    Load per-symbol standard and risk metrics (Governance-Driven).
    Replaces auto-discovery with strict Stage-3 Master Filter selection.
    Uses Run-ID based folder resolution (no folder filtering).
    """
    metrics = {}

    # 1. Read Master Sheet (DB-first, Excel fallback)
    try:
        from tools.ledger_db import read_master_filter
        df_master = read_master_filter()
        if df_master.empty:
            raise ValueError("Master Filter is empty")
    except Exception as e:
        raise ValueError(f"Failed to read Strategy Master Filter: {e}")

    # 2. Filter Rows.
    # IN_PORTFOLIO was retired 2026-04-16 and is no longer required; the
    # filter below matches by strategy prefix, which is the authoritative
    # semantics for resolving per-symbol run rows.
    if 'strategy' not in df_master.columns or 'run_id' not in df_master.columns or 'symbol' not in df_master.columns:
         raise ValueError("Master Sheet missing required columns: 'strategy', 'run_id', or 'symbol'")

    selected_rows = df_master[
        (df_master['strategy'].astype(str).str.startswith(strategy_id + "_")) 
    ]
    
    if selected_rows.empty:
        # Fallback: Try Exact Match
        selected_rows = df_master[df_master['strategy'] == strategy_id]
        
    if selected_rows.empty:
        raise ValueError(f"No strategies found in Master Filter matching {strategy_id}")
        
    # 3. Locate Folders (Pre-scan for Run-ID mapping)
    run_id_map = {}
    for folder in BACKTESTS_ROOT.iterdir():
        if folder.is_dir():
            meta_path = folder / "metadata" / "run_metadata.json"
            if meta_path.exists():
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                except Exception:
                    continue
                
                rid = str(meta.get("run_id"))
                
                # Governance: Detect duplicates strict
                if rid in run_id_map:
                    raise ValueError(f"Duplicate run_id detected in backtests: {rid}")
                
                run_id_map[rid] = folder

    # 4. Load Metrics
    for idx, row in selected_rows.iterrows():
        run_id = str(row['run_id'])
        symbol = row.get('symbol')
        
        run_folder = run_id_map.get(run_id)
        if run_folder is None:
             raise ValueError(
                f"Governance violation: run_id {run_id} selected in Master Sheet "
                f"but no corresponding backtest folder found."
            )

        std_path = run_folder / "raw" / "results_standard.csv"
        risk_path = run_folder / "raw" / "results_risk.csv"
        
        if not std_path.exists() or not risk_path.exists():
            raise ValueError(
                f"Governance violation: standard/risk metrics missing for run_id {run_id}."
            )
            
        try:
            std = pd.read_csv(std_path).iloc[0].to_dict()
            risk = pd.read_csv(risk_path).iloc[0].to_dict()
            if symbol:
                metrics[symbol] = {**std, **risk}
        except Exception as e:
            raise ValueError(
                f"Governance violation: failed to read metrics for run_id {run_id}: {e}"
            )
                
    return metrics


# ==================================================================
# 1) PORTFOLIO CONSTRUCTION
# ==================================================================
def build_portfolio_equity(portfolio_df, symbol_trades):
    """Build cumulative equity curves for portfolio and per-symbol."""
    # Per-symbol equity curves (daily, by exit date)
    symbol_equity = {}
    capital_per_symbol = TOTAL_PORTFOLIO_CAPITAL / len(symbol_trades)
    for sym, df in symbol_trades.items():
        daily_pnl = df.groupby(df['exit_timestamp'].dt.date)['pnl_usd'].sum()
        daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)
        equity = daily_pnl.cumsum() + capital_per_symbol
        symbol_equity[sym] = equity

    # Portfolio equity: merge all trades chronologically
    daily_pnl = portfolio_df.groupby(portfolio_df['exit_timestamp'].dt.date)['pnl_usd'].sum()
    daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)

    portfolio_equity = daily_pnl.cumsum() + TOTAL_PORTFOLIO_CAPITAL

    return portfolio_equity, symbol_equity, daily_pnl


def compute_portfolio_metrics(portfolio_equity, daily_pnl, portfolio_df, num_symbols):
    """Compute portfolio-level metrics."""
    total_capital = TOTAL_PORTFOLIO_CAPITAL
    net_pnl = portfolio_equity.iloc[-1] - total_capital

    # CAGR
    start_date = portfolio_equity.index[0]
    end_date = portfolio_equity.index[-1]
    years = (end_date - start_date).days / 365.25
    if years > 0 and portfolio_equity.iloc[-1] > 0:
        cagr = (portfolio_equity.iloc[-1] / total_capital) ** (1 / years) - 1
    else:
        cagr = 0.0

    # Max Drawdown
    running_max = portfolio_equity.cummax()
    drawdown = portfolio_equity - running_max
    dd_pct = drawdown / running_max
    max_dd_usd = drawdown.min()
    max_dd_pct = dd_pct.min()
    peak_dd_ratio = round(float(running_max.max()) / abs(float(max_dd_usd)), 4) if max_dd_usd != 0 else 0.0

    # Return/DD
    return_dd = abs(net_pnl / max_dd_usd) if max_dd_usd != 0 else 0.0

    # NOTE: 'sharpe' here is DAILY RETURN BASED and ANNUALIZED (sqrt(252) scaling).
    # This is NOT comparable to trade-level Sharpe in Stage 2 (mean(trade_pnl)/stdev).
    # Sharpe (annualized from daily returns)
    equity_series = portfolio_equity.shift(1)
    # Avoid division by zero/NaN at start
    # Safe division: replace 0 with NaN to avoid inf
    equity_series.replace(0, np.nan, inplace=True)
    daily_returns = daily_pnl / equity_series
    daily_returns.dropna(inplace=True)
    
    # Use daily_returns for metrics
    returns = daily_returns
    
    if len(returns) > 1 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    # Sortino
    downside = returns[returns < 0]
    if len(downside) > 1 and downside.std() > 0:
        sortino = (returns.mean() / downside.std()) * np.sqrt(252)
    else:
        sortino = 0.0

    # NOTE: 'equity_stability_k_ratio' is computed on LOG DAILY EQUITY.
    # Stage 2 K-Ratio is based on cumulative TRADE PnL (linear).
    # Values are not comparable.
    # K-Ratio (slope of log equity / std error)
    log_eq = np.log(portfolio_equity.values)
    x = np.arange(len(log_eq))
    if len(x) > 2:
        slope, intercept = np.polyfit(x, log_eq, 1)
        predicted = slope * x + intercept
        residuals = log_eq - predicted
        se_slope = np.sqrt(np.sum(residuals**2) / (len(x) - 2)) / np.sqrt(np.sum((x - x.mean())**2))
        k_ratio = slope / se_slope if se_slope > 0 else 0.0
    else:
        k_ratio = 0.0

    # MAR ratio (CAGR / |MaxDD%|)
    mar = cagr / abs(max_dd_pct) if max_dd_pct != 0 else 0.0

    # Longest flat period
    high_water = portfolio_equity.cummax()
    in_dd = portfolio_equity < high_water
    flat_periods = []
    current_start = None
    for i, (dt, is_flat) in enumerate(in_dd.items()):
        if is_flat and current_start is None:
            current_start = dt
        elif not is_flat and current_start is not None:
            flat_periods.append((current_start, dt))
            current_start = None
    if current_start is not None:
        flat_periods.append((current_start, portfolio_equity.index[-1]))

    if flat_periods:
        longest_flat = max(flat_periods, key=lambda x: (x[1] - x[0]).days)
        longest_flat_days = (longest_flat[1] - longest_flat[0]).days
    else:
        longest_flat_days = 0

    # Trades during longest flat
    flat_trades = 0
    if flat_periods and longest_flat_days > 0:
        lf_start, lf_end = longest_flat
        flat_trades = len(portfolio_df[
            (portfolio_df['exit_timestamp'] >= lf_start) &
            (portfolio_df['exit_timestamp'] <= lf_end)
        ])

    # ------------------------------------------------------------------
    # PHASE 15 PATCH: MANDATORY RESEARCH METRICS
    # ------------------------------------------------------------------
    # Win Rate
    total_trades = len(portfolio_df)
    if total_trades > 0:
        win_rate = (portfolio_df['pnl_usd'] > 0).mean() * 100.0
    else:
        win_rate = 0.0

    # Profit Factor
    gross_profit = portfolio_df[portfolio_df['pnl_usd'] > 0]['pnl_usd'].sum()
    gross_loss = abs(portfolio_df[portfolio_df['pnl_usd'] < 0]['pnl_usd'].sum())
    
    if gross_loss == 0:
        profit_factor = float('inf') if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    # Expectancy
    if total_trades > 0:
        expectancy = portfolio_df['pnl_usd'].mean()
    else:
        expectancy = 0.0

    # Portfolio SQN — computed from combined R-multiples of all constituent trades.
    # SQN = sqrt(N) * mean(R) / stdev(R, ddof=1)   [Van Tharp]
    # Edge Quality = mean(R) / stdev(R) — SQN without sqrt(N), comparable across portfolio sizes.
    sqn = 0.0
    edge_quality = 0.0
    if 'r_multiple' in portfolio_df.columns:
        r_vals = portfolio_df['r_multiple'].dropna()
        n_r = len(r_vals)
        if n_r >= 2:
            r_std = r_vals.std(ddof=1)
            if r_std > 0:
                r_mean = r_vals.mean()
                sqn = round(math.sqrt(n_r) * r_mean / r_std, 4)
                edge_quality = round(r_mean / r_std, 4)
    # ------------------------------------------------------------------

    return {
        'net_pnl_usd': net_pnl,
        'cagr': cagr,
        'max_dd_usd': max_dd_usd,
        'max_dd_pct': max_dd_pct,
        'return_dd_ratio': return_dd,
        'sharpe': sharpe,
        'sortino': sortino,
        'k_ratio': k_ratio,
        'mar': mar,
        'longest_flat_days': longest_flat_days,
        'longest_flat_trades': flat_trades,
        'total_trades': total_trades,
        'years': years,
        'start_date': str(start_date.date()),
        'end_date': str(end_date.date()),
        # Phase 15 Metrics
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'expectancy': expectancy,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'sqn': sqn,
        'edge_quality': edge_quality,
        'peak_dd_ratio': peak_dd_ratio,
    }



def compute_concurrency_series(portfolio_df):
    """Delegate deterministic concurrency math to shared portfolio_core."""
    return core_compute_concurrency_series(portfolio_df)


# ==================================================================
# 2) CAPITAL UTILIZATION
# ==================================================================
def capital_utilization(portfolio_df, symbol_trades, _precomputed_concurrency=None):
    """Analyze capital deployment over time.

    Args:
        _precomputed_concurrency: Optional tuple from compute_concurrency_series()
            to avoid recomputing the same series (called again by concurrency_profile).
    """
    if _precomputed_concurrency is not None:
        series, max_conc, avg_conc, pct_max, pct_deployed = _precomputed_concurrency
    else:
        series, max_conc, avg_conc, pct_max, pct_deployed = compute_concurrency_series(portfolio_df)

    start = portfolio_df['entry_timestamp'].min()
    end = portfolio_df['exit_timestamp'].max()
    total_days = (end - start).days if pd.notnull(start) and pd.notnull(end) else 0

    return {
        'pct_time_deployed': pct_deployed,
        'avg_concurrent': avg_conc,
        'max_concurrent': int(max_conc),
        'total_trading_days': total_days,
    }


# ==================================================================
# 2.5) CONCURRENCY PROFILE
# ==================================================================
def concurrency_profile(portfolio_df, portfolio_equity, _precomputed_concurrency=None):
    """Analyze concurrency distribution and extreme loads.

    Args:
        _precomputed_concurrency: Optional tuple from compute_concurrency_series()
            to avoid recomputing the same series (already called by capital_utilization).
    """
    if _precomputed_concurrency is not None:
        series, max_conc, avg_conc, pct_at_max, pct_deployed = _precomputed_concurrency
    else:
        series, max_conc, avg_conc, pct_at_max, pct_deployed = compute_concurrency_series(portfolio_df)
    
    concurrent_values = np.array(series)
    
    # 1. Distribution
    if len(concurrent_values) > 0:
        counts = pd.Series(concurrent_values).value_counts(normalize=True).sort_index()
        distribution = {int(k): v for k, v in counts.items()}
        p95_conc = np.percentile(concurrent_values, 95)
    else:
        distribution = {}
        p95_conc = 0
    
    # Full load clustering check (float precision safe)
    full_load_cluster = (p95_conc >= max_conc - 1e-9)
    # pct_days_at_max (now pct_time_at_max)
    pct_days_at_max = pct_at_max
    
    # 3. During Largest DD
    running_max = portfolio_equity.cummax()
    dd = portfolio_equity - running_max
    
    trough_date = dd.idxmin()
    peak_data = portfolio_equity[:trough_date]
    peak_date = peak_data.idxmax() if not peak_data.empty else trough_date
    
    # Filter trades active during DD window
    # Using entry timestamp for strict alignment with series
    # Or filter portfolio_df by window and re-compute?
    # Simpler: Filter portfolio_df for trades active in window, then compute avg/max
    active_in_dd = portfolio_df[
        (portfolio_df['exit_timestamp'] >= peak_date) & 
        (portfolio_df['entry_timestamp'] <= trough_date)
    ]
    
    if not active_in_dd.empty:
        dd_series, dd_max, dd_avg, _, _ = compute_concurrency_series(active_in_dd)
    else:
        dd_max = 0
        dd_avg = 0
        
    # 4. Regime Stats
    # Align series with sorted DF to map regimes
    df_sorted = portfolio_df.sort_values('entry_timestamp').copy()
    
    # Safety check: lengths must match
    if len(df_sorted) == len(series):
        df_sorted['concurrency'] = series
        regime_means = df_sorted.groupby('volatility_regime')['concurrency'].mean()
        regime_avg = {r: round(regime_means.get(r, 0), 2) for r in ['low', 'normal', 'high']}
    else:
        # Fallback if alignment fails (should not happen)
        regime_avg = {'low': 0, 'normal': 0, 'high': 0}

    return {
        "avg_concurrent": avg_conc,
        "max_concurrent": int(max_conc),
        "p95_concurrent": p95_conc,
        "distribution": distribution,
        "dd_avg_concurrent": dd_avg,
        "dd_max_concurrent": int(dd_max),
        "regime_avg": regime_means.to_dict(),
        "full_load_cluster": bool(full_load_cluster),
        "pct_days_at_max": pct_days_at_max
    }


# ==================================================================
# 3) CORRELATION & DEPENDENCY
# ==================================================================
def correlation_analysis(symbol_equity):
    """Compute correlation between symbol equity curves."""
    # Build daily returns per symbol on common date range
    all_dates = set()
    for eq in symbol_equity.values():
        all_dates.update(eq.index)
    all_dates = sorted(all_dates)
    date_range = pd.DatetimeIndex(all_dates)

    returns_df = pd.DataFrame(index=date_range)
    for sym, eq in symbol_equity.items():
        returns_df[sym] = eq.reindex(date_range).ffill().pct_change()

    returns_df = returns_df.dropna(how='all')

    # Static correlation matrix
    corr_matrix = returns_df.corr()

    # Average pairwise correlation
    n = len(corr_matrix)
    if n > 1:
        upper_tri = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
        avg_corr = upper_tri.stack().mean()
    else:
        avg_corr = 0.0

    # Identify clusters
    us_syms = ['NAS100', 'SPX500', 'US30']
    eu_syms = ['ESP35', 'EUSTX50', 'FRA40', 'GER40', 'UK100']
    ap_syms = ['AUS200', 'JPN225']

    us_corr = corr_matrix.loc[
        [s for s in us_syms if s in corr_matrix.index],
        [s for s in us_syms if s in corr_matrix.columns]
    ]
    us_avg = us_corr.where(np.triu(np.ones(us_corr.shape), k=1).astype(bool)).stack().mean() if len(us_corr) > 1 else 0

    eu_corr = corr_matrix.loc[
        [s for s in eu_syms if s in corr_matrix.index],
        [s for s in eu_syms if s in corr_matrix.columns]
    ]
    eu_avg = eu_corr.where(np.triu(np.ones(eu_corr.shape), k=1).astype(bool)).stack().mean() if len(eu_corr) > 1 else 0

    return {
        'corr_matrix': corr_matrix,
        'avg_pairwise_corr': avg_corr,
        'us_cluster_corr': us_avg,
        'eu_cluster_corr': eu_avg,
        'returns_df': returns_df,
    }


def compute_stress_correlation(returns_df, peak_date, trough_date):
    """
    Compute max pairwise correlation during stress window (SOP 6.3).
    Stress window = Peak-to-Trough of largest drawdown.
    """
    # Filter returns by window
    start_dt = pd.to_datetime(peak_date)
    end_dt = pd.to_datetime(trough_date)
    
    mask = (returns_df.index >= start_dt) & (returns_df.index <= end_dt)
    stress_returns = returns_df.loc[mask]

    # Need minimal data and at least 2 symbols
    if len(stress_returns) < 3 or len(stress_returns.columns) < 2:
        return 0.0

    # Correlation matrix
    corr_matrix = stress_returns.corr()
    
    # Max off-diagonal
    # Mask diagonal with -2 (since valid corr is [-1, 1])
    vals = corr_matrix.values
    np.fill_diagonal(vals, -2.0)
    
    max_stress_corr = float(vals.max())
    
    # Safety clamp (floating point artifacts)
    max_stress_corr = min(max_stress_corr, 1.0)
    
    return max_stress_corr


# ==================================================================
# 4) CONTRIBUTION ANALYSIS
# ==================================================================
def contribution_analysis(symbol_trades, portfolio_df):
    """Per-symbol contribution to portfolio metrics."""
    total_pnl = portfolio_df['pnl_usd'].sum()
    contributions = {}

    for sym, df in symbol_trades.items():
        sym_pnl = df['pnl_usd'].sum()
        pnl_pct = (sym_pnl / total_pnl) if total_pnl != 0 else 0

        # Volatility contribution (std of PnL)
        sym_vol = df['pnl_usd'].std()

        # Regime contribution
        regime_pnl = {}
        for regime in ['low', 'normal', 'high']:
            r_df = df[df['volatility_regime'] == regime]
            regime_pnl[regime] = r_df['pnl_usd'].sum()

        contributions[sym] = {
            'total_pnl': sym_pnl,
            'pnl_pct': pnl_pct,
            'volatility': sym_vol,
            'trades': len(df),
            'regime_pnl': regime_pnl,
        }

    return contributions


# ==================================================================
# 5) DRAWDOWN ANATOMY
# ==================================================================
def drawdown_anatomy(portfolio_equity, portfolio_df):
    """Analyze the largest drawdown event."""
    running_max = portfolio_equity.cummax()
    drawdown = portfolio_equity - running_max
    dd_pct = drawdown / running_max

    # Find the trough
    trough_idx = drawdown.idxmin()
    trough_val = drawdown.min()
    trough_pct = dd_pct.min()

    # Find the peak before trough
    peak_idx = portfolio_equity[:trough_idx].idxmax()
    peak_val = portfolio_equity[peak_idx]

    # Find recovery (if any)
    post_trough = portfolio_equity[trough_idx:]
    recovered = post_trough[post_trough >= peak_val]
    if len(recovered) > 0:
        recovery_idx = recovered.index[0]
        recovery_days = (recovery_idx - trough_idx).days
    else:
        recovery_idx = None
        recovery_days = None

    # Duration
    dd_duration = (trough_idx - peak_idx).days

    # Trades during collapse
    dd_trades = portfolio_df[
        (portfolio_df['exit_timestamp'] >= peak_idx) &
        (portfolio_df['exit_timestamp'] <= trough_idx)
    ]

    # Regime during collapse
    if 'volatility_regime' in dd_trades.columns and len(dd_trades) > 0:
        regime_counts = dd_trades['volatility_regime'].value_counts().to_dict()
    else:
        regime_counts = {}

    return {
        'peak_date': str(peak_idx.date()),
        'trough_date': str(trough_idx.date()),
        'absolute_drop_usd': trough_val,
        'pct_retracement': trough_pct,
        'duration_days': dd_duration,
        'recovery_days': recovery_days,
        'trades_during_collapse': len(dd_trades),
        'regime_during_collapse': regime_counts,
    }


# ==================================================================
# 6) STRESS TESTING
# ==================================================================
def stress_test(symbol_trades, portfolio_df):
    """Simulate removal of symbols and recompute metrics."""
    results = {}

    # Find top and worst performing symbols
    sym_pnl = {sym: df['pnl_usd'].sum() for sym, df in symbol_trades.items()}
    top_sym = max(sym_pnl, key=sym_pnl.get)
    worst_sym = min(sym_pnl, key=sym_pnl.get)
    us_cluster = ['NAS100', 'SPX500', 'US30']

    scenarios = {
        'baseline': list(symbol_trades.keys()),
        f'remove_top ({top_sym})': [s for s in symbol_trades if s != top_sym],
        f'remove_worst ({worst_sym})': [s for s in symbol_trades if s != worst_sym],
        'remove_US_cluster': [s for s in symbol_trades if s not in us_cluster],
    }

    for name, syms in scenarios.items():
        subset = portfolio_df[portfolio_df['symbol'].isin(syms)].copy()
        subset.sort_values('exit_timestamp', inplace=True)

        if len(subset) == 0:
            results[name] = {'net_pnl': 0, 'sharpe': 0, 'max_dd_usd': 0, 'return_dd': 0}
            continue

        daily_pnl = subset.groupby(subset['exit_timestamp'].dt.date)['pnl_usd'].sum()
        daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)
        capital = TOTAL_PORTFOLIO_CAPITAL
        equity = daily_pnl.cumsum() + capital
        net = equity.iloc[-1] - capital

        # Max DD
        rm = equity.cummax()
        dd = (equity - rm).min()

        # Sharpe
        # rets = daily_pnl / capital (Old method)
        # New method: Compounded daily returns (SOP 6.3)
        equity_series = equity.shift(1)
        rets = daily_pnl / equity_series
        rets = rets.dropna()
        
        sh = (rets.mean() / rets.std()) * np.sqrt(252) if len(rets) > 1 and rets.std() > 0 else 0

        # Return/DD
        rdd = abs(net / dd) if dd != 0 else 0

        results[name] = {
            'symbols': len(syms),
            'net_pnl': net,
            'sharpe': sh,
            'max_dd_usd': dd,
            'return_dd': rdd,
        }

    return results


# ==================================================================
# 7) REGIME SEGMENTATION
# ==================================================================
def regime_segmentation(portfolio_df):
    """Segment performance by volatility regime and year."""
    regime_stats = {}
    for regime in ['low', 'normal', 'high']:
        r_df = portfolio_df[portfolio_df['volatility_regime'] == regime]
        if len(r_df) == 0:
            continue
        regime_stats[regime] = {
            'trades': len(r_df),
            'net_pnl': r_df['pnl_usd'].sum(),
            'avg_pnl': r_df['pnl_usd'].mean(),
            'win_rate': (r_df['pnl_usd'] > 0).mean(),
        }

    # Yearly
    portfolio_df = portfolio_df.copy()
    portfolio_df['year'] = portfolio_df['exit_timestamp'].dt.year
    yearly = {}
    for yr, ydf in portfolio_df.groupby('year'):
        yearly[int(yr)] = {
            'trades': len(ydf),
            'net_pnl': ydf['pnl_usd'].sum(),
            'avg_pnl': ydf['pnl_usd'].mean(),
            'win_rate': (ydf['pnl_usd'] > 0).mean(),
        }

    return {'regime': regime_stats, 'yearly': yearly}


# ==================================================================
# 8) VISUAL OUTPUTS
# ==================================================================
def generate_charts(portfolio_equity, symbol_equity, corr_data, contributions,
                    stress_results, output_dir, strategy_id):
    """Generate all required PNG charts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Equity Curve ---
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(portfolio_equity.index, portfolio_equity.values,
            color='#00d4ff', linewidth=2, label='Portfolio')
    for i, (sym, eq) in enumerate(symbol_equity.items()):
        ax.plot(eq.index, eq.values, color=COLORS[i % len(COLORS)],
                linewidth=0.8, alpha=0.5, label=sym)
    ax.set_title(f'{strategy_id} - Portfolio Equity Curve', fontweight='bold')
    ax.set_ylabel('Equity (USD)')
    ax.legend(loc='upper left', fontsize=7, ncol=3)
    ax.grid(True)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    fig.tight_layout()
    fig.savefig(output_dir / 'equity_curve.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Drawdown Curve ---
    fig, ax = plt.subplots(figsize=(14, 4))
    running_max = portfolio_equity.cummax()
    dd_pct = (portfolio_equity - running_max) / running_max * 100
    ax.fill_between(dd_pct.index, dd_pct.values, 0,
                    color='#ff4757', alpha=0.6)
    ax.plot(dd_pct.index, dd_pct.values, color='#ff6b81', linewidth=0.8)
    ax.set_title(f'{strategy_id} - Portfolio Drawdown', fontweight='bold')
    ax.set_ylabel('Drawdown (%)')
    ax.grid(True)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    fig.tight_layout()
    fig.savefig(output_dir / 'drawdown_curve.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Correlation Heatmap ---
    corr_matrix = corr_data['corr_matrix']
    fig, ax = plt.subplots(figsize=(10, 8))
    cmap = LinearSegmentedColormap.from_list('custom', ['#2196F3', '#1a1a2e', '#FF5722'])
    im = ax.imshow(corr_matrix.values, cmap=cmap, vmin=-1, vmax=1, aspect='auto')
    ax.set_xticks(range(len(corr_matrix.columns)))
    ax.set_yticks(range(len(corr_matrix.index)))
    ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right', fontsize=9)
    ax.set_yticklabels(corr_matrix.index, fontsize=9)
    for i in range(len(corr_matrix)):
        for j in range(len(corr_matrix)):
            val = corr_matrix.iloc[i, j]
            ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                    color='white', fontsize=8, fontweight='bold')
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(f'{strategy_id} - Correlation Matrix', fontweight='bold')
    fig.tight_layout()
    fig.savefig(output_dir / 'correlation_matrix.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Contribution Bar Chart ---
    fig, ax = plt.subplots(figsize=(12, 6))
    syms = list(contributions.keys())
    pnls = [contributions[s]['total_pnl'] for s in syms]
    colors_bar = ['#2ecc71' if p >= 0 else '#e74c3c' for p in pnls]
    bars = ax.bar(syms, pnls, color=colors_bar, edgecolor='#ffffff22', linewidth=0.5)
    for bar, val in zip(bars, pnls):
        ypos = bar.get_height() + (10 if val >= 0 else -30)
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f'${val:.0f}', ha='center', fontsize=9, fontweight='bold')
    ax.set_title(f'{strategy_id} - PnL Contribution by Symbol', fontweight='bold')
    ax.set_ylabel('Net PnL (USD)')
    ax.axhline(y=0, color='#ffffff44', linewidth=0.8)
    ax.grid(True, axis='y')
    fig.tight_layout()
    fig.savefig(output_dir / 'contribution_chart.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    # --- Stress Test Chart ---
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    scenarios = list(stress_results.keys())
    for idx, metric in enumerate(['net_pnl', 'sharpe', 'return_dd']):
        vals = [stress_results[s][metric] for s in scenarios]
        labels = [s.replace('remove_', '-').replace('_', ' ') for s in scenarios]
        colors_stress = ['#00d4ff' if i == 0 else '#ffaa00' for i in range(len(vals))]
        axes[idx].barh(labels, vals, color=colors_stress, edgecolor='#ffffff22')
        axes[idx].set_title(metric.replace('_', ' ').title(), fontweight='bold')
        axes[idx].grid(True, axis='x')
        for i, v in enumerate(vals):
            xoff = abs(max(vals) - min(vals)) * 0.05 if max(vals) != min(vals) else 1
            axes[idx].text(v + (xoff if v >= 0 else -xoff),
                          i, f'{v:.0f}' if metric != 'sharpe' else f'{v:.2f}',
                          va='center', fontsize=8)
    fig.suptitle(f'{strategy_id} - Stress Test Results', fontweight='bold', fontsize=14)
    fig.tight_layout()
    fig.savefig(output_dir / 'stress_test_chart.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    print(f"  [CHARTS] 5 charts saved to {output_dir}")


def generate_portfolio_tradelevel(portfolio_df, output_dir, total_capital):
    """
    Generate and save portfolio_tradelevel.csv with enriched metrics.
    Satisfies SOP_PORTFOLIO_ANALYSIS Section 5.
    """
    df = portfolio_df.copy()
    
    # 1. Ensure/Derive Notional
    if 'notional_usd' not in df.columns:
        if 'position_units' in df.columns and 'entry_price' in df.columns:
             df['notional_usd'] = df['position_units'] * df['entry_price']
        else:
             df['notional_usd'] = 0.0
             
    # 2. Concurrency & Capital Deployed at Entry (Sweep Line)
    # Similar to compute_concurrency_series but tracking capital and assigning to explicit rows
    
    # Sort by entry for strict time sweep
    df.sort_values('entry_timestamp', inplace=True)
    df.reset_index(inplace=True, drop=True) # Reset index to map 0..N
    
    events = []
    for idx, row in df.iterrows():
        events.append((row['entry_timestamp'], 1, idx, row['notional_usd']))
        events.append((row['exit_timestamp'], -1, idx, row['notional_usd']))
        
    # Sort: time asc, exit(-1) before entry(1)
    events.sort(key=lambda x: (x[0], x[1]))
    
    current_concurrent = 0
    current_capital = 0.0
    
    conc_map = {}
    cap_map = {}
    
    for t, type_, idx, notional in events:
        if type_ == 1: # Entry
            # Record state BEFORE adding this trade? 
            # SOP: "concurrency_at_entry". Usually includes the entering trade?
            # Metric interpretation: "How many trades active *including* this one?"
            # Let's assume inclusive.
            current_concurrent += 1
            current_capital += notional
            
            conc_map[idx] = current_concurrent
            cap_map[idx] = current_capital
            
        else: # Exit
            current_concurrent -= 1
            current_capital -= notional
            
    df['concurrency_at_entry'] = df.index.map(conc_map)
    df['capital_deployed_at_entry'] = df.index.map(cap_map)
    
    # 3. Equity Tracking (Before/After Trade)
    # E_t = E_(t-1) + pnl_t
    # Updates on logic: Equity updates ONLY when trades close.
    
    # We need a strictly time-sorted playback of EVENTS (Entry/Exit) to determine equity state at that moment.
    # Re-use events list, but this time we track equity.
    
    events_eq = []
    for idx, row in df.iterrows():
        events_eq.append({'t': row['entry_timestamp'], 'type': 'entry', 'idx': idx})
        events_eq.append({'t': row['exit_timestamp'], 'type': 'exit', 'idx': idx, 'pnl': row['pnl_usd']})
        
    events_eq.sort(key=lambda x: (x['t'], 0 if x['type']=='exit' else 1)) # Exits processed before entries
    
    current_equity = total_capital
    eq_before_map = {}
    eq_after_map = {}
    
    for e in events_eq:
        if e['type'] == 'entry':
            eq_before_map[e['idx']] = current_equity
        else:
            current_equity += e['pnl']
            eq_after_map[e['idx']] = current_equity
            
    df['equity_before_trade'] = df.index.map(eq_before_map)
    df['equity_after_trade'] = df.index.map(eq_after_map)
    
    # 4. Final Format & Save
    # "Chronologically sorted by exit_timestamp"
    df.sort_values('exit_timestamp', inplace=True)
    
    required_cols = [
        'source_run_id', 'strategy_name', 'entry_timestamp', 'exit_timestamp', 'direction',
        'entry_price', 'exit_price', 'pnl_usd', 'position_units', 'notional_usd', 'bars_held',
        'equity_before_trade', 'equity_after_trade', 'concurrency_at_entry', 'capital_deployed_at_entry'
    ]
    
    # Graceful fallback for missing optional columns (bars_held, position_units, etc might be missing in raw?)
    # bars_held is in SOP schema, results_tradelevel has it.
    for c in required_cols:
        if c not in df.columns:
            df[c] = None # Or 0/NaN
            
    output_path = output_dir / 'portfolio_tradelevel.csv'
    df[required_cols].to_csv(output_path, index=False)
    
    # --- Capital Transparency Metrics (SOP 4.3) ---
    if not df.empty:
        # Find index of peak capital deployment
        peak_idx = df['capital_deployed_at_entry'].idxmax()
        peak_capital = df.loc[peak_idx, 'capital_deployed_at_entry']
        
        # Equity at the moment of peak deployment (Equity BEFORE the trade that caused the peak)
        # This is the most accurate "account value" available when the decision to deploy was made.
        equity_at_peak = df.loc[peak_idx, 'equity_before_trade']
        
        ratio = (peak_capital / equity_at_peak) if equity_at_peak > 0 else 0.0
    else:
        peak_capital = 0.0
        ratio = 0.0
    
    return {
        'peak_capital_deployed': peak_capital,
        'capital_overextension_ratio': ratio
    }
def save_snapshot(strategy_id, port_metrics, contributions, corr_data,
                  dd_anatomy, stress_results, regime_data, cap_util, concurrency_data, 
                  max_stress_corr, constituent_run_ids, inert_warnings, output_dir):
    """Save frozen evaluation snapshot."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- portfolio_summary.json ---
    summary = {
        'strategy_id': strategy_id,
        'evaluation_date': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'portfolio_engine_version': PORTFOLIO_ENGINE_VERSION,
        'data_range': f"{port_metrics['start_date']} to {port_metrics['end_date']}",
        'total_constituent_runs': len(constituent_run_ids) if isinstance(constituent_run_ids, list) else 1,
        'total_assets_evaluated': len(contributions),
        'capital_per_symbol': TOTAL_PORTFOLIO_CAPITAL / len(contributions),
        'total_capital': TOTAL_PORTFOLIO_CAPITAL,
        'net_pnl_usd': port_metrics['net_pnl_usd'],
        'cagr_pct': port_metrics['cagr'],
        'sharpe': port_metrics['sharpe'],
        'sortino': port_metrics['sortino'],
        'max_dd_usd': port_metrics['max_dd_usd'],
        'max_dd_pct': port_metrics['max_dd_pct'],
        'return_dd_ratio': port_metrics['return_dd_ratio'],
        'k_ratio': port_metrics['k_ratio'],
        'mar': port_metrics['mar'],
        'avg_correlation': corr_data['avg_pairwise_corr'],
        'max_pairwise_corr_stress': max_stress_corr,
        'avg_concurrent': concurrency_data['avg_concurrent'],
        'max_concurrent': concurrency_data['max_concurrent'],
        'p95_concurrent': concurrency_data['p95_concurrent'],
        'dd_max_concurrent': concurrency_data['dd_max_concurrent'],
        'full_load_cluster': concurrency_data['full_load_cluster'],
        'pct_days_at_max': concurrency_data['pct_days_at_max'],
        'top_contributor_pct': max(c['pnl_pct'] for c in contributions.values()),
        'total_trades': port_metrics['total_trades'],
        'peak_capital_deployed': port_metrics.get('peak_capital_deployed', 0.0),
        'capital_overextension_ratio': port_metrics.get('capital_overextension_ratio', 0.0),
        'portfolio_net_profit_low_vol': port_metrics.get('portfolio_net_profit_low_vol', 0.0),
        'portfolio_net_profit_normal_vol': port_metrics.get('portfolio_net_profit_normal_vol', 0.0),
        'portfolio_net_profit_high_vol': port_metrics.get('portfolio_net_profit_high_vol', 0.0),
        'signal_timeframes': port_metrics.get('signal_timeframes', "UNKNOWN"),
        # Phase 15 Metrics
        'win_rate': port_metrics.get('win_rate', 0.0),
        'profit_factor': port_metrics.get('profit_factor', 0.0),
        'expectancy': port_metrics.get('expectancy', 0.0),
        'exposure_pct': port_metrics.get('exposure_pct', 0.0),
        'equity_stability_k_ratio': port_metrics.get('equity_stability_k_ratio', 0.0),
        'inert_filter_warnings': inert_warnings
    }
    with open(output_dir / 'portfolio_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=4)



    # --- portfolio_metadata.json (SOP Requirement) ---
    metadata = {
      "portfolio_id": strategy_id,
      "creation_timestamp_utc": datetime.utcnow().isoformat(),
      "constituent_run_ids": constituent_run_ids,
      "evaluated_assets": list(contributions.keys()),
      "total_constituent_runs": len(constituent_run_ids) if isinstance(constituent_run_ids, list) else 1,
      "total_assets_evaluated": len(contributions),
      "reference_capital_usd": summary['total_capital'],
      "capital_model_version": "v1.0_trade_close_compounding",
      "portfolio_engine_version": PORTFOLIO_ENGINE_VERSION,
      "schema_version": "1.0",
      "signal_timeframes": port_metrics.get('signal_timeframes', "UNKNOWN")
    }
    with open(output_dir / 'portfolio_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=4)

    # --- portfolio_metrics.csv ---
    with open(output_dir / 'portfolio_metrics.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value'])
        for k, v in port_metrics.items():
            w.writerow([k, v])

    # --- portfolio_overview.md ---
    top_sym = max(contributions, key=lambda s: contributions[s]['total_pnl'])
    worst_sym = min(contributions, key=lambda s: contributions[s]['total_pnl'])

    # Recommendation logic
    score = 0
    if port_metrics['sharpe'] >= 1.0: score += 2
    elif port_metrics['sharpe'] >= 0.5: score += 1
    if port_metrics['return_dd_ratio'] >= 2.0: score += 2
    elif port_metrics['return_dd_ratio'] >= 1.0: score += 1
    if abs(port_metrics['max_dd_pct']) <= 0.10: score += 1
    if port_metrics['net_pnl_usd'] > 0: score += 1
    if corr_data['avg_pairwise_corr'] < 0.5: score += 1
    top_conc = max(c['pnl_pct'] for c in contributions.values())
    if top_conc < 0.30: score += 1
    if concurrency_data['p95_concurrent'] <= 4: score += 1

    if score >= 7:
        recommendation = "**PROMOTE** - Strong structural edge, diversified, robust under stress."
    elif score >= 4:
        recommendation = "**HOLD** - Positive edge but concentration or fragility concerns require further testing."
    else:
        recommendation = "**REJECT** - Insufficient edge, structural weakness, or excessive concentration."

    # Stress fragility assessment
    baseline_pnl = stress_results.get('baseline', {}).get('net_pnl', 0)
    us_removed = [v for k, v in stress_results.items() if 'US_cluster' in k]
    us_removed_pnl = us_removed[0]['net_pnl'] if us_removed else 0
    us_dependency = ((baseline_pnl - us_removed_pnl) / baseline_pnl) if baseline_pnl != 0 else 0.0

    overview = f"""# {strategy_id} - Portfolio Evaluation Summary

## Portfolio Key Metrics (All Symbols Combined)

| Metric | Value |
|--------|-------|
| Net PnL | ${port_metrics['net_pnl_usd']:,.2f} |
| CAGR | {port_metrics['cagr']:.2%} |
| Sharpe | {port_metrics['sharpe']:.2f} |
| Sortino | {port_metrics['sortino']:.2f} |
| Max DD (USD) | ${port_metrics['max_dd_usd']:,.2f} |
| Max DD (%) | {port_metrics['max_dd_pct']:.2%} |
| Return/DD | {port_metrics['return_dd_ratio']:.2f} |
| K-Ratio | {port_metrics['k_ratio']:.2f} |
| MAR | {port_metrics['mar']:.2f} |
| Avg Correlation | {corr_data['avg_pairwise_corr']:.3f} |
| Total Trades | {port_metrics['total_trades']} |
| Period | {port_metrics['start_date']} to {port_metrics['end_date']} ({port_metrics['years']:.1f} yrs) |

## Top/Worst Contributors

- **Top**: {top_sym} (${contributions[top_sym]['total_pnl']:,.2f}, {contributions[top_sym]['pnl_pct']:.1%})
- **Worst**: {worst_sym} (${contributions[worst_sym]['total_pnl']:,.2f}, {contributions[worst_sym]['pnl_pct']:.1%})

## Capital Utilization

- Time deployed: {cap_util['pct_time_deployed']:.1%}
- Avg concurrent positions: {cap_util['avg_concurrent']:.2f}
- Max concurrent: {cap_util['max_concurrent']}

## Concurrency Profile

- 95th percentile concurrency: {concurrency_data['p95_concurrent']:.2f}
- Pct days at max concurrency: {concurrency_data['pct_days_at_max']:.1%}
- Avg concurrency during largest DD: {concurrency_data['dd_avg_concurrent']:.2f}
- Max concurrency during largest DD: {concurrency_data['dd_max_concurrent']}
- Regime avg concurrency:
    - Low: {concurrency_data['regime_avg'].get('low', 0.0):.2f}
    - Normal: {concurrency_data['regime_avg'].get('normal', 0.0):.2f}
    - High: {concurrency_data['regime_avg'].get('high', 0.0):.2f}
"""

    if concurrency_data['full_load_cluster']:
        overview += """
[WARN] **Full-load clustering detected**: 95th percentile concurrency equals maximum concurrency. Monitor regime transition risk.
"""
    if inert_warnings:
        overview += f"""
[WARN] **INERT FILTER WARNING**: The following symbols have filters enabled but 0% coverage (0 bars filtered during execution), indicating the filter had no effect vs un-filtered baseline: {', '.join(inert_warnings)}
"""

    overview += f"""
## Risk Assessment

- Largest drawdown: {dd_anatomy['peak_date']} to {dd_anatomy['trough_date']} (${dd_anatomy['absolute_drop_usd']:,.2f}, {dd_anatomy['pct_retracement']:.2%})
- Recovery: {'%d days' % dd_anatomy['recovery_days'] if dd_anatomy['recovery_days'] else 'Not recovered'}
- US cluster dependency: {us_dependency:.1%} of PnL

## Concentration Risk

- Top contributor accounts for {top_conc:.1%} of total PnL
- US cluster (NAS100, SPX500, US30): ~{us_dependency:.0%} dependency
- Avg pairwise correlation: {corr_data['avg_pairwise_corr']:.3f}

## Regime Performance

"""
    for regime, stats in regime_data['regime'].items():
        overview += f"- **{regime.title()}** vol: {stats['trades']} trades, ${stats['net_pnl']:,.2f} PnL, {stats['win_rate']:.1%} WR\n"

    overview += f"""
## Recommendation

{recommendation}

---
*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Engine: Universal_Research_Engine v{PORTFOLIO_ENGINE_VERSION}*
"""

    with open(output_dir / 'portfolio_overview.md', 'w', encoding='utf-8') as f:
        f.write(overview)

    # --- stress_test_report.md ---
    stress_md = f"# {strategy_id} - Stress Test Report\n\n"
    stress_md += "| Scenario | Symbols | Net PnL | Sharpe | Max DD | Return/DD |\n"
    stress_md += "|----------|---------|---------|--------|--------|-----------|\n"
    for name, data in stress_results.items():
        stress_md += f"| {name} | {data.get('symbols','?')} | ${data['net_pnl']:,.2f} | {data['sharpe']:.2f} | ${data['max_dd_usd']:,.2f} | {data['return_dd']:.2f} |\n"

    with open(output_dir / 'stress_test_report.md', 'w', encoding='utf-8') as f:
        f.write(stress_md)

    print(f"  [SNAPSHOT] Saved to {output_dir}")
    return recommendation


def _safe_float(value, default=0.0):
    """Best-effort numeric coercion for ledger writes."""
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_bool(value, default=False):
    """Best-effort boolean coercion for profile validity checks."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in {"true", "1", "yes", "y"}:
        return True
    if token in {"false", "0", "no", "n"}:
        return False
    return default


def _execution_health(rejection_rate_pct):
    """Classify execution regime from rejection rate."""
    rej = _safe_float(rejection_rate_pct, 0.0)
    if rej > 60.0:
        return "DEGRADED"
    if rej > 30.0:
        return "WARNING"
    return "HEALTHY"


def _profile_return_dd(profile_metrics):
    """Base Return/DD helper used to resolve deployed profile deterministically."""
    realized = _safe_float(profile_metrics.get("realized_pnl"), 0.0)
    max_dd = abs(_safe_float(profile_metrics.get("max_drawdown_usd"), 0.0))
    return realized / max(max_dd, 1.0)


def _per_symbol_realized_density(strategy_id, sim_years, rejection_rate_pct=0.0, mf_df=None):
    """Return {symbol: trades_per_year_int} — per-symbol density AFTER deployed
    profile's rejection filter.

    Two-stage derivation:
      1. Raw per-symbol density = portfolio_tradelevel.csv trade count per
         symbol / deployed profile's simulation_years. This captures the
         actual parameterization selected per symbol (not the max-across-reruns
         theoretical from master_filter).
      2. Apply deployed profile's portfolio-wide rejection_rate_pct uniformly
         (only resolution available — capital wrapper doesn't emit per-symbol
         rejection counts).

    Resolves symbol via source_run_id → master_filter lookup.
    Returns None if the tradelevel file is missing / unreadable / empty.
    """
    try:
        sim_years = float(sim_years) if sim_years is not None else 0.0
    except (TypeError, ValueError):
        sim_years = 0.0
    if sim_years <= 0:
        return None
    try:
        rej = float(rejection_rate_pct) if rejection_rate_pct is not None else 0.0
    except (TypeError, ValueError):
        rej = 0.0
    retention = max(0.0, 1.0 - rej / 100.0)
    tl_path = (STRATEGIES_ROOT / str(strategy_id)
               / "portfolio_evaluation" / "portfolio_tradelevel.csv")
    if not tl_path.exists():
        return None
    try:
        import pandas as _pd
        tl = _pd.read_csv(tl_path)
        if tl.empty or "source_run_id" not in tl.columns:
            return None
        if mf_df is None:
            from tools.ledger_db import read_master_filter
            mf_df = read_master_filter()
        if mf_df is None or mf_df.empty:
            return None
        if "run_id" not in mf_df.columns or "symbol" not in mf_df.columns:
            return None
        run_to_sym = dict(zip(mf_df["run_id"].astype(str),
                              mf_df["symbol"].astype(str)))
        tl = tl.copy()
        tl["_symbol"] = tl["source_run_id"].astype(str).map(run_to_sym)
        tl = tl.dropna(subset=["_symbol"])
        if tl.empty:
            return None
        per_sym = (tl.groupby("_symbol").size() / sim_years) * retention
        return {str(k): int(round(v)) for k, v in per_sym.items()}
    except Exception as e:
        print(f"  [WARN] per-symbol realized density failed for {strategy_id}: {e}")
        return None


def _to_mt5_timeframe(signal_tf: str) -> str:
    """Convert signal_timeframes string to MT5 notation (M5, M15, H1, D1, …).
    For multi-timeframe composites (e.g. '15m|1h'), returns pipe-separated MT5 names."""
    _MAP = {
        "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
        "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1", "1mn": "MN1",
    }
    if not signal_tf or signal_tf in ("UNKNOWN", "nan", "None"):
        return "UNKNOWN"
    parts = str(signal_tf).split("|")
    mt5_parts = []
    for p in parts:
        p_lower = p.strip().lower()
        mt5 = _MAP.get(p_lower, p.strip().upper())
        # Handle cases like "15M" -> already looks like MT5 but lowercase came through
        if mt5 not in _MAP.values() and p_lower in _MAP:
            mt5 = _MAP[p_lower]
        mt5_parts.append(mt5)
    return "|".join(sorted(set(mt5_parts)))


# Asset class detection — single source of truth (config.asset_classification).
# Replaces inline keyword matching; uses token-position-aware parsing.
from config.asset_classification import classify_asset as _detect_asset_class
from config.asset_classification import EXP_FAIL_GATES as _EXP_FAIL_GATES
from config.asset_classification import parse_strategy_name as _parse_strategy_name


def _compute_portfolio_status(realized_pnl, total_accepted, rejection_rate_pct,
                              expectancy=0.0, portfolio_id="",
                              trade_density_min=None,
                              edge_quality=None, sqn=None,
                              is_single_asset=False):
    """Deterministic portfolio status classification for ledger rows.

    Quality gates (additive — on top of all existing FAIL gates):
      Portfolios tab  → edge_quality >= 0.12 for CORE, >= 0.08 for WATCH
      Single-Asset tab → sqn >= 2.5 for CORE, >= 2.0 for WATCH
    ``is_single_asset`` controls which quality metric governs the WATCH gate.

    The density gate uses the PER-SYMBOL FLOOR (trade_density_min), not the
    composite sum. A portfolio is only as calendar-viable as its slowest leg.
    """
    realized = _safe_float(realized_pnl, 0.0)
    accepted = int(round(_safe_float(total_accepted, 0.0)))
    rejection = _safe_float(rejection_rate_pct, 0.0)
    exp = _safe_float(expectancy, 0.0)
    td = _safe_float(trade_density_min, None)
    eq = _safe_float(edge_quality, None)
    sq = _safe_float(sqn, None)

    # Asset-class expectancy gate (same thresholds as candidates sheet)
    asset_class = _detect_asset_class(portfolio_id)
    exp_gate = _EXP_FAIL_GATES.get(asset_class, 0.0)

    # ── FAIL gates (any one triggers) ────────────────────────────────
    if realized <= 0.0 or accepted < 50:
        return "FAIL"
    # Per-symbol trade density floor: composite total can inflate past 50
    # while the weakest leg has statistically meaningless sample size.
    # Burn-in calendar viability binds to the slowest symbol, not the sum.
    if td is not None and td < 50:
        return "FAIL"
    if exp < exp_gate:
        return "FAIL"

    # ── CORE gate (all conditions required) ──────────────────────────
    core_base = (realized > 1000.0 and accepted >= 200 and rejection <= 30.0)
    if core_base:
        # Portfolios: edge_quality gate
        if eq is not None and eq >= 0.12:
            return "CORE"
        # Single-Asset: SQN gate
        if sq is not None and sq >= 2.5:
            return "CORE"
        # If neither quality metric provided, fall back to base CORE
        if eq is None and sq is None:
            return "CORE"

    # ── WATCH gate (quality floor required) ──────────────────────────
    if is_single_asset:
        # Single-Asset: SQN is the governing metric
        if sq is not None:
            return "WATCH" if sq >= 2.0 else "FAIL"
        # SQN unavailable — fall back to edge_quality
        if eq is not None:
            return "WATCH" if eq >= 0.08 else "FAIL"
    else:
        # Portfolios: edge_quality is the governing metric
        if eq is not None:
            return "WATCH" if eq >= 0.08 else "FAIL"
        # edge_quality unavailable — fall back to SQN
        if sq is not None:
            return "WATCH" if sq >= 2.0 else "FAIL"
    # No quality metric available — default WATCH (backwards compat)
    return "WATCH"


def _empty_selection_debug(previous_profile=None):
    """Build default selection diagnostics payload."""
    return {
        "candidates": [],
        "selected_profile": None,
        "selection_reason": "fallback",
        "previous_profile": previous_profile,
        "persistence_used": False,
        "reliability_override": False,
    }


def _load_profile_comparison(strategy_id):
    """Load strategies/<id>/deployable/profile_comparison.json."""
    comparison_path = STRATEGIES_ROOT / strategy_id / "deployable" / "profile_comparison.json"
    if not comparison_path.exists():
        return None, comparison_path
    try:
        payload = json.loads(comparison_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] Failed to parse profile comparison for {strategy_id}: {e}")
        return None, comparison_path
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        print(f"  [WARN] Invalid profile comparison schema for {strategy_id}: missing non-empty 'profiles'.")
        return None, comparison_path

    # Invariant: all profiles must share the same starting_capital — otherwise
    # CAGR/ROI/score comparisons across profiles are built on inconsistent
    # denominators and silently select the wrong deployed_profile.
    _caps = {
        name: m.get("starting_capital")
        for name, m in profiles.items()
        if isinstance(m, dict) and m.get("starting_capital") is not None
    }
    _cap_values = {round(float(v), 6) for v in _caps.values()}
    if len(_cap_values) > 1:
        raise ValueError(
            f"PROFILE_CAPITAL_MISMATCH: profile_comparison.json for {strategy_id} "
            f"has inconsistent starting_capital across profiles: {_caps}. "
            f"All profiles must share the same starting_capital for valid "
            f"CAGR/ROI/score comparison."
        )
    return profiles, comparison_path


# CRITICAL INVARIANT:
# This is the ONLY function allowed to select deployed_profile.
# All other modules must treat deployed_profile as read-only.
def _resolve_deployed_profile(strategy_id, profiles, df_ledger):
    """
    Resolve deployed profile using:
      1) Hard validity filter (realized_pnl > 0 and capital_validity_flag is True).
      2) Penalized Return/DD score with execution health bands.
      3) Similar-score stabilization tie-breaks.

    STATELESS: selection is computed purely from profile_comparison.json.
    No hint or persistence from existing ledger values.
    """
    selection_debug = _empty_selection_debug(previous_profile=None)
    reliable_candidates = []
    hard_valid_candidates = []
    debug_candidates = []
    for name in sorted(profiles.keys()):
        metrics = profiles.get(name)
        if not isinstance(metrics, dict):
            debug_candidates.append(
                {
                    "profile": name,
                    "valid": False,
                    "flags": {
                        "pnl_invalid": True,
                        "capital_invalid": True,
                        "low_samples": True,
                        "low_years": True,
                    },
                    "base_score": 0.0,
                    "penalty_multiplier": 0.0,
                    "final_score": 0.0,
                    "rejection_rate": 0.0,
                    "total_accepted": 0,
                }
            )
            continue

        realized = _safe_float(metrics.get("realized_pnl"), 0.0)
        capital_valid = _safe_bool(metrics.get("capital_validity_flag"), False)
        avg_risk = _safe_float(metrics.get("avg_risk_multiple"), 0.0)
        rej = _safe_float(metrics.get("rejection_rate_pct"), 0.0)
        # Execution-health penalty uses execution_rejection_rate_pct when present:
        # excludes RETAIL_MAX_LOT_EXCEEDED skips (capital-ceiling saturation is
        # evidence of outstanding returns, not weak execution — penalizing it
        # was upside-down logic). Falls back to raw rej for legacy metrics.
        rej_health = _safe_float(
            metrics.get("execution_rejection_rate_pct", rej), rej
        )
        accepted = int(round(_safe_float(metrics.get("total_accepted"), 0.0)))
        sim_years = _safe_float(metrics.get("simulation_years"), 0.0)
        base_score = _profile_return_dd(metrics)

        health = _execution_health(rej_health)
        if health == "DEGRADED":
            penalty = 0.4
        elif health == "WARNING":
            penalty = 0.7
        else:
            penalty = 1.0
        score = base_score * penalty

        flags = {
            "pnl_invalid": realized <= 0.0,
            "capital_invalid": not capital_valid,
            # Retail-realistic oversizing tolerance: compounding small-account profiles
            # (REAL_MODEL_V1 tier-ramp) exceed 1.5× early in the curve before equity
            # grows past the min-lot barrier. 2.5 matches industry realistic-retail norm.
            "risk_overextended": avg_risk > 2.5,
            "low_samples": accepted < RELIABILITY_MIN_ACCEPTED,
            "low_years": sim_years < RELIABILITY_MIN_SIM_YEARS,
        }
        hard_valid = (not flags["pnl_invalid"]) and (not flags["capital_invalid"]) and (not flags["risk_overextended"])
        reliable_valid = hard_valid and (not flags["low_samples"]) and (not flags["low_years"])

        candidate_row = {
            "name": name,
            "metrics": metrics,
            "score": score,
            "base_score": base_score,
            "rejection_rate_pct": rej,
            "total_accepted": accepted,
            "health": health,
            "flags": flags,
            "hard_valid": hard_valid,
            "reliable_valid": reliable_valid,
        }

        debug_candidates.append(
            {
                "profile": name,
                "valid": False,  # finalized after reliability override decision
                "flags": flags,
                "base_score": round(base_score, 6),
                "penalty_multiplier": penalty,
                "final_score": round(score, 6),
                "rejection_rate": round(rej, 4),
                "total_accepted": accepted,
            }
        )

        if hard_valid:
            hard_valid_candidates.append(candidate_row)
            if reliable_valid:
                reliable_candidates.append(candidate_row)

    if reliable_candidates:
        candidates = reliable_candidates
        reliability_override = False
    elif hard_valid_candidates:
        candidates = hard_valid_candidates
        reliability_override = True
    else:
        candidates = []
        reliability_override = False

    selection_debug["reliability_override"] = reliability_override
    for dbg in debug_candidates:
        profile_name = dbg["profile"]
        src = next((c for c in hard_valid_candidates if c["name"] == profile_name), None)
        if src is None:
            dbg["valid"] = False
        elif reliability_override:
            dbg["valid"] = True
        else:
            dbg["valid"] = bool(src["reliable_valid"])
    selection_debug["candidates"] = debug_candidates

    if not candidates:
        return None, None, "no_valid_profiles", selection_debug

    # Stable deterministic ordering for tie handling.
    candidates.sort(
        key=lambda c: (
            -c["score"],
            c["rejection_rate_pct"],
            -c["total_accepted"],
            c["name"],
        )
    )

    # Similar-score stabilization window (within 15% of current best score).
    best = candidates[0]
    for cand in candidates[1:]:
        denom = max(best["score"], cand["score"])
        rel_gap = 0.0 if denom <= 1e-12 else abs(best["score"] - cand["score"]) / denom
        if rel_gap < 0.15:
            tie_key_best = (best["rejection_rate_pct"], -best["total_accepted"], best["name"])
            tie_key_cand = (cand["rejection_rate_pct"], -cand["total_accepted"], cand["name"])
            if tie_key_cand < tie_key_best:
                best = cand
        else:
            break

    best_name = best["name"]
    best_metrics = best["metrics"]
    best_score = best["score"]

    # STATELESS: no persistence logic — always use the best-scored profile.
    selection_debug["selected_profile"] = best_name
    selection_debug["selection_reason"] = "fallback" if reliability_override else "highest_score"
    selection_debug["persistence_used"] = False
    return best_name, best_metrics, "best_scored", selection_debug


def _get_deployed_profile_metrics(strategy_id, df_ledger):
    """Return deployed profile payload for ledger injection, or None."""
    profiles, comparison_path = _load_profile_comparison(strategy_id)
    if profiles is None:
        debug = _empty_selection_debug(previous_profile=None)
        if comparison_path.exists():
            print(f"  [WARN] Profile comparison unusable for {strategy_id}: {comparison_path}")
        else:
            print(f"  [WARN] Profile comparison not found for {strategy_id}: {comparison_path}")
        return {
            "profile_name": None,
            "realized_pnl": 0.0,
            "trades_accepted": None,
            "trades_rejected": None,
            "rejection_rate_pct": None,
            "source": "missing_profile_comparison",
            "selection_debug": debug,
        }

    profile_name, profile_metrics, source, selection_debug = _resolve_deployed_profile(strategy_id, profiles, df_ledger)
    if profile_name is None or profile_metrics is None:
        print(f"  [WARN] Could not resolve deployed profile for {strategy_id} (no valid profile).")
        return {
            "profile_name": None,
            "realized_pnl": 0.0,
            "trades_accepted": None,
            "trades_rejected": None,
            "rejection_rate_pct": None,
            "source": source,
            "selection_debug": selection_debug,
        }

    deployed = {
        "profile_name": profile_name,
        "realized_pnl": round(_safe_float(profile_metrics.get("realized_pnl"), 0.0), 2),
        "trades_accepted": int(round(_safe_float(profile_metrics.get("total_accepted"), 0.0))),
        "trades_rejected": int(round(_safe_float(profile_metrics.get("total_rejected"), 0.0))),
        "rejection_rate_pct": round(_safe_float(profile_metrics.get("rejection_rate_pct"), 0.0), 2),
        "simulation_years": _safe_float(profile_metrics.get("simulation_years"), 0.0),
        "source": source,
        "selection_debug": selection_debug,
    }
    print(
        f"  [PROFILE] Using {deployed['profile_name']} ({deployed['source']}) "
        f"for ledger PnL/trade counts."
    )
    return deployed


def update_master_portfolio_ledger(strategy_id, metrics, corr_data, max_stress_corr, concurrency_data, constituent_run_ids, n_assets=1):
    """
    Append portfolio result to Master_Portfolio_Sheet.xlsx (SOP 8).
    Enforces append-only logic and schema validation.

    Routes rows into two sheets based on asset count:
      - "Portfolios"               (multi-asset, n_assets > 1)
      - "Single-Asset Composites"  (single-asset, n_assets == 1)

    Single-asset sheet drops meaningless correlation columns and adds
    regime-aware metrics (placeholders until Strategy Activation System).
    """
    ledger_path = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"

    is_single_asset = (n_assets <= 1)
    target_sheet = "Single-Asset Composites" if is_single_asset else "Portfolios"

    # Schema: shared base columns (both sheets)
    _BASE_COLUMNS = [
        # Identity
        "portfolio_id",
        "source_strategy",

        # Capital & Performance
        "reference_capital_usd",
        "portfolio_status",
        "evaluation_timeframe",
        "symbol_count",
        "trade_density_total",
        "trade_density_min",
        "profile_trade_density_total",
        "profile_trade_density_min",
        "theoretical_pnl",
        "realized_pnl",
        "sharpe",
        "max_dd_pct",
        "return_dd_ratio",
        "win_rate",
        "profit_factor",
        "expectancy",
        "total_trades",
        "exposure_pct",
        "equity_stability_k_ratio",

        # Deployed Profile
        "deployed_profile",
        "trades_accepted",
        "trades_rejected",
        "rejection_rate_pct",
        "realized_vs_theoretical_pnl",

        # Capital Utilization
        "peak_capital_deployed",
        "capital_overextension_ratio",

        # Concurrency
        "avg_concurrent",
        "max_concurrent",
        "p95_concurrent",
        "dd_max_concurrent",
    ]

    # Multi-asset: edge_quality (not sqn) + correlation columns
    _MULTI_ASSET_TAIL = [
        "edge_quality",
        "full_load_cluster",
        "avg_pairwise_corr",
        "max_pairwise_corr_stress",
        "portfolio_net_profit_low_vol",
        "portfolio_net_profit_normal_vol",
        "portfolio_net_profit_high_vol",
        "parsed_fields",
        "portfolio_engine_version",
        "creation_timestamp",
        "constituent_run_ids",
    ]

    # Single-asset: sqn (not edge_quality), n_strategies
    _SINGLE_ASSET_TAIL = [
        "sqn",
        "n_strategies",
        "portfolio_net_profit_low_vol",
        "portfolio_net_profit_normal_vol",
        "portfolio_net_profit_high_vol",
        "parsed_fields",
        "portfolio_engine_version",
        "creation_timestamp",
        "constituent_run_ids",
    ]

    columns = _BASE_COLUMNS + (_SINGLE_ASSET_TAIL if is_single_asset else _MULTI_ASSET_TAIL)

    # Process constituent_run_ids (list -> string)
    if isinstance(constituent_run_ids, list):
        run_ids_str = ",".join(str(x) for x in constituent_run_ids)
    else:
        run_ids_str = str(constituent_run_ids)

    # Load or Create — read from correct sheet, preserve other sheet
    _other_sheet = "Portfolios" if is_single_asset else "Single-Asset Composites"
    df_other = None
    from tools.ledger_db import read_mps as _read_mps_ledger
    df_ledger = _read_mps_ledger(sheet=target_sheet)
    if df_ledger.empty:
        df_ledger = pd.DataFrame(columns=columns)
    df_other = _read_mps_ledger(sheet=_other_sheet)
    if df_other.empty:
        df_other = None

    # Column migration for existing sheets.
    # Fix renamed headers left by old formatter (sharpe (ann.) → sharpe, etc.)
    _HEADER_FIXUPS = {"sharpe (ann.)": "sharpe", "k_ratio (log)": "equity_stability_k_ratio",
                      "realized_pnl_usd": "edge_quality" if not is_single_asset else "sqn"}
    for old_name, canonical in _HEADER_FIXUPS.items():
        if old_name in df_ledger.columns and canonical not in df_ledger.columns:
            df_ledger.rename(columns={old_name: canonical}, inplace=True)
    # Drop ghost columns from pandas dedup (.1, .2, .3 suffixes)
    ghost = [c for c in df_ledger.columns if any(c.startswith(p) for p in
             ("sharpe (ann.).", "k_ratio (log)."))]
    if ghost:
        df_ledger.drop(columns=ghost, inplace=True, errors="ignore")
    if "realized_pnl" not in df_ledger.columns and "net_pnl_usd" in df_ledger.columns:
        df_ledger["realized_pnl"] = df_ledger["net_pnl_usd"]
    if "theoretical_pnl" not in df_ledger.columns:
        if "net_pnl_usd" in df_ledger.columns:
            df_ledger["theoretical_pnl"] = pd.to_numeric(df_ledger["net_pnl_usd"], errors="coerce")
        else:
            df_ledger["theoretical_pnl"] = pd.to_numeric(df_ledger.get("realized_pnl"), errors="coerce")
    # Recompute portfolio_status for ALL rows (expectancy + quality gates may reclassify)
    df_ledger["portfolio_status"] = df_ledger.apply(
        lambda row: _compute_portfolio_status(
            row.get("realized_pnl", 0.0),
            row.get("trades_accepted", row.get("total_accepted", 0)),
            row.get("rejection_rate_pct", 0.0),
            expectancy=row.get("expectancy", 0.0),
            portfolio_id=row.get("portfolio_id", ""),
            trade_density_min=row.get("trade_density_min",
                                     row.get("trade_density", None)),
            edge_quality=row.get("edge_quality", None),
            sqn=row.get("sqn", None),
            is_single_asset=is_single_asset,
        ),
        axis=1,
    )

    # Recompute deployed_profile for ALL existing rows.
    # Previous bug: only the NEW row got a fresh profile selection; existing rows
    # kept stale values from the version of the algorithm that originally wrote them.
    # Now we re-run the full selection algorithm (including persistence) for every row.
    _profile_fields = ["deployed_profile", "trades_accepted",
                       "trades_rejected", "rejection_rate_pct", "realized_vs_theoretical_pnl"]
    _recomputed = 0
    for idx in df_ledger.index:
        pid = str(df_ledger.at[idx, "portfolio_id"])
        if pid == str(strategy_id):
            continue  # Skip the row we're about to append — it gets fresh selection below
        dep = _get_deployed_profile_metrics(pid, df_ledger)
        if dep is None or dep.get("profile_name") is None:
            # No valid profile — clear stale values
            df_ledger.at[idx, "deployed_profile"] = None
            df_ledger.at[idx, "realized_vs_theoretical_pnl"] = 0.0
            continue
        df_ledger.at[idx, "deployed_profile"] = dep["profile_name"]
        df_ledger.at[idx, "realized_pnl"] = dep["realized_pnl"]
        df_ledger.at[idx, "trades_accepted"] = dep["trades_accepted"]
        df_ledger.at[idx, "trades_rejected"] = dep["trades_rejected"]
        df_ledger.at[idx, "rejection_rate_pct"] = dep["rejection_rate_pct"]
        theo = _safe_float(df_ledger.at[idx, "theoretical_pnl"], 0.0)
        if abs(theo) > 1e-12:
            df_ledger.at[idx, "realized_vs_theoretical_pnl"] = round(dep["realized_pnl"] / theo, 4)
        _recomputed += 1
    if _recomputed:
        print(f"  [LEDGER] Recomputed deployed_profile for {_recomputed} existing rows.")

    # Baseline "theoretical" portfolio PnL from raw Stage-4 aggregation.
    # Realized PnL may differ when deployed profiles apply sizing/rejection rules.
    theoretical_pnl = round(_safe_float(metrics.get("net_pnl_usd"), 0.0), 2)
    realized_pnl = theoretical_pnl
    deployed_profile = None
    trades_accepted = None
    trades_rejected = None
    rejection_rate_pct = None

    deployed = _get_deployed_profile_metrics(strategy_id, df_ledger)
    selection_debug = deployed.get("selection_debug") if isinstance(deployed, dict) else _empty_selection_debug()
    if deployed is not None and deployed.get("profile_name") is not None:
        deployed_profile = deployed["profile_name"]
        realized_pnl = deployed["realized_pnl"]
        trades_accepted = deployed["trades_accepted"]
        trades_rejected = deployed["trades_rejected"]
        rejection_rate_pct = deployed["rejection_rate_pct"]

    if abs(theoretical_pnl) > 1e-12:
        ratio_realized_vs_theoretical = round(realized_pnl / theoretical_pnl, 4)
    else:
        ratio_realized_vs_theoretical = 0.0

    # ── Per-symbol trade density (computed BEFORE status so density gate applies to new row) ──
    # Rule: groupby symbol → take MAX across reruns (most favorable run per symbol),
    # then sum for total, min for floor. min governs burn-in calendar viability.
    td_total = None
    td_min = None
    symbol_count = None
    if isinstance(constituent_run_ids, list) and len(constituent_run_ids) > 0:
        try:
            from tools.ledger_db import read_master_filter
            ms_df = read_master_filter()
            if (not ms_df.empty
                    and 'run_id' in ms_df.columns
                    and 'trade_density' in ms_df.columns
                    and 'symbol' in ms_df.columns):
                valid = ms_df[ms_df['run_id'].astype(str)
                              .isin([str(x) for x in constituent_run_ids])]
                valid = valid.dropna(subset=['trade_density'])
                if not valid.empty:
                    per_sym = valid.groupby('symbol')['trade_density'].max()
                    td_total = int(per_sym.sum())
                    td_min = int(per_sym.min())
                    symbol_count = int(per_sym.size)
        except Exception as e:
            print(f"  [WARN] Failed to aggregate component trade density: {e}")

    # ── Profile-adjusted per-symbol density ──
    # Preferred: derive from portfolio_tradelevel.csv (true realized per-symbol
    # density under the deployed profile — captures per-symbol asymmetric
    # capital rejection AND the actual parameterization selected per symbol).
    # Fallback: raw × (1 - portfolio_rejection) — uniform approximation when
    # tradelevel is unavailable.
    profile_td_total = None
    profile_td_min = None
    sim_years = deployed.get("simulation_years") if isinstance(deployed, dict) else None
    realized_map = _per_symbol_realized_density(
        strategy_id, sim_years, rejection_rate_pct=rejection_rate_pct)
    if realized_map:
        vals = list(realized_map.values())
        profile_td_total = int(sum(vals))
        profile_td_min = int(min(vals))
    else:
        effective_rejection = rejection_rate_pct if rejection_rate_pct is not None else 0.0
        profile_td_total = (int(round(td_total * (1.0 - effective_rejection / 100.0)))
                            if td_total is not None else None)
        profile_td_min = (int(round(td_min * (1.0 - effective_rejection / 100.0)))
                          if td_min is not None else None)

    portfolio_status = _compute_portfolio_status(
        realized_pnl, trades_accepted, rejection_rate_pct,
        expectancy=metrics.get("expectancy", 0.0),
        portfolio_id=strategy_id,
        trade_density_min=td_min,
        edge_quality=metrics.get("edge_quality", None),
        sqn=metrics.get("sqn", None),
        is_single_asset=is_single_asset,
    )

    # Construct Row Data (shared fields)
    row_data = {
        "portfolio_id": strategy_id,
        "creation_timestamp": datetime.utcnow().isoformat(),
        "constituent_run_ids": run_ids_str,
        "source_strategy": strategy_id,
        # OWNER: Step 7 only. All other steps read-only.
        # Effective capital = max concurrent positions × $1,000 per asset.
        "reference_capital_usd": concurrency_data["max_concurrent"] * 1000,
        "portfolio_status": portfolio_status,
        "theoretical_pnl": theoretical_pnl,
        "realized_pnl": realized_pnl,
        "sharpe": metrics["sharpe"],
        "max_dd_pct": metrics["max_dd_pct"] * 100,  # convert fraction to percentage
        "return_dd_ratio": metrics["return_dd_ratio"],
        "peak_capital_deployed": metrics.get("peak_capital_deployed", 0.0),
        "capital_overextension_ratio": metrics.get("capital_overextension_ratio", 0.0),
        "avg_concurrent": concurrency_data["avg_concurrent"],
        "max_concurrent": concurrency_data["max_concurrent"],
        "p95_concurrent": concurrency_data["p95_concurrent"],
        "dd_max_concurrent": concurrency_data["dd_max_concurrent"],
        "full_load_cluster": concurrency_data["full_load_cluster"],
        "total_trades": metrics["total_trades"],

        # Per-symbol density fields (computed above, before status gate).
        # total = SUM across symbols; min = SLOWEST leg; profile_* = same × (1-rejection).
        "symbol_count": symbol_count if symbol_count is not None else "NA",
        "trade_density_total": td_total if td_total is not None else "NA",
        "trade_density_min": td_min if td_min is not None else "NA",
        "profile_trade_density_total": profile_td_total if profile_td_total is not None else "NA",
        "profile_trade_density_min": profile_td_min if profile_td_min is not None else "NA",

        "portfolio_engine_version": PORTFOLIO_ENGINE_VERSION,
        "portfolio_net_profit_low_vol": metrics.get("portfolio_net_profit_low_vol", 0.0),
        "portfolio_net_profit_normal_vol": metrics.get("portfolio_net_profit_normal_vol", 0.0),
        "portfolio_net_profit_high_vol": metrics.get("portfolio_net_profit_high_vol", 0.0),
        "evaluation_timeframe": metrics.get("signal_timeframes", "UNKNOWN"),
        "signal_timeframes": metrics.get("signal_timeframes", "UNKNOWN"),
        "win_rate": metrics.get("win_rate", 0.0),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "expectancy": metrics.get("expectancy", 0.0),
        "exposure_pct": metrics.get("exposure_pct", 0.0),
        "equity_stability_k_ratio": metrics.get("equity_stability_k_ratio", 0.0),
        "deployed_profile": deployed_profile,
        "edge_quality": metrics.get("edge_quality", 0.0),
        "peak_dd_ratio": metrics.get("peak_dd_ratio", 0.0),
        "trades_accepted": trades_accepted,
        "trades_rejected": trades_rejected,
        "rejection_rate_pct": rejection_rate_pct,
        "realized_vs_theoretical_pnl": ratio_realized_vs_theoretical,
        "selection_debug": selection_debug,
    }

    # Fix 2: parsed_fields — machine-parsed decomposition of the strategy name.
    # Eliminates re-parsing the same string across multiple consumers.
    parsed = _parse_strategy_name(strategy_id)
    row_data["parsed_fields"] = json.dumps(parsed) if parsed else None

    # Sheet-specific fields
    if is_single_asset:
        n_strats = len(constituent_run_ids) if isinstance(constituent_run_ids, list) else 1
        row_data["n_strategies"] = n_strats
        row_data["sqn"] = metrics.get("sqn", 0.0)
        # Fix 3: readable_alias — human-readable label for PF_ hash composites.
        # Format: <SYMBOL>_<N>S_<PRIMARY_FAMILY>_<TF>
        if strategy_id.upper().startswith("PF_"):
            _alias_parts = []
            # Symbol from evaluated_assets (already known — n_assets == 1)
            _eval_dir = STRATEGIES_ROOT / strategy_id / "portfolio_evaluation"
            _alias_sym = None
            for _fn in ("portfolio_metadata.json", "portfolio_summary.json"):
                _fp = _eval_dir / _fn
                if _fp.exists():
                    try:
                        with open(_fp, encoding="utf-8") as _f:
                            _d = json.load(_f)
                        _ea = _d.get("evaluated_assets")
                        if _ea and isinstance(_ea, list):
                            _alias_sym = _ea[0].upper()
                            break
                    except Exception:
                        pass
            _alias_tf = metrics.get("signal_timeframes", "")
            if _alias_sym:
                _alias_parts.append(_alias_sym)
            _alias_parts.append(f"{n_strats}S")
            if _alias_tf and _alias_tf != "UNKNOWN":
                _alias_parts.append(_alias_tf.replace("|", "_"))
            row_data["readable_alias"] = "_".join(_alias_parts) if _alias_parts else None
        else:
            row_data["readable_alias"] = None
        # Regime-aware metrics — placeholders until Strategy Activation System is implemented.
        # When regime_router is integrated, these will be populated from actual gating results.
        row_data["regime_gate_enabled"] = False
        row_data["activation_rate_pct"] = None
        row_data["regime_blocked_trades"] = None
        row_data["blocked_pnl_raw"] = None
    else:
        row_data["avg_pairwise_corr"] = corr_data["avg_pairwise_corr"]
        row_data["max_pairwise_corr_stress"] = max_stress_corr

    # (Trade density already computed above, before status gate — no post-row writeback.)

    # Check Duplicate & Append-Only Idempotent Guard
    if strategy_id in df_ledger["portfolio_id"].astype(str).values:
        existing_row = df_ledger[df_ledger["portfolio_id"].astype(str) == strategy_id].iloc[-1]
        is_identical = True
        for k, v in row_data.items():
            if k in ["creation_timestamp", "portfolio_engine_version", "selection_debug"]:
                continue
            old_val = existing_row.get(k)
            if pd.isna(old_val) and (v is None or pd.isna(v)):
                continue
            try:
                if abs(float(old_val) - float(v)) > 1e-4:
                    is_identical = False
                    break
            except Exception:
                if str(old_val) != str(v):
                    is_identical = False
                    break
        if is_identical:
            print(f"  [LEDGER] Portfolio '{strategy_id}' already exists and is identical. Skipping append (idempotent).")
            return
        raise ValueError(
            f"[FATAL] Attempted modification of existing portfolio entry '{strategy_id}'.\n"
            f"Explicit human authorization required. No automatic overwrite allowed."
        )

    # Append (FileLock prevents concurrent xlsx corruption when running parallel directives)
    new_row = pd.DataFrame([row_data])
    for c in columns:
        if c not in new_row.columns:
            new_row[c] = None
    df_final = pd.concat([df_ledger, new_row[columns]], ignore_index=True)
    _lock_path = ledger_path.with_suffix(".lock")
    with FileLock(str(_lock_path), timeout=120):
        ensure_xlsx_writable(ledger_path)
        # DB FIRST (mandatory) — SQLite is the source of truth
        from tools.ledger_db import _connect as _db_connect, create_tables as _db_create, upsert_mps_df as _db_upsert
        _db_conn = _db_connect()
        _db_create(_db_conn)
        _db_upsert(_db_conn, df_final, sheet=target_sheet)
        if df_other is not None and not df_other.empty:
            _db_upsert(_db_conn, df_other, sheet=_other_sheet)
        _db_conn.close()
        print(f"  [LEDGER_DB] Synced {len(df_final)} {target_sheet} rows to ledger.db")

        # EXCEL SECOND (derived view, best-effort)
        # Preserve non-data sheets (e.g. Notes).
        _preserve = {}
        _data_names = {target_sheet, _other_sheet}
        if ledger_path.exists():
            with pd.ExcelFile(ledger_path) as _xls:
                for _sn in _xls.sheet_names:
                    if _sn not in _data_names:
                        try:
                            _preserve[_sn] = pd.read_excel(_xls, sheet_name=_sn)
                        except Exception:
                            pass
        try:
            _tmp_ledger = ledger_path.with_suffix(".xlsx.tmp")
            with pd.ExcelWriter(_tmp_ledger, engine="openpyxl", mode="w") as writer:
                df_final.to_excel(writer, sheet_name=target_sheet, index=False)
                if df_other is not None and not df_other.empty:
                    df_other.to_excel(writer, sheet_name=_other_sheet, index=False)
                for _sn, _sdf in _preserve.items():
                    _sdf.to_excel(writer, sheet_name=_sn, index=False)
            import os as _os_atomic
            with open(_tmp_ledger, "r+b") as _fh:
                _os_atomic.fsync(_fh.fileno())
            _os_atomic.replace(str(_tmp_ledger), str(ledger_path))
        except Exception as _xl_err:
            print(f"  [WARN] Excel export failed ({_xl_err}). Run: python tools/ledger_db.py --export-mps")

        # Call Unified Formatter (best-effort)
        _formatter = PROJECT_ROOT / "tools" / "format_excel_artifact.py"
        try:
            subprocess.run(
                [sys.executable, str(_formatter), "--file", str(ledger_path), "--profile", "portfolio"],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Formatting failed: {e}")

        try:
            subprocess.run(
                [sys.executable, str(_formatter), "--file", str(ledger_path), "--notes-type", "portfolio"],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Notes sheet failed: {e}")


# ==================================================================
# MAIN
# ==================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("strategy_id", help="The Portfolio ID name (e.g. P001)")
    parser.add_argument("--run-ids", required=True, nargs="+", help="Explicit atomic runs to construct the portfolio from")
    parser.add_argument("--force-ledger", action="store_true", help="Force Master Ledger write even for single-run/single-asset strategies (sweep tracking)")
    args = parser.parse_args()

    strategy_id = args.strategy_id
    run_ids = args.run_ids
    
    print(f"\n{'='*60}")
    print(f"PORTFOLIO EVALUATION - {strategy_id}")
    print(f"Constituents: {run_ids}")
    print(f"{'='*60}")

    output_dir = STRATEGIES_ROOT / strategy_id / "portfolio_evaluation"

    # Load data
    print("\n[1/9] Loading trade data...")
    portfolio_df, symbol_trades, meta_records = load_all_trades(run_ids)
    print(f"  Loaded {len(portfolio_df)} trades across {len(symbol_trades)} symbols")
    
    # Phase 1: Metadata Contract Enforcement - HARD FAIL
    REQUIRED_META_KEYS = ["signature_hash", "trend_filter_enabled", "filter_coverage", "filtered_bars", "total_bars"]
    meta_warnings = []
    for sym, meta in meta_records.items():
        missing_keys = [k for k in REQUIRED_META_KEYS if k not in meta]
        if missing_keys:
            meta_warnings.append(f"{sym}: missing {missing_keys}")
    if meta_warnings:
        for w in meta_warnings:
            print(f"    - {w}")
        raise RuntimeError(
            f"GOVERNANCE_ABORT: {len(meta_warnings)} symbols missing required metadata contract. "
            f"Re-run backtests with updated pipeline to populate missing fields."
        )
    
    # Phase 1: Signature Hash Consistency Check
    unique_hashes = set()
    for sym, meta in meta_records.items():
        h = meta.get('signature_hash')
        if h:
            unique_hashes.add(h)
    if len(unique_hashes) > 1:
        print(
            f"[WARN] GOVERNANCE_ABORT bypassed: Mixed signature hashes detected across symbols. "
            f"Found {len(unique_hashes)} unique hashes: {unique_hashes}. "
            f"Bypassing to allow multi-strategy portfolio."
        )
    print(f"  [GOVERNANCE] Signature hash consistent across {len(meta_records)} symbols.")
    
    # Check for Inert Filters
    inert_warnings = []
    for sym, meta in meta_records.items():
        if meta.get('trend_filter_enabled', False):
            coverage = meta.get('filter_coverage', -1)
            if coverage == 0.0:
                inert_warnings.append(sym)
    if inert_warnings:
        print(f"  [WARN] Inert filters detected on {len(inert_warnings)} symbols (0% filter coverage)")

    # Portfolio construction
    print("[2/9] Building portfolio equity curve...")
    
    if not symbol_trades:
        raise ValueError("Cannot compute reference capital: no symbols detected")

    portfolio_equity, symbol_equity, daily_pnl = build_portfolio_equity(portfolio_df, symbol_trades)
    port_metrics = compute_portfolio_metrics(portfolio_equity, daily_pnl, portfolio_df, len(symbol_trades))
    
    # Deterministic capital calculation (SOP Issue #2)
    port_metrics['total_capital'] = TOTAL_PORTFOLIO_CAPITAL

    # Regime PnL Calculation (Zero Structural Change Injection)
    if "volatility_regime" in portfolio_df.columns:
        regime_pnl = portfolio_df.groupby("volatility_regime")["pnl_usd"].sum()
        low_pnl = float(regime_pnl.get("low", 0.0))
        normal_pnl = float(regime_pnl.get("normal", 0.0))
        high_pnl = float(regime_pnl.get("high", 0.0))
    else:
        low_pnl = normal_pnl = high_pnl = 0.0

    port_metrics["portfolio_net_profit_low_vol"] = low_pnl
    port_metrics["portfolio_net_profit_normal_vol"] = normal_pnl
    port_metrics["portfolio_net_profit_high_vol"] = high_pnl

    # Timeframe Metadata Extraction (SOP Requirement)
    try:
        from tools.ledger_db import read_master_filter as _read_mf_local
        df_master_local = _read_mf_local()
        
        # Filter for runs present in the loaded portfolio
        # unique_runs is defined later in the code (line ~1461), but we need it now or we can use portfolio_df['source_run_id']
        current_run_ids = sorted(list(set(portfolio_df['source_run_id'].astype(str).unique())))
        
        related_runs = df_master_local[df_master_local['run_id'].astype(str).isin(current_run_ids)]
        
        # Normalize column name
        tf_col = 'timeframe' if 'timeframe' in related_runs.columns else 'TIMEFRAME'
        
        if tf_col in related_runs.columns:
             timeframes = sorted(related_runs[tf_col].astype(str).unique())
             signal_timeframes_str = "|".join(timeframes)
        else:
             signal_timeframes_str = "UNKNOWN"
             
    except Exception as e:
        print(f"  [WARN] Failed to extract timeframes: {e}")
        signal_timeframes_str = "UNKNOWN"

    # Normalize signal_timeframes to MT5 notation (M5, M15, H1, D1, …)
    port_metrics['signal_timeframes'] = _to_mt5_timeframe(signal_timeframes_str)
    
    print(f"  Net PnL: ${port_metrics['net_pnl_usd']:,.2f} | Sharpe: {port_metrics['sharpe']}")

    # Concurrency base (compute once, reuse in capital_utilization + concurrency_profile)
    _conc_base = compute_concurrency_series(portfolio_df)

    # Capital utilization
    print("[3/9] Analyzing capital utilization...")
    cap_util = capital_utilization(portfolio_df, symbol_trades, _precomputed_concurrency=_conc_base)
    print(f"  Deployed: {cap_util['pct_time_deployed']}% | Max concurrent: {cap_util['max_concurrent']}")

    # Concurrency
    print("[X/9] Computing concurrency profile...")
    concurrency_data = concurrency_profile(portfolio_df, portfolio_equity, _precomputed_concurrency=_conc_base)
    print(f"  avg_concurrent: {concurrency_data['avg_concurrent']}")
    print(f"  max_concurrent: {concurrency_data['max_concurrent']}")
    print(f"  p95_concurrent: {concurrency_data['p95_concurrent']}")
    print(f"  dd_max_concurrent: {concurrency_data['dd_max_concurrent']}")

    # Correlation
    print("[4/9] Computing correlation structure...")
    corr_data = correlation_analysis(symbol_equity)
    print(f"  Avg pairwise correlation: {corr_data['avg_pairwise_corr']}")

    # Contribution
    print("[5/9] Analyzing symbol contributions...")
    contributions = contribution_analysis(symbol_trades, portfolio_df)
    top_sym = max(contributions, key=lambda s: contributions[s]['total_pnl'])
    print(f"  Top contributor: {top_sym} ({contributions[top_sym]['pnl_pct']:.1%})")

    # Drawdown anatomy
    print("[6/9] Dissecting largest drawdown...")
    dd_anatomy = drawdown_anatomy(portfolio_equity, portfolio_df)
    print(f"  Largest DD: ${dd_anatomy['absolute_drop_usd']:,.2f} ({dd_anatomy['pct_retracement']:.2%})")

    # Stress Correlation (Injection)
    print("[6.5/9] Computing stress-window correlation...")
    max_stress_corr = compute_stress_correlation(
        corr_data['returns_df'], 
        dd_anatomy['peak_date'], 
        dd_anatomy['trough_date']
    )
    print(f"  Max pairwise (stress): {max_stress_corr:.3f}")

    # Stress testing
    print("[7/9] Running stress tests...")
    stress_results = stress_test(symbol_trades, portfolio_df)
    for name, data in stress_results.items():
        print(f"  {name}: PnL=${data['net_pnl']:,.2f}, Sharpe={data['sharpe']}")

    # Regime segmentation
    print("[8/9] Segmenting by regime...")
    regime_data = regime_segmentation(portfolio_df)
    for regime, stats in regime_data['regime'].items():
        print(f"  {regime}: {stats['trades']} trades, PnL=${stats['net_pnl']:,.2f}")

    # Charts
    print("[9/9] Generating visual outputs...")
    generate_charts(portfolio_equity, symbol_equity, corr_data,
                    contributions, stress_results, output_dir, strategy_id)

    # Generate Portfolio Trade-Level Artifact (Surgical Addition)
    print("  [ARTIFACT] Generating portfolio_tradelevel.csv...")
    try:
        transparency = generate_portfolio_tradelevel(portfolio_df, output_dir, TOTAL_PORTFOLIO_CAPITAL)
        port_metrics.update(transparency)
    except Exception as e:
        print(f"  [WARN] Failed to generate portfolio_tradelevel.csv: {e}")

    # Extract unique source run IDs (moved up for save_snapshot)
    unique_runs = sorted(list(set(portfolio_df['source_run_id'].astype(str).unique())))

    # ------------------------------------------------------------------
    # PHASE 15 PATCH: SNAPSHOT METRIC ENRICHMENT
    # ------------------------------------------------------------------
    # Exposure % (Formalized)
    exposure_pct = cap_util.get('pct_time_deployed', 0.0) * 100.0
    port_metrics['exposure_pct'] = exposure_pct

    # Equity Stability (Raw K-Ratio)
    port_metrics['equity_stability_k_ratio'] = port_metrics.get('k_ratio', 0.0)
    # ------------------------------------------------------------------

    # Save snapshot
    recommendation = save_snapshot(
        strategy_id, port_metrics, contributions, corr_data,
        dd_anatomy, stress_results, regime_data, cap_util, concurrency_data, 
        max_stress_corr, unique_runs, inert_warnings, output_dir
    )


    # 10) Master Ledger Update (SOP 8)
    # User Constraint: Only allow curated composite runs or multi-asset directives into the master sheet.
    # --force-ledger overrides this gate for single-symbol sweep tracking (explicit operator intent required).
    is_valid_for_master = (
        len(unique_runs) > 1 or
        len(symbol_trades) > 1 or
        str(strategy_id).startswith("PF_") or
        getattr(args, 'force_ledger', False)
    )
    
    if is_valid_for_master:
        print(f"[10/10] Updating Master Portfolio Ledger...")
        try:
            update_master_portfolio_ledger(strategy_id, port_metrics, corr_data, max_stress_corr, concurrency_data, unique_runs, n_assets=len(symbol_trades))
            print(f"  [LEDGER] Row appended to Master_Portfolio_Sheet.xlsx")
        except Exception as e:
            print(f"  [ERROR] Failed to update ledger: {e}")
            # SOP 8: Ledger failure is critical? 
            # "Portfolio evaluation is considered COMPLETE only if: Ledger append successful"
            # So we should probably re-raise or exit non-zero.
            raise
    else:
        print(f"[10/10] Skipping Master Ledger Update (Filtered: Single-Run / Single-Asset Strategy).")

    print(f"\n{'='*60}")
    print(f"PORTFOLIO EVALUATION COMPLETE - {strategy_id}")
    print(f"{'='*60}")
    print(f"\n  Net PnL:     ${port_metrics['net_pnl_usd']:,.2f}")
    print(f"  CAGR:         {port_metrics['cagr']:.2%}")
    print(f"  Sharpe:       {port_metrics['sharpe']}")
    print(f"  Sortino:      {port_metrics['sortino']}")
    print(f"  Max DD:       {port_metrics['max_dd_pct']:.2%} (${port_metrics['max_dd_usd']:,.2f})")
    print(f"  Return/DD:    {port_metrics['return_dd_ratio']}")
    print(f"  Peak Capital: ${port_metrics.get('peak_capital_deployed', 0):,.2f}")
    print(f"  Overextension: {port_metrics.get('capital_overextension_ratio', 0):.2f}")
    print(f"  K-Ratio:      {port_metrics['k_ratio']}")
    print(f"  Avg Corr:     {corr_data['avg_pairwise_corr']}")
    print(f"  Stress Corr:  {max_stress_corr:.3f}")
    print(f"\n  {recommendation}")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        _msg = str(_e)
        if "XLSX_LOCK_TIMEOUT" in _msg or _e.__class__.__name__ == "Timeout":
            print(f"[FATAL] XLSX_LOCK_TIMEOUT: {_msg}")
            sys.exit(3)
        raise

