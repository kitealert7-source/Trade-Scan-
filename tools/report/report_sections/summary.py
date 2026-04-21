"""Summary-family section builders: header, key metrics, direction split,
symbol summary, yearwise, volatility edge, trend edge."""

from __future__ import annotations

import pandas as pd


def _build_header_section(directive_name, engine_ver, timeframe, start_date, end_date,
                          total_symbols, n_symbol_dirs, now_utc, stage3_counts,
                          port_pf_value):
    """Header block + stage-mode banner. Returns (md_lines, port_pf_str)."""
    md = [
        f"# Report Summary — {directive_name}\n",
        f"Engine Version: {engine_ver}",
        f"Timeframe: {timeframe}",
        f"Date Range: {start_date} → {end_date}",
        f"Symbols Evaluated: {total_symbols} / {n_symbol_dirs}",
        f"Generated: {now_utc}\n",
        "---\n",
    ]

    if stage3_counts == 0:
        md.insert(0, "## ⚠️ Stage-1 Only Report\n")
        md.insert(1, "Metrics limited to trade-level data. No risk metrics computed.\n\n")
        port_pf_str = "N/A"
    elif stage3_counts < total_symbols:
        md.insert(0, "## ⚠️ Partial Report (Mixed Stage-1 / Stage-3)\n")
        md.insert(1, "Some symbols lack full risk metrics. Portfolio metrics limited.\n\n")
        port_pf_str = "N/A"
    else:
        port_pf_str = f"{port_pf_value:.2f}"
    return md, port_pf_str


def _build_key_metrics_section(portfolio_pnl, portfolio_trades, port_pf_str,
                               totals, risk_data_list):
    """Portfolio Key Metrics section (first after header)."""
    md = ["## Portfolio Key Metrics (All Symbols Combined)\n"]
    expectancy = (portfolio_pnl / portfolio_trades) if portfolio_trades > 0 else 0.0
    if risk_data_list:
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Trades | {portfolio_trades} |")
        md.append(f"| Net PnL | ${portfolio_pnl:.2f} |")
        md.append(f"| Expectancy | ${expectancy:.2f} |")
        md.append(f"| Profit Factor | {port_pf_str} |")
        md.append(f"| Sharpe | {totals['sharpe']:.2f} |")
        md.append(f"| Sortino | {totals['sortino']:.2f} |")
        md.append(f"| K-Ratio | {totals['k_ratio']:.2f} |")
        md.append(f"| Max DD | ${totals['max_dd_usd']:.2f} ({totals['max_dd_pct']:.2f}%) |")
        md.append(f"| Return/DD | {totals['ret_dd']:.2f} |")
        md.append(f"| Win Rate | {totals['win_rate'] * 100:.1f}% |")
        md.append(f"| Avg R | {totals['avg_r']:+.3f} |")
        md.append(f"| SQN | {totals['sqn']:.2f} |")
    else:
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Trades | {portfolio_trades} |")
        md.append(f"| Net PnL | ${portfolio_pnl:.2f} |")
        md.append(f"| Expectancy | ${expectancy:.2f} |")
        md.append(f"| Profit Factor | {port_pf_str} |")
        md.append(f"| Avg R | {totals['avg_r']:+.3f} |")
        md.append(f"| Sharpe | N/A (S1) |")
        md.append(f"| Max DD | N/A (S1) |")
    md.append("\n---\n")
    return md


def _build_direction_split_section(all_trades_dfs):
    md = ["## Direction Split\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Direction Split.\n")
        md.append("\n---\n")
        return md
    _dir_df = pd.concat(all_trades_dfs, ignore_index=True)
    if 'direction' in _dir_df.columns and 'pnl_usd' in _dir_df.columns:
        md.append("| Direction | Trades | Net PnL | PF | Win % | Avg Bars |")
        md.append("|-----------|--------|---------|-----|-------|----------|")
        for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
            _ds = _dir_df[_dir_df['direction'] == _dv]
            if len(_ds) == 0:
                continue
            _d_trades = len(_ds)
            _d_pnl = _ds['pnl_usd'].sum()
            _d_gp = float(_ds[_ds['pnl_usd'] > 0]['pnl_usd'].sum())
            _d_gl = abs(float(_ds[_ds['pnl_usd'] < 0]['pnl_usd'].sum()))
            _d_pf = (_d_gp / _d_gl) if _d_gl > 0 else (_d_gp if _d_gp > 0 else 0.0)
            _d_pf_str = f"{_d_pf:.2f}" if _d_pf != float('inf') else "∞"
            _d_wr = (_ds['pnl_usd'] > 0).mean() * 100
            _d_bars = f"{_ds['bars_held'].mean():.1f}" if 'bars_held' in _ds.columns else "N/A"
            md.append(f"| {_dl} | {_d_trades} | ${_d_pnl:.2f} | {_d_pf_str} | {_d_wr:.1f}% | {_d_bars} |")
    md.append("\n---\n")
    return md


