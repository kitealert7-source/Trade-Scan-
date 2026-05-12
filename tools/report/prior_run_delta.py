"""Prior-run delta for the family analysis report.

Computes the metric Δ between a strategy's *current* MF row and the
*immediately preceding* MF row for the same strategy (= same
``clean_id + _<SYMBOL>`` value in the MF ``strategy`` column).

Two comparison policies live in the report — keep them straight:

  - **Cross-strategy comparison** (parent → child, e.g. P09 vs P08).
    Window mismatch makes the comparison invalid (you'd be comparing
    different time periods), so the parent-Δ block in
    ``tools/report/report_sections/verdict_risk.py`` *suppresses* with a
    warning when windows differ beyond tolerance.

  - **Same-strategy comparison** (this module).
    Window mismatch is *informative* — the window change itself is one
    of the things that may have changed between runs. So this block
    *renders* the delta and *annotates* the window change instead of
    suppressing.

Inputs are small (1–2 MF rows per call) and the DB query is rowid-bounded,
so calling this per family variant is cheap.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


_DEFAULT_WINDOW_TOLERANCE_DAYS = 5

# Metrics shown in the delta block. Each entry is
# (mf_column_name, display_label, format_kind).
#
# format_kind:
#   "f2"      → fixed 2 decimals  (SQN, PF, expectancy)
#   "pct"     → percentage points (max_dd_pct already in % units)
#   "money"   → $ with thousands separator
#   "int"     → integer count
_METRIC_SPEC: list[tuple[str, str, str]] = [
    ("sqn",              "SQN",         "f2"),
    ("profit_factor",    "PF",          "f2"),
    ("expectancy",       "Expectancy",  "money"),
    ("max_dd_pct",       "Max DD%",     "pct"),
    ("total_trades",     "Trades",      "int"),
    ("total_net_profit", "Net Profit",  "money"),
]


def compute_prior_run_delta(
    db_path: Path,
    strategy: str,
    current_rowid: int | None,
    current_row: dict | pd.Series | None,
    tolerance_days: int = _DEFAULT_WINDOW_TOLERANCE_DAYS,
) -> dict | None:
    """Return the prior-run delta payload, or None if no prior run exists.

    ``current_rowid`` is the rowid of the row currently being rendered. The
    prior-run lookup is for the highest rowid strictly less than this. Pass
    ``None`` to ask for the second-newest row of the strategy regardless of
    which one is "current".

    Returns a dict shaped for the renderer::

        {
            "found": True,
            "prior_run_id": "old_rid",
            "prior_window": {"start": "2024-07-19", "end": "2026-05-04"},
            "prior_is_current": 1 | 0 | None,
            "current_window": {"start": "2024-05-11", "end": "2026-05-11"},
            "window_mismatch": True,
            "window_drift": {"start_days": -69, "end_days": 7},
            "metrics": [
                {"label": "SQN", "current": 2.34, "prior": 2.41,
                 "delta": -0.07, "pct_change": -2.9,
                 "current_str": "2.34", "prior_str": "2.41",
                 "delta_str": "-0.07", "kind": "f2"},
                ...
            ],
        }

    When no prior run exists, returns ``{"found": False}``.
    """
    prior = _fetch_prior_row(db_path, strategy, current_rowid)
    if prior is None:
        return {"found": False}

    if current_row is None:
        return {"found": False}

    current_dict = (
        dict(current_row) if isinstance(current_row, pd.Series) else dict(current_row)
    )

    current_start = _parse_date(current_dict.get("test_start"))
    current_end   = _parse_date(current_dict.get("test_end"))
    prior_start   = _parse_date(prior.get("test_start"))
    prior_end     = _parse_date(prior.get("test_end"))

    start_drift = _drift_days(current_start, prior_start)
    end_drift   = _drift_days(current_end,   prior_end)
    window_mismatch = (
        (start_drift is not None and abs(start_drift) > tolerance_days)
        or (end_drift is not None and abs(end_drift) > tolerance_days)
    )

    metrics: list[dict[str, Any]] = []
    for col, label, kind in _METRIC_SPEC:
        cur_val = _coerce_number(current_dict.get(col))
        pri_val = _coerce_number(prior.get(col))
        metrics.append(_build_metric_row(label, cur_val, pri_val, kind))

    is_cur = prior.get("is_current")
    return {
        "found": True,
        "prior_run_id": str(prior.get("run_id", "?")),
        "prior_window": {
            "start": _fmt_date(prior_start),
            "end":   _fmt_date(prior_end),
        },
        "prior_is_current": None if is_cur is None else int(is_cur),
        "current_window": {
            "start": _fmt_date(current_start),
            "end":   _fmt_date(current_end),
        },
        "window_mismatch": bool(window_mismatch),
        "window_drift": {
            "start_days": start_drift,
            "end_days":   end_drift,
        },
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# DB lookup
# ---------------------------------------------------------------------------

def _fetch_prior_row(
    db_path: Path,
    strategy: str,
    current_rowid: int | None,
) -> dict | None:
    """Return the prior MF row for ``strategy`` (rowid strictly < current_rowid).

    Includes ``is_current = 0`` rows by design — the historical metric is
    still a fact, and surfacing "this was superseded" is informative. The
    renderer annotates that case visually.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        if current_rowid is None:
            df = pd.read_sql_query(
                "SELECT rowid AS _rowid, * FROM master_filter "
                "WHERE strategy = ? ORDER BY rowid DESC LIMIT 2",
                conn,
                params=(strategy,),
            )
            if len(df) < 2:
                return None
            return df.iloc[1].to_dict()
        df = pd.read_sql_query(
            "SELECT rowid AS _rowid, * FROM master_filter "
            "WHERE strategy = ? AND rowid < ? "
            "ORDER BY rowid DESC LIMIT 1",
            conn,
            params=(strategy, int(current_rowid)),
        )
        if len(df) == 0:
            return None
        return df.iloc[0].to_dict()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Number / date helpers
