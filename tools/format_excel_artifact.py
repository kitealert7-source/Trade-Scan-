"""
format_excel_artifact.py — Unified Excel Formatter & Rounding Governance (CLI shim)

Applies strict styling and number formatting to Excel artifacts.
Logic is presentation-layer only. No data mutation.

Implementation lives in the tools.excel_format package:
  - tools/excel_format/rules.py     — styling constants + column orders
  - tools/excel_format/styling.py   — apply_formatting (data sheets)
  - tools/excel_format/notes.py     — add_notes_sheet_to_ledger (Notes generation)

This file is the CLI entry point only.

Usage:
    # Canonical (full formatting; portfolio profile auto-regenerates Notes):
    python tools/format_excel_artifact.py --file <path> --profile <strategy|portfolio>

    # Maintenance ONLY — regenerate just the Notes sheet. Requires the explicit
    # --allow-notes-only confirmation; without it the run is REFUSED (exit 2) so a
    # partially formatted workbook can never be produced silently:
    python tools/format_excel_artifact.py --file <path> --notes-type <master_filter|candidates|portfolio> --allow-notes-only
"""

import argparse
import sys
from pathlib import Path

# When invoked as `python tools/format_excel_artifact.py`, sys.path[0] is the
# `tools/` directory — so `from excel_format import ...` resolves the package
# sibling. When invoked as a module (`python -m tools.format_excel_artifact`)
# or imported under its package path, `tools/` is not on sys.path; add the
# parent of this file to sys.path and import via the full package path instead.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
# Also expose the project ROOT so `from tools.pipeline_utils import ...` inside
# the excel_format package (e.g. styling's resilient save) resolves when this
# shim is invoked as a standalone script (sys.path[0] would be tools/).
_PROJECT_ROOT = _TOOLS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from excel_format import add_notes_sheet_to_ledger, apply_formatting  # noqa: E402


_NOTES_ONLY_REFUSAL = """\
WARNING:
--notes-type only regenerates the Notes sheet.
Workbook formatting (sorting, ranking, styling, hyperlinks, freeze panes)
has NOT been applied.

For canonical formatting use:
    --profile strategy
or
    --profile portfolio

To intentionally regenerate ONLY the Notes sheet (maintenance), re-run with:
    --allow-notes-only
"""

_NOTES_ONLY_COMPLETION_WARNING = """\
NOTES regenerated successfully.

WARNING:
Workbook formatting was skipped (--allow-notes-only).
Workbook is NOT in canonical formatted state.
"""


def main():
    parser = argparse.ArgumentParser(description="Unified Excel Formatter")
    parser.add_argument("--file", required=True, help="Path to Excel file")
    parser.add_argument("--profile", choices=["strategy", "portfolio"], default=None, help="Formatting profile")
    parser.add_argument("--notes-type", choices=["master_filter", "candidates", "portfolio"],
                        default=None, help="If set, append a Notes sheet of this type")
    parser.add_argument("--allow-notes-only", action="store_true",
                        help="Explicitly confirm a notes-ONLY run (maintenance). Without this "
                             "flag, --notes-type alone is refused so a partially formatted "
                             "workbook can never be produced silently (guard added 2026-07-02).")

    args = parser.parse_args()

    if args.profile:
        apply_formatting(args.file, args.profile)
        # Auto-generate Notes for portfolio profile so it never regresses.
        if args.profile == "portfolio":
            add_notes_sheet_to_ledger(args.file, "portfolio")
        # Both flags given: honor --notes-type too (pre-guard behavior silently
        # IGNORED --profile when both were passed — strictly worse than either).
        if args.notes_type and args.notes_type != ("portfolio" if args.profile == "portfolio" else None):
            add_notes_sheet_to_ledger(args.file, args.notes_type)
    elif args.notes_type:
        # Guard: a bare --notes-type run is syntactically valid but produces a
        # partially formatted workbook that LOOKS done. Refuse unless the caller
        # explicitly declares notes-only intent (recurring silent-failure mode,
        # root-caused 2026-07-02: agents reached for --notes-type after bare
        # invocation errored, leaving MPS unstyled).
        if not args.allow_notes_only:
            sys.stderr.write(_NOTES_ONLY_REFUSAL)
            sys.exit(2)
        add_notes_sheet_to_ledger(args.file, args.notes_type)
        sys.stdout.write(_NOTES_ONLY_COMPLETION_WARNING)
    else:
        parser.error("--profile is required when --notes-type is not specified")


if __name__ == "__main__":
    main()
