"""
Generate research_memory_index.json from RESEARCH_MEMORY.md + ARCHIVE.

Fail-fast parser: any malformed entry causes a non-zero exit and logs the
line number, block preview, and specific parse failure reason.

Usage:
    python tools/generate_research_memory_index.py           # generate index
    python tools/generate_research_memory_index.py --check   # verify only (no write)
    python tools/generate_research_memory_index.py --verbose  # show each parsed entry

Output:  TradeScan_State/research_memory_index.json
Schema:
  {
    "generated_at": "ISO timestamp",
    "source_files": ["RESEARCH_MEMORY.md", ...],
    "parse_warnings": 0,
    "entry_count": N,
    "entries": [
      {
        "date": "2026-04-01",
        "tags": "tag1, tag2",
        "strategy": "28_PA_...",
        "run_ids": "abc123",
        "body": "...",
        "source_file": "RESEARCH_MEMORY.md",
        "source_line": 42
      },
      ...
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import STATE_ROOT

INDEX_PATH = STATE_ROOT / "research_memory_index.json"

# Two header formats supported:
# Format A (standard): 2026-04-01 | Tags: ... | Strategy: ... | Run IDs: ...
# Format B (alt):      ### Entry: Family NN — description
HEADER_A = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s*\|\s*Tags:\s*([^|]+?)"
    r"(?:\s*\|\s*Strategy:\s*(.+?))?"
    r"(?:\s*\|\s*Run IDs?:\s*(.+?))?$"
)
HEADER_B = re.compile(
    r"^###\s+Entry:\s+Family\s+(\d+)\s+.*?(?:\u2014|--)\s*(.*)"
)


def parse_research_memory(
    text: str,
    source_file: str = "RESEARCH_MEMORY.md",
    *,
    verbose: bool = False,
) -> tuple[list[dict], list[str]]:
    """Parse RESEARCH_MEMORY markdown into structured entries.

    Returns (entries, warnings).
    warnings is a list of human-readable strings describing parse issues.
    Each warning includes the line number and a preview of the problematic block.
    """
    entries: list[dict] = []
    warnings: list[str] = []

    # Split into lines to track line numbers
    lines = text.split("\n")

    # Find block boundaries: blocks are separated by \n---\s*\n
    # We rebuild blocks with their starting line numbers
    blocks: list[tuple[int, str]] = []  # (start_line_1indexed, block_text)
    current_block_lines: list[str] = []
    current_block_start: int = 1
    in_block = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect separator: a line that is just "---" (possibly with whitespace)
        if stripped == "---":
            # If we have accumulated block content, save it
            if current_block_lines:
                block_text = "\n".join(current_block_lines).strip()
                if block_text:
                    blocks.append((current_block_start, block_text))
                current_block_lines = []

            # Skip consecutive separators and blank lines after separator
            i += 1
            while i < len(lines) and lines[i].strip() in ("", "---"):
                i += 1
            current_block_start = i + 1  # 1-indexed
            continue

        # Skip the FORMAT POLICY / preamble header (before first entry)
        if not blocks and not in_block:
            # Check if this line could be an entry header
            if HEADER_A.match(stripped) or HEADER_B.match(stripped):
                in_block = True
                current_block_start = i + 1
                current_block_lines.append(line)
                i += 1
                continue
            # Preamble line — skip
            i += 1
            continue

        in_block = True
        current_block_lines.append(line)
        i += 1

    # Flush last block
    if current_block_lines:
        block_text = "\n".join(current_block_lines).strip()
        if block_text:
            blocks.append((current_block_start, block_text))

    # Parse each block
    for start_line, block in blocks:
        # Strip any leading "---" lines within the block (double-separator artifacts)
        block = re.sub(r"^---\s*\n", "", block).strip()
        if not block:
            continue

        first_line = block.split("\n")[0]
        body_lines = block.split("\n")[1:]

        # Try Format A
        header_a = HEADER_A.match(first_line)
        if header_a:
            entry = {
                "date": header_a.group(1),
                "tags": header_a.group(2).strip(),
                "strategy": (header_a.group(3) or "").strip(),
                "run_ids": (header_a.group(4) or "").strip(),
                "body": "\n".join(body_lines).strip(),
                "source_file": source_file,
                "source_line": start_line,
            }

            # Validate date
            try:
                datetime.strptime(entry["date"], "%Y-%m-%d")
            except ValueError:
                warnings.append(
                    f"{source_file}:{start_line}: Invalid date '{entry['date']}' "
                    f"in header: {first_line[:80]}"
                )

            # Validate tags non-empty
            if not entry["tags"]:
                warnings.append(
                    f"{source_file}:{start_line}: Empty tags in header: {first_line[:80]}"
                )

            # Validate body non-empty
            if not entry["body"]:
                warnings.append(
                    f"{source_file}:{start_line}: Empty body for entry: {first_line[:80]}"
                )

            entries.append(entry)
            if verbose:
                print(f"  [PARSED] {source_file}:{start_line} "
                      f"date={entry['date']} tags={entry['tags'][:40]}")
            continue

        # Try Format B (alt header)
        header_b = HEADER_B.match(first_line)
        if header_b:
            idea_id = header_b.group(1)
            tags_m = re.search(r"Tags:\s*(.+)", block)
            strat_m = re.search(r"Strateg(?:y|ies):\s*(.+)", block)
            date_m = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", block)
            run_ids_m = re.search(r"Run IDs?:\s*(.+)", block)

            filtered_body = [
                line for line in body_lines
                if not line.strip().startswith(("Tags:", "Date:", "Strateg", "Run ID"))
            ]

            entry = {
                "date": date_m.group(1) if date_m else "",
                "tags": tags_m.group(1).strip() if tags_m else "",
                "strategy": strat_m.group(1).strip() if strat_m else f"Family_{idea_id}",
                "run_ids": run_ids_m.group(1).strip() if run_ids_m else "",
                "body": "\n".join(filtered_body).strip(),
                "source_file": source_file,
                "source_line": start_line,
            }

            if not entry["date"]:
                warnings.append(
                    f"{source_file}:{start_line}: Missing Date: field in alt-header entry: "
                    f"{first_line[:80]}"
                )

            entries.append(entry)
            if verbose:
                print(f"  [PARSED] {source_file}:{start_line} "
                      f"(alt) family={idea_id} tags={entry['tags'][:40]}")
            continue

        # Neither header matched — this is a malformed entry
        preview = block[:120].replace("\n", " ").strip()
        warnings.append(
            f"{source_file}:{start_line}: MALFORMED ENTRY — header does not match "
            f"any known format. Preview: \"{preview}\""
        )

    return entries, warnings


def generate_index(
    *,
    check_only: bool = False,
    verbose: bool = False,
) -> tuple[dict, list[str]]:
    """Parse all RESEARCH_MEMORY files and build the index.

    Returns (index_dict, all_warnings).
    """
    all_entries: list[dict] = []
    all_warnings: list[str] = []
    source_files: list[str] = []

    for filename in ("RESEARCH_MEMORY.md", "RESEARCH_MEMORY_ARCHIVE.md"):
        path = PROJECT_ROOT / filename
        if not path.exists():
            continue
        source_files.append(filename)

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            all_warnings.append(f"Failed to read {filename}: {e}")
            continue

        entries, warnings = parse_research_memory(text, filename, verbose=verbose)
        all_entries.extend(entries)
        all_warnings.extend(warnings)

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": source_files,
        "parse_warnings": len(all_warnings),
        "entry_count": len(all_entries),
        "entries": all_entries,
    }

    if all_warnings:
        print(f"\n[WARN] {len(all_warnings)} parse warning(s):")
        for w in all_warnings:
            print(f"  - {w}")

    if not check_only:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n[OK] Wrote {INDEX_PATH} "
              f"({index['entry_count']} entries, {index['parse_warnings']} warnings)")
    else:
        print(f"\n[CHECK] {index['entry_count']} entries parsed, "
              f"{index['parse_warnings']} warnings (dry run — no file written)")

    return index, all_warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate research_memory_index.json from RESEARCH_MEMORY markdown files"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Verify parse only — do not write index file"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print each parsed entry"
    )
    args = parser.parse_args()

    index, warnings = generate_index(check_only=args.check, verbose=args.verbose)

    if warnings:
        print(f"\n[EXIT 1] {len(warnings)} parse warning(s) — fix before committing")
        sys.exit(1)

    print("[DONE] All entries parsed cleanly.")
    sys.exit(0)


if __name__ == "__main__":
    main()
