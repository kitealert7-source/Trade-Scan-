"""Risk-family section builders: exit analysis, edge decomposition, risk characteristics."""

from __future__ import annotations

import pandas as pd

from tools.report.report_sessions import _classify_session, _build_cross_tab


def _build_exit_analysis_section(all_trades_dfs):
    md = ["\n---\n", "## Exit Analysis\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Exit Analysis.\n")
        return md
    _exit_df = pd.concat(all_trades_dfs, ignore_index=True).copy()
    _has_r    = 'r_multiple'  in _exit_df.columns
    _has_bars = 'bars_held'   in _exit_df.columns
    _has_mfe  = 'mfe_r'       in _exit_df.columns
    _has_src  = 'exit_source' in _exit_df.columns

    if _has_src:
        # ── Primary path: engine-attributed exit_source ──────────────────────
        # exit_source values emitted by Stage-1: ENGINE_STOP, ENGINE_TP,
        # ENGINE_TRAIL, STRATEGY_DAY_CLOSE, ENGINE_SESSION_RESET,
        # ENGINE_DATA_END, STRATEGY_<LABEL>.
        _src_counts = _exit_df['exit_source'].value_counts()

        md.append("### Exit Type Summary\n")
        md.append("| Exit Source | Trades | % | PnL | Avg R |")
        md.append("|-------------|--------|---|-----|-------|")
        for _src in _src_counts.index:
            _s   = _exit_df[_exit_df['exit_source'] == _src]
            _pct = len(_s) / len(_exit_df) * 100
            _pnl = _s['pnl_usd'].sum() if 'pnl_usd' in _s else 0.0
            _r   = f"{_s['r_multiple'].mean():+.2f}R" if _has_r else "n/a"
            md.append(f"| {_src} | {len(_s)} | {_pct:.1f}% | ${_pnl:.2f} | {_r} |")
        md.append("")

        md.append("### Exit Type by Direction\n")
        md.append("| Direction | Exit Source | Trades | % of Dir | PnL | Avg R |")
        md.append("|-----------|-------------|--------|----------|-----|-------|")
        for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
            _ds = _exit_df[_exit_df['direction'] == _dv]
            if len(_ds) == 0:
                continue
            for _src in _src_counts.index:
                _s   = _ds[_ds['exit_source'] == _src]
                if len(_s) == 0:
                    continue
                _pct = len(_s) / len(_ds) * 100
                _pnl = _s['pnl_usd'].sum() if 'pnl_usd' in _s else 0.0
                _r   = f"{_s['r_multiple'].mean():+.2f}R" if _has_r else "n/a"
                md.append(f"| {_dl} | {_src} | {len(_s)} | {_pct:.1f}% | ${_pnl:.2f} | {_r} |")
        md.append("")

        # Masks for downstream MFE analytics — map exit_source to role.
        _stop_mask = _exit_df['exit_source'] == 'ENGINE_STOP'
        _time_mask = _exit_df['exit_source'].isin(
            ['STRATEGY_DAY_CLOSE', 'ENGINE_SESSION_RESET', 'ENGINE_DATA_END'])

        if _has_r:
            _rmean, _rmedian = _exit_df['r_multiple'].mean(), _exit_df['r_multiple'].median()
            md.append(f"**R-Multiple:** Mean {_rmean:+.3f} | Median {_rmedian:+.3f}\n")

        if _has_mfe:
            _time_exits = _exit_df[_time_mask]
            if len(_time_exits) > 0:
                _gave_back = _time_exits[_time_exits['mfe_r'] >= 0.5]
                _gb_pct = len(_gave_back) / len(_time_exits) * 100
                if len(_gave_back) > 0:
                    _avg_left = (_gave_back['mfe_r'] - _gave_back['r_multiple']).mean()
                    md.append(f"**MFE Giveback:** {_gb_pct:.0f}% of day-close exits had MFE >= 0.5R,"
                              f" gave back {_avg_left:+.2f}R avg\n")
            _sl_trades = _exit_df[_stop_mask]
            if len(_sl_trades) > 0:
                _imm_adv = _sl_trades[_sl_trades['mfe_r'] < 0.1]
                _ia_pct  = len(_imm_adv) / len(_sl_trades) * 100
                md.append(f"**Immediate Adverse:** {len(_imm_adv)}/{len(_sl_trades)}"
                          f" ENGINE_STOP trades ({_ia_pct:.0f}%) never reached 0.1R MFE\n")

        if _has_bars:
            md.append("### Avg Bars to Exit\n")
            md.append("| Exit Source | Avg Bars | Median Bars |")
            md.append("|-------------|----------|-------------|")
            for _src in _src_counts.index:
                _s = _exit_df[_exit_df['exit_source'] == _src]
                md.append(f"| {_src} | {_s['bars_held'].mean():.1f} | {_s['bars_held'].median():.0f} |")
            _all_avg = _exit_df['bars_held'].mean()
            _all_med = _exit_df['bars_held'].median()
            md.append(f"| ALL | {_all_avg:.1f} | {_all_med:.0f} |")
            md.append("")

    else:
        # ── Fallback: R-bucket proxy (legacy runs, no exit_source column) ────
        if _has_r and _has_bars:
            _exit_df['_exit_type'] = 'OTHER'
            _max_bars_val = int(_exit_df['bars_held'].max())
            _exit_df.loc[_exit_df['bars_held'] >= _max_bars_val, '_exit_type'] = 'TIME'
            _exit_df.loc[(_exit_df['bars_held'] < _max_bars_val) & (_exit_df['r_multiple'] <= -0.9), '_exit_type'] = 'SL'
            _exit_df.loc[(_exit_df['bars_held'] < _max_bars_val) & (_exit_df['r_multiple'] >= 1.2), '_exit_type'] = 'TP'

            md.append("### Exit Type Summary _(R-bucket proxy — no exit\\_source column)_\n")
            md.append("| Type | Trades | % | PnL | Avg R |")
            md.append("|------|--------|---|-----|-------|")
            for _et in ['SL', 'TP', 'TIME']:
                _s = _exit_df[_exit_df['_exit_type'] == _et]
                if len(_s) == 0:
                    continue
                _pct = len(_s) / len(_exit_df) * 100
                _pnl = _s['pnl_usd'].sum()
                _avg_r = _s['r_multiple'].mean()
                md.append(f"| {_et} | {len(_s)} | {_pct:.1f}% | ${_pnl:.2f} | {_avg_r:+.2f}R |")
            md.append("")

            md.append("### Exit Type by Direction\n")
            md.append("| Direction | SL % | TP % | Time % | Trades |")
            md.append("|-----------|------|------|--------|--------|")
            for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
                _ds = _exit_df[_exit_df['direction'] == _dv]
                if len(_ds) == 0:
                    continue
                _sl_pct = (_ds['_exit_type'] == 'SL').mean() * 100
                _tp_pct = (_ds['_exit_type'] == 'TP').mean() * 100
                _tm_pct = (_ds['_exit_type'] == 'TIME').mean() * 100
                md.append(f"| {_dl} | {_sl_pct:.1f}% | {_tp_pct:.1f}% | {_tm_pct:.1f}% | {len(_ds)} |")
            md.append("")

        if _has_r:
            _rmean, _rmedian = _exit_df['r_multiple'].mean(), _exit_df['r_multiple'].median()
            md.append(f"**R-Multiple:** Mean {_rmean:+.3f} | Median {_rmedian:+.3f}\n")

        if _has_mfe and '_exit_type' in _exit_df.columns:
            _time_exits = _exit_df[_exit_df['_exit_type'] == 'TIME']
            if len(_time_exits) > 0:
                _gave_back = _time_exits[_time_exits['mfe_r'] >= 0.5]
                _gb_pct = len(_gave_back) / len(_time_exits) * 100
                if len(_gave_back) > 0:
                    _avg_left = (_gave_back['mfe_r'] - _gave_back['r_multiple']).mean()
                    md.append(f"**MFE Giveback:** {_gb_pct:.0f}% of time exits had MFE >= 0.5R,"
                              f" gave back {_avg_left:+.2f}R avg\n")
            _sl_trades = _exit_df[_exit_df['_exit_type'] == 'SL']
            if len(_sl_trades) > 0:
                _imm_adv = _sl_trades[_sl_trades['mfe_r'] < 0.1]
                _ia_pct  = len(_imm_adv) / len(_sl_trades) * 100
                md.append(f"**Immediate Adverse:** {len(_imm_adv)}/{len(_sl_trades)}"
                          f" SL trades ({_ia_pct:.0f}%) never reached 0.1R MFE\n")

        if _has_bars:
            md.append("### Avg Bars to Exit\n")
            md.append("| Type | Avg Bars | Median Bars |")
            md.append("|------|----------|-------------|")
            if '_exit_type' in _exit_df.columns:
                for _et in ['SL', 'TP', 'TIME']:
                    _s = _exit_df[_exit_df['_exit_type'] == _et]
                    if len(_s) == 0:
                        continue
                    md.append(f"| {_et} | {_s['bars_held'].mean():.1f} | {_s['bars_held'].median():.0f} |")
            _all_avg = _exit_df['bars_held'].mean()
            _all_med = _exit_df['bars_held'].median()
            md.append(f"| ALL | {_all_avg:.1f} | {_all_med:.0f} |")
            md.append("")

    return md


