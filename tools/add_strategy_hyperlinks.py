"""
add_strategy_hyperlinks.py — Add clickable hyperlinks to Column C (strategy)
in Filtered_Strategies_Passed.xlsx.

Links point to: ../strategies/{base_strategy_id}/portfolio_evaluation/
Uses relative paths so the links work regardless of machine or user directory.

Requires: base_strategy_id column (added by filter_strategies.py).

Idempotent: re-running overwrites stale links, skips matching links.
Preserves all existing formatting (headers, widths, number formats).

Usage:
    python tools/add_strategy_hyperlinks.py
    python tools/add_strategy_hyperlinks.py --dry-run
"""

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import CANDIDATE_FILTER_PATH

# Relative path from candidates/ to strategies/ (both under TradeScan_State)
_REL_PREFIX = "../strategies"


def _find_columns(ws) -> tuple:
    """Find column indices for 'strategy' and 'base_strategy_id' from header row."""
    strategy_col = None
    base_id_col = None
    for col_idx, cell in enumerate(ws[1], start=1):
        val = str(cell.value or "").strip()
        if val == "strategy":
            strategy_col = col_idx
        elif val == "base_strategy_id":
            base_id_col = col_idx
    return strategy_col, base_id_col


def add_hyperlinks(dry_run: bool = False) -> dict:
    """Add hyperlinks to strategy column. Returns summary dict."""
    if not CANDIDATE_FILTER_PATH.exists():
        print(f"[ABORT] Candidates file not found: {CANDIDATE_FILTER_PATH}")
        sys.exit(1)

    wb = load_workbook(CANDIDATE_FILTER_PATH)
    ws = wb.active

    strategy_col, base_id_col = _find_columns(ws)
    if strategy_col is None:
        print("[ABORT] 'strategy' column not found in header row.")
        sys.exit(1)
    if base_id_col is None:
        print("[ABORT] 'base_strategy_id' column not found in header row.")
        print("  Run filter_strategies.py first to generate this column.")
        sys.exit(1)

    # Hyperlink font — blue underline, preserves size from formatter
    link_font = Font(color="0563C1", underline="single")

    total = 0
    linked = 0
    skipped_missing = 0
    skipped_match = 0
    missing_targets = []

    for row_idx in range(2, ws.max_row + 1):
        total += 1
        strategy_cell = ws.cell(row=row_idx, column=strategy_col)
        base_id_cell = ws.cell(row=row_idx, column=base_id_col)

        base_id = str(base_id_cell.value or "").strip()
        if not base_id or base_id == "None":
            skipped_missing += 1
            continue

        target = f"{_REL_PREFIX}/{base_id}/portfolio_evaluation/"

        # Idempotent: skip if hyperlink already matches
        if strategy_cell.hyperlink and strategy_cell.hyperlink.target == target:
            skipped_match += 1
            continue

        if not dry_run:
            strategy_cell.hyperlink = target
            strategy_cell.font = link_font

        linked += 1

        # Check if target file actually exists (informational, non-blocking)
        abs_target = CANDIDATE_FILTER_PATH.parent / target
        if not abs_target.exists():
            missing_targets.append(base_id)

    if not dry_run and linked > 0:
        wb.save(CANDIDATE_FILTER_PATH)

    # Summary
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Processed:               {total} rows")
    print(f"{prefix}Linked:                  {linked} rows")
    print(f"{prefix}Skipped (matching link):  {skipped_match} rows")
    print(f"{prefix}Skipped (missing base_id):{skipped_missing} rows")
    if missing_targets:
        print(f"{prefix}Missing targets:         {len(missing_targets)} file(s)")
        for mt in missing_targets[:10]:
            print(f"  Missing target: {mt}")
        if len(missing_targets) > 10:
            print(f"  ... and {len(missing_targets) - 10} more")

    return {
        "total": total,
        "linked": linked,
        "skipped_match": skipped_match,
        "skipped_missing": skipped_missing,
        "missing_targets": missing_targets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add clickable hyperlinks to strategy column in candidates ledger.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without modifying the file")
    args = parser.parse_args()
    add_hyperlinks(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
