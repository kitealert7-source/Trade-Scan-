"""
Append entries to RESEARCH_MEMORY.md in append-only format.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = PROJECT_ROOT / "RESEARCH_MEMORY.md"

INITIAL_HEADER = """# RESEARCH MEMORY

This file stores important findings from experiments.

Rules:
- Append only
- Never delete prior entries
- Each entry must include date, finding, evidence, conclusion, implication
"""


def ensure_memory_file(path: Path) -> None:
    if path.exists():
        return
    path.write_text(INITIAL_HEADER.rstrip() + "\n", encoding="utf-8")


def build_entry(finding: str, evidence: str, conclusion: str, implication: str) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"\n{date_str}\n"
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
    parser.add_argument("--finding", required=True, help="Finding summary")
    parser.add_argument("--evidence", required=True, help="Evidence supporting the finding")
    parser.add_argument("--conclusion", required=True, help="Conclusion based on finding/evidence")
    parser.add_argument("--implication", required=True, help="Actionable implication to apply in future research")
    args = parser.parse_args()

    ensure_memory_file(MEMORY_PATH)
    entry = build_entry(
        finding=args.finding.strip(),
        evidence=args.evidence.strip(),
        conclusion=args.conclusion.strip(),
        implication=args.implication.strip(),
    )
    append_entry(MEMORY_PATH, entry)
    print(f"[DONE] Appended research entry to {MEMORY_PATH}")


if __name__ == "__main__":
    main()
