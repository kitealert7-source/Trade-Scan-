"""cointegration_excel.py — Phase 3: SQLite → Excel report.

Reads cointegration_daily + singles_daily from SQLite and writes a
multi-sheet workbook organized by ASSET CLASS (per 2026-05-21 cleanup):

  1. Summary                   — universe-level structural state
  2. Forex (incl. Metals)      — curated FX + XAU candidates only
  3. Crypto                    — curated BTC/ETH candidates only
  4. Indices & Stocks          — placeholder (deferred until equity universe)
  5. All Pairs (Diagnostic)    — full 210-pair-pair output, audit-only
  6. Singles (Diagnostic)      — full single-symbol ADF output, audit-only
  7. History                   — last 90 daily snapshots per pair-window
  8. Notes                     — doctrine, classifier rules, per-candidate
                                  rationale

The asset-class tabs (2-4) are operator-actionable; the diagnostic tabs
(5-6) preserve the full screener output as audit trail but are flagged
as not-to-be-acted-on-without-economic-rationale. The curated candidates
come from governance/cointegration_candidates.yaml — see that file for
the structural reasoning behind each candidate.

Per COINTEGRATION_SCREENER_V1_SPEC.md §8 (ranking) + §9 (sheet layout)
+ 2026-05-21 hypothesis-led curation amendment.

Conditional formatting is applied via explicit cell fills (computed in
Python) — simpler than openpyxl ConditionalFormatting rules for the
mixed categorical+numeric thresholds we use.

CLI:
    python tools/cointegration_excel.py --export
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import yaml

from config.path_authority import DATA_ROOT
from tools.cointegration_db import (
    HYSTERESIS_LOOKBACK,
    P_BREAKING,
    P_COINTEGRATED,
    SINGLES_TABLE_NAME,
    SQLITE_DB,
    TABLE_NAME,
    connect,
)
# Co-located with parquet + SQLite under SYSTEM_FACTORS — see
# cointegration_db.py for the 2026-05-20 location-move rationale.
EXCEL_PATH = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION" / "Cointegration_Screener.xlsx"
CANDIDATES_YAML = PROJECT_ROOT / "governance" / "cointegration_candidates.yaml"

# --- Colors (hex without #) --------------------------------------
COLOR_HEADER_BG    = "4472C4"  # matches existing format_excel convention
COLOR_HEADER_FG    = "FFFFFF"
COLOR_SECTION_BG   = "D9E1F2"  # section header in Summary
COLOR_GREEN_BG     = "C6EFCE"
COLOR_GREEN_FG     = "006100"
COLOR_YELLOW_BG    = "FFEB9C"
COLOR_YELLOW_FG    = "9C5700"
COLOR_RED_BG       = "FFC7CE"
COLOR_RED_FG       = "9C0006"
COLOR_GREY_BG      = "EAEAEA"
COLOR_BOOTSTRAP_BG = "FCE4D6"  # soft orange — bootstrap-classifier flag

THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ---------------------------------------------------------------------------
# Composite ranking score (spec §8)
# ---------------------------------------------------------------------------


def _half_life_quality(hl: float | None) -> float:
    """Peaks at 15 days; falls off below 3 or above 60 (spec §8)."""
    if hl is None or pd.isna(hl) or hl <= 0:
        return 0.0
    return float(math.exp(-abs(math.log(hl / 15.0))))


def _stability_persistence(conn: sqlite3.Connection,
                            pair_a: str, pair_b: str, lookback_days: int,
                            *, days: int = 90) -> float:
    """Fraction of last `days` snapshots in regime='cointegrated'.

    On day 1 returns 1.0 or 0.0 depending on today's regime alone.
    """
    rows = conn.execute(
        f"""SELECT regime FROM {TABLE_NAME}
            WHERE pair_a = ? AND pair_b = ? AND lookback_days = ?
            ORDER BY as_of DESC LIMIT ?""",
        (pair_a, pair_b, int(lookback_days), int(days)),
    ).fetchall()
    if not rows:
        return 0.0
    return sum(1 for r in rows if r["regime"] == "cointegrated") / len(rows)


def _excursion_containment(conn: sqlite3.Connection,
                            pair_a: str, pair_b: str, lookback_days: int,
                            *, days: int = 252) -> float:
    """Fraction of last `days` snapshots with |current_zscore| ≤ 3.0."""
    rows = conn.execute(
        f"""SELECT current_zscore FROM {TABLE_NAME}
            WHERE pair_a = ? AND pair_b = ? AND lookback_days = ?
            ORDER BY as_of DESC LIMIT ?""",
        (pair_a, pair_b, int(lookback_days), int(days)),
    ).fetchall()
    if not rows:
        return 0.0
    contained = sum(
        1 for r in rows
        if r["current_zscore"] is not None and abs(r["current_zscore"]) <= 3.0
    )
    return contained / len(rows)


def composite_score(conn: sqlite3.Connection, row: dict) -> float:
    """`stability_persistence * half_life_quality * excursion_containment`.

    Each component ∈ [0, 1]; NaN inputs → 0. (Spec §8.)
    """
    sp = _stability_persistence(conn, row["pair_a"], row["pair_b"],
                                  row["lookback_days"])
    hq = _half_life_quality(row["half_life_days"])
    ec = _excursion_containment(conn, row["pair_a"], row["pair_b"],
                                  row["lookback_days"])
    return float(sp * hq * ec)


# ---------------------------------------------------------------------------
# Conditional-fill helpers
# ---------------------------------------------------------------------------


def _fill(bg: str, fg: str | None = None) -> tuple[PatternFill, Font]:
    return (PatternFill("solid", fgColor=bg),
            Font(color=fg) if fg else Font())


_REGIME_FILL = {
    "cointegrated": _fill(COLOR_GREEN_BG,  COLOR_GREEN_FG),
    "breaking":     _fill(COLOR_YELLOW_BG, COLOR_YELLOW_FG),
    "broken":       _fill(COLOR_RED_BG,    COLOR_RED_FG),
}
_AGREEMENT_FILL = {
    "BOTH":     _fill(COLOR_GREEN_BG,  COLOR_GREEN_FG),
    "252-only": _fill(COLOR_YELLOW_BG, COLOR_YELLOW_FG),
    "504-only": _fill(COLOR_YELLOW_BG, COLOR_YELLOW_FG),
    "NEITHER":  _fill(COLOR_RED_BG,    COLOR_RED_FG),
}
def _half_life_color(hl) -> tuple[PatternFill, Font] | None:
    if hl is None or pd.isna(hl):
        return _fill(COLOR_RED_BG, COLOR_RED_FG)
    if 5 <= hl <= 30:
        return _fill(COLOR_GREEN_BG, COLOR_GREEN_FG)
    if (3 <= hl < 5) or (30 < hl <= 60):
        return _fill(COLOR_YELLOW_BG, COLOR_YELLOW_FG)
    return _fill(COLOR_RED_BG, COLOR_RED_FG)


def _zscore_color(z) -> tuple[PatternFill, Font] | None:
    if z is None or pd.isna(z):
        return None
    az = abs(z)
    if az >= 3.0:
        return _fill(COLOR_RED_BG, COLOR_RED_FG)
    if az >= 2.0:
        return _fill(COLOR_YELLOW_BG, COLOR_YELLOW_FG)
    return None


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------


def _header_style(cell) -> None:
    cell.fill = PatternFill("solid", fgColor=COLOR_HEADER_BG)
    cell.font = Font(color=COLOR_HEADER_FG, bold=True)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = BORDER


def _section_header(ws, row: int, text: str, span: int = 4) -> int:
    ws.cell(row=row, column=1, value=text)
    ws.cell(row=row, column=1).font = Font(bold=True, size=12, color="000000")
    ws.cell(row=row, column=1).fill = PatternFill("solid", fgColor=COLOR_SECTION_BG)
    ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=span)
    return row + 1


def _apply_default_filter_cointegrated(
    ws, header_row: int, regime_col_idx: int,
) -> None:
    """Add an Excel AutoFilter to the sheet's data range and pre-apply a
    'cointegrated'-only filter on the named regime column.

    Sets:
      * `auto_filter.ref` so Excel renders the filter dropdown UI
      * `add_filter_column` so the saved file remembers the cointegrated
        filter is active
      * `row_dimensions[r].hidden = True` for every non-cointegrated row so
        Excel renders the filtered view immediately on open (without this,
        the filter UI shows as "applied" but all rows still display until
        the user re-clicks the filter)

    Operator can click the filter dropdown and uncheck `(Show All)` /
    pick a different regime to expand the view manually.
    """
    last_row = ws.max_row
    if last_row <= header_row:
        return
    last_col = get_column_letter(ws.max_column)
    ws.auto_filter.ref = f"A{header_row}:{last_col}{last_row}"
    # add_filter_column wants a 0-indexed offset from auto_filter.ref's
    # first column; our ref starts at A so offset = (col_idx - 1)
    ws.auto_filter.add_filter_column(regime_col_idx - 1, ["cointegrated"])
    for r in range(header_row + 1, last_row + 1):
        if ws.cell(row=r, column=regime_col_idx).value != "cointegrated":
            ws.row_dimensions[r].hidden = True


# ---------------------------------------------------------------------------
# Curated candidates loader + per-candidate query
# ---------------------------------------------------------------------------


def load_candidates(path: Path = CANDIDATES_YAML) -> dict:
    """Read the hypothesis-led candidates YAML.

    Returns the raw `asset_classes` dict. Each top-level key is an
    asset-class slug (e.g. 'forex'); values carry `label`, `description`,
    `candidates` list (may be empty), and optional `deferred` bool.
    """
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("asset_classes") or {}


def _query_candidate_rows(
    conn: sqlite3.Connection, candidate: dict, df_pairs: pd.DataFrame,
    df_singles: pd.DataFrame,
) -> dict:
    """Resolve one candidate to per-window result rows.

    Returns a dict with `regime`, `adf_pvalue`, `half_life_days`,
    `current_zscore` for each lookback window (252, 504), plus
    `route`, `rationale`, `type`, `subject` (display label).
    Empty values become None.
    """
    ctype = candidate["type"]

    def _cells(sub: pd.DataFrame) -> dict:
        out: dict[str, object] = {}
        for lb in (252, 504):
            r = sub[sub.lookback_days == lb]
            if r.empty:
                out[f"regime_{lb}"] = None
                out[f"p_{lb}"] = None
                out[f"hl_{lb}"] = None
                out[f"z_{lb}"] = None
            else:
                rr = r.iloc[0]
                out[f"regime_{lb}"] = rr["regime"]
                out[f"p_{lb}"] = float(rr["adf_pvalue"])
                out[f"hl_{lb}"] = float(rr["half_life_days"]) if pd.notna(
                    rr["half_life_days"]) else None
                out[f"z_{lb}"] = float(rr["current_zscore"]) if pd.notna(
                    rr["current_zscore"]) else None
        return out

    if ctype == "single":
        sym = candidate["symbol"]
        sub = df_singles[df_singles.symbol == sym]
        subject = sym
    elif ctype == "synthetic_ratio":
        sym = f"RATIO:{candidate['pair_a']}/{candidate['pair_b']}"
        sub = df_singles[df_singles.symbol == sym]
        subject = sym
    elif ctype == "pair":
        # Canonical orientation: alphabetical
        a, b = sorted([candidate["pair_a"], candidate["pair_b"]])
        sub = df_pairs[(df_pairs.pair_a == a) & (df_pairs.pair_b == b)]
        subject = f"{a}/{b}"
    else:
        sub = pd.DataFrame()
        subject = candidate.get("key", "?")

    cells = _cells(sub)
    cells.update({
        "key":       candidate["key"],
        "type":      ctype,
        "subject":   subject,
        "route":     candidate.get("route", "—"),
        "canonical": candidate.get("canonical"),
        "rationale": candidate.get("rationale", "").strip(),
    })
    return cells


def _pivot_today(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot from (pair, window) rows to (pair) rows with window columns."""
    if df.empty:
        return df
    pivoted = []
    for (a, b), grp in df.groupby(["pair_a", "pair_b"], sort=True):
        r252 = grp[grp.lookback_days == 252]
        r504 = grp[grp.lookback_days == 504]
        if r252.empty or r504.empty:
            continue
        r252 = r252.iloc[0]
        r504 = r504.iloc[0]
        regime_252 = r252["regime"]
        regime_504 = r504["regime"]
        if regime_252 == "cointegrated" and regime_504 == "cointegrated":
            agreement = "BOTH"
        elif regime_252 == "cointegrated":
            agreement = "252-only"
        elif regime_504 == "cointegrated":
            agreement = "504-only"
        else:
            agreement = "NEITHER"
        pivoted.append({
            "pair_a": a, "pair_b": b,
            "agreement": agreement,
            "regime_252": regime_252, "regime_504": regime_504,
            "adf_pvalue_252": r252["adf_pvalue"], "adf_pvalue_504": r504["adf_pvalue"],
            "half_life_days_252": r252["half_life_days"], "half_life_days_504": r504["half_life_days"],
            "current_zscore_252": r252["current_zscore"], "current_zscore_504": r504["current_zscore"],
            "hedge_ratio_252": r252["hedge_ratio"], "hedge_ratio_504": r504["hedge_ratio"],
            "history_depth": max(r252["history_depth"], r504["history_depth"]),
        })
    return pd.DataFrame(pivoted)


