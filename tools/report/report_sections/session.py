"""Session-family section builders: regime-age, fill-age, htf-delta, exec-delta,
session breakdown (+ overlap + late-NY sub-analyses), weekday breakdown."""

from __future__ import annotations

import pandas as pd

from tools.report.report_sessions import (
    _classify_session, _classify_weekday, _is_late_ny, _is_overlap,
    _build_cross_tab, _WEEKDAY_NAMES,
)


def _build_age_section(age_data):
    if not age_data:
        return []
    md = ["## Regime Lifecycle (Age)\n"]
    _age_buckets = ["Age_0", "Age_1", "Age_2", "Age_3_5", "Age_6_10", "Age_11plus"]
    _age_labels = ["Age 0", "Age 1", "Age 2", "Age 3-5", "Age 6-10", "Age 11+"]
    md.append("| Symbol | " + " | ".join(_age_labels) + " |")
    md.append("|--------" + "|-------" * len(_age_labels) + "|")
    for row in age_data:
        cells = []
        for bk in _age_buckets:
            t = row.get(f"{bk}_T", 0)
            pnl = row.get(f"{bk}_PnL", 0.0)
            pf = row.get(f"{bk}_PF", 0.0)
            wr = row.get(f"{bk}_WR", 0.0)
            cells.append(f"T:{t} ${pnl:.2f} PF:{pf:.2f} WR:{wr:.0f}%")
        md.append(f"| {row['Symbol']} | " + " | ".join(cells) + " |")
    md.append("\n---\n")
    return md


def _build_fill_age_section(fill_age_data):
    if not fill_age_data:
        return []
    md = ["## Regime Lifecycle (Fill Age \u2014 HTF Granularity)\n",
          "*Regime age is computed on the HTF grid (e.g. 4H for 1H exec) and broadcast to exec bars; "
          "this table shows the HTF-bucket age at the fill bar. Multiple exec bars within the same HTF "
          "bar share the same age value.*\n"]
    _fill_buckets = ["Age_0", "Age_1", "Age_2", "Age_3_5", "Age_6_10", "Age_11plus", "NaN_Missing"]
    _fill_labels  = ["Age 0", "Age 1", "Age 2", "Age 3-5", "Age 6-10", "Age 11+", "NaN"]
    md.append("| Symbol | " + " | ".join(_fill_labels) + " |")
    md.append("|--------" + "|-------" * len(_fill_labels) + "|")
    for row in fill_age_data:
        cells = []
        for bk in _fill_buckets:
            t = row.get(f"{bk}_T", 0)
            pnl = row.get(f"{bk}_PnL", 0.0)
            pf = row.get(f"{bk}_PF", 0.0)
            wr = row.get(f"{bk}_WR", 0.0)
            cells.append(f"T:{t} ${pnl:.2f} PF:{pf:.2f} WR:{wr:.0f}%")
        md.append(f"| {row['Symbol']} | " + " | ".join(cells) + " |")
    md.append("\n---\n")
    return md


