"""repair_integrity.py — reconcile FSP + MPS ledgers against disk artifacts.

Two actions for the operator-driven cleanup workflow defined in
`.claude/skills/pipeline-state-cleanup/SKILL.md` (Critical Authority Note):

  * `--action drop` (default) — operator-driven cleanup. The operator
    deleted disk artifacts (`runs/<id>/`, `backtests/<id>.json`, or
    `strategies/<portfolio_id>/`); the matching ledger rows are dropped to
    bring the spreadsheets in line with the now-authoritative disk state.
    This is the documented exception to CLAUDE.md invariant #2 — the
    operator's `rm -rf` is the signal of intent, not an automated tool.

  * `--action mark` — lineage-preserving alternative. Tags rows
    `quarantine_status=ARCHIVED_DEPENDENCY_LOST` so they stay visible-as-
    archived in the workbook. Use when the audit trail for the row matters
    even though the artifacts are gone (rare; SUPERSEDED / ARCHIVED_UNRESOLVED
    from the H3 rehab batch is a related pattern but for different reasons).

Drop mode honors LINEAGE_PROTECTED_TAGS = {SUPERSEDED, ARCHIVED_UNRESOLVED}.
Rows carrying either tag are preserved on drop because those tags are
explicit audit decisions (from the H3 leg_direction_flip_bug rehab batch).
ARCHIVED_DEPENDENCY_LOST is *not* protected — it's a soft tombstone that
drop can re-resolve.

Writes preserve every sheet in MPS (Portfolios + Single-Asset Composites +
Baskets + Notes) via the `ExcelWriter(mode="a", if_sheet_exists="replace")`
pattern. The pre-2026-05-26 implementation read MPS as a single sheet and
wrote it back single-sheet — which deleted SAC + Baskets + Notes on every
run. Anyone who ran the old tool against a populated workbook would have
silently lost the entire H3 rehabilitation history.

CLI:
    python tools/state_lifecycle/repair_integrity.py                       # dry-run, drop
    python tools/state_lifecycle/repair_integrity.py --execute             # drop, write
    python tools/state_lifecycle/repair_integrity.py --action mark         # dry-run, mark
    python tools/state_lifecycle/repair_integrity.py --action mark --execute

Companion to:
    - lineage_pruner.py — must run AFTER any --action mark; the pruner's
      integrity check honors quarantine_status to skip tagged rows.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE as STATE_ROOT

MASTER_SHEET_PATH = STATE_ROOT / "strategies" / "Master_Portfolio_Sheet.xlsx"
FILTERED_SHEET_PATH = STATE_ROOT / "candidates" / "Filtered_Strategies_Passed.xlsx"
RUNS_DIR = STATE_ROOT / "runs"
BACKTESTS_DIR = STATE_ROOT / "backtests"
SANDBOX_DIR = STATE_ROOT / "sandbox"
STRATEGIES_DIR = STATE_ROOT / "strategies"
# Cointegration ledger is DB-canonical (the "Cointegration" MPS tab is a lossy
# one-way view that drops run_id) — so the coint drop arm reads/deletes the DB
# table, unlike the xlsx-driven Baskets arm. Module-level so tests can patch it.
# The "COINT TRADE CANDIDATES" MPS tab is likewise a pure pair-grain render of
# cointegration_sheet (one row per pair, no independent rows) — regenerated on
# export, never pruned/repaired here; managing the coint table covers it.
LEDGER_DB_PATH = STATE_ROOT / "ledger.db"

# Sheets read + rewritten in MPS. Baskets uses single run_id orphan detection
# (like FSP, scan_baskets); Portfolios + SAC use constituent_run_ids +
# portfolio_id folder checks (scan_mps_sheet + scan_mps_missing_portfolio_folder).
# Extended 2026-05-27 to cover Baskets — the H3 rehab tag-only convention was
# reversed by commit 5e16a16, and Baskets is now a first-class managed sheet.
MPS_TAGGED_SHEETS = ("Portfolios", "Single-Asset Composites")
MPS_BASKETS_SHEET = "Baskets"
# Cointegration is DB-canonical with a lossy projected "Cointegration" tab.
# Orphan detection + drop run against the cointegration_sheet table; the tab is
# re-rendered from the DB after a drop (see scan_cointegration / the apply path).
# This constant also satisfies the sheet-coverage CI test, which literal-string-
# searches this source for every live MPS data-sheet name.
MPS_COINTEGRATION_SHEET = "Cointegration"

# Reason text cap — quarantine_reason is a single-line audit field, not a log.
_REASON_MAX_CHARS = 200

QUARANTINE_REASON_PREFIX = "constituent_run_ids reference orphan run(s) on disk: "
QUARANTINE_REASON_FOLDER = "deployed portfolio folder missing from TradeScan_State/strategies/"
QUARANTINE_REASON_BASKETS_RUN = "run_id directory missing from TradeScan_State/runs/: "


def _check_file_writable(path: Path) -> None:
    """Verify file can be opened for writing (catches Excel-open lock).

    Uses binary append mode so the lint_encoding hook stays happy without
    forcing text decoding on a binary xlsx we don't read.
    """
    try:
        with open(path, "ab"):
            pass
    except PermissionError:
        print(f"[BLOCK] Cannot write {path.name} — file is open in another application. Close Excel and retry.")
        sys.exit(1)


def is_valid_run(run_id: str) -> bool:
    """True iff `run_id` has both a folder (runs/ or sandbox/) AND a JSON artifact.

    The pruner uses the same definition; we keep the two in lock-step so the
    tag-then-pruner pipeline can't disagree on what's "missing."
    """
    r_str = str(run_id).strip()
    if not r_str or r_str.lower() == "nan":
        return False

    t_run = RUNS_DIR / r_str
    t_sand = SANDBOX_DIR / r_str
    folder_valid = t_run.exists() or t_sand.exists()

    regular_json = BACKTESTS_DIR / f"{r_str}.json"
    local_run_json = t_run / "run_state.json"
    sandbox_json = t_sand / "run_state.json"
    json_valid = regular_json.exists() or local_run_json.exists() or sandbox_json.exists()

    return folder_valid and json_valid


def is_valid_basket_run(run_id: str, directive_id: str, basket_id: str) -> bool:
    """Basket-specific validity: accepts EITHER standard run_dir+JSON OR a
    populated basket backtest dir (backtests/<directive_id>_<basket_id>/raw/
    results_basket_per_bar.parquet).

    Basket runs canonically write their research artifacts to backtests/, not
    runs/. The standard is_valid_run is too strict for baskets — it would
    flag rows as orphan whenever the runs/<run_id>/ metadata layer is gone
    even though the actual research data is still on disk in backtests/.
    """
    if is_valid_run(run_id):
        return True
    d_str = str(directive_id).strip() if directive_id else ""
    b_str = str(basket_id).strip() if basket_id else ""
    if not d_str or not b_str or d_str.lower() == "nan" or b_str.lower() == "nan":
        return False
    bt_parquet = BACKTESTS_DIR / f"{d_str}_{b_str}" / "raw" / "results_basket_per_bar.parquet"
    return bt_parquet.exists()


def _ensure_columns(df: pd.DataFrame, columns: tuple[tuple[str, object], ...]) -> pd.DataFrame:
    """Add missing columns with default value (idempotent)."""
    for col, default in columns:
        if col not in df.columns:
            df[col] = default
    return df


# Tags that an explicit human decision flagged for *lineage preservation*
# (the row's history must survive cleanup). Drop mode honors these as
# "do not delete." Mark mode also leaves them alone to avoid overwriting
# a more-specific tag with the generic ARCHIVED_DEPENDENCY_LOST one.
LINEAGE_PROTECTED_TAGS = {"SUPERSEDED", "ARCHIVED_UNRESOLVED"}

# Tag the mark-mode applier writes. Distinct from LINEAGE_PROTECTED_TAGS:
# drop mode WILL remove rows carrying this tag (it's a "should have been
# dropped but the operator chose to preserve the row as a soft tombstone"
# marker, not an audit-immutable record). Documented in the skill preamble.
TAG_ARCHIVED_DEPENDENCY_LOST = "ARCHIVED_DEPENDENCY_LOST"


def _mps_quarantine_tag(row: pd.Series) -> str | None:
    """Return the row's quarantine_status string if set, else None."""
    v = row.get("quarantine_status")
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    return s


