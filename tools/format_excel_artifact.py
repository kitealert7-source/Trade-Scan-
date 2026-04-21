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
    python tools/format_excel_artifact.py --file <path> --profile <strategy|portfolio>
    python tools/format_excel_artifact.py --file <path> --notes-type <master_filter|candidates|portfolio>
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

from excel_format import add_notes_sheet_to_ledger, apply_formatting  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Unified Excel Formatter")
    parser.add_argument("--file", required=True, help="Path to Excel file")
    parser.add_argument("--profile", choices=["strategy", "portfolio"], default=None, help="Formatting profile")
    parser.add_argument("--notes-type", choices=["master_filter", "candidates", "portfolio"],
                        default=None, help="If set, append a Notes sheet of this type (skips formatting)")

    args = parser.parse_args()

    if args.notes_type:
        add_notes_sheet_to_ledger(args.file, args.notes_type)
    elif args.profile:
        apply_formatting(args.file, args.profile)
        # Auto-generate Notes for portfolio profile so it never regresses.
        if args.profile == "portfolio":
            add_notes_sheet_to_ledger(args.file, "portfolio")
    else:
        parser.error("--profile is required when --notes-type is not specified")


if __name__ == "__main__":
    main()