def _build_symbol_summary_section(symbols_data):
    md = ["## Symbol Summary\n",
          "| Symbol | Trades | Net PnL | PF | Max DD | Return/DD | Win % | Avg R |",
          "|--------|--------|---------|----|--------|-----------|-------|-------|"]
    for row in symbols_data:
        if row['PF'] is not None:
            pf_str = f"{row['PF']:.2f} ✔ (S3)"
            max_dd_str = f"{row['Max DD']:.2f}%"
            ret_dd_str = f"{row['Return/DD']:.2f}"
            win_str = f"{row['Win %']:.1f}%"
        else:
            pf_str = "N/A (S1)"
            max_dd_str = "N/A (S1)"
            ret_dd_str = "N/A (S1)"
            win_str = "N/A (S1)"
        md.append(f"| {row['Symbol']} | {row['Trades']} | ${row['Net PnL']:.2f} | {pf_str} | {max_dd_str} | {ret_dd_str} | {win_str} | {row['Avg R']:.2f} |")
    md.append("\n---\n")
    return md


def _build_yearwise_section(all_trades_dfs):
    md = ["## Yearwise Performance\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Yearwise Performance.\n")
        md.append("\n---\n")
        return md
    _yr_df = pd.concat(all_trades_dfs, ignore_index=True)
    if 'entry_timestamp' in _yr_df.columns and 'pnl_usd' in _yr_df.columns:
        _yr_df['_year'] = pd.to_datetime(_yr_df['entry_timestamp'], errors='coerce').dt.year
        _yr_df = _yr_df[_yr_df['_year'].notna()]
        _yr_df['_year'] = _yr_df['_year'].astype(int)
        _years = sorted(_yr_df['_year'].unique())
        md.append("| Year | Trades | Net PnL | PF | Win % | Max DD |")
        md.append("|------|--------|---------|-----|-------|--------|")
        for _y in _years:
            _ys = _yr_df[_yr_df['_year'] == _y]
            _yt = len(_ys)
            _ypnl = _ys['pnl_usd'].sum()
            _ygp = float(_ys[_ys['pnl_usd'] > 0]['pnl_usd'].sum())
            _ygl = abs(float(_ys[_ys['pnl_usd'] < 0]['pnl_usd'].sum()))
            _ypf = (_ygp / _ygl) if _ygl > 0 else (_ygp if _ygp > 0 else 0.0)
            _ypf_s = f"{_ypf:.2f}" if _ypf != float('inf') else "inf"
            _ywr = (_ys['pnl_usd'] > 0).mean() * 100
            _cum = _ys['pnl_usd'].cumsum()
            _peak = _cum.cummax()
            _dd = _cum - _peak
            _max_dd = abs(float(_dd.min())) if len(_dd) > 0 else 0.0
            md.append(f"| {_y} | {_yt} | ${_ypnl:.2f} | {_ypf_s} | {_ywr:.1f}% | ${_max_dd:.2f} |")
        md.append("")
    else:
        md.append("> No timestamp data available for Yearwise Performance.\n")
    md.append("\n---\n")
    return md


def _build_volatility_edge_section(vol_data):
    md = ["## Volatility Edge\n",
          "| Symbol | High | Normal | Low |",
          "|--------|------|--------|-----|"]
    for row in vol_data:
        md.append(f"| {row['Symbol']} | T:{row['High_T']} ${row['High']:.2f} | T:{row['Normal_T']} ${row['Normal']:.2f} | T:{row['Low_T']} ${row['Low']:.2f} |")
    md.append("\n---\n")
    return md


def _build_trend_edge_section(trend_data):
    md = ["## Trend Edge\n",
          "| Symbol | StrongUp | WeakUp | Neutral | WeakDn | StrongDn |",
          "|--------|----------|--------|---------|--------|----------|"]
    for row in trend_data:
        md.append(f"| {row['Symbol']} | T:{row['StrongUp_T']} ${row['StrongUp']:.2f} | T:{row['WeakUp_T']} ${row['WeakUp']:.2f} | T:{row['Neutral_T']} ${row['Neutral']:.2f} | T:{row['WeakDn_T']} ${row['WeakDn']:.2f} | T:{row['StrongDn_T']} ${row['StrongDn']:.2f} |")
    md.append("\n---\n")
    return md