def _is_already_quarantined_fsp(row: pd.Series) -> bool:
    v = row.get("quarantined")
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("true", "1", "yes")


def scan_fsp(df: pd.DataFrame) -> list[int]:
    """Return row indices in FSP whose run_id is orphan.

    No tag-based skip — the applier decides what to do with each target.
    """
    targets = []
    for idx, row in df.iterrows():
        rid = str(row.get("run_id", "")).strip()
        if not rid or rid.lower() == "nan":
            continue
        if not is_valid_run(rid):
            targets.append(idx)
    return targets


def scan_mps_sheet(df: pd.DataFrame) -> list[tuple[int, list[str]]]:
    """Return [(row_idx, [orphan_run_ids])] for MPS rows where any constituent is missing.

    No tag-based skip — the applier decides what to do.
    """
    targets = []
    for idx, row in df.iterrows():
        cons_str = str(row.get("constituent_run_ids", "")).strip()
        if not cons_str or cons_str.lower() == "nan":
            continue
        c_list = [c.strip() for c in cons_str.split(",") if c.strip()]
        orphans = [c for c in c_list if not is_valid_run(c)]
        if orphans:
            targets.append((idx, orphans))
    return targets


def scan_mps_missing_portfolio_folder(df: pd.DataFrame) -> list[int]:
    """Return row indices for MPS rows whose portfolio_id has no deployed folder."""
    targets = []
    for idx, row in df.iterrows():
        pid = str(row.get("portfolio_id", "")).strip()
        if not pid or pid.lower() == "nan":
            continue
        if not (STRATEGIES_DIR / pid).is_dir():
            targets.append(idx)
    return targets


