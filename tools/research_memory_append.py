"""
Append entries to RESEARCH_MEMORY.md in append-only format.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = PROJECT_ROOT / "RESEARCH_MEMORY.md"

INITIAL_HEADER = """# RESEARCH MEMORY

This file stores important findings from experiments.

Rules:
- Append only
- Never delete prior entries
- See NEW ENTRY CONTRACT block at the end of RESEARCH_MEMORY.md for field rules.
"""


def ensure_memory_file(path: Path) -> None:
    if path.exists():
        return
    path.write_text(INITIAL_HEADER.rstrip() + "\n", encoding="utf-8")


def build_entry(
    tags: list[str],
    strategy: str,
    run_ids: str,
    finding: str,
    evidence: str,
    conclusion: str,
    implication: str,
) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    tags_block = "\n".join(tags)
    strategy_block = f"Strategy: {strategy}\n" if strategy else ""
    
    return (
        f"{date_str}\n"
        "Tags:\n"
        f"{tags_block}\n\n"
        f"{strategy_block}"
        f"Run IDs: {run_ids}\n\n"
        "Finding:\n"
        f"{finding}\n\n"
        "Evidence:\n"
        f"{evidence}\n\n"
        "Conclusion:\n"
        f"{conclusion}\n\n"
        "Implication:\n"
        f"{implication}\n"
    )


def append_entry(path: Path, entry: str) -> None:
    existing = path.read_text(encoding="utf-8")
    separator = "" if existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(separator + entry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Append an entry to RESEARCH_MEMORY.md.")
    parser.add_argument("--tags", required=True, help="Comma-separated list of tags (min 3)")
    parser.add_argument("--strategy", required=False, default="", help="Optional strategy ID")
    parser.add_argument("--run-ids", required=True, help="MANDATORY: Run IDs as reference pointers")
    parser.add_argument("--finding", required=True, help="Finding summary")
    parser.add_argument("--evidence", required=True, help="Evidence supporting the finding (max 2 lines, must contain numeric metric)")
    parser.add_argument("--conclusion", required=True, help="Conclusion based on finding/evidence")
    parser.add_argument("--implication", required=True, help="Actionable implication to apply in future research")
    args = parser.parse_args()

    # Validation: tags
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if len(tags) < 3:
        print("[REJECTED] Validation failed: At least 3 tags are required.", file=sys.stderr)
        sys.exit(1)

    # Validation: Run IDs
    raw_run_ids = [rid.strip() for rid in args.run_ids.split(",") if rid.strip()]
    if not raw_run_ids:
        print("[REJECTED] Validation failed: Run IDs cannot be empty.", file=sys.stderr)
        sys.exit(1)
    run_ids_formatted = ", ".join(raw_run_ids)

    # Validation: Evidence
    evidence_str = args.evidence.strip()
    evidence_lines = [l for l in evidence_str.splitlines() if l.strip()]
    if len(evidence_lines) > 2:
        print(f"[REJECTED] Validation failed: Evidence exceeds 2 lines (found {len(evidence_lines)}).", file=sys.stderr)
        sys.exit(1)
    if not any(char.isdigit() for char in evidence_str):
        print("[REJECTED] Validation failed: Evidence must contain at least one numeric metric or delta.", file=sys.stderr)
        sys.exit(1)

    ensure_memory_file(MEMORY_PATH)
    entry = build_entry(
        tags=tags,
        strategy=args.strategy.strip(),
        run_ids=run_ids_formatted,
        finding=args.finding.strip(),
        evidence=evidence_str,
        conclusion=args.conclusion.strip(),
        implication=args.implication.strip(),
    )
    append_entry(MEMORY_PATH, entry)
    print(f"[DONE] Appended research entry to {MEMORY_PATH}")


if __name__ == "__main__":
    main()