def _write_summary(wb: Workbook, conn: sqlite3.Connection,
                    df_today: pd.DataFrame) -> None:
    ws = wb.create_sheet("Summary", 0)
    as_of = df_today["as_of"].iloc[0] if not df_today.empty else "—"
    ws.cell(row=1, column=1, value=f"Cointegration Screener — Summary  ({as_of})").font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, end_row=1, start_column=1, end_column=6)

    row = 3

    # --- Section 1: Universe regime distribution
    row = _section_header(ws, row, "1. Universe regime distribution", span=5)
    headers = ["window", "cointegrated", "breaking", "broken", "total"]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=row, column=c, value=h))
    row += 1
    for lb in (252, 504):
        sub = df_today[df_today.lookback_days == lb]
        c1 = sub[sub.regime == "cointegrated"].shape[0]
        c2 = sub[sub.regime == "breaking"].shape[0]
        c3 = sub[sub.regime == "broken"].shape[0]
        ws.cell(row=row, column=1, value=f"{lb}d")
        for col_i, (val, fill_key) in enumerate(
            [(c1, "cointegrated"), (c2, "breaking"), (c3, "broken")], start=2):
            cell = ws.cell(row=row, column=col_i, value=val)
            cell.fill, cell.font = _REGIME_FILL[fill_key]
            cell.alignment = Alignment(horizontal="center")
        ws.cell(row=row, column=5, value=c1 + c2 + c3).alignment = Alignment(horizontal="center")
        row += 1
    row += 1

    # --- Section 2: Half-life summary (cointegrated only)
    row = _section_header(ws, row, "2. Half-life days (cointegrated pairs only)", span=5)
    headers = ["window", "median", "mean", "min", "max"]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=row, column=c, value=h))
    row += 1
    for lb in (252, 504):
        sub = df_today[(df_today.lookback_days == lb) & (df_today.regime == "cointegrated")]
        if sub.empty or sub["half_life_days"].isna().all():
            ws.cell(row=row, column=1, value=f"{lb}d")
            ws.cell(row=row, column=2, value="—")
            row += 1
            continue
        hl = sub["half_life_days"].dropna()
        ws.cell(row=row, column=1, value=f"{lb}d")
        ws.cell(row=row, column=2, value=round(float(hl.median()), 2))
        ws.cell(row=row, column=3, value=round(float(hl.mean()), 2))
        ws.cell(row=row, column=4, value=round(float(hl.min()), 2))
        ws.cell(row=row, column=5, value=round(float(hl.max()), 2))
        for c in range(1, 6):
            ws.cell(row=row, column=c).alignment = Alignment(horizontal="center")
        row += 1
    row += 1

    # --- Section 3: Top recurring currencies in cointegrated pairs (252d)
    row = _section_header(ws, row, "3. Top currencies in cointegrated pairs (252d)", span=3)
    headers = ["currency", "appearances", "% of cointegrated pairs"]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=row, column=c, value=h))
    row += 1
    coint_252 = df_today[(df_today.lookback_days == 252) & (df_today.regime == "cointegrated")]
    counter: Counter[str] = Counter()
    for _, r in coint_252.iterrows():
        for sym in (r["pair_a"], r["pair_b"]):
            for currency in (sym[:3], sym[3:]):
                counter[currency] += 1
    total = coint_252.shape[0] * 2 or 1
    for currency, count in counter.most_common(10):
        ws.cell(row=row, column=1, value=currency).alignment = Alignment(horizontal="center")
        ws.cell(row=row, column=2, value=count).alignment = Alignment(horizontal="center")
        ws.cell(row=row, column=3, value=f"{count/total*100:.1f}%").alignment = Alignment(horizontal="center")
        row += 1
    row += 1

    # --- Section 4: Window agreement
    row = _section_header(ws, row, "4. Window agreement (252d × 504d cointegration overlap)", span=2)
    headers = ["agreement", "pair count"]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=row, column=c, value=h))
    row += 1
    pivoted = _pivot_today(df_today)
    agree_counts = (pivoted["agreement"].value_counts() if not pivoted.empty else pd.Series(dtype=int))
    for label in ("BOTH", "252-only", "504-only", "NEITHER"):
        ws.cell(row=row, column=1, value=label)
        if label in _AGREEMENT_FILL:
            ws.cell(row=row, column=1).fill, ws.cell(row=row, column=1).font = _AGREEMENT_FILL[label]
            ws.cell(row=row, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=row, column=2, value=int(agree_counts.get(label, 0))).alignment = Alignment(horizontal="center")
        row += 1
    row += 1

    # --- Section 5: Regime changes vs prior snapshot
    row = _section_header(ws, row, "5. Regime changes vs prior snapshot", span=4)
    headers = ["transition", "count", "pair examples (up to 5)"]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=row, column=c, value=h))
    row += 1
    if df_today.empty:
        prior_as_of = None
    else:
        # Distinct as_of values, sorted descending
        prior_row = conn.execute(
            f"SELECT DISTINCT as_of FROM {TABLE_NAME} ORDER BY as_of DESC LIMIT 2"
        ).fetchall()
        prior_as_of = prior_row[1]["as_of"] if len(prior_row) >= 2 else None
    if prior_as_of is None:
        ws.cell(row=row, column=1, value="(no prior snapshot — first run)")
        row += 2
    else:
        prior_df = pd.read_sql_query(
            f"SELECT pair_a, pair_b, lookback_days, regime FROM {TABLE_NAME} WHERE as_of = ?",
            conn, params=(prior_as_of,))
        # Join today × prior on the key
        merged = df_today.merge(
            prior_df, on=["pair_a", "pair_b", "lookback_days"],
            suffixes=("_today", "_prior"))
        newly_broken = merged[(merged.regime_prior == "cointegrated")
                              & (merged.regime_today.isin(["broken", "breaking"]))]
        newly_recovered = merged[(merged.regime_prior.isin(["broken", "breaking"]))
                                 & (merged.regime_today == "cointegrated")]
        for label, sub in (("newly_broken", newly_broken),
                           ("newly_recovered", newly_recovered)):
            ws.cell(row=row, column=1, value=label)
            ws.cell(row=row, column=2, value=len(sub)).alignment = Alignment(horizontal="center")
            examples = ", ".join(
                f"{r.pair_a}/{r.pair_b} ({r.lookback_days}d)"
                for r in sub.head(5).itertuples()
            ) or "—"
            ws.cell(row=row, column=3, value=examples)
            row += 1
    row += 1

    # --- Section 6: Bootstrap visibility
    row = _section_header(ws, row, "6. Bootstrap visibility (history_depth distribution)", span=3)
    headers = ["status", "row count", "% of universe"]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=row, column=c, value=h))
    row += 1
    n_total = len(df_today)
    n_bootstrap = (df_today["history_depth"] < HYSTERESIS_LOOKBACK).sum()
    n_hysteresis = (df_today["history_depth"] >= HYSTERESIS_LOOKBACK).sum()
    for label, count, fill in (
        (f"bootstrap (history_depth < {HYSTERESIS_LOOKBACK})", n_bootstrap, _fill(COLOR_BOOTSTRAP_BG, "000000")),
        (f"hysteresis-active (history_depth ≥ {HYSTERESIS_LOOKBACK})", n_hysteresis, _fill(COLOR_GREEN_BG, COLOR_GREEN_FG)),
    ):
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=1).fill, ws.cell(row=row, column=1).font = fill
        ws.cell(row=row, column=2, value=int(count)).alignment = Alignment(horizontal="center")
        pct = (count / n_total * 100) if n_total else 0
        ws.cell(row=row, column=3, value=f"{pct:.1f}%").alignment = Alignment(horizontal="center")
        row += 1

    # Column widths
    for c, w in enumerate([26, 14, 14, 14, 14], start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["C"].width = 40   # examples + % cells


def _write_today(wb: Workbook, conn: sqlite3.Connection,
                  df_today: pd.DataFrame, position: int | None = None) -> None:
    if position is None:
        position = len(wb.sheetnames)
    ws = wb.create_sheet("Today", position)
    pivoted = _pivot_today(df_today)

    # Compute composite score per row from SQLite (uses 252d row only).
    scores = []
    for _, r in pivoted.iterrows():
        score_row = {"pair_a": r["pair_a"], "pair_b": r["pair_b"],
                     "lookback_days": 252,
                     "half_life_days": r["half_life_days_252"]}
        scores.append(composite_score(conn, score_row))
    pivoted["score"] = scores
    pivoted = pivoted.sort_values("score", ascending=False).reset_index(drop=True)

    columns = [
        "pair_a", "pair_b", "agreement",
        "regime_252", "regime_504",
        "adf_pvalue_252", "adf_pvalue_504",
        "half_life_days_252", "half_life_days_504",
        "current_zscore_252", "current_zscore_504",
        "hedge_ratio_252", "hedge_ratio_504",
        "history_depth", "score",
    ]
    for c, h in enumerate(columns, start=1):
        _header_style(ws.cell(row=1, column=c, value=h))

    for i, r in pivoted.iterrows():
        excel_row = i + 2
        for c, col in enumerate(columns, start=1):
            v = r[col]
            cell = ws.cell(row=excel_row, column=c)
            if isinstance(v, float) and not pd.isna(v):
                cell.value = round(v, 4)
            elif pd.isna(v):
                cell.value = None
            else:
                cell.value = v
            cell.alignment = Alignment(horizontal="center")
            cell.border = BORDER
            # Conditional fills
            if col in ("regime_252", "regime_504") and v in _REGIME_FILL:
                cell.fill, cell.font = _REGIME_FILL[v]
            elif col == "agreement" and v in _AGREEMENT_FILL:
                cell.fill, cell.font = _AGREEMENT_FILL[v]
            elif col in ("half_life_days_252", "half_life_days_504"):
                fc = _half_life_color(v)
                if fc:
                    cell.fill, cell.font = fc
            elif col in ("current_zscore_252", "current_zscore_504"):
                zc = _zscore_color(v)
                if zc:
                    cell.fill, cell.font = zc
            elif col == "history_depth":
                if isinstance(v, (int, float)) and v < HYSTERESIS_LOOKBACK:
                    cell.fill, cell.font = _fill(COLOR_BOOTSTRAP_BG, "000000")

    ws.freeze_panes = "D2"
    widths = [10, 10, 11, 13, 13, 14, 14, 18, 18, 18, 18, 14, 14, 14, 10]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w

    # All Pairs (Diagnostic): pre-apply cointegrated filter on regime_252 (col D = 4)
    _apply_default_filter_cointegrated(ws, header_row=1, regime_col_idx=4)


_ROUTE_FILL = {
    "direct":         _fill(COLOR_GREEN_BG,  COLOR_GREEN_FG),
    "synthesize":     _fill(COLOR_YELLOW_BG, COLOR_YELLOW_FG),
    "redundant_with": _fill(COLOR_GREY_BG,   "000000"),
}


def _write_asset_class_tab(
    wb: Workbook, conn: sqlite3.Connection, class_key: str, class_def: dict,
    df_pairs: pd.DataFrame, df_singles: pd.DataFrame, position: int,
) -> None:
    """Write one asset-class tab with curated candidates only."""
    label = class_def.get("label", class_key)
    description = class_def.get("description", "")
    deferred = bool(class_def.get("deferred", False))
    candidates = class_def.get("candidates") or []

    ws = wb.create_sheet(label, position)

    # Header row + description
    ws.cell(row=1, column=1, value=label).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, end_row=1, start_column=1, end_column=10)
    ws.cell(row=2, column=1, value=description.replace("\n", " ").strip())
    ws.cell(row=2, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=2, end_row=2, start_column=1, end_column=10)
    ws.row_dimensions[2].height = 45

    if deferred:
        ws.cell(row=4, column=1, value="DEFERRED — no candidates active.")
        ws.cell(row=4, column=1).font = Font(italic=True, color="9C5700")
        ws.column_dimensions["A"].width = 80
        return

    if not candidates:
        ws.cell(row=4, column=1, value="No curated candidates configured.")
        ws.column_dimensions["A"].width = 80
        return

    headers = [
        "key", "type", "subject", "route", "canonical",
        "reg252", "reg504", "p252", "p504", "hl252", "hl504",
        "z252", "z504", "rationale",
    ]
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=4, column=c, value=h))

    for i, candidate in enumerate(candidates):
        row = 5 + i
        cells = _query_candidate_rows(conn, candidate, df_pairs, df_singles)

        def put(col_idx, value):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.alignment = Alignment(horizontal="center" if col_idx <= 13 else "left",
                                       vertical="top",
                                       wrap_text=col_idx == 14)
            cell.border = BORDER
            return cell

        put(1, cells["key"])
        put(2, cells["type"])
        put(3, cells["subject"])
        route_cell = put(4, cells["route"])
        if cells["route"] in _ROUTE_FILL:
            route_cell.fill, route_cell.font = _ROUTE_FILL[cells["route"]]
        put(5, cells.get("canonical") or "")

        # regime + p-value cells, with regime-fill
        for col_offset, lb in enumerate((252, 504)):
            reg = cells.get(f"regime_{lb}")
            cell = put(6 + col_offset, reg)
            if reg in _REGIME_FILL:
                cell.fill, cell.font = _REGIME_FILL[reg]
            p = cells.get(f"p_{lb}")
            put(8 + col_offset, round(p, 4) if p is not None else None)

        for col_offset, lb in enumerate((252, 504)):
            hl = cells.get(f"hl_{lb}")
            hl_cell = put(10 + col_offset, round(hl, 1) if hl is not None else None)
            fc = _half_life_color(hl)
            if fc:
                hl_cell.fill, hl_cell.font = fc

        for col_offset, lb in enumerate((252, 504)):
            z = cells.get(f"z_{lb}")
            z_cell = put(12 + col_offset, round(z, 2) if z is not None else None)
            zc = _zscore_color(z)
            if zc:
                z_cell.fill, z_cell.font = zc

        # Rationale — wrapped
        put(14, cells["rationale"])
        ws.row_dimensions[row].height = 50

    # Column widths
    widths = [22, 16, 22, 14, 22, 12, 12, 9, 9, 9, 9, 9, 9, 70]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w

    # Auto-hide `canonical` column (col E) when no candidate uses route=
    # redundant_with on this tab. Cross-asset tabs without triangular
    # restatements (e.g. Indices & Stocks, where FX-equity pairs have no
    # shared token to cancel) get a cleaner view. Column un-hides
    # automatically the moment a redundant_with entry is added to this
    # class in the yaml.
    if not any(c.get("canonical") for c in candidates):
        ws.column_dimensions[get_column_letter(5)].hidden = True

    # Pre-applied cointegrated-only filter on reg252 (col F = index 6) for
    # crypto + indices_stocks tabs. Forex left unfiltered so all candidates
    # (incl. currently-broken ones like AUDNZD) stay visible by default.
    if class_key in ("crypto", "indices_stocks"):
        _apply_default_filter_cointegrated(ws, header_row=4, regime_col_idx=6)

    ws.freeze_panes = "F5"