def scan_baskets(df: pd.DataFrame) -> list[int]:
    """Return row indices in MPS::Baskets whose disk is gone.

    Uses basket-aware validity: accepts either standard run_dir+JSON OR a
    populated backtest dir (see is_valid_basket_run). A row is flagged
    only when BOTH paths are missing — true orphan with no research data.
    """
    targets = []
    for idx, row in df.iterrows():
        rid = str(row.get("run_id", "")).strip()
        did = str(row.get("directive_id", "")).strip()
        bid = str(row.get("basket_id", "")).strip()
        if not rid or rid.lower() == "nan":
            continue
        if not is_valid_basket_run(rid, did, bid):
            targets.append(idx)
    return targets


def _build_reason(orphans: list[str]) -> str:
    body = QUARANTINE_REASON_PREFIX + ", ".join(orphans)
    if len(body) > _REASON_MAX_CHARS:
        body = body[: _REASON_MAX_CHARS - 1] + "…"
    return body


def apply_fsp_mark(df: pd.DataFrame, targets: list[int]) -> tuple[pd.DataFrame, int]:
    """Mark mode: set `quarantined = True` for orphan rows not already tagged.

    Returns (df, count_actually_tagged).
    """
    df = _ensure_columns(df, (("quarantined", False),))
    n = 0
    for idx in targets:
        if _is_already_quarantined_fsp(df.iloc[idx]):
            continue
        df.at[idx, "quarantined"] = True
        n += 1
    return df, n


def apply_mps_mark(df: pd.DataFrame, constituent_targets: list[tuple[int, list[str]]],
                   folder_targets: list[int]) -> tuple[pd.DataFrame, int]:
    """Mark mode: tag MPS orphan-parent rows with ARCHIVED_DEPENDENCY_LOST.

    Rows already carrying any quarantine_status are left alone (idempotent +
    don't overwrite SUPERSEDED / ARCHIVED_UNRESOLVED with a less-specific tag).
    Constituent-tagging takes precedence over folder-tagging (more-specific
    reason wins) when both apply to the same row.
    """
    df = _ensure_columns(df, (
        ("quarantine_status", None),
        ("quarantine_reason", None),
    ))
    constituent_indexes = {idx for idx, _ in constituent_targets}
    n = 0
    for idx, orphans in constituent_targets:
        if _mps_quarantine_tag(df.iloc[idx]) is not None:
            continue
        df.at[idx, "quarantine_status"] = TAG_ARCHIVED_DEPENDENCY_LOST
        df.at[idx, "quarantine_reason"] = _build_reason(orphans)
        n += 1
    for idx in folder_targets:
        if idx in constituent_indexes:
            continue
        if _mps_quarantine_tag(df.iloc[idx]) is not None:
            continue
        pid = str(df.at[idx, "portfolio_id"])
        df.at[idx, "quarantine_status"] = TAG_ARCHIVED_DEPENDENCY_LOST
        df.at[idx, "quarantine_reason"] = QUARANTINE_REASON_FOLDER + pid
        n += 1
    return df, n


def apply_fsp_drop(df: pd.DataFrame, targets: list[int]) -> tuple[pd.DataFrame, int]:
    """Drop mode: remove orphan rows from FSP.

    FSP `quarantined=True` rows are *not* in LINEAGE_PROTECTED_TAGS — they're
    a soft-flag the operator can re-resolve. Drop still removes them; the
    operator's disk-deletion was the explicit "this is dead" signal.
    """
    if not targets:
        return df, 0
    n = len(targets)
    df = df.drop(index=targets).reset_index(drop=True)
    return df, n


