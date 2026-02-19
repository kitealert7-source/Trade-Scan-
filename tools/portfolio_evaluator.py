"""
Portfolio Evaluator — Multi-Instrument Portfolio Analysis + Snapshot Archival
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
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')


# ------------------------------------------------------------------
# IMPORTS (numpy/pandas/matplotlib)
# ------------------------------------------------------------------
import subprocess

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
CAPITAL_PER_SYMBOL = 5000.0
RISK_FREE_RATE = 0.0  # For Sharpe/Sortino

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
def load_all_trades(strategy_id):
    """
    Load trade-level results for all symbols (Governance-Driven).
    Replaces auto-discovery with strict Stage-3 Master Filter selection.
    Uses Run-ID based folder resolution (no folder filtering).
    """
    all_trades = []
    symbol_trades = {}

    # 1. Read Master Sheet
    master_path = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
    if not master_path.exists():
        raise FileNotFoundError(f"Strategy Master Filter not found at {master_path}")
    
    try:
        # Read using default engine
        df_master = pd.read_excel(master_path)
    except Exception as e:
        raise ValueError(f"Failed to read Strategy Master Filter: {e}")

    # 2. Filter Rows (strategy starts with strategy_id AND IN_PORTFOLIO == True)
    if 'strategy' not in df_master.columns or 'IN_PORTFOLIO' not in df_master.columns or 'run_id' not in df_master.columns or 'symbol' not in df_master.columns:
         raise ValueError("Master Sheet missing required columns: 'strategy', 'IN_PORTFOLIO', 'run_id', or 'symbol'")

    # Using startswith because Master Sheet strategy column often contains {STRATEGY_ID}_{SYMBOL}
    # Governed by SOP: Strict prefix matching to avoid collisions (e.g. IDX2 vs IDX27)
    selected_rows = df_master[
        (df_master['strategy'].astype(str).str.startswith(strategy_id + "_"))
    ]

    if selected_rows.empty:
        # Fallback: Try Exact Match
        selected_rows = df_master[df_master['strategy'] == strategy_id]
        
    if selected_rows.empty:
        raise ValueError(f"No strategies found in Master Filter matching {strategy_id}")
    
    # 3. Extract and Load
    loaded_symbols = []
    
    # Pre-scan backtests root to map run_id -> folder (Optimization)
    # Mapping: run_id -> folder_path
    run_id_map = {}
    print("  Indexing backtest folders...")
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
                
                # Governance: Detect duplicate run_ids (prevent silent corruption)
                if rid in run_id_map:
                    raise ValueError(f"Duplicate run_id detected in backtests: {rid}")
                    
                run_id_map[rid] = folder
    
    for idx, row in selected_rows.iterrows():
        run_id = str(row['run_id'])
        symbol = row['symbol']
        
        # Locate folder by run_id
        run_folder = run_id_map.get(run_id)
        
        if run_folder is None:
            raise ValueError(
                f"Governance violation: run_id {run_id} selected in Master Sheet "
                f"but no corresponding backtest folder found."
            )
             
        csv_path = run_folder / "raw" / "results_tradelevel.csv"
        # Validate CSV existence
        if not csv_path.exists():
             raise ValueError(
                f"Governance violation: results_tradelevel.csv missing for run_id {run_id}."
            )
             
        # Load Metadata (Preserved Logic)
        strat_name = strategy_id
        meta_path = run_folder / "metadata" / "run_metadata.json"
        try:
            if meta_path.exists():
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    strat_name = meta.get('strategy_name', strategy_id)
        except Exception:
            pass

        # Load Trade Data
        try:
            df = pd.read_csv(csv_path)
            df['source_run_id'] = run_id
            df['strategy_name'] = strat_name
            df['exit_timestamp'] = pd.to_datetime(df['exit_timestamp'])
            df['entry_timestamp'] = pd.to_datetime(df['entry_timestamp'])
            df['symbol'] = symbol
            
            symbol_trades[symbol] = df
            all_trades.append(df)
            loaded_symbols.append(symbol)
        except Exception as e:
            raise ValueError(
                f"Governance violation: failed to load trade data for run_id {run_id}: {e}"
            )

    if not all_trades:
        raise ValueError(f"No valid trade data loaded for {strategy_id} (Governance selected {len(selected_rows)} candidates)")

    print(f"  Loaded symbols (Governance): {loaded_symbols}")

    # 4. Combine and Sort (Preserved Logic)
    portfolio_df = pd.concat(all_trades, ignore_index=True)
    portfolio_df.sort_values('exit_timestamp', inplace=True)
    portfolio_df.reset_index(drop=True, inplace=True)
    
    return portfolio_df, symbol_trades


def load_symbol_metrics(strategy_id):
    """
    Load per-symbol standard and risk metrics (Governance-Driven).
    Replaces auto-discovery with strict Stage-3 Master Filter selection.
    Uses Run-ID based folder resolution (no folder filtering).
    """
    metrics = {}

    # 1. Read Master Sheet
    master_path = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
    if not master_path.exists():
        raise FileNotFoundError(f"Strategy Master Filter not found at {master_path}")
    
    try:
        df_master = pd.read_excel(master_path)
    except Exception as e:
        raise ValueError(f"Failed to read Strategy Master Filter: {e}")

    # 2. Filter Rows
    if 'strategy' not in df_master.columns or 'IN_PORTFOLIO' not in df_master.columns or 'run_id' not in df_master.columns or 'symbol' not in df_master.columns:
         raise ValueError("Master Sheet missing required columns: 'strategy', 'IN_PORTFOLIO', 'run_id', or 'symbol'")

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
    for sym, df in symbol_trades.items():
        daily_pnl = df.groupby(df['exit_timestamp'].dt.date)['pnl_usd'].sum()
        daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)
        equity = daily_pnl.cumsum() + CAPITAL_PER_SYMBOL
        symbol_equity[sym] = equity

    # Portfolio equity: merge all trades chronologically
    daily_pnl = portfolio_df.groupby(portfolio_df['exit_timestamp'].dt.date)['pnl_usd'].sum()
    daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)

    total_capital = CAPITAL_PER_SYMBOL * len(symbol_trades)
    portfolio_equity = daily_pnl.cumsum() + total_capital

    return portfolio_equity, symbol_equity, daily_pnl


def compute_portfolio_metrics(portfolio_equity, daily_pnl, portfolio_df, num_symbols):
    """Compute portfolio-level metrics."""
    total_capital = CAPITAL_PER_SYMBOL * num_symbols
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

    # Return/DD
    return_dd = abs(net_pnl / max_dd_usd) if max_dd_usd != 0 else 0.0

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
        'gross_loss': gross_loss
    }



def compute_concurrency_series(portfolio_df):
    """
    Compute concurrency metrics using exact timestamp overlap.
    Returns:
        - concurrency_series: list of concurrency counts at each trade entry
        - max_concurrent: global maximum peak
        - avg_concurrent: time-weighted average
        - pct_time_at_max: percentage of time at global max
        - pct_time_deployed: percentage of time with count > 0
    """
    if portfolio_df.empty:
        return [], 0, 0.0, 0.0, 0.0

    # Ensure chronological order by entry time
    df_sorted = portfolio_df.sort_values('entry_timestamp').copy()
    
    events = []
    for idx, row in df_sorted.iterrows():
        events.append((row['entry_timestamp'], 1))
        events.append((row['exit_timestamp'], -1))
        
    # Sort events: time asc, then exit(-1) before entry(1)
    events.sort(key=lambda x: (x[0], x[1]))
    
    current_concurrent = 0
    max_concurrent = 0
    weighted_sum = 0.0
    time_deployed = 0.0
    duration_by_count = defaultdict(float)
    
    last_time = events[0][0]
    total_duration = (events[-1][0] - events[0][0]).total_seconds()
    
    series = []
    
    for t, type_ in events:
        delta = (t - last_time).total_seconds()
        if delta > 0:
            weighted_sum += current_concurrent * delta
            duration_by_count[current_concurrent] += delta
            if current_concurrent > 0:
                time_deployed += delta
        
        if type_ == 1:
            current_concurrent += 1
            series.append(current_concurrent)
        else:
            current_concurrent -= 1
            
        if current_concurrent > max_concurrent:
            max_concurrent = current_concurrent
            
        last_time = t
        
    avg_concurrent = weighted_sum / total_duration if total_duration > 0 else 0.0
    pct_deployed = (time_deployed / total_duration) if total_duration > 0 else 0.0
    
    time_at_max = duration_by_count[max_concurrent]
    pct_at_max = (time_at_max / total_duration) if total_duration > 0 else 0.0
    
    return series, max_concurrent, avg_concurrent, pct_at_max, pct_deployed


# ==================================================================
# 2) CAPITAL UTILIZATION
# ==================================================================
def capital_utilization(portfolio_df, symbol_trades):
    """Analyze capital deployment over time."""
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
def concurrency_profile(portfolio_df, portfolio_equity):
    """Analyze concurrency distribution and extreme loads."""
    
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
        capital = CAPITAL_PER_SYMBOL * len(syms)
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
    ax.set_title(f'{strategy_id} — Portfolio Equity Curve', fontweight='bold')
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
    ax.set_title(f'{strategy_id} — Portfolio Drawdown', fontweight='bold')
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
    ax.set_title(f'{strategy_id} — Correlation Matrix', fontweight='bold')
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
    ax.set_title(f'{strategy_id} — PnL Contribution by Symbol', fontweight='bold')
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
    fig.suptitle(f'{strategy_id} — Stress Test Results', fontweight='bold', fontsize=14)
    fig.tight_layout()
    fig.savefig(output_dir / 'stress_test_chart.png', dpi=150, bbox_inches='tight')
    plt.close(fig)

    print(f"  [CHARTS] 5 charts saved to {output_dir}")


def generate_portfolio_tradelevel(portfolio_df, output_dir, total_capital):
    """
    Generate and save portfolio_tradelevel.csv with enriched metrics.
    Satisfies SOP_PORTFOLIO_ANALYSIS §5.
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
                  max_stress_corr, constituent_run_ids, output_dir):
    """Save frozen evaluation snapshot."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- portfolio_summary.json ---
    summary = {
        'strategy_id': strategy_id,
        'evaluation_date': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'portfolio_engine_version': '1.2.1',
        'data_range': f"{port_metrics['start_date']} to {port_metrics['end_date']}",
        'capital_per_symbol': CAPITAL_PER_SYMBOL,
        'total_capital': CAPITAL_PER_SYMBOL * len(contributions),
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
        'evaluation_timeframe': port_metrics.get('evaluation_timeframe', "1D"),
        # Phase 15 Metrics
        'win_rate': port_metrics.get('win_rate', 0.0),
        'profit_factor': port_metrics.get('profit_factor', 0.0),
        'expectancy': port_metrics.get('expectancy', 0.0),
        'exposure_pct': port_metrics.get('exposure_pct', 0.0),
        'equity_stability_k_ratio': port_metrics.get('equity_stability_k_ratio', 0.0)
    }
    with open(output_dir / 'portfolio_summary.json', 'w') as f:
        json.dump(summary, f, indent=4)



    # --- portfolio_metadata.json (SOP Requirement) ---
    metadata = {
      "portfolio_id": strategy_id,
      "creation_timestamp_utc": datetime.utcnow().isoformat(),
      "constituent_run_ids": constituent_run_ids,
      "reference_capital_usd": summary['total_capital'],
      "capital_model_version": "v1.0_trade_close_compounding",
      "portfolio_engine_version": "1.2.1",
      "schema_version": "1.0",
      "signal_timeframes": port_metrics.get('signal_timeframes', "UNKNOWN"),
      "evaluation_timeframe": port_metrics.get('evaluation_timeframe', "1D")
    }
    with open(output_dir / 'portfolio_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=4)

    # --- portfolio_metrics.csv ---
    with open(output_dir / 'portfolio_metrics.csv', 'w', newline='') as f:
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

    overview = f"""# {strategy_id} — Portfolio Evaluation Summary