def _write_singles_diagnostic(wb: Workbook, conn: sqlite3.Connection,
                                df_singles: pd.DataFrame, position: int) -> None:
    """Full singles output (diagnostic / audit). Not operator-actionable
    unless an entry survives economic-rationale screening (then promote
    to candidates yaml).
    """
    ws = wb.create_sheet("Singles (Diagnostic)", position)
    ws.cell(row=1, column=1, value="Singles — full single-symbol ADF (diagnostic only)"
            ).font = Font(bold=True, size=12)
    ws.cell(row=2, column=1,
            value=("Each row: ADF on log-price of a single symbol (or synthetic "
                   "ratio). NOT operator-actionable without explicit economic "
                   "rationale — see Forex/Crypto tabs for curated subset."))
    ws.cell(row=2, column=1).alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=2, end_row=2, start_column=1, end_column=10)
    ws.row_dimensions[2].height = 30

    if df_singles.empty:
        ws.cell(row=4, column=1, value="(no singles data yet — daily runner pending)")
        return

    # Pivot per symbol: 252 + 504 side-by-side
    pivot = []
    for sym, sub in df_singles.groupby("symbol"):
        r252 = sub[sub.lookback_days == 252]
        r504 = sub[sub.lookback_days == 504]
        if r252.empty or r504.empty:
            continue
        pivot.append({
            "symbol": sym,
            "regime_252": r252.iloc[0]["regime"],
            "regime_504": r504.iloc[0]["regime"],
            "adf_pvalue_252": r252.iloc[0]["adf_pvalue"],
            "adf_pvalue_504": r504.iloc[0]["adf_pvalue"],
            "half_life_days_252": r252.iloc[0]["half_life_days"],
            "half_life_days_504": r504.iloc[0]["half_life_days"],
            "current_zscore_252": r252.iloc[0]["current_zscore"],
            "current_zscore_504": r504.iloc[0]["current_zscore"],
            "history_depth": max(r252.iloc[0]["history_depth"],
                                  r504.iloc[0]["history_depth"]),
        })
    df_pivot = pd.DataFrame(pivot).sort_values("adf_pvalue_252")

    headers = list(df_pivot.columns) if not df_pivot.empty else []
    for c, h in enumerate(headers, start=1):
        _header_style(ws.cell(row=4, column=c, value=h))

    for i, r in df_pivot.reset_index(drop=True).iterrows():
        excel_row = i + 5
        for c, col in enumerate(headers, start=1):
            v = r[col]
            cell = ws.cell(row=excel_row, column=c)
            cell.value = (round(float(v), 4) if isinstance(v, float) and pd.notna(v)
                          else (None if pd.isna(v) else v))
            cell.alignment = Alignment(horizontal="center")
            cell.border = BORDER
            if col in ("regime_252", "regime_504") and v in _REGIME_FILL:
                cell.fill, cell.font = _REGIME_FILL[v]
            elif col in ("half_life_days_252", "half_life_days_504"):
                fc = _half_life_color(v)
                if fc:
                    cell.fill, cell.font = fc
            elif col in ("current_zscore_252", "current_zscore_504"):
                zc = _zscore_color(v)
                if zc:
                    cell.fill, cell.font = zc

    ws.freeze_panes = "B5"
    widths = [22, 12, 12, 14, 14, 18, 18, 18, 18, 14]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w

    # Singles (Diagnostic): pre-apply cointegrated filter on regime_252 (col B = 2)
    _apply_default_filter_cointegrated(ws, header_row=4, regime_col_idx=2)