def apply_mps_drop(df: pd.DataFrame, constituent_targets: list[tuple[int, list[str]]],
                   folder_targets: list[int]) -> tuple[pd.DataFrame, int, list[str]]:
    """Drop mode: remove MPS orphan-parent rows.

    Rows tagged with LINEAGE_PROTECTED_TAGS (SUPERSEDED / ARCHIVED_UNRESOLVED)
    are preserved — those tags are explicit audit-trail decisions that drop
    must honor. ARCHIVED_DEPENDENCY_LOST and untagged rows are dropped.

    Returns (df_post_drop, count_dropped, portfolio_ids_dropped). The ids feed
    apply_mps_db_drop — by construction they have already passed the
    LINEAGE_PROTECTED_TAGS filter, so the DB delete does not re-check tags.
    """
    drop_indexes: set[int] = set()
    for idx, _ in constituent_targets:
        tag = _mps_quarantine_tag(df.iloc[idx])
        if tag in LINEAGE_PROTECTED_TAGS:
            continue
        drop_indexes.add(idx)
    for idx in folder_targets:
        tag = _mps_quarantine_tag(df.iloc[idx])
        if tag in LINEAGE_PROTECTED_TAGS:
            continue
        drop_indexes.add(idx)
    if not drop_indexes:
        return df, 0, []
    dropped_ids: list[str] = []
    for idx in drop_indexes:
        pid = str(df.iloc[idx].get("portfolio_id", "")).strip()
        if pid and pid.lower() != "nan":
            dropped_ids.append(pid)
    n = len(drop_indexes)
    df = df.drop(index=list(drop_indexes)).reset_index(drop=True)
    return df, n, dropped_ids


def apply_mps_db_drop(portfolio_ids: list[str], sheet: str) -> int:
    """Drop mode (DB side): hard-DELETE portfolio_sheet rows by (portfolio_id, sheet).

    Mirror of apply_baskets_db_drop for the Portfolios / Single-Asset Composites
    tabs. Without this delete, ledger_db.export_mps() re-emits the dropped row
    from portfolio_sheet (canonical: export reads SELECT * FROM portfolio_sheet)
    on the next export and overwrites the cleaned xlsx — the operator-driven
    cleanup silently undone at the next export trigger. portfolio_sheet is keyed
    (portfolio_id, sheet), so the delete is scoped to BOTH so a same-id row on the
    other tab is not removed. Operator-driven cleanup is the documented append-only
    exception (CLAUDE.md #2).

    Contract: caller (apply_mps_drop) has already filtered LINEAGE_PROTECTED_TAGS,
    so every id here is safe to delete. Returns the count of rows removed.
    """
    if not portfolio_ids:
        return 0
    from tools.ledger_db import _connect
    conn = _connect(LEDGER_DB_PATH)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='portfolio_sheet'"
        ).fetchone():
            return 0  # fresh/tmp DB with no portfolio_sheet table — nothing to delete
        n = 0
        for pid in portfolio_ids:
            cur = conn.execute(
                'DELETE FROM portfolio_sheet WHERE "portfolio_id" = ? AND "sheet" = ?',
                (pid, sheet),
            )
            n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def apply_baskets_drop(df: pd.DataFrame, targets: list[int]) -> tuple[pd.DataFrame, int, list[str]]:
    """Drop mode: remove orphan rows from MPS::Baskets.

    Honors LINEAGE_PROTECTED_TAGS — SUPERSEDED / ARCHIVED_UNRESOLVED rows are
    preserved even when their disk is gone (those tags come from the H3 rehab
    batch and represent explicit audit decisions). ARCHIVED_DEPENDENCY_LOST
    and untagged rows are dropped.

    Returns (df_post_drop, count_dropped, run_ids_dropped). The run_ids list
    is the contract input to apply_baskets_db_drop — by construction these
    have already passed the LINEAGE_PROTECTED_TAGS filter, so the DB delete
    does not re-check tags.
    """
    drop_indexes: list[int] = []
    dropped_run_ids: list[str] = []
    for idx in targets:
        tag = _mps_quarantine_tag(df.iloc[idx])
        if tag in LINEAGE_PROTECTED_TAGS:
            continue
        drop_indexes.append(idx)
        rid = str(df.iloc[idx].get("run_id", "")).strip()
        if rid and rid.lower() != "nan":
            dropped_run_ids.append(rid)
    if not drop_indexes:
        return df, 0, []
    n = len(drop_indexes)
    df = df.drop(index=drop_indexes).reset_index(drop=True)
    return df, n, dropped_run_ids


