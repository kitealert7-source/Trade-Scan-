"""Session / weekday / confidence classification + direction cross-tab helper.

Shared primitive helpers used across multiple section builders — keeps
the classification boundaries (UTC hour ranges) in one place.
"""

from __future__ import annotations

import pandas as pd


# Session boundaries (UTC hours) — mirrored from stage2_compiler.py
_ASIA_START, _ASIA_END = 0, 8
_LONDON_START, _LONDON_END = 8, 16
_NY_START, _NY_END = 16, 24

_OVERLAP_START, _OVERLAP_END = 13, 16  # London-NY overlap window (UTC)
_LATE_NY_START, _LATE_NY_END = 21, 24  # Late NY / off-hours window (UTC)

_WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _classify_session(ts) -> str:
    """Classify entry_timestamp string → session label. Mirrors stage2 _get_session."""
    if pd.isna(ts):
        return "unknown"
    try:
        dt = pd.Timestamp(ts)
        hour = dt.hour
    except Exception:
        return "unknown"
    if _ASIA_START <= hour < _ASIA_END:
        return "asia"
    elif _LONDON_START <= hour < _LONDON_END:
        return "london"
    else:
        return "ny"


def _is_overlap(ts) -> bool:
    """True if entry_timestamp falls in London-NY overlap (13:00-15:59 UTC)."""
    if pd.isna(ts):
        return False
    try:
        hour = pd.Timestamp(ts).hour
    except Exception:
        return False
    return _OVERLAP_START <= hour < _OVERLAP_END


def _is_late_ny(ts) -> bool:
    """True if entry_timestamp falls in Late NY window (21:00-23:59 UTC)."""
    if pd.isna(ts):
        return False
    try:
        hour = pd.Timestamp(ts).hour
    except Exception:
        return False
    return _LATE_NY_START <= hour < _LATE_NY_END


def _conf_tag(trades: int) -> str:
    """Confidence tag based on primary trade count: High (>=50), Medium (20-49), Low (<20)."""
    if trades >= 50:
        return "High"
    elif trades >= 20:
        return "Medium"
    return "Low"


def _classify_weekday(ts) -> str:
    """Classify entry_timestamp → weekday name."""
    if pd.isna(ts):
        return "unknown"
    try:
        return _WEEKDAY_NAMES[pd.Timestamp(ts).weekday()]
    except Exception:
        return "unknown"


def _build_cross_tab(df, target_col, col_keys):
    """Build a Direction x <target_col> markdown cross-tab from trade-level data."""
    if target_col not in df.columns or 'direction' not in df.columns or 'pnl_usd' not in df.columns:
        return ["| Data Unavailable |"]

    df_c = df.copy()
    df_c[target_col] = df_c[target_col].astype(str).str.lower().str.strip()

    # Map direction safely and drop nulls to avoid silent misclassification
    df_c['dir_label'] = pd.to_numeric(df_c['direction'], errors='coerce')
    if df_c['dir_label'].isnull().any():
        print("[WARN] Dropping null direction mappings in cross-tab for {}".format(target_col))
    df_c = df_c[df_c['dir_label'].notnull()]
    df_c['dir_label'] = df_c['dir_label'].apply(lambda x: 'Long' if x > 0 else 'Short')

    headers = ["Direction"] + list(col_keys.keys())
    lines = ["| " + " | ".join(headers) + " |", "|-" + "-|-".join(["-" * len(h) for h in headers]) + "-|"]

    for dir_val in ['Long', 'Short']:
        dir_df = df_c[df_c['dir_label'] == dir_val]
        row_vals = [dir_val]
        for nice_name, raw_val in col_keys.items():
            cell_df = dir_df[dir_df[target_col] == raw_val]
            if len(cell_df) == 0:
                row_vals.append("-")
                continue
            trades = len(cell_df)
            net_pnl = cell_df['pnl_usd'].sum()
            wins = sum((cell_df['pnl_usd'] > 0).astype(int))
            wr = (wins / trades) * 100
            g_prof = float(cell_df[cell_df['pnl_usd'] > 0]['pnl_usd'].sum())
            g_loss = abs(float(cell_df[cell_df['pnl_usd'] < 0]['pnl_usd'].sum()))
            if g_loss == 0:
                pf = float('inf') if g_prof > 0 else 0.0
            else:
                pf = g_prof / g_loss

            flag = ""
            if trades >= 20 and pf >= 1.5:
                 flag = "✔ "
            elif trades >= 20 and pf <= 0.9:
                 flag = "✖ "

            pf_str = "∞" if pf == float('inf') else f"{pf:.2f}"
            row_vals.append("{flag}T:{t} P:${pnl:.2f} W:{wr:.1f}% PF:{pf}".format(
                flag=flag, t=trades, pnl=net_pnl, wr=wr, pf=pf_str))
        lines.append("| " + " | ".join(row_vals) + " |")
    return lines
