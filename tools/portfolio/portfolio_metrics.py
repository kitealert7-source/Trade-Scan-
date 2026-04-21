"""All numeric computations for portfolio evaluation — pure helpers, no I/O.

Contents:
  build_portfolio_equity
  compute_portfolio_metrics (+ 4 sub-helpers)
  compute_concurrency_series  (delegates to tools.portfolio_core)
  capital_utilization
  concurrency_profile
  correlation_analysis
  compute_stress_correlation
  contribution_analysis
  drawdown_anatomy
  stress_test
  regime_segmentation
  _to_mt5_timeframe
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tools.portfolio.portfolio_config import TOTAL_PORTFOLIO_CAPITAL
from tools.portfolio_core import (
    compute_concurrency_series as core_compute_concurrency_series,
)


# ==================================================================
# 1) PORTFOLIO CONSTRUCTION
# ==================================================================
def build_portfolio_equity(portfolio_df, symbol_trades):
    """Build cumulative equity curves for portfolio and per-symbol."""
    symbol_equity = {}
    capital_per_symbol = TOTAL_PORTFOLIO_CAPITAL / len(symbol_trades)
    for sym, df in symbol_trades.items():
        daily_pnl = df.groupby(df['exit_timestamp'].dt.date)['pnl_usd'].sum()
        daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)
        equity = daily_pnl.cumsum() + capital_per_symbol
        symbol_equity[sym] = equity

    daily_pnl = portfolio_df.groupby(portfolio_df['exit_timestamp'].dt.date)['pnl_usd'].sum()
    daily_pnl.index = pd.DatetimeIndex(daily_pnl.index)

    portfolio_equity = daily_pnl.cumsum() + TOTAL_PORTFOLIO_CAPITAL

    return portfolio_equity, symbol_equity, daily_pnl


# ------------------------------------------------------------------
# compute_portfolio_metrics helpers (Phase A decomposition)
# ------------------------------------------------------------------

def _metrics_cagr_and_drawdown(portfolio_equity, total_capital):
    """Returns net_pnl, years, cagr, max_dd_usd, max_dd_pct, peak_dd_ratio, return_dd,
    plus the running_max series for downstream flat-period analysis."""
    net_pnl = portfolio_equity.iloc[-1] - total_capital

    start_date = portfolio_equity.index[0]
    end_date = portfolio_equity.index[-1]
    years = (end_date - start_date).days / 365.25
    if years > 0 and portfolio_equity.iloc[-1] > 0:
        cagr = (portfolio_equity.iloc[-1] / total_capital) ** (1 / years) - 1
    else:
        cagr = 0.0

    running_max = portfolio_equity.cummax()
    drawdown = portfolio_equity - running_max
    dd_pct = drawdown / running_max
    max_dd_usd = drawdown.min()
    max_dd_pct = dd_pct.min()
    peak_dd_ratio = (round(float(running_max.max()) / abs(float(max_dd_usd)), 4)
                     if max_dd_usd != 0 else 0.0)

    return_dd = abs(net_pnl / max_dd_usd) if max_dd_usd != 0 else 0.0

    return {
        "net_pnl": net_pnl,
        "start_date": start_date,
        "end_date": end_date,
        "years": years,
        "cagr": cagr,
        "max_dd_usd": max_dd_usd,
        "max_dd_pct": max_dd_pct,
        "peak_dd_ratio": peak_dd_ratio,
        "return_dd": return_dd,
        "running_max": running_max,
    }


def _metrics_risk_ratios(portfolio_equity, daily_pnl):
    """Sharpe (daily-return-based, annualized), Sortino, and K-Ratio (log equity)."""
    # NOTE: 'sharpe' here is DAILY RETURN BASED and ANNUALIZED (sqrt(252) scaling).
    # This is NOT comparable to trade-level Sharpe in Stage 2 (mean(trade_pnl)/stdev).
    equity_series = portfolio_equity.shift(1)
    equity_series.replace(0, np.nan, inplace=True)
    daily_returns = daily_pnl / equity_series
    daily_returns.dropna(inplace=True)

    returns = daily_returns

    if len(returns) > 1 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    downside = returns[returns < 0]
    if len(downside) > 1 and downside.std() > 0:
        sortino = (returns.mean() / downside.std()) * np.sqrt(252)
    else:
        sortino = 0.0

    # NOTE: 'equity_stability_k_ratio' is computed on LOG DAILY EQUITY.
    # Stage 2 K-Ratio is based on cumulative TRADE PnL (linear).
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

    return sharpe, sortino, k_ratio


def _metrics_flat_period(portfolio_equity, portfolio_df):
    """Longest flat period (calendar days below prior HWM) + trades during it."""
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

    flat_trades = 0
    if flat_periods and longest_flat_days > 0:
        lf_start, lf_end = longest_flat
        flat_trades = len(portfolio_df[
            (portfolio_df['exit_timestamp'] >= lf_start) &
            (portfolio_df['exit_timestamp'] <= lf_end)
        ])

    return longest_flat_days, flat_trades


def _metrics_trade_stats(portfolio_df):
    """Win rate, profit factor, expectancy, SQN, edge_quality + gross P/L."""
    total_trades = len(portfolio_df)
    win_rate = (portfolio_df['pnl_usd'] > 0).mean() * 100.0 if total_trades > 0 else 0.0

    gross_profit = portfolio_df[portfolio_df['pnl_usd'] > 0]['pnl_usd'].sum()
    gross_loss = abs(portfolio_df[portfolio_df['pnl_usd'] < 0]['pnl_usd'].sum())

    if gross_loss == 0:
        profit_factor = float('inf') if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    expectancy = portfolio_df['pnl_usd'].mean() if total_trades > 0 else 0.0

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

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "sqn": sqn,
        "edge_quality": edge_quality,
    }


def compute_portfolio_metrics(portfolio_equity, daily_pnl, portfolio_df, num_symbols):
    """Compute portfolio-level metrics (orchestrator)."""
    total_capital = TOTAL_PORTFOLIO_CAPITAL
    dd = _metrics_cagr_and_drawdown(portfolio_equity, total_capital)
    sharpe, sortino, k_ratio = _metrics_risk_ratios(portfolio_equity, daily_pnl)
    longest_flat_days, flat_trades = _metrics_flat_period(portfolio_equity, portfolio_df)
    trade_stats = _metrics_trade_stats(portfolio_df)

    mar = dd["cagr"] / abs(dd["max_dd_pct"]) if dd["max_dd_pct"] != 0 else 0.0

    return {
        'net_pnl_usd': dd["net_pnl"],
        'cagr': dd["cagr"],
        'max_dd_usd': dd["max_dd_usd"],
        'max_dd_pct': dd["max_dd_pct"],
        'return_dd_ratio': dd["return_dd"],
        'sharpe': sharpe,
        'sortino': sortino,
        'k_ratio': k_ratio,
        'mar': mar,
        'longest_flat_days': longest_flat_days,
        'longest_flat_trades': flat_trades,
        'total_trades': trade_stats["total_trades"],
        'years': dd["years"],
        'start_date': str(dd["start_date"].date()),
        'end_date': str(dd["end_date"].date()),
        'win_rate': trade_stats["win_rate"],
        'profit_factor': trade_stats["profit_factor"],
        'expectancy': trade_stats["expectancy"],
        'gross_profit': trade_stats["gross_profit"],
        'gross_loss': trade_stats["gross_loss"],
        'sqn': trade_stats["sqn"],
        'edge_quality': trade_stats["edge_quality"],
        'peak_dd_ratio': dd["peak_dd_ratio"],
    }


def compute_concurrency_series(portfolio_df):
    """Delegate deterministic concurrency math to shared portfolio_core."""
    return core_compute_concurrency_series(portfolio_df)


# ==================================================================
# 2) CAPITAL UTILIZATION
# ==================================================================
def capital_utilization(portfolio_df, symbol_trades, _precomputed_concurrency=None):
    """Analyze capital deployment over time."""
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
    """Analyze concurrency distribution and extreme loads."""
    if _precomputed_concurrency is not None:
        series, max_conc, avg_conc, pct_at_max, pct_deployed = _precomputed_concurrency
    else:
        series, max_conc, avg_conc, pct_at_max, pct_deployed = compute_concurrency_series(portfolio_df)

    concurrent_values = np.array(series)

    if len(concurrent_values) > 0:
        counts = pd.Series(concurrent_values).value_counts(normalize=True).sort_index()
        distribution = {int(k): v for k, v in counts.items()}
        p95_conc = np.percentile(concurrent_values, 95)
    else:
        distribution = {}
        p95_conc = 0

    full_load_cluster = (p95_conc >= max_conc - 1e-9)
    pct_days_at_max = pct_at_max

    running_max = portfolio_equity.cummax()
    dd = portfolio_equity - running_max

    trough_date = dd.idxmin()
    peak_data = portfolio_equity[:trough_date]
    peak_date = peak_data.idxmax() if not peak_data.empty else trough_date

    active_in_dd = portfolio_df[
        (portfolio_df['exit_timestamp'] >= peak_date) &
        (portfolio_df['entry_timestamp'] <= trough_date)
    ]

    if not active_in_dd.empty:
        dd_series, dd_max, dd_avg, _, _ = compute_concurrency_series(active_in_dd)
    else:
        dd_max = 0
        dd_avg = 0

    df_sorted = portfolio_df.sort_values('entry_timestamp').copy()

    if len(df_sorted) == len(series):
        df_sorted['concurrency'] = series
        regime_means = df_sorted.groupby('volatility_regime')['concurrency'].mean()
        regime_avg = {r: round(regime_means.get(r, 0), 2) for r in ['low', 'normal', 'high']}
    else:
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
    all_dates = set()
    for eq in symbol_equity.values():
        all_dates.update(eq.index)
    all_dates = sorted(all_dates)
    date_range = pd.DatetimeIndex(all_dates)

    returns_df = pd.DataFrame(index=date_range)
    for sym, eq in symbol_equity.items():
        returns_df[sym] = eq.reindex(date_range).ffill().pct_change()

    returns_df = returns_df.dropna(how='all')

    corr_matrix = returns_df.corr()

    n = len(corr_matrix)
    if n > 1:
        upper_tri = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
        avg_corr = upper_tri.stack().mean()
    else:
        avg_corr = 0.0

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
    """Compute max pairwise correlation during stress window (SOP 6.3)."""
    start_dt = pd.to_datetime(peak_date)
    end_dt = pd.to_datetime(trough_date)

    mask = (returns_df.index >= start_dt) & (returns_df.index <= end_dt)
    stress_returns = returns_df.loc[mask]

    if len(stress_returns) < 3 or len(stress_returns.columns) < 2:
        return 0.0

    corr_matrix = stress_returns.corr()

    vals = corr_matrix.values
    np.fill_diagonal(vals, -2.0)

    max_stress_corr = float(vals.max())

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

        sym_vol = df['pnl_usd'].std()

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

    trough_idx = drawdown.idxmin()
    trough_val = drawdown.min()
    trough_pct = dd_pct.min()

    peak_idx = portfolio_equity[:trough_idx].idxmax()
    peak_val = portfolio_equity[peak_idx]

    post_trough = portfolio_equity[trough_idx:]
    recovered = post_trough[post_trough >= peak_val]
    if len(recovered) > 0:
        recovery_idx = recovered.index[0]
        recovery_days = (recovery_idx - trough_idx).days
    else:
        recovery_idx = None
        recovery_days = None

    dd_duration = (trough_idx - peak_idx).days

    dd_trades = portfolio_df[
        (portfolio_df['exit_timestamp'] >= peak_idx) &
        (portfolio_df['exit_timestamp'] <= trough_idx)
    ]

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

        rm = equity.cummax()
        dd = (equity - rm).min()

        equity_series = equity.shift(1)
        rets = daily_pnl / equity_series
        rets = rets.dropna()

        sh = (rets.mean() / rets.std()) * np.sqrt(252) if len(rets) > 1 and rets.std() > 0 else 0

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
# MT5 TIMEFRAME NOTATION
# ==================================================================
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
        if mt5 not in _MAP.values() and p_lower in _MAP:
            mt5 = _MAP[p_lower]
        mt5_parts.append(mt5)
    return "|".join(sorted(set(mt5_parts)))
