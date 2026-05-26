"""repair_integrity.py — tag ledger rows whose lineage is missing on disk.

Reconciles `Filtered_Strategies_Passed.xlsx` and `Master_Portfolio_Sheet.xlsx`
against the physical artifact set under `TradeScan_State/{runs,sandbox,backtests}`.
Rows referencing run_ids that no longer exist on disk are *tagged*, not deleted —
honoring the append-only ledger invariant (CLAUDE.md #2).

Tagging conventions (same as the H3 rehab batch, 2026-05-25):
  * FSP rows: boolean `quarantined = True`
  * MPS Portfolios + Single-Asset Composites rows: string `quarantine_status =
    "ARCHIVED_DEPENDENCY_LOST"` + diagnostic `quarantine_reason`

Writes preserve every sheet in MPS (Portfolios + Single-Asset Composites +
Baskets + Notes) via the `ExcelWriter(mode="a", if_sheet_exists="replace")`
pattern. The pre-2026-05-26 implementation read MPS as a single sheet and
wrote it back single-sheet — which deleted SAC + Baskets + Notes on every
run. Anyone who ran the old tool against a populated workbook would have
silently lost the entire H3 rehabilitation history.

CLI:
    python tools/state_lifecycle/repair_integrity.py             # dry-run (default)
    python tools/state_lifecycle/repair_integrity.py --execute   # actually write

The `--action drop` argument has been removed. Row deletion violates the
append-only invariant and is no longer supported. If you need the legacy
behavior, pull from git history — the recovery cost was the original sin
this rewrite addresses.

Companion to:
    - lineage_pruner.py — must run AFTER tagging; honors quarantine_status
      to skip these rows in the integrity check.
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

# Sheets read + rewritten in MPS. Baskets is excluded — H3 rehab governs it
# separately and its rows already use quarantine_status.
MPS_TAGGED_SHEETS = ("Portfolios", "Single-Asset Composites")

# Reason text cap — quarantine_reason is a single-line audit field, not a log.
_REASON_MAX_CHARS = 200

QUARANTINE_REASON_PREFIX = "constituent_run_ids reference orphan run(s) on disk: "


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


def _ensure_columns(df: pd.DataFrame, columns: tuple[tuple[str, object], ...]) -> pd.DataFrame:
    """Add missing columns with default value (idempotent)."""
    for col, default in columns:
        if col not in df.columns:
            df[col] = default
    return df


def _is_already_quarantined_mps(row: pd.Series) -> bool:
    v = row.get("quarantine_status")
    if v is None:
        return False
    s = str(v).strip()
    return bool(s) and s.lower() not in ("nan", "none")


def _is_already_quarantined_fsp(row: pd.Series) -> bool:
    v = row.get("quarantined")
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("true", "1", "yes")


def scan_fsp(df: pd.DataFrame) -> list[int]:
    """Return row indices in FSP whose run_id is orphan AND not already quarantined."""
    targets = []
    for idx, row in df.iterrows():
        if _is_already_quarantined_fsp(row):
            continue
        rid = str(row.get("run_id", "")).strip()
        if not rid or rid.lower() == "nan":
            continue
        if not is_valid_run(rid):
            targets.append(idx)
    return targets


def scan_mps_sheet(df: pd.DataFrame) -> list[tuple[int, list[str]]]:
    """Return [(row_idx, [orphan_run_ids])] for MPS rows where any constituent is missing."""
    targets = []
    for idx, row in df.iterrows():
        if _is_already_quarantined_mps(row):
            continue
        cons_str = str(row.get("constituent_run_ids", "")).strip()
        if not cons_str or cons_str.lower() == "nan":
            continue
        c_list = [c.strip() for c in cons_str.split(",") if c.strip()]
        orphans = [c for c in c_list if not is_valid_run(c)]
        if orphans:
            targets.append((idx, orphans))
    return targets


def _build_reason(orphans: list[str]) -> str:
    body = QUARANTINE_REASON_PREFIX + ", ".join(orphans)
    if len(body) > _REASON_MAX_CHARS:
        body = body[: _REASON_MAX_CHARS - 1] + "…"
    return body


def apply_fsp_tags(df: pd.DataFrame, targets: list[int]) -> pd.DataFrame:
    """Set `quarantined = True` for the indicated rows. Column added if missing."""
    df = _ensure_columns(df, (("quarantined", False),))
    for idx in targets:
        df.at[idx, "quarantined"] = True
    return df


def apply_mps_tags(df: pd.DataFrame, targets: list[tuple[int, list[str]]]) -> pd.DataFrame:
    """Set quarantine_status + quarantine_reason for orphan-parent rows."""
    df = _ensure_columns(df, (
        ("quarantine_status", None),
        ("quarantine_reason", None),
    ))
    for idx, orphans in targets:
        df.at[idx, "quarantine_status"] = "ARCHIVED_DEPENDENCY_LOST"
        df.at[idx, "quarantine_reason"] = _build_reason(orphans)
    return df


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
    # refuse to make it worse.
    pre_sheets = set(pd.ExcelFile(mps_path).sheet_names)
    expected = set(MPS_TAGGED_SHEETS)
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
        description="Tag ledger rows whose lineage is missing on disk (append-only).",
    )
    parser.add_argument("--execute", action="store_true",
                        help="Apply changes. Default is dry-run.")
    # Refuse the legacy --action argument loudly. If we silently dropped it,
    # operators with stale habits would think their drops landed.
    parser.add_argument("--action", default=None,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.action is not None:
        print("[FAIL] --action removed in the 2026-05-26 rewrite.")
        print("       Row deletion violates the append-only invariant (CLAUDE.md #2).")
        print("       This tool now ONLY tags rows. Re-run without --action.")
        return 2

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"--- repair_integrity ({mode}) ---")

    if not MASTER_SHEET_PATH.exists():
        print(f"[FAIL] Missing {MASTER_SHEET_PATH}")
        return 1
    if not FILTERED_SHEET_PATH.exists():
        print(f"[FAIL] Missing {FILTERED_SHEET_PATH}")
        return 1

    # --- Scan ---
    fsp_df = pd.read_excel(FILTERED_SHEET_PATH)
    fsp_targets = scan_fsp(fsp_df)

    mps_sheets: dict[str, pd.DataFrame] = {}
    mps_targets: dict[str, list[tuple[int, list[str]]]] = {}
    for sheet in MPS_TAGGED_SHEETS:
        try:
            df = pd.read_excel(MASTER_SHEET_PATH, sheet_name=sheet)
        except (ValueError, KeyError):
            print(f"[INFO] MPS sheet {sheet!r} not present; skipping.")
            continue
        mps_sheets[sheet] = df
        mps_targets[sheet] = scan_mps_sheet(df)

    # --- Report ---
    print()
    print(f"FSP rows to tag (quarantined=True): {len(fsp_targets)}")
    for sheet, targets in mps_targets.items():
        print(f"MPS::{sheet} rows to tag (ARCHIVED_DEPENDENCY_LOST): {len(targets)}")
        for idx, orphans in targets[:10]:
            pid = str(mps_sheets[sheet].at[idx, "portfolio_id"])
            print(f"  -> {pid}  orphans={orphans}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10} more.")

    total = len(fsp_targets) + sum(len(t) for t in mps_targets.values())
    if total == 0:
        print("\n[INFO] No integrity issues found. Spreadsheets unchanged.")
        return 0

    if not args.execute:
        print(f"\n[DRY-RUN] {total} row(s) WOULD be tagged. Re-run with --execute to apply.")
        return 0

    # --- Apply ---
    _check_file_writable(FILTERED_SHEET_PATH)
    _check_file_writable(MASTER_SHEET_PATH)

    if fsp_targets:
        fsp_df = apply_fsp_tags(fsp_df, fsp_targets)
        safe_rewrite_fsp(FILTERED_SHEET_PATH, fsp_df)
        _reformat(FILTERED_SHEET_PATH, "strategy")
        print(f"-> Tagged {len(fsp_targets)} FSP row(s) as quarantined.")

    mps_to_write = {}
    for sheet, targets in mps_targets.items():
        if not targets:
            continue
        mps_sheets[sheet] = apply_mps_tags(mps_sheets[sheet], targets)
        mps_to_write[sheet] = mps_sheets[sheet]

    if mps_to_write:
        safe_rewrite_mps(MASTER_SHEET_PATH, mps_to_write)
        _reformat(MASTER_SHEET_PATH, "portfolio")
        for sheet, targets in mps_targets.items():
            if targets:
                print(f"-> Tagged {len(targets)} {sheet!r} row(s) as ARCHIVED_DEPENDENCY_LOST.")

    print("\n[SUCCESS] Referential integrity tagging complete. Lineage preserved (append-only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