def _build_htf_delta_section(delta_age_data, dual_meta_data):
    if not delta_age_data:
        return []
    md = ["## HTF Transition Distribution (Fill vs Signal Age)\n",
          "*Delta = fill_age \u2212 signal_age on the HTF grid. **Delta 0** = signal and fill land in the "
          "same HTF bar (dominant, ~3/4 under 4H\u21921H). **Delta 1** = fill crosses into the next HTF bar "
          "(~1/4). **Delta \u2264-2** = regime flip occurred between signal and fill (rare, but a candidate "
          "structural-edge bucket). Exec-TF timing is NOT captured here \u2014 that's a future second clock.*\n"]
    for meta_row in dual_meta_data:
        sym = meta_row.get("Symbol", "?")
        n_total = meta_row.get("n_total", 0)
        n_valid = meta_row.get("n_delta_valid", 0)
        n_sig_nan = meta_row.get("n_signal_nan", 0)
        n_fil_nan = meta_row.get("n_fill_nan", 0)
        pct = (100.0 * n_valid / n_total) if n_total else 0.0
        md.append(f"- **{sym}** \u2014 valid delta trades: {n_valid} / {n_total} ({pct:.1f}%)  "
                  f"(signal NaN: {n_sig_nan}, fill NaN: {n_fil_nan})")
    md.append("")
    _delta_buckets = ["Delta_leneg2", "Delta_neg1", "Delta_0", "Delta_1", "Delta_ge2"]
    _delta_labels  = ["\u2264-2", "-1", "0", "1", "\u22652"]
    md.append("| Symbol | " + " | ".join(_delta_labels) + " |")
    md.append("|--------" + "|-------" * len(_delta_labels) + "|")
    for row in delta_age_data:
        cells = []
        for bk in _delta_buckets:
            t = row.get(f"{bk}_T", 0)
            pnl = row.get(f"{bk}_PnL", 0.0)
            pf = row.get(f"{bk}_PF", 0.0)
            wr = row.get(f"{bk}_WR", 0.0)
            cells.append(f"T:{t} ${pnl:.2f} PF:{pf:.2f} WR:{wr:.0f}%")
        md.append(f"| {row['Symbol']} | " + " | ".join(cells) + " |")
    md.append("\n---\n")
    return md


def _build_exec_delta_section(exec_delta_data, exec_meta_data):
    if not exec_delta_data:
        return []
    md = ["## Exec-TF Age Delta (Signal vs Fill) \u2014 v1.5.6 Probe\n",
          "*Delta on the EXEC-TF regime_age clock (separate from the HTF table above). "
          "Under next_bar_open, **Delta 1** should dominate (exec clock ticks one bar between "
          "signal and fill). **Delta 0** is only possible if the regime reset at the fill bar. "
          "**Delta \u2264-1** = regime flip between signal and fill (rare).*\n"]
    for meta_row in exec_meta_data:
        sym = meta_row.get("Symbol", "?")
        n_total = meta_row.get("n_total", 0)
        n_valid = meta_row.get("n_delta_valid", 0)
        n_sig_nan = meta_row.get("n_signal_nan", 0)
        n_fil_nan = meta_row.get("n_fill_nan", 0)
        pct = (100.0 * n_valid / n_total) if n_total else 0.0
        md.append(f"- **{sym}** \u2014 valid exec-delta trades: {n_valid} / {n_total} ({pct:.1f}%)  "
                  f"(signal NaN: {n_sig_nan}, fill NaN: {n_fil_nan})")
    md.append("")
    _xd_buckets = ["Exec_Delta_leneg1", "Exec_Delta_0", "Exec_Delta_1", "Exec_Delta_ge2"]
    _xd_labels  = ["\u2264-1", "0", "1", "\u22652"]
    md.append("| Symbol | " + " | ".join(_xd_labels) + " |")
    md.append("|--------" + "|-------" * len(_xd_labels) + "|")
    for row in exec_delta_data:
        cells = []
        for bk in _xd_buckets:
            t = row.get(f"{bk}_T", 0)
            pnl = row.get(f"{bk}_PnL", 0.0)
            pf = row.get(f"{bk}_PF", 0.0)
            wr = row.get(f"{bk}_WR", 0.0)
            cells.append(f"T:{t} ${pnl:.2f} PF:{pf:.2f} WR:{wr:.0f}%")
        md.append(f"| {row['Symbol']} | " + " | ".join(cells) + " |")
    md.append("\n---\n")
    return md