## Key Metrics

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
⚠ **Full-load clustering detected**: 95th percentile concurrency equals maximum concurrency. Monitor regime transition risk.
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
*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Engine: Universal_Research_Engine v1.2.1*
"""

    with open(output_dir / 'portfolio_overview.md', 'w', encoding='utf-8') as f:
        f.write(overview)

    # --- stress_test_report.md ---
    stress_md = f"# {strategy_id} — Stress Test Report\n\n"
    stress_md += "| Scenario | Symbols | Net PnL | Sharpe | Max DD | Return/DD |\n"
    stress_md += "|----------|---------|---------|--------|--------|-----------|\n"
    for name, data in stress_results.items():
        stress_md += f"| {name} | {data.get('symbols','?')} | ${data['net_pnl']:,.2f} | {data['sharpe']:.2f} | ${data['max_dd_usd']:,.2f} | {data['return_dd']:.2f} |\n"

    with open(output_dir / 'stress_test_report.md', 'w') as f:
        f.write(stress_md)

    print(f"  [SNAPSHOT] Saved to {output_dir}")
    return recommendation


def update_master_portfolio_ledger(strategy_id, metrics, corr_data, max_stress_corr, concurrency_data, constituent_run_ids):
    """
    Append portfolio result to Master_Portfolio_Sheet.xlsx (SOP 8).
    Enforces append-only logic and schema validation.
    """
    ledger_path = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"
    
    # Schema Definition (Col Order matters)
    columns = [
        "portfolio_id",
        "creation_timestamp",
        "constituent_run_ids", # Required Governance Field (SOP 8)
        "source_strategy",
        "reference_capital_usd",
        "net_pnl_usd", # Renamed from net_pnl
        "sharpe",
        "max_dd_pct",
        "return_dd_ratio",
        "peak_capital_deployed",
        "capital_overextension_ratio",
        "avg_concurrent",
        "max_concurrent",
        "p95_concurrent",
        "dd_max_concurrent",
        "full_load_cluster",
        "avg_pairwise_corr",
        "max_pairwise_corr_stress",
        "total_trades",
        "portfolio_engine_version",
        "portfolio_net_profit_low_vol",
        "portfolio_net_profit_normal_vol",
        "portfolio_net_profit_high_vol",
        "signal_timeframes",
        "evaluation_timeframe",
        # Phase 15 Metrics
        "win_rate",
        "profit_factor",
        "expectancy",
        "exposure_pct",
        "equity_stability_k_ratio"
    ]
    
    
    # Process constituent_run_ids (list -> string)
    if isinstance(constituent_run_ids, list):
        run_ids_str = ",".join(str(x) for x in constituent_run_ids)
    else:
        run_ids_str = str(constituent_run_ids)

    # Construct Row Data
    row_data = {
        "portfolio_id": strategy_id,
        "creation_timestamp": datetime.utcnow().isoformat(),
        "constituent_run_ids": run_ids_str,
        "source_strategy": strategy_id, 
        "reference_capital_usd": metrics['total_capital'], 
        "net_pnl_usd": metrics['net_pnl_usd'],
        "sharpe": metrics['sharpe'],
        "max_dd_pct": metrics['max_dd_pct'],
        "return_dd_ratio": metrics['return_dd_ratio'],
        "peak_capital_deployed": metrics.get('peak_capital_deployed', 0.0),
        "capital_overextension_ratio": metrics.get('capital_overextension_ratio', 0.0),
        "avg_concurrent": concurrency_data['avg_concurrent'],
        "max_concurrent": concurrency_data['max_concurrent'],
        "p95_concurrent": concurrency_data['p95_concurrent'],
        "dd_max_concurrent": concurrency_data['dd_max_concurrent'],
        "full_load_cluster": concurrency_data['full_load_cluster'],
        "avg_pairwise_corr": corr_data['avg_pairwise_corr'],
        "max_pairwise_corr_stress": max_stress_corr,
        "total_trades": metrics['total_trades'],
        "portfolio_engine_version": "1.2.1",
        "portfolio_net_profit_low_vol": metrics.get('portfolio_net_profit_low_vol', 0.0),
        "portfolio_net_profit_normal_vol": metrics.get('portfolio_net_profit_normal_vol', 0.0),
        "portfolio_net_profit_high_vol": metrics.get('portfolio_net_profit_high_vol', 0.0),
        "signal_timeframes": metrics.get('signal_timeframes', "UNKNOWN"),
        "evaluation_timeframe": metrics.get('evaluation_timeframe', "1D"),
        # Phase 15 Metrics
        "win_rate": metrics.get('win_rate', 0.0),
        "profit_factor": metrics.get('profit_factor', 0.0),
        "expectancy": metrics.get('expectancy', 0.0),
        "exposure_pct": metrics.get('exposure_pct', 0.0),
        "equity_stability_k_ratio": metrics.get('equity_stability_k_ratio', 0.0)
    }
    
    # Load or Create
    if ledger_path.exists():
        try:
            df_ledger = pd.read_excel(ledger_path)
        except Exception:
            # Corrupt file? Backup and recreate?
            # For now, duplicate safe logic
            df_ledger = pd.DataFrame(columns=columns)
    else:
        df_ledger = pd.DataFrame(columns=columns)
        
    # Check Duplicate
    if strategy_id in df_ledger['portfolio_id'].astype(str).values:
        raise ValueError(f"Portfolio ID '{strategy_id}' already exists in ledger. Update rejected (Append-Only).")
        
    # Append
    new_row = pd.DataFrame([row_data])
    # Align columns
    for c in columns:
        if c not in new_row.columns:
            new_row[c] = None
            
    df_final = pd.concat([df_ledger, new_row[columns]], ignore_index=True)
    
    # Save
    # Use pandas default writer (openpyxl engine implied by xlsx extension, but we don't import it directly)
    # Actually, pandas might need 'openpyxl' installed, which is fine. We just don't use it for styling here.
    df_final.to_excel(ledger_path, index=False)

    # Call Unified Formatter
    try:
        cmd = [
            sys.executable, 
            str(PROJECT_ROOT / "tools" / "format_excel_artifact.py"),
            "--file", str(ledger_path),
            "--profile", "portfolio"
        ]
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Formatting failed: {e}")


# ==================================================================
# MAIN
# ==================================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/portfolio_evaluator.py <STRATEGY_ID>")
        sys.exit(1)

    strategy_id = sys.argv[1]
    print(f"\n{'='*60}")
    print(f"PORTFOLIO EVALUATION — {strategy_id}")
    print(f"{'='*60}")

    output_dir = STRATEGIES_ROOT / strategy_id / "portfolio_evaluation"

    # Load data
    print("\n[1/9] Loading trade data...")
    portfolio_df, symbol_trades = load_all_trades(strategy_id)
    print(f"  Loaded {len(portfolio_df)} trades across {len(symbol_trades)} symbols")

    # Portfolio construction
    print("[2/9] Building portfolio equity curve...")
    
    if not symbol_trades:
        raise ValueError("Cannot compute reference capital: no symbols detected")

    portfolio_equity, symbol_equity, daily_pnl = build_portfolio_equity(portfolio_df, symbol_trades)
    port_metrics = compute_portfolio_metrics(portfolio_equity, daily_pnl, portfolio_df, len(symbol_trades))
    
    # Deterministic capital calculation (SOP Issue #2)
    port_metrics['total_capital'] = CAPITAL_PER_SYMBOL * len(symbol_trades)

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
    # Read Master Sheet locally to avoid refactoring load_all_trades
    try:
        master_path_local = BACKTESTS_ROOT / "Strategy_Master_Filter.xlsx"
        df_master_local = pd.read_excel(master_path_local)
        
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

    port_metrics['signal_timeframes'] = signal_timeframes_str
    port_metrics['evaluation_timeframe'] = "1D"
    
    print(f"  Net PnL: ${port_metrics['net_pnl_usd']:,.2f} | Sharpe: {port_metrics['sharpe']}")

    # Capital utilization
    print("[3/9] Analyzing capital utilization...")
    cap_util = capital_utilization(portfolio_df, symbol_trades)
    print(f"  Deployed: {cap_util['pct_time_deployed']}% | Max concurrent: {cap_util['max_concurrent']}")

    # Concurrency
    print("[X/9] Computing concurrency profile...")
    concurrency_data = concurrency_profile(portfolio_df, portfolio_equity)
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
        transparency = generate_portfolio_tradelevel(portfolio_df, output_dir, CAPITAL_PER_SYMBOL * len(symbol_trades))
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
        max_stress_corr, unique_runs, output_dir
    )


    # 10) Master Ledger Update (SOP 8)
    print(f"[10/10] Updating Master Portfolio Ledger...")
    try:
        # Pass list directly (ledger function handles join)
        
        update_master_portfolio_ledger(strategy_id, port_metrics, corr_data, max_stress_corr, concurrency_data, unique_runs)
        print(f"  [LEDGER] Row appended to Master_Portfolio_Sheet.xlsx")
    except Exception as e:
        print(f"  [ERROR] Failed to update ledger: {e}")
        # SOP 8: Ledger failure is critical? 
        # "Portfolio evaluation is considered COMPLETE only if: Ledger append successful"
        # So we should probably re-raise or exit non-zero.
        raise

    print(f"\n{'='*60}")
    print(f"PORTFOLIO EVALUATION COMPLETE — {strategy_id}")
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
    main()