def _write_history(wb: Workbook, conn: sqlite3.Connection,
                    position: int | None = None) -> None:
    if position is None:
        position = len(wb.sheetnames)
    ws = wb.create_sheet("History", position)
    df = pd.read_sql_query(
        f"""SELECT as_of, pair_a, pair_b, lookback_days, regime,
                   adf_pvalue, pvalue_rolling_median_5d, half_life_days,
                   hedge_ratio, current_zscore, history_depth
            FROM {TABLE_NAME}
            WHERE as_of >= date('now', '-90 days')
            ORDER BY pair_a, pair_b, lookback_days, as_of DESC""",
        conn,
    )
    columns = list(df.columns)
    for c, h in enumerate(columns, start=1):
        _header_style(ws.cell(row=1, column=c, value=h))
    for i, r in df.iterrows():
        excel_row = i + 2
        for c, col in enumerate(columns, start=1):
            v = r[col]
            cell = ws.cell(row=excel_row, column=c)
            if isinstance(v, float) and not pd.isna(v):
                cell.value = round(v, 4)
            elif pd.isna(v):
                cell.value = None
            else:
                cell.value = v
            cell.alignment = Alignment(horizontal="center")
            if col == "regime" and v in _REGIME_FILL:
                cell.fill, cell.font = _REGIME_FILL[v]
    ws.freeze_panes = "A2"
    for c, w in enumerate([12, 10, 10, 10, 14, 12, 14, 14, 12, 12, 12], start=1):
        ws.column_dimensions[get_column_letter(c)].width = w

    # History: pre-apply cointegrated filter on regime (col E = 5)
    _apply_default_filter_cointegrated(ws, header_row=1, regime_col_idx=5)