# ---------------------------------------------------------------------------

def _build_metric_row(label: str, cur: float | None, pri: float | None, kind: str) -> dict[str, Any]:
    delta = None
    pct = None
    if cur is not None and pri is not None:
        delta = cur - pri
        if pri != 0:
            pct = (delta / abs(pri)) * 100.0
    return {
        "label":       label,
        "kind":        kind,
        "current":     cur,
        "prior":       pri,
        "delta":       delta,
        "pct_change":  pct,
        "current_str": _fmt_value(cur, kind),
        "prior_str":   _fmt_value(pri, kind),
        "delta_str":   _fmt_delta(delta, kind),
        "pct_str":     _fmt_pct(pct, kind),
    }


def _coerce_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not _is_nan(v):
        return float(v)
    try:
        out = float(v)
        return None if _is_nan(out) else out
    except (TypeError, ValueError):
        return None


def _is_nan(v: float) -> bool:
    return v != v  # NaN-safe (NaN is the only float not equal to itself)


def _parse_date(v: Any) -> pd.Timestamp | None:
    if v is None or v == "":
        return None
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return None
        return ts
    except (TypeError, ValueError):
        return None


def _drift_days(a: pd.Timestamp | None, b: pd.Timestamp | None) -> int | None:
    if a is None or b is None:
        return None
    return int((a - b).days)


def _fmt_date(ts: pd.Timestamp | None) -> str:
    if ts is None:
        return "?"
    return str(ts.date())


def _fmt_value(v: float | None, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "f2":
        return f"{v:.2f}"
    if kind == "pct":
        return f"{v:.2f}%"
    if kind == "money":
        return f"${v:,.2f}"
    if kind == "int":
        return f"{int(round(v)):,}"
    return f"{v}"


def _fmt_delta(d: float | None, kind: str) -> str:
    if d is None:
        return "—"
    sign = "+" if d >= 0 else ""
    if kind == "f2":
        return f"{sign}{d:.2f}"
    if kind == "pct":
        return f"{sign}{d:.2f} pp"
    if kind == "money":
        return f"{sign}${d:,.2f}"
    if kind == "int":
        return f"{sign}{int(round(d)):,}"
    return f"{sign}{d}"


def _fmt_pct(pct: float | None, kind: str) -> str:
    # Don't render a percent change for percentage-point or count metrics.
    if pct is None or kind in ("pct", "int"):
        return ""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"