def apply_baskets_db_drop(orphan_run_ids: list[str]) -> int:
    """Drop mode (DB side): hard-DELETE basket_sheet rows by run_id.

    Mirrors apply_cointegration_drop — operator-driven cleanup is the
    documented exception to append-only (CLAUDE.md #2). Without this delete,
    the next `ledger_db.py --export` re-emits the row from basket_sheet
    because export_mps() rebuilds df_baskets from query_baskets() and
    _merge_audit_columns only carries audit columns onto the DB-sourced
    rows; it does not drop rows the operator removed from the xlsx. The
    cointegration arm doesn't need this distinction (the xlsx tab is a
    lossy projection, not a managed sheet), but baskets does.

    Contract: caller (apply_baskets_drop) has already filtered out
    LINEAGE_PROTECTED_TAGS rows, so every run_id passed here is safe to
    delete. This function does NOT re-check tags. Returns the count of
    rows actually removed.
    """
    if not orphan_run_ids:
        return 0
    from tools.ledger_db import _connect
    conn = _connect(LEDGER_DB_PATH)
    try:
        n = 0
        for rid in orphan_run_ids:
            cur = conn.execute(
                'DELETE FROM basket_sheet WHERE "run_id" = ?', (rid,)
            )
            n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def apply_baskets_mark(df: pd.DataFrame, targets: list[int]) -> tuple[pd.DataFrame, int]:
    """Mark mode: tag orphan Baskets rows ARCHIVED_DEPENDENCY_LOST.

    Idempotent: rows already carrying any quarantine_status are left alone
    (avoids overwriting SUPERSEDED / ARCHIVED_UNRESOLVED with the generic tag).

    Xlsx-only by design. quarantine_status / quarantine_reason are operator
    audit columns absent from the basket_sheet DB schema; ledger_db's
    _merge_audit_columns carries them xlsx → xlsx across export_mps() calls,
    so marking only the xlsx is durable. (Drop mode, by contrast, MUST also
    hard-DELETE from basket_sheet — see apply_baskets_db_drop — because
    otherwise the next export re-emits the row from DB.)
    """
    df = _ensure_columns(df, (
        ("quarantine_status", None),
        ("quarantine_reason", None),
    ))
    n = 0
    for idx in targets:
        if _mps_quarantine_tag(df.iloc[idx]) is not None:
            continue
        rid = str(df.at[idx, "run_id"])
        df.at[idx, "quarantine_status"] = TAG_ARCHIVED_DEPENDENCY_LOST
        reason = QUARANTINE_REASON_BASKETS_RUN + rid
        if len(reason) > _REASON_MAX_CHARS:
            reason = reason[: _REASON_MAX_CHARS - 1] + "…"
        df.at[idx, "quarantine_reason"] = reason
        n += 1
    return df, n


# ---------------------------------------------------------------------------
# Cointegration arm — DB-canonical (the xlsx "Cointegration" tab is a lossy,
# one-way projected view that drops run_id/directive_id, so orphan detection and
# the drop must operate on the cointegration_sheet table, not the tab). This is
# the mirror of scan_baskets / apply_baskets_drop adapted for that asymmetry.
# Cointegration runs live in backtests/<directive_id>_<basket_id>/ like baskets,
# so the same backtests-aware validity (is_valid_basket_run) applies. There is
# no mark path: cointegration_sheet has no quarantine_status column by deliberate
# schema design (tools/portfolio/cointegration_schema.py) — it uses DB-native
# lineage (is_current). The operator's rm -rf of the substrate authorizes the
# row drop (CLAUDE.md invariant #2 append-only exception), same as baskets.
# ---------------------------------------------------------------------------


