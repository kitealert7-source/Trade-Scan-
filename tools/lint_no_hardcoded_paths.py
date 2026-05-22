#!/usr/bin/env python3
"""
lint_no_hardcoded_paths.py — Pre-commit gate: block hardcoded user paths
=========================================================================
Scans staged .py files for patterns like C:\\Users\\, C:/Users/, or
/home/<user>/ and exits nonzero if any are found.

Usage:
    python tools/lint_no_hardcoded_paths.py          # scan all .py in repo
    python tools/lint_no_hardcoded_paths.py --staged  # scan only git-staged .py files

Exit codes:
    0 = clean
    1 = hardcoded paths detected (prints file:line for each violation)
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lint_helpers import get_staged_py_files, get_all_py_files, is_in_exempt_dir

# Directories that are exempt (frozen archives, throwaway scripts)
EXEMPT_DIRS = {
    "vault",        # frozen DR snapshots
    "engine_dev",   # frozen engine versions (engine_status: FROZEN, immutable)
    "tmp",          # throwaway one-off scripts
    "archive",      # retired legacy code
    ".git",
    "__pycache__",
    "node_modules",
}

# Files that are allowed to mention path patterns (the lint script itself)
EXEMPT_FILES = {
    "lint_no_hardcoded_paths.py",
}

# Patterns that indicate a hardcoded user-specific path
VIOLATION_PATTERNS = [
    re.compile(r'["\']?[A-Za-z]:\\Users\\', re.IGNORECASE),          # C:\Users\...
    re.compile(r'["\']?[A-Za-z]:/Users/', re.IGNORECASE),            # C:/Users/...
    re.compile(r'["\']?/home/[a-z_][a-z0-9_-]*/', re.IGNORECASE),   # /home/username/...
    re.compile(r'["\']?/Users/[A-Za-z]', re.IGNORECASE),             # macOS /Users/Name
]

# Banned sibling-resolution patterns. Naive PROJECT_ROOT.parent / "<sibling>"
# resolves wrong from a git worktree (PROJECT_ROOT.parent is .claude/worktrees/,
# not the user's container). Use config/path_authority.py instead. The
# authority module itself and state_paths.py are exempt — they are the
# resolution layer.
SIBLING_BAN_PATTERNS = [
    re.compile(r'PROJECT_ROOT\s*\.\s*parent\s*/\s*["\']TradeScan_State["\']'),
    re.compile(r'PROJECT_ROOT\s*\.\s*parent\s*/\s*["\']TS_Execution["\']'),
    re.compile(r'PROJECT_ROOT\s*\.\s*parent\s*/\s*["\']DRY_RUN_VAULT["\']'),
    re.compile(r'PROJECT_ROOT\s*\.\s*parent\s*/\s*["\']Anti_Gravity_DATA_ROOT["\']'),
]

SIBLING_BAN_EXEMPT_FILES = {
    "path_authority.py",        # the resolver itself
    "state_paths.py",           # legacy resolver kept as compatibility wrapper
    "lint_no_hardcoded_paths.py",  # this file (regex literals)
    "test_path_authority_worktree_compat.py",  # docstring quotes bug pattern
}

# Lines that are comments or docstrings mentioning paths as documentation are still flagged
# because even documented hardcoded paths encourage copy-paste. Only EXEMPT_DIRS get a pass.


def is_exempt(filepath: Path) -> bool:
    """Check if file is inside an exempt directory or is an exempt file."""
    return is_in_exempt_dir(filepath, EXEMPT_DIRS) or filepath.name in EXEMPT_FILES


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Scan a single file. Returns list of (line_number, line_text, kind)
    violations. `kind` is "hardcoded-path" or "naive-sibling"."""
    violations = []
    sibling_exempt = filepath.name in SIBLING_BAN_EXEMPT_FILES
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                for pattern in VIOLATION_PATTERNS:
                    if pattern.search(line):
                        violations.append((lineno, line.rstrip(), "hardcoded-path"))
                        break  # one match per line is enough
                else:
                    if sibling_exempt:
                        continue
                    for pattern in SIBLING_BAN_PATTERNS:
                        if pattern.search(line):
                            violations.append((lineno, line.rstrip(), "naive-sibling"))
                            break
    except (OSError, UnicodeDecodeError):
        pass
    return violations


def main():
    staged_only = "--staged" in sys.argv

    repo_root = Path(__file__).resolve().parent.parent

    if staged_only:
        files = get_staged_py_files(repo_root)
    else:
        files = get_all_py_files(repo_root, is_exempt)

    # Filter exemptions
    files = [f for f in files if not is_exempt(f)]

    total_violations = 0
    sibling_violations = 0
    for filepath in sorted(files):
        violations = scan_file(filepath)
        if violations:
            rel = filepath.relative_to(repo_root) if filepath.is_relative_to(repo_root) else filepath
            for lineno, line, kind in violations:
                tag = "HARDCODED-PATH" if kind == "hardcoded-path" else "NAIVE-SIBLING"
                print(f"  VIOLATION [{tag}]: {rel}:{lineno}  ->  {line.strip()}")
                total_violations += 1
                if kind == "naive-sibling":
                    sibling_violations += 1

    if total_violations > 0:
        print(f"\n  BLOCKED: {total_violations} violation(s) found.")
        print("  Fix hardcoded paths: use Path(__file__).resolve().parents[N].")
        if sibling_violations:
            print("  Fix naive-sibling: import sibling repos from config.path_authority.")
            print("    e.g. from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT")
        sys.exit(1)
    else:
        if not staged_only:
            print("  PASS: No hardcoded user paths or naive-sibling resolutions detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