def _write_notes(wb: Workbook) -> None:
    # Notes sheet appended last by export_excel orchestrator; position arg
    # is the new index after all earlier tabs have been written.
    position = len(wb.sheetnames)
    ws = wb.create_sheet("Notes", position)
    ws.cell(row=1, column=1, value="Cointegration Screener — Operator Notes").font = Font(bold=True, size=14)
    lines = [
        "",
        "HYPOTHESIS-LED CURATION (2026-05-21 amendment)",
        "  This workbook is organized by ASSET CLASS, with operator-actionable",
        "  candidates separated from the full diagnostic ADF surface. Curated",
        "  candidates have explicit economic rationale (governance/cointegration",
        "  _candidates.yaml). Diagnostic tabs preserve the full universe output",
        "  but are NOT operator-actionable without economic-rationale screening.",
        "",
        "  Why: a blind ADF screen of ~210 pair-pairs × 2 windows is a data-",
        "  mining exercise. At α=0.05 you expect ~21 spurious 'cointegrated'",
        "  finds even on pure random walks. Hypothesis-led curation flips the",
        "  workflow: start from structural reasoning, use the screener to",
        "  confirm and monitor regime persistence — not to discover.",
        "",
        "TAB GUIDE",
        "  • Forex (incl. Metals)   : curated FX + XAU candidates only",
        "  • Crypto                 : curated BTC/ETH candidates only",
        "  • Indices & Stocks       : deferred placeholder",
        "  • All Pairs (Diagnostic) : full pair-pair output, audit-only",
        "  • Singles (Diagnostic)   : full single-symbol output, audit-only",
        "  • History                : last 90 days per pair-window",
        "  • Notes                  : this sheet",
        "",
        "ROUTE COLUMN (curated tabs)",
        "  • direct           — trade the symbol/pair as listed (cheapest execution)",
        "  • synthesize       — trade as two-leg basket (no direct symbol available)",
        "  • redundant_with   — pointer to canonical candidate; this row is the",
        "                       triangular-synthesis alternative, generally not",
        "                       preferred over the canonical (see candidate row)",
        "",
        "SOURCE OF TRUTH",
        "  Parquet (data_root/SYSTEM_FACTORS/FX_COINTEGRATION/coint_1d_latest.parquet) is the deterministic",
        "  computation artifact. SQLite (DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db) is the",
        "  longitudinal history sink. This Excel file is regenerated FROM SQLite on demand.",
        "",
        "REGIME CLASSIFIER (spec §7)",
        "  current_pvalue < 0.05  AND  ≥ 4 of last 5 priors also < 0.05   →  cointegrated",
        "  current_pvalue in [0.05, 0.10)  OR  insufficient persistence    →  breaking",
        "  current_pvalue ≥ 0.10                                            →  broken",
        f"  History depth required for hysteresis: {HYSTERESIS_LOOKBACK} prior daily snapshots.",
        "  Rows with history_depth < hysteresis threshold use the BOOTSTRAP classifier",
        "  (current p-value only) — flagged with orange highlight in the Today sheet.",
        "",
        "RANKING SCORE (spec §8)",
        "  score = stability_persistence × half_life_quality × excursion_containment",
        "    stability_persistence  = fraction of last 90 days regime='cointegrated'",
        "    half_life_quality      = exp(−|log(half_life_days / 15)|)    (peaks at 15d, falls off below 3 or above 60)",
        "    excursion_containment  = fraction of last 252 days with |z-score| ≤ 3.0",
        "  Score helps SORTING. It does NOT replace diagnostic columns (p-value, half-life, z-score, regime, rolling-median).",
        "",
        "AGREEMENT COLUMN (Today sheet)",
        "  BOTH      — both 252d and 504d windows are cointegrated (strongest signal)",
        "  252-only  — only short window cointegrated; possibly a recent regime formation, treat with caution",
        "  504-only  — only long window cointegrated; relationship may be degrading",
        "  NEITHER   — neither window cointegrated",
        "",
        "CORRELATION ≠ COINTEGRATION (spec §1 doctrine)",
        "  Two high-correlation pairs can still have a non-stationary (non-mean-reverting) spread.",
        "  Trading mean-reversion on a non-cointegrated pair lets the spread drift indefinitely.",
        "  Empirical example from this corpus: EURUSD/NZDUSD at chart-TF correlation ≈ 0.79 but ADF",
        "  p-value 0.086 (252d) / 0.110 (504d) — regime='breaking'/'broken'. The screener catches this.",
        "",
        "STRATEGY-CONSTRUCTION CAVEAT (cleanup 2026-05-21)",
        "  Cointegration says: spread B − β·A is stationary for some β.",
        "  Trading that spread requires β-weighted lot sizing — NOT equal-lot.",
        "  An equal-lot trade on a cointegrated pair with |β| large is a",
        "  directional bet weighted by whichever leg has higher dollar-volatility,",
        "  not a mean-reversion trade. The retired COINTREV v1 strategy made",
        "  exactly this mistake and was deleted on 2026-05-21. Any future",
        "  strategy that consumes this screener must size legs by the screener's",
        "  hedge_ratio (β) column, not 1:1.",
        "",
        "THE PROBE",
        "  Phase 0a probe script: tools/cointegration_screener_smoke.py (re-runnable via the registered",
        "  Windows task 'CointegrationScreener_Phase0aProbe').",
        "",
        f"  Generated: {datetime.now(timezone.utc).isoformat()}",
    ]
    for i, text in enumerate(lines, start=2):
        ws.cell(row=i, column=1, value=text)
    ws.column_dimensions["A"].width = 110


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def export_excel(db_path: Path | str = SQLITE_DB,
                 output_path: Path | str = EXCEL_PATH) -> Path:
    """Read DB, build workbook, write to `output_path`.

    Sheet order (2026-05-21):
      0  Summary
      1  Forex (incl. Metals)         [curated]
      2  Crypto                       [curated]
      3  Indices & Stocks             [deferred placeholder]
      4  All Pairs (Diagnostic)       [full pair-pair output]
      5  Singles (Diagnostic)         [full single-symbol output]
      6  History
      7  Notes
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    try:
        # PER-PAIR latest as_of (not global MAX). Different symbols have
        # different trading calendars: FX + most indices stop trading Friday,
        # but BTC/ETH trade weekends. A naive `MAX(as_of)` query on a Saturday
        # or Sunday returns only the crypto rows under today's date, leaving
        # FX/index pairs absent from `df_today` and blanking out their cells
        # in the curated asset-class tabs.
        df_today = pd.read_sql_query(
            f"""SELECT t.* FROM {TABLE_NAME} t
                WHERE t.as_of = (
                    SELECT MAX(as_of) FROM {TABLE_NAME}
                    WHERE pair_a = t.pair_a AND pair_b = t.pair_b
                      AND tf = t.tf AND lookback_days = t.lookback_days
                )
                ORDER BY t.pair_a, t.pair_b, t.lookback_days""",
            conn,
        )
        df_singles = pd.read_sql_query(
            f"""SELECT t.* FROM {SINGLES_TABLE_NAME} t
                WHERE t.as_of = (
                    SELECT MAX(as_of) FROM {SINGLES_TABLE_NAME}
                    WHERE symbol = t.symbol AND tf = t.tf
                      AND lookback_days = t.lookback_days
                )
                ORDER BY t.symbol, t.lookback_days""",
            conn,
        ) if _table_exists(conn, SINGLES_TABLE_NAME) else pd.DataFrame()
        candidates = load_candidates()

        wb = Workbook()
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

        # 0 — Summary (always first)
        _write_summary(wb, conn, df_today)

        # 1-3 — asset class tabs in canonical order
        class_order = ["forex", "crypto", "indices_stocks"]
        pos = 1
        for class_key in class_order:
            if class_key in candidates:
                _write_asset_class_tab(
                    wb, conn, class_key, candidates[class_key],
                    df_today, df_singles, position=pos,
                )
                pos += 1

        # 4 — All Pairs (Diagnostic)
        _write_today(wb, conn, df_today)
        wb["Today"].title = "All Pairs (Diagnostic)"

        # 5 — Singles (Diagnostic)
        _write_singles_diagnostic(wb, conn, df_singles, position=pos + 1)

        # 6 — History; 7 — Notes
        _write_history(wb, conn)
        _write_notes(wb)
        wb.save(str(output_path))
    finally:
        conn.close()
    return output_path


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cointegration screener — Phase 3 SQLite → Excel."
    )
    p.add_argument("--export", action="store_true",
                   help="Regenerate Cointegration_Screener.xlsx from SQLite.")
    p.add_argument("--db", type=str, default=str(SQLITE_DB))
    p.add_argument("--output", type=str, default=str(EXCEL_PATH))
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.export:
        print("Specify --export to regenerate the Excel file.")
        return 2
    out = export_excel(args.db, args.output)
    print(f"[cointegration_excel] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