def scan_cointegration() -> list[str]:
    """Return run_ids of current (is_current=1) cointegration_sheet rows whose
    disk artifacts are gone.

    DB-sourced: mirrors lineage_pruner._cointegration_keep_info — reads run_id +
    directive_id + backtests_path, recovers basket_id from the backtests_path
    basename ("<directive_id>_<basket_id>"), and flags a row only when the
    basket-aware check fails (no runs/<run_id>/+JSON AND no populated
    backtests/<directive_id>_<basket_id>/ dir). Empty on any error / absent table
    so a fresh DB or a read hiccup is a clean no-op, never a false orphan.
    """
    orphans: list[str] = []
    try:
        from tools.ledger_db import _connect
        conn = _connect(LEDGER_DB_PATH)
        try:
            has = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='cointegration_sheet'"
            ).fetchone()
            if not has:
                return orphans
            rows = conn.execute(
                "SELECT run_id, directive_id, backtests_path FROM cointegration_sheet "
                "WHERE is_current = 1"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[INFO] Cointegration scan skipped: {exc}")
        return orphans

    for rid, did, btp in rows:
        rid = str(rid or "").strip()
        if not rid:
            continue
        did = str(did or "").strip()
        folder = Path(str(btp or "")).name
        bid = folder[len(did) + 1:] if folder.startswith(did + "_") else ""
        if not is_valid_basket_run(rid, did, bid):
            orphans.append(rid)
    return orphans


def apply_cointegration_drop(orphans: list[str]) -> int:
    """Drop mode: hard-DELETE orphan rows from cointegration_sheet.

    Unlike the Baskets arm (which drops xlsx rows), this deletes from the DB
    because the Cointegration tab carries no run_id to key on. The deletion is
    the operator-driven cleanup exception to append-only (CLAUDE.md #2). Returns
    the count of rows actually removed.
    """
    if not orphans:
        return 0
    from tools.ledger_db import _connect
    conn = _connect(LEDGER_DB_PATH)
    try:
        n = 0
        for rid in orphans:
            cur = conn.execute(
                'DELETE FROM cointegration_sheet WHERE run_id = ?', (rid,)
            )
            n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def _rebuild_cointegration_view() -> pd.DataFrame:
    """Re-render the lean Cointegration human view from the post-drop DB rows so
    the xlsx tab matches the table. Empty DataFrame on any error (the tab is then
    written empty-but-present, which is the correct state once all coint rows are
    gone). Reuses the canonical view builder so the projection never drifts.
    """
    try:
        from tools.ledger_db import _connect, _read_cointegration_current
        from tools.portfolio.cointegration_view import build_cointegration_view_df
        conn = _connect(LEDGER_DB_PATH)
        try:
            df_cur = _read_cointegration_current(conn)
        finally:
            conn.close()
        return build_cointegration_view_df(df_cur)
    except Exception as exc:
        print(f"[INFO] Cointegration view rebuild skipped: {exc}")
        return pd.DataFrame()


def safe_rewrite_mps(mps_path: Path, modified: dict[str, pd.DataFrame]) -> None:
    """Write back modified sheets while preserving every other sheet.

    Uses the `ExcelWriter(mode="a", if_sheet_exists="replace")` pattern from
    `tools/basket_reset.py:204`. Confirmed by `tools/excel_format/styling.py`
    comments: ExcelWriter(mode="w") truncates the file and would drop any
    sheet not explicitly re-written in the same writer context. mode="a"
    keeps everything; `if_sheet_exists="replace"` lets us overwrite the
    sheets we did modify.
    """
    # Sanity guard: confirm the file has the sub-sheets we expect BEFORE writing.
    # If something else already mutated the workbook into a single-sheet shape,
    # refuse to make it worse. Baskets is included because it's now a managed
    # sheet (2026-05-27 extension).
    pre_sheets = set(pd.ExcelFile(mps_path).sheet_names)
    expected = set(MPS_TAGGED_SHEETS) | {MPS_BASKETS_SHEET}
    missing = expected - pre_sheets
    if missing:
        print(f"[FAIL] MPS missing expected sheets {sorted(missing)}; refusing to write back.")
        print(f"       Found sheets: {sorted(pre_sheets)}")
        sys.exit(1)

    with pd.ExcelWriter(mps_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        for sheet_name, df in modified.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    # Post-write invariant: every pre-existing sheet must still be present.
    post_sheets = set(pd.ExcelFile(mps_path).sheet_names)
    lost = pre_sheets - post_sheets
    if lost:
        print(f"[FAIL] safe_rewrite_mps lost sheets {sorted(lost)} — this is the bug we set out to fix.")
        sys.exit(1)


def safe_rewrite_fsp(fsp_path: Path, df: pd.DataFrame) -> None:
    """Write FSP back preserving Notes and any other auxiliary sheets."""
    pre_sheets = pd.ExcelFile(fsp_path).sheet_names
    # First sheet is the data sheet. We re-write it; everything else preserved.
    data_sheet = pre_sheets[0]
    with pd.ExcelWriter(fsp_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name=data_sheet, index=False)

    post_sheets = set(pd.ExcelFile(fsp_path).sheet_names)
    lost = set(pre_sheets) - post_sheets
    if lost:
        print(f"[FAIL] safe_rewrite_fsp lost sheets {sorted(lost)}.")
        sys.exit(1)


def _reformat(path: Path, profile: str) -> None:
    _formatter = PROJECT_ROOT / "tools" / "format_excel_artifact.py"
    try:
        subprocess.run(
            [sys.executable, str(_formatter), "--file", str(path), "--profile", profile],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[WARN] Failed to re-format {path.name}: {exc.stderr.decode(errors='replace')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile FSP + MPS ledgers against disk artifacts.",
    )
    parser.add_argument("--action", choices=["drop", "mark"], default="drop",
                        help="drop: remove rows whose disk artifacts are gone "
                             "(operator-driven cleanup; default). "
                             "mark: tag rows ARCHIVED_DEPENDENCY_LOST (lineage-"
                             "preserving alternative).")
    parser.add_argument("--execute", action="store_true",
                        help="Apply changes. Default is dry-run.")
    args = parser.parse_args()

    action = args.action
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"--- repair_integrity (action={action.upper()}, {mode}) ---")

    if not MASTER_SHEET_PATH.exists():
        print(f"[FAIL] Missing {MASTER_SHEET_PATH}")
        return 1
    if not FILTERED_SHEET_PATH.exists():
        print(f"[FAIL] Missing {FILTERED_SHEET_PATH}")
        return 1

    # --- Scan (action-agnostic) ---
    fsp_df = pd.read_excel(FILTERED_SHEET_PATH)
    fsp_targets = scan_fsp(fsp_df)

    mps_sheets: dict[str, pd.DataFrame] = {}
    mps_constituent_targets: dict[str, list[tuple[int, list[str]]]] = {}
    mps_folder_targets: dict[str, list[int]] = {}
    for sheet in MPS_TAGGED_SHEETS:
        try:
            df = pd.read_excel(MASTER_SHEET_PATH, sheet_name=sheet)
        except (ValueError, KeyError):
            print(f"[INFO] MPS sheet {sheet!r} not present; skipping.")
            continue
        mps_sheets[sheet] = df
        mps_constituent_targets[sheet] = scan_mps_sheet(df)
        mps_folder_targets[sheet] = scan_mps_missing_portfolio_folder(df)

    # Baskets — different structure (single run_id per row, no constituents).
    try:
        baskets_df: pd.DataFrame | None = pd.read_excel(MASTER_SHEET_PATH, sheet_name=MPS_BASKETS_SHEET)
        baskets_targets = scan_baskets(baskets_df)
    except (ValueError, KeyError):
        print(f"[INFO] MPS sheet {MPS_BASKETS_SHEET!r} not present; skipping.")
        baskets_df = None
        baskets_targets = []

    # Cointegration — DB-canonical (the tab is a lossy projected view, so this
    # reads the cointegration_sheet table directly, not the xlsx).
    coint_targets = scan_cointegration()

    # --- Report ---
    print()
    print(f"FSP orphan rows: {len(fsp_targets)}")
    for sheet, targets in mps_constituent_targets.items():
        print(f"MPS::{sheet} rows w/ orphan constituents: {len(targets)}")
        for idx, orphans in targets[:5]:
            pid = str(mps_sheets[sheet].at[idx, "portfolio_id"])
            print(f"  -> {pid}  orphans={orphans}")
        if len(targets) > 5:
            print(f"  ... and {len(targets) - 5} more.")
    for sheet, targets in mps_folder_targets.items():
        print(f"MPS::{sheet} rows w/ missing deployed folder: {len(targets)}")
        for idx in targets[:5]:
            pid = str(mps_sheets[sheet].at[idx, "portfolio_id"])
            print(f"  -> {pid}")
        if len(targets) > 5:
            print(f"  ... and {len(targets) - 5} more.")
    if baskets_df is not None:
        print(f"MPS::{MPS_BASKETS_SHEET} rows w/ orphan run_id: {len(baskets_targets)}")
        for idx in baskets_targets[:5]:
            rid = str(baskets_df.at[idx, "run_id"])
            did = str(baskets_df.at[idx, "directive_id"])
            print(f"  -> run_id={rid[:12]}...  {did}")
        if len(baskets_targets) > 5:
            print(f"  ... and {len(baskets_targets) - 5} more.")

    print(f"MPS::{MPS_COINTEGRATION_SHEET} rows w/ orphan run_id: {len(coint_targets)}"
          + ("" if action == "drop" else "  (drop-only; mark not supported)"))
    for rid in coint_targets[:5]:
        print(f"  -> run_id={rid[:12]}...")
    if len(coint_targets) > 5:
        print(f"  ... and {len(coint_targets) - 5} more.")
    if coint_targets and action == "mark":
        print(f"[INFO] {MPS_COINTEGRATION_SHEET}: mark mode is a no-op here — "
              f"cointegration_sheet has no quarantine_status column (DB-native "
              f"lineage). Use --action drop to remove these orphan rows.")

    total = (
        len(fsp_targets)
        + sum(len(t) for t in mps_constituent_targets.values())
        + sum(len(t) for t in mps_folder_targets.values())
        + len(baskets_targets)
        # Coint orphans are actionable only under drop (no mark path), so they
        # count toward the "would change" total only then.
        + (len(coint_targets) if action == "drop" else 0)
    )
    if total == 0:
        print("\n[INFO] No integrity issues found. Spreadsheets unchanged.")
        return 0

    if not args.execute:
        verb = "dropped" if action == "drop" else "tagged"
        print(f"\n[DRY-RUN] up to {total} row(s) WOULD be {verb} (action={action}). "
              f"Re-run with --execute to apply.")
        return 0

    # --- Apply ---
    _check_file_writable(FILTERED_SHEET_PATH)
    _check_file_writable(MASTER_SHEET_PATH)

    fsp_applied = 0
    if fsp_targets:
        if action == "drop":
            fsp_df, fsp_applied = apply_fsp_drop(fsp_df, fsp_targets)
        else:
            fsp_df, fsp_applied = apply_fsp_mark(fsp_df, fsp_targets)
        if fsp_applied:
            safe_rewrite_fsp(FILTERED_SHEET_PATH, fsp_df)
            _reformat(FILTERED_SHEET_PATH, "strategy")
            verb = "Dropped" if action == "drop" else "Tagged"
            print(f"-> {verb} {fsp_applied} FSP row(s).")

    mps_to_write = {}
    mps_applied: dict[str, int] = {}
    for sheet in MPS_TAGGED_SHEETS:
        if sheet not in mps_sheets:
            continue
        c_targets = mps_constituent_targets.get(sheet, [])
        f_targets = mps_folder_targets.get(sheet, [])
        if not c_targets and not f_targets:
            continue
        if action == "drop":
            # Dual-write: xlsx rewrite + portfolio_sheet DB hard-DELETE. Without the
            # DB delete, export_mps() re-emits the dropped row from portfolio_sheet
            # (canonical) on the next export and overwrites the cleaned xlsx — the
            # same durability gap fixed for baskets below. portfolio_sheet.sheet
            # equals the MPS_TAGGED_SHEETS tab name, so the delete is sheet-scoped.
            mps_sheets[sheet], n, dropped_pids = apply_mps_drop(mps_sheets[sheet], c_targets, f_targets)
            db_dropped = apply_mps_db_drop(dropped_pids, sheet)
            if db_dropped:
                print(f"-> Deleted {db_dropped} portfolio_sheet DB row(s) from '{sheet}'.")
        else:
            mps_sheets[sheet], n = apply_mps_mark(mps_sheets[sheet], c_targets, f_targets)
        mps_applied[sheet] = n
        if n:
            mps_to_write[sheet] = mps_sheets[sheet]

    # Baskets apply (single run_id semantics, separate code path).
    # Drop is dual-write: xlsx rewrite + DB hard-DELETE. Without the DB
    # delete, ledger_db.export_mps() would re-emit the dropped row from
    # basket_sheet (canonical) on the next export and overwrite the
    # cleaned xlsx. See apply_baskets_db_drop docstring for the rationale.
    if baskets_df is not None and baskets_targets:
        if action == "drop":
            baskets_df, n, dropped_basket_run_ids = apply_baskets_drop(baskets_df, baskets_targets)
            db_dropped = apply_baskets_db_drop(dropped_basket_run_ids)
            if db_dropped:
                print(f"-> Deleted {db_dropped} basket_sheet DB row(s).")
        else:
            baskets_df, n = apply_baskets_mark(baskets_df, baskets_targets)
        mps_applied[MPS_BASKETS_SHEET] = n
        if n:
            mps_to_write[MPS_BASKETS_SHEET] = baskets_df

    # Cointegration apply — DB delete (drop only; mark already reported as a
    # no-op above). The tab is re-rendered from the post-drop DB and queued for
    # the multi-sheet-safe writer alongside any other modified sheets.
    if coint_targets and action == "drop":
        n = apply_cointegration_drop(coint_targets)
        mps_applied[MPS_COINTEGRATION_SHEET] = n
        if n:
            mps_to_write[MPS_COINTEGRATION_SHEET] = _rebuild_cointegration_view()

    if mps_to_write:
        safe_rewrite_mps(MASTER_SHEET_PATH, mps_to_write)
        _reformat(MASTER_SHEET_PATH, "portfolio")
        for sheet, n in mps_applied.items():
            if n:
                verb = "Dropped" if action == "drop" else "Tagged"
                print(f"-> {verb} {n} {sheet!r} row(s).")

    if action == "drop":
        print("\n[SUCCESS] Orphan rows dropped. Append-only invariant honored — "
              "operator-driven cleanup is the documented exception "
              "(see .claude/skills/pipeline-state-cleanup Critical Authority Note).")
    else:
        print("\n[SUCCESS] Orphan rows tagged ARCHIVED_DEPENDENCY_LOST. "
              "Lineage preserved; rows hidden from active views by the formatter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
