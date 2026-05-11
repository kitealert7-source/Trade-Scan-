"""Session-classification + Direction×{Session,Trend,Vol} cross-tabs for the
family analysis report.

This is the **only** genuinely new analytics module in Phase B per the
post-audit Rule 2 — every other section reuses an existing primitive
(`tail_contribution`, `directional_removal`, `rolling_window`, etc).

The session classifier mirrors `tools/report/report_sessions.py:_classify_session`
boundaries (asia 0-8, london 8-16, ny 16-24 UTC). The audit notes that strategies
using `session_clock` (XAU-tuned, 0-7 / 7-13 / 13-21) would derive different
session labels from their own indicator output; for *family-level* comparison
we use one consistent classifier so cross-variant cells are like-for-like.
The two strategy lineages (S01 XAU-tuned vs S02 universal) are intentional
choices observed by the family-level table, not hidden by it.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Session boundaries (UTC). Same as `tools/report/report_sessions.py:13-15`.
_ASIA_START, _ASIA_END = 0, 8
_LONDON_START, _LONDON_END = 8, 16
# NY: 16-24


# ---------------------------------------------------------------------------
# Session derivation
# ---------------------------------------------------------------------------

def classify_session(ts) -> str:
    """Classify entry_timestamp → asia / london / ny / unknown.

    UTC-hour based. Mirrors `tools/report/report_sessions.py:_classify_session`
    boundaries; duplicated here so the family report doesn't depend on the
    per-strategy report's module layout.
    """
    if pd.isna(ts):
        return "unknown"
    try:
        hour = pd.Timestamp(ts).hour
    except Exception:
        return "unknown"
    if _ASIA_START <= hour < _ASIA_END:
        return "asia"
    if _LONDON_START <= hour < _LONDON_END:
        return "london"
    return "ny"


def add_session_column(tr_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `tr_df` with a derived `session` column."""
    if tr_df is None or len(tr_df) == 0:
        return tr_df
    if "entry_timestamp" not in tr_df.columns:
        return tr_df
    out = tr_df.copy()
    out["session"] = pd.to_datetime(out["entry_timestamp"], errors="coerce").apply(classify_session)
    return out


# ---------------------------------------------------------------------------
# Per-cell aggregation
# ---------------------------------------------------------------------------

_MIN_CELL_TRADES = 30  # filter threshold for "best / worst" cell identification


def crosstab_direction_x(tr_df: pd.DataFrame, target_col: str) -> pd.DataFrame:
    """Direction × `<target_col>` cell aggregation.

    Returns a DataFrame keyed by ("direction_label", "<target_col>") with
    columns: trades, net_pnl, win_rate, profit_factor.
    """
    if tr_df is None or len(tr_df) == 0:
        return pd.DataFrame(columns=["direction", target_col, "trades", "net_pnl", "win_rate", "profit_factor"])
    if target_col not in tr_df.columns or "direction" not in tr_df.columns or "pnl_usd" not in tr_df.columns:
        return pd.DataFrame(columns=["direction", target_col, "trades", "net_pnl", "win_rate", "profit_factor"])

    d = tr_df.copy()
    d["direction"] = pd.to_numeric(d["direction"], errors="coerce")
    d = d[d["direction"].notna()]
    d["direction_label"] = d["direction"].apply(lambda x: "Long" if x > 0 else "Short")
    d[target_col] = d[target_col].astype(str).str.lower().str.strip()

    rows = []
    for dir_lbl in ("Long", "Short"):
        sub = d[d["direction_label"] == dir_lbl]
        for cell_val in sorted(sub[target_col].unique()):
            cell = sub[sub[target_col] == cell_val]
            n = len(cell)
            if n == 0:
                continue
            pnl = float(cell["pnl_usd"].sum())
            wins = int((cell["pnl_usd"] > 0).sum())
            wr = (wins / n) * 100.0 if n > 0 else 0.0
            gp = float(cell[cell["pnl_usd"] > 0]["pnl_usd"].sum())
            gl = abs(float(cell[cell["pnl_usd"] < 0]["pnl_usd"].sum()))
            pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
            rows.append({
                "direction": dir_lbl,
                target_col: cell_val,
                "trades": n,
                "net_pnl": pnl,
                "win_rate": wr,
                "profit_factor": pf,
            })
    return pd.DataFrame(rows)


def best_worst_cells(
    crosstab_df: pd.DataFrame,
    target_col: str,
    min_trades: int = _MIN_CELL_TRADES,
) -> dict[str, Any]:
    """Return the best (max net_pnl) and worst (min net_pnl) cells subject
    to `trades >= min_trades`. If no cell qualifies, returns {} for that side.
    """
    if crosstab_df is None or len(crosstab_df) == 0:
        return {"best": None, "worst": None}
    qualified = crosstab_df[crosstab_df["trades"] >= min_trades]
    if len(qualified) == 0:
        return {"best": None, "worst": None}
    best_row = qualified.loc[qualified["net_pnl"].idxmax()]
    worst_row = qualified.loc[qualified["net_pnl"].idxmin()]

    def _fmt_cell(row) -> dict:
        return {
            "cell": f"{row['direction']} × {row[target_col].title()}",
            "trades": int(row["trades"]),
            "net_pnl": float(row["net_pnl"]),
            "win_rate": float(row["win_rate"]),
            "profit_factor": float(row["profit_factor"]),
        }

    return {"best": _fmt_cell(best_row), "worst": _fmt_cell(worst_row)}


# ---------------------------------------------------------------------------
# Convenience wrappers for the three matrices the family report needs
# ---------------------------------------------------------------------------

def direction_session_matrix(tr_df: pd.DataFrame) -> pd.DataFrame:
    """Direction × Session (derived from entry_timestamp UTC hour)."""
    return crosstab_direction_x(add_session_column(tr_df), "session")


def direction_trend_matrix(tr_df: pd.DataFrame) -> pd.DataFrame:
    """Direction × trend_label (StrongUp / WeakUp / Neutral / WeakDn / StrongDn)."""
    return crosstab_direction_x(tr_df, "trend_label")


def direction_volatility_matrix(tr_df: pd.DataFrame) -> pd.DataFrame:
    """Direction × volatility_regime."""
    return crosstab_direction_x(tr_df, "volatility_regime")


def session_share(tr_df: pd.DataFrame) -> dict[str, float]:
    """% share of total net PnL by session. Returns {asia, london, ny}.

    Used in the family report's "Session Contribution" row.
    """
    d = add_session_column(tr_df)
    if d is None or len(d) == 0 or "session" not in d.columns:
        return {"asia": 0.0, "london": 0.0, "ny": 0.0}
    total = float(d["pnl_usd"].sum())
    if total == 0:
        return {"asia": 0.0, "london": 0.0, "ny": 0.0}
    out: dict[str, float] = {}
    for sess in ("asia", "london", "ny"):
        out[sess] = float(d.loc[d["session"] == sess, "pnl_usd"].sum()) / total * 100.0
    return out
