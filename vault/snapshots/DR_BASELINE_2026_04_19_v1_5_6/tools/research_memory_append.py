"""
Append entries to RESEARCH_MEMORY.md in append-only format.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = PROJECT_ROOT / "RESEARCH_MEMORY.md"

_REQUIRED_FIELDS = ("tags", "run_ids", "finding", "evidence", "conclusion", "implication")


def _load_entry_file(path: Path) -> dict:
    """Load a research entry from YAML or JSON.

    Detection: suffix `.json` -> json; everything else -> YAML. Returns a dict
    with the six/seven canonical fields. Normalizes `tags` and `run_ids` to
    comma-separated strings to match the CLI contract.
    """
    if not path.exists():
        print(f"[REJECTED] --from-file not found: {path}", file=sys.stderr)
        sys.exit(1)

    raw = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            import yaml  # lazy import — already a project-wide dep
            data = yaml.safe_load(raw)
    except Exception as e:
        print(f"[REJECTED] Failed to parse {path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"[REJECTED] --from-file must be a mapping, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)

    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        print(f"[REJECTED] --from-file missing required fields: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    # Normalize list-form tags/run_ids into the comma-separated string the
    # CLI validator already understands.
    if isinstance(data["tags"], list):
        data["tags"] = ",".join(str(t) for t in data["tags"])
    if isinstance(data["run_ids"], list):
        data["run_ids"] = ",".join(str(r) for r in data["run_ids"])

    data.setdefault("strategy", "")
    return data

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
    parser.add_argument("--from-file", dest="from_file",
                        help="Path to YAML (.yaml/.yml/.txt) or JSON (.json) file with the 6 fields. "
                             "Mutually exclusive with the per-field flags below.")
    parser.add_argument("--tags", help="Comma-separated list of tags (min 3)")
    parser.add_argument("--strategy", required=False, default="", help="Optional strategy ID")
    parser.add_argument("--run-ids", help="MANDATORY: Run IDs as reference pointers")
    parser.add_argument("--finding", help="Finding summary")
    parser.add_argument("--evidence", help="Evidence supporting the finding (max 2 lines, must contain numeric metric)")
    parser.add_argument("--conclusion", help="Conclusion based on finding/evidence")
    parser.add_argument("--implication", help="Actionable implication to apply in future research")
    args = parser.parse_args()

    # Source selection: --from-file takes precedence; fill argparse namespace.
    if args.from_file:
        data = _load_entry_file(Path(args.from_file))
        for field in _REQUIRED_FIELDS:
            setattr(args, field.replace("-", "_"), data[field])
        args.strategy = str(data.get("strategy", ""))
    else:
        missing = [f for f in _REQUIRED_FIELDS if getattr(args, f.replace("-", "_"), None) in (None, "")]
        if missing:
            parser.error(
                f"missing required field(s): {', '.join('--' + f.replace('_', '-') for f in missing)}. "
                f"Alternatively pass --from-file <path.yaml|path.json>."
            )

    # Validation: tags
    tags = [t.strip() for t in str(args.tags).split(",") if t.strip()]
    if len(tags) < 3:
        print("[REJECTED] Validation failed: At least 3 tags are required.", file=sys.stderr)
        sys.exit(1)

    # Validation: Run IDs
    raw_run_ids = [rid.strip() for rid in str(args.run_ids).split(",") if rid.strip()]
    if not raw_run_ids:
        print("[REJECTED] Validation failed: Run IDs cannot be empty.", file=sys.stderr)
        sys.exit(1)
    run_ids_formatted = ", ".join(raw_run_ids)

    # Validation: Evidence
    evidence_str = str(args.evidence).strip()
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
        strategy=str(args.strategy).strip(),
        run_ids=run_ids_formatted,
        finding=str(args.finding).strip(),
        evidence=evidence_str,
        conclusion=str(args.conclusion).strip(),
        implication=str(args.implication).strip(),
    )
    append_entry(MEMORY_PATH, entry)
    print(f"[DONE] Appended research entry to {MEMORY_PATH}")


if __name__ == "__main__":
    main()