def _build_session_overlap_subsection(sess_df):
    """Overlap (13-16 UTC) sub-analysis inside the Session Breakdown section."""
    md = []
    sess_df['_is_overlap'] = sess_df['entry_timestamp'].apply(_is_overlap)
    _ov = sess_df[sess_df['_is_overlap']]
    _non_ov = sess_df[~sess_df['_is_overlap']]
    md.append("### Overlap Analysis (London-NY, 13-16 UTC)\n")
    if len(_ov) < 10:
        md.append(f"> Only {len(_ov)} trades in overlap window — insufficient for analysis.\n")
        return md

    md.append("| Segment | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
    md.append("|---------|--------|---------|-----|-------|-------|----------|")
    for _label, _sub in [('Overlap (13-16)', _ov), ('Non-overlap', _non_ov)]:
        _t = len(_sub)
        if _t == 0:
            md.append(f"| {_label} | 0 | - | - | - | - | - |")
            continue
        _pnl = _sub['pnl_usd'].sum()
        _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
        _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
        _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
        _pf_s = f"{_pf:.2f}" if _pf != float('inf') else "∞"
        _wr = (_sub['pnl_usd'] > 0).mean() * 100
        _ar = f"{_sub['r_multiple'].mean():+.3f}" if 'r_multiple' in _sub.columns else "N/A"
        _ab = f"{_sub['bars_held'].mean():.1f}" if 'bars_held' in _sub.columns else "N/A"
        md.append(f"| {_label} | {_t} | ${_pnl:.2f} | {_pf_s} | {_wr:.1f}% | {_ar} | {_ab} |")
    md.append("")

    # Session × Overlap cross-tab (London and NY only — Asia can't overlap)
    md.append("### Session x Overlap\n")
    md.append("| Session | Core (no overlap) | Overlap (13-16) |")
    md.append("|---------|-------------------|-----------------|")
    for _sl, _sn in [('london', 'London'), ('ny', 'New York')]:
        _s_all = sess_df[sess_df['_session'] == _sl]
        _s_core = _s_all[~_s_all['_is_overlap']]
        _s_ov = _s_all[_s_all['_is_overlap']]
        parts = []
        for _sub in [_s_core, _s_ov]:
            if len(_sub) == 0:
                parts.append("-")
                continue
            _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
            _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
            _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
            _pf_s = "∞" if _pf == float('inf') else f"{_pf:.2f}"
            parts.append(f"T:{len(_sub)} ${_sub['pnl_usd'].sum():.2f} PF:{_pf_s}")
        md.append(f"| {_sn} | {parts[0]} | {parts[1]} |")
    md.append("")
    return md


def _build_session_late_ny_subsection(sess_df):
    """Late NY (21-24 UTC) sub-analysis inside the Session Breakdown section."""
    md = []
    sess_df['_is_late_ny'] = sess_df['entry_timestamp'].apply(_is_late_ny)
    _lny = sess_df[sess_df['_is_late_ny']]
    _non_lny = sess_df[~sess_df['_is_late_ny']]

    md.append("### Late NY Analysis (21-24 UTC)\n")
    if len(_lny) < 10:
        md.append(f"> Only {len(_lny)} trades in Late NY window — insufficient for analysis.\n")
        return md

    md.append("| Segment | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
    md.append("|---------|--------|---------|-----|-------|-------|----------|")
    for _label, _sub in [('Late NY (21-24)', _lny), ('Rest', _non_lny)]:
        _t = len(_sub)
        if _t == 0:
            md.append(f"| {_label} | 0 | - | - | - | - | - |")
            continue
        _pnl = _sub['pnl_usd'].sum()
        _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
        _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
        _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
        _pf_s = f"{_pf:.2f}" if _pf != float('inf') else "∞"
        _wr = (_sub['pnl_usd'] > 0).mean() * 100
        _ar = f"{_sub['r_multiple'].mean():+.3f}" if 'r_multiple' in _sub.columns else "N/A"
        _ab = f"{_sub['bars_held'].mean():.1f}" if 'bars_held' in _sub.columns else "N/A"
        md.append(f"| {_label} | {_t} | ${_pnl:.2f} | {_pf_s} | {_wr:.1f}% | {_ar} | {_ab} |")
    md.append("")

    # NY core vs Late NY split
    md.append("### NY x Late Session\n")
    md.append("| Segment | Core NY (16-21) | Late NY (21-24) |")
    md.append("|---------|-----------------|-----------------|")
    _ny_all = sess_df[sess_df['_session'] == 'ny']
    _ny_core = _ny_all[~_ny_all['_is_late_ny']]
    _ny_late = _ny_all[_ny_all['_is_late_ny']]
    parts = []
    for _sub in [_ny_core, _ny_late]:
        if len(_sub) == 0:
            parts.append("-")
            continue
        _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
        _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
        _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
        _pf_s = "∞" if _pf == float('inf') else f"{_pf:.2f}"
        parts.append(f"T:{len(_sub)} ${_sub['pnl_usd'].sum():.2f} PF:{_pf_s}")
    md.append(f"| NY | {parts[0]} | {parts[1]} |")
    md.append("")

    # Direction × Late NY
    if 'direction' in sess_df.columns:
        md.append("### Direction x Late NY\n")
        md.append("| Direction | Core NY (16-21) | Late NY (21-24) |")
        md.append("|-----------|-----------------|-----------------|")
        for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
            _d_ny = _ny_all[_ny_all['direction'] == _dv]
            _d_core = _d_ny[~_d_ny['_is_late_ny']]
            _d_late = _d_ny[_d_ny['_is_late_ny']]
            parts = []
            for _sub in [_d_core, _d_late]:
                if len(_sub) == 0:
                    parts.append("-")
                    continue
                _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
                _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
                _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
                _pf_s = "∞" if _pf == float('inf') else f"{_pf:.2f}"
                _wr = (_sub['pnl_usd'] > 0).mean() * 100
                parts.append(f"T:{len(_sub)} ${_sub['pnl_usd'].sum():.2f} PF:{_pf_s} W:{_wr:.0f}%")
            md.append(f"| {_dl} | {parts[0]} | {parts[1]} |")
        md.append("")
    return md


def _build_session_section(all_trades_dfs, session_data, show_overlap, show_late_ny):
    md = ["## Session Breakdown\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Session Breakdown.\n")
        return md
    _sess_df = pd.concat(all_trades_dfs, ignore_index=True)
    if 'entry_timestamp' not in _sess_df.columns or 'pnl_usd' not in _sess_df.columns:
        md.append("> No entry_timestamp data available for Session Breakdown.\n")
        return md
    _sess_df['_session'] = _sess_df['entry_timestamp'].apply(_classify_session)
    md.append("| Session | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
    md.append("|---------|--------|---------|-----|-------|-------|----------|")
    for _sl, _sn in [('asia', 'Asia'), ('london', 'London'), ('ny', 'New York')]:
        _ss = _sess_df[_sess_df['_session'] == _sl]
        if len(_ss) == 0:
            md.append(f"| {_sn} | 0 | - | - | - | - | - |")
            continue
        _s_trades = len(_ss)
        _s_pnl = _ss['pnl_usd'].sum()
        _s_gp = float(_ss[_ss['pnl_usd'] > 0]['pnl_usd'].sum())
        _s_gl = abs(float(_ss[_ss['pnl_usd'] < 0]['pnl_usd'].sum()))
        _s_pf = (_s_gp / _s_gl) if _s_gl > 0 else (_s_gp if _s_gp > 0 else 0.0)
        _s_pf_str = f"{_s_pf:.2f}" if _s_pf != float('inf') else "∞"
        _s_wr = (_ss['pnl_usd'] > 0).mean() * 100
        _s_avg_r = f"{_ss['r_multiple'].mean():+.3f}" if 'r_multiple' in _ss.columns else "N/A"
        _s_bars = f"{_ss['bars_held'].mean():.1f}" if 'bars_held' in _ss.columns else "N/A"
        md.append(f"| {_sn} | {_s_trades} | ${_s_pnl:.2f} | {_s_pf_str} | {_s_wr:.1f}% | {_s_avg_r} | {_s_bars} |")
    md.append("")

    # Per-symbol session grid (only if multi-symbol)
    if len(session_data) > 1:
        md.append("### Per-Symbol Session Grid\n")
        md.append("| Symbol | Asia | London | NY |")
        md.append("|--------|------|--------|-----|")
        for row in session_data:
            md.append(f"| {row['Symbol']} | T:{row['Asia_T']} ${row['Asia']:.2f} | T:{row['London_T']} ${row['London']:.2f} | T:{row['NY_T']} ${row['NY']:.2f} |")
        md.append("")

    if show_overlap:
        md.extend(_build_session_overlap_subsection(_sess_df))
    if show_late_ny:
        md.extend(_build_session_late_ny_subsection(_sess_df))
    return md


def _build_weekday_section(all_trades_dfs, show_weekday):
    if not show_weekday or not all_trades_dfs:
        return []
    _wd_df = pd.concat(all_trades_dfs, ignore_index=True)
    if 'entry_timestamp' not in _wd_df.columns or 'pnl_usd' not in _wd_df.columns:
        return []
    _wd_df['_weekday'] = _wd_df['entry_timestamp'].apply(_classify_weekday)
    _wd_valid = _wd_df[_wd_df['_weekday'] != 'unknown']
    if len(_wd_valid) < 10:
        return []

    md = ["\n---\n", "## Weekday Breakdown\n",
          "| Day | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |",
          "|-----|--------|---------|-----|-------|-------|----------|"]
    for _day in _WEEKDAY_NAMES[:5]:  # Mon-Fri only (Sat/Sun typically empty)
        _ds = _wd_valid[_wd_valid['_weekday'] == _day]
        if len(_ds) == 0:
            md.append(f"| {_day} | 0 | - | - | - | - | - |")
            continue
        _dt = len(_ds)
        _dpnl = _ds['pnl_usd'].sum()
        _dgp = float(_ds[_ds['pnl_usd'] > 0]['pnl_usd'].sum())
        _dgl = abs(float(_ds[_ds['pnl_usd'] < 0]['pnl_usd'].sum()))
        _dpf = (_dgp / _dgl) if _dgl > 0 else (_dgp if _dgp > 0 else 0.0)
        _dpf_s = f"{_dpf:.2f}" if _dpf != float('inf') else "inf"
        _dwr = (_ds['pnl_usd'] > 0).mean() * 100
        _dar = f"{_ds['r_multiple'].mean():+.3f}" if 'r_multiple' in _ds.columns else "N/A"
        _dab = f"{_ds['bars_held'].mean():.1f}" if 'bars_held' in _ds.columns else "N/A"
        md.append(f"| {_day} | {_dt} | ${_dpnl:.2f} | {_dpf_s} | {_dwr:.1f}% | {_dar} | {_dab} |")
    # Weekend rows only if trades exist
    for _day in _WEEKDAY_NAMES[5:]:
        _ds = _wd_valid[_wd_valid['_weekday'] == _day]
        if len(_ds) > 0:
            _dt = len(_ds)
            _dpnl = _ds['pnl_usd'].sum()
            _dgp = float(_ds[_ds['pnl_usd'] > 0]['pnl_usd'].sum())
            _dgl = abs(float(_ds[_ds['pnl_usd'] < 0]['pnl_usd'].sum()))
            _dpf = (_dgp / _dgl) if _dgl > 0 else (_dgp if _dgp > 0 else 0.0)
            _dpf_s = f"{_dpf:.2f}" if _dpf != float('inf') else "inf"
            _dwr = (_ds['pnl_usd'] > 0).mean() * 100
            _dar = f"{_ds['r_multiple'].mean():+.3f}" if 'r_multiple' in _ds.columns else "N/A"
            _dab = f"{_ds['bars_held'].mean():.1f}" if 'bars_held' in _ds.columns else "N/A"
            md.append(f"| {_day} | {_dt} | ${_dpnl:.2f} | {_dpf_s} | {_dwr:.1f}% | {_dar} | {_dab} |")
    md.append("")

    # Direction × Day cross-tab
    _wd_valid['_weekday_lc'] = _wd_valid['_weekday'].str.lower()
    _day_cols = {d: d.lower() for d in _WEEKDAY_NAMES[:5]}
    for _day in _WEEKDAY_NAMES[5:]:
        if len(_wd_valid[_wd_valid['_weekday'] == _day]) > 0:
            _day_cols[_day] = _day.lower()
    md.append("### Direction &times; Day\n")
    md.extend(_build_cross_tab(_wd_valid, "_weekday_lc", _day_cols))
    md.append("")
    return md