def _build_edge_decomposition_section(all_trades_dfs):
    md = ["\n---\n", "## Edge Decomposition (Core)\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Edge Decomposition.\n")
        return md
    all_trades_df = pd.concat(all_trades_dfs, ignore_index=True)

    md.append("### A) Direction &times; Volatility\n")
    vol_cols = {"High": "high", "Normal": "normal", "Low": "low"}
    md.extend(_build_cross_tab(all_trades_df, "volatility_regime", vol_cols))
    md.append("\n")

    md.append("### B) Direction &times; Trend\n")
    trend_cols = {"Strong Up": "strong_up", "Weak Up": "weak_up", "Neutral": "neutral", "Weak Down": "weak_down", "Strong Down": "strong_down"}
    md.extend(_build_cross_tab(all_trades_df, "trend_label", trend_cols))
    md.append("\n")

    if 'entry_timestamp' in all_trades_df.columns:
        all_trades_df['_session'] = all_trades_df['entry_timestamp'].apply(_classify_session)
        md.append("### C) Direction &times; Session\n")
        session_cols = {"Asia": "asia", "London": "london", "NY": "ny"}
        md.extend(_build_cross_tab(all_trades_df, "_session", session_cols))
        md.append("\n")
    return md


def _build_risk_characteristics_section(all_trades_dfs):
    md = ["---\n", "## Risk Characteristics\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Risk Characteristics.\n")
        return md
    _risk_df = pd.concat(all_trades_dfs, ignore_index=True)
    if 'pnl_usd' not in _risk_df.columns or len(_risk_df) == 0:
        md.append("> Insufficient data for Risk Characteristics.\n")
        return md

    md.append("| Metric | Value |")
    md.append("|--------|-------|")

    # Max Consecutive Losses
    _losses = (_risk_df['pnl_usd'] <= 0).astype(int)
    _max_consec = 0
    _cur = 0
    for _v in _losses:
        if _v == 1:
            _cur += 1
            _max_consec = max(_max_consec, _cur)
        else:
            _cur = 0
    md.append(f"| Max Consecutive Losses | {_max_consec} |")

    # Longest Flat Period
    if 'entry_timestamp' in _risk_df.columns:
        _risk_df_sorted = _risk_df.sort_values('entry_timestamp').copy()
        _cum_pnl = _risk_df_sorted['pnl_usd'].cumsum()
        _peak = _cum_pnl.cummax()
        _ts = pd.to_datetime(_risk_df_sorted['entry_timestamp'], errors='coerce')
        _at_peak = _cum_pnl >= _peak
        _peak_dates = _ts[_at_peak]
        if len(_peak_dates) >= 2:
            _gaps = _peak_dates.diff().dt.days.dropna()
            _flat_days = int(_gaps.max()) if len(_gaps) > 0 else 0
        else:
            _flat_days = 0
        md.append(f"| Longest Flat Period | {_flat_days} days |")

    # Top-5 Trade Concentration
    _total_abs_pnl = abs(_risk_df['pnl_usd'].sum())
    if _total_abs_pnl > 0:
        _top5 = _risk_df.nlargest(5, 'pnl_usd')['pnl_usd'].sum()
        _top5_pct = (_top5 / _total_abs_pnl) * 100
        md.append(f"| Top-5 Trade Concentration | {_top5_pct:.1f}% of Net PnL |")

    # Edge Ratio (avg MFE / avg MAE)
    if 'mfe_r' in _risk_df.columns and 'mae_r' in _risk_df.columns:
        _avg_mfe = _risk_df['mfe_r'].mean()
        _avg_mae = abs(_risk_df['mae_r'].mean())
        _edge_ratio = (_avg_mfe / _avg_mae) if _avg_mae > 0 else 0.0
        md.append(f"| Edge Ratio (MFE/MAE) | {_edge_ratio:.2f} |")

    md.append("")
    return md
