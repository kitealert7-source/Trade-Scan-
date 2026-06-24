#!/usr/bin/env python3
"""check_memory_index_budget.py -- byte-budget gate for the auto-memory MEMORY.md index.

MEMORY.md (the auto-memory index under ~/.claude/projects/<slug>/memory/) is loaded in
full into context at the start of every session. Past the harness load cap (~24.4 KB) it
loads only PARTIALLY, silently dropping entries. This is a deliberately simple byte-budget
check -- NOT a memory-management framework: it locates the file, measures it, and exits
non-zero when over the FAIL budget so /session-close blocks until the index is trimmed.

Remedy when it fails is the HOT-index policy: delete settled-arc lines from MEMORY.md (the
topic file stays on disk and is still recalled on demand by its description frontmatter),
or run /anthropic-skills:consolidate-memory. See feedback_memory_index_discipline.

Path resolution is worktree-safe: prefers config.path_authority.REAL_REPO_ROOT, falls back
to the tool's own repo root, then to a lone project memory dir on the machine.

Exit codes:
  0  OK (< warn) or WARN (>= warn, < fail) -- warn never blocks
  1  FAIL -- at/over the fail budget; trim before closing
  2  MEMORY.md could not be located
"""
import argparse
import re
import sys
from pathlib import Path

WARN_KB = 22.0   # advisory headroom warning (no block)
FAIL_KB = 24.0   # hard block; sits just below the ~24.4 KB harness load cap


def find_memory_index():
    """Locate the auto-memory MEMORY.md for THIS project (worktree-safe)."""
    try:
        from config.path_authority import REAL_REPO_ROOT as root
    except Exception:
        # Direct-script invocation (no repo root on sys.path) or a worktree:
        # tools/<this>.py -> repo root is parent.parent.
        root = Path(__file__).resolve().parent.parent
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    mem = Path.home() / ".claude" / "projects" / slug / "memory" / "MEMORY.md"
    if mem.exists():
        return mem
    # Fallback: a single project memory dir on this machine (covers worktree slug skew).
    hits = list((Path.home() / ".claude" / "projects").glob("*/memory/MEMORY.md"))
    return hits[0] if len(hits) == 1 else None


def main():
    ap = argparse.ArgumentParser(
        description="Byte-budget gate for the auto-memory MEMORY.md index."
    )
    ap.add_argument("--warn-kb", type=float, default=WARN_KB,
                    help="advisory warning threshold in KB (default %(default)s)")
    ap.add_argument("--fail-kb", type=float, default=FAIL_KB,
                    help="hard-fail threshold in KB; exit 1 at/over (default %(default)s)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress output when status is OK")
    args = ap.parse_args()

    mem = find_memory_index()
    if mem is None:
        print("[MEMORY-BUDGET] ERROR: could not locate auto-memory MEMORY.md "
              "under ~/.claude/projects/*/memory/", file=sys.stderr)
        return 2

    data = mem.read_text(encoding="utf-8")
    nbytes = len(data.encode("utf-8"))
    nlines = data.count("\n") + 1
    kb = nbytes / 1024.0
    warn = args.warn_kb * 1024
    fail = args.fail_kb * 1024

    if nbytes >= fail:
        status = "FAIL"
    elif nbytes >= warn:
        status = "WARN"
    else:
        status = "OK"

    if not (args.quiet and status == "OK"):
        print(f"[MEMORY-BUDGET] {status}: {nlines} lines / {nbytes} bytes ({kb:.1f} KB) "
              f"| warn {args.warn_kb:.1f} KB, fail {args.fail_kb:.1f} KB")
        print(f"               {mem}")

    if status == "FAIL":
        print("[MEMORY-BUDGET] over budget -> trim the HOT index before close: drop "
              "settled-arc lines (topic files stay, recalled on demand) or run "
              "/anthropic-skills:consolidate-memory. See feedback_memory_index_discipline.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
