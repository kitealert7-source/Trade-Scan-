"""Cross-window comparability guard for family-report metric comparison.

The 2026-05-07 NAS incident + the 2026-05-11 deep-history recovery taught
this codebase that comparing metric rows across different backtest windows
silently produces wrong conclusions. The family report's headline table is
the most exposed to this — researchers naturally read it as "apples-to-apples"
when in practice rows can come from windows differing by 21 months.

This module provides the guard: parse each row's ``test_start`` and
``test_end``, find the family median window, mark rows whose window deviates
by more than the tolerance at either boundary.

Same semantics as `tools/report/report_sections/verdict_risk.py:_windows_compatible`
applied to a single row, but here generalized over a family.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_TOLERANCE_DAYS = 5


def find_family_window(rows: list[dict] | pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return the (start_median, end_median) of the family's backtest windows.

    Returns (None, None) if no row has parseable dates.
    """
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for row in _iter_rows(rows):
        s = _parse_date(row.get("test_start"))
        e = _parse_date(row.get("test_end"))
        if s is not None:
            starts.append(s)
        if e is not None:
            ends.append(e)
    if not starts or not ends:
        return None, None
    return pd.Series(starts).median(), pd.Series(ends).median()


def classify_window(
    row: dict,
    family_start: pd.Timestamp | None,
    family_end: pd.Timestamp | None,
    tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
) -> dict[str, Any]:
    """For a single row, classify its window vs the family median.

    Returns ``{
        "in_window": bool,
        "start_drift_days": int | None,
        "end_drift_days": int | None,
        "reason": str,
    }``. If either family bound is unknown OR the row's bounds are unknown,
    treats as in-window (permissive on unparseable data).
    """
    if family_start is None or family_end is None:
        return {"in_window": True, "start_drift_days": None, "end_drift_days": None, "reason": ""}
    rs = _parse_date(row.get("test_start"))
    re_ = _parse_date(row.get("test_end"))
    if rs is None or re_ is None:
        return {"in_window": True, "start_drift_days": None, "end_drift_days": None, "reason": ""}
    s_drift = int(abs((rs - family_start).days))
    e_drift = int(abs((re_ - family_end).days))
    in_window = (s_drift <= tolerance_days) and (e_drift <= tolerance_days)
    reason = ""
    if not in_window:
        reason = (
            f"window {rs.date()}..{re_.date()} vs family median "
            f"{family_start.date()}..{family_end.date()} "
            f"(start Δ {s_drift}d, end Δ {e_drift}d > {tolerance_days}d tolerance)"
        )
    return {
        "in_window": in_window,
        "start_drift_days": s_drift,
        "end_drift_days": e_drift,
        "reason": reason,
    }


def annotate_window_status(
    rows: list[dict] | pd.DataFrame,
    tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
) -> list[dict]:
    """Tag every row with `in_window` / drift fields. Returns a list of dicts.

    The first call to this function on a family establishes the median window;
    all rows are then classified against it. Rows whose window can't be parsed
    are marked `in_window=True` (permissive).
    """
    start, end = find_family_window(rows)
    annotated: list[dict] = []
    for row in _iter_rows(rows):
        r = dict(row)
        r.update(classify_window(row, start, end, tolerance_days=tolerance_days))
        annotated.append(r)
    return annotated


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _iter_rows(rows):
    """Yield dict-like rows from either a list of dicts or a DataFrame."""
    if isinstance(rows, pd.DataFrame):
        for _, r in rows.iterrows():
            yield r.to_dict()
    elif rows is None:
        return
    else:
        for r in rows:
            yield r if isinstance(r, dict) else dict(r)


def _parse_date(v) -> pd.Timestamp | None:
    if v is None:
        return None
    try:
        s = str(v)[:10]
        return pd.to_datetime(s)
    except Exception:
        return None
