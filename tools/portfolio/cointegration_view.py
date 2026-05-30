"""cointegration_view.py -- the lean, human-readable projection of the
cointegration_sheet for the MPS "Cointegration" tab.

The DB keeps every column (rich, future-proof). This module projects the
current rows down to the ~16 columns a human scans, with familiar header
names, the deterministic sort, and a 1-based rank. It is a pure transform
(DataFrame -> DataFrame) so it is unit-testable without Excel.

Renaming headers here is safe (unlike the portfolio sheets): the Cointegration
tab is a ONE-WAY render regenerated from the DB on every export, never re-read
and appended to by a writer -- so there is no canonical-name collision risk.

Sort that produces `rank`: canonical_ret_dd desc, then completed_at_utc desc,
then run_id desc -- stable, so exact-ret_dd ties float the most recent run up.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Final display order (== the locked human view; column-budget guard caps this).
# methodology added 2026-05-30 (C4): surfaces the cohort tag so operators can
# tell v1_raw_adf legacy rows apart from v2_log_eg / v2_log_adf post-correction
# rows — the two are NOT comparable head-to-head (different EG vs raw-ADF
# criticals, log vs raw spread). See COINTEGRATION_SCREEN_MATH_V2.md.
COINTEGRATION_VIEW_COLUMNS = [
    "rank",
    "pair",
    "timeframe",
    "lookback",
    "run_date",
    "test_start",
    "test_end",
    "return_dd_ratio",
    "net_pct",
    "max drawdown %",
    "final_equity_usd",
    "total_trades",
    "cycles",
    "win_rate",
    "regime",
    "methodology",
    "backtest",
]

# Hard cap on the human view (enforcement: the budget test asserts this).
COINTEGRATION_VIEW_BUDGET = 17

# DB column -> friendly display header.
_RENAME = {
    "lookback_days": "lookback",
    "canonical_ret_dd": "return_dd_ratio",
    "canonical_net_pct": "net_pct",
    "canonical_max_dd_pct": "max drawdown %",
    "canonical_final_equity_usd": "final_equity_usd",
    "trades_total": "total_trades",
    "cycles_completed": "cycles",
    "cycle_win_rate_pct": "win_rate",
    "regime_state": "regime",
    "methodology_version": "methodology",
}

# Sort keys (descending): primary metric, then recency, then a stable tiebreak.
_SORT_KEYS = ["canonical_ret_dd", "completed_at_utc", "run_id"]


def build_cointegration_view_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Project raw cointegration_sheet rows to the lean human view (sorted,
    ranked, friendly-named). Pure transform; no I/O."""
    if df_raw is None or len(df_raw) == 0:
        return pd.DataFrame(columns=COINTEGRATION_VIEW_COLUMNS)

    df = df_raw.copy()

    sort_keys = [k for k in _SORT_KEYS if k in df.columns]
    if "canonical_ret_dd" in df.columns:
        df["canonical_ret_dd"] = pd.to_numeric(df["canonical_ret_dd"], errors="coerce")
    if sort_keys:
        df = df.sort_values(
            by=sort_keys,
            ascending=[False] * len(sort_keys),
            kind="mergesort",  # stable: preserves recency tiebreak on exact ret_dd ties
            na_position="last",
        ).reset_index(drop=True)

    # Derived display columns.
    if "pair_a" in df.columns and "pair_b" in df.columns:
        df["pair"] = df["pair_a"].astype(str) + " / " + df["pair_b"].astype(str)
    if "backtests_path" in df.columns:
        df["backtest"] = df["backtests_path"].fillna("").apply(
            lambda p: Path(str(p)).name if str(p) else ""
        )
    if "completed_at_utc" in df.columns:
        df["run_date"] = df["completed_at_utc"].fillna("").astype(str).str.slice(0, 10)

    df = df.rename(columns=_RENAME)
    df.insert(0, "rank", range(1, len(df) + 1))

    cols = [c for c in COINTEGRATION_VIEW_COLUMNS if c in df.columns]
    return df[cols]


__all__ = [
    "COINTEGRATION_VIEW_COLUMNS",
    "COINTEGRATION_VIEW_BUDGET",
    "build_cointegration_view_df",
]
