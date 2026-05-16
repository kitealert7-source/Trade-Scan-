"""Harvest Robustness Harness — CLI entry.

Examples:

    # Run all sections defined in sections.yaml
    python tools/harvest_robustness/cli.py

    # Run only specific sections by id
    python tools/harvest_robustness/cli.py --sections intrabar_floating,realized_metrics

    # Run only sections tagged with 'capital' or 'dd'
    python tools/harvest_robustness/cli.py --tags capital,dd

    # Custom label + output dir
    python tools/harvest_robustness/cli.py --label E1_champion_review \\
        --output outputs/harvest_robustness/E1_review/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.harvest_robustness.harness import run_harness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harvest Robustness Harness — orchestrates basket analysis scripts into one report.",
    )
    parser.add_argument(
        "--sections",
        type=str,
        default=None,
        help="Comma-separated list of section IDs to run (default: all). See sections.yaml.",
    )
    parser.add_argument(
        "--tags",
        type=str,
        default=None,
        help="Comma-separated list of tags to filter sections by (any-match).",
    )
    parser.add_argument(
        "--label",
        type=str,
        default="default",
        help="Label appended to report filename (e.g. 'E1_review').",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory for report (default: outputs/harvest_robustness/).",
    )
    args = parser.parse_args()

    sections_subset = args.sections.split(",") if args.sections else None
    tags_subset = args.tags.split(",") if args.tags else None

    report = run_harness(
        sections_subset=sections_subset,
        tags_subset=tags_subset,
        output_dir=args.output,
        label=args.label,
    )
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
