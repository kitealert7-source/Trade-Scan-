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
import subprocess
from pathlib import Path

# Directories that are exempt (frozen archives, throwaway scripts)
EXEMPT_DIRS = {
    "vault",        # frozen DR snapshots
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
    # Files with their own worktree-safe resolver (TD: migrate to
    # path_authority in a follow-up session, then drop these exemptions).
    "burnin_evaluator.py",      # has _resolve_ts_exec_root walk-up helper
}

# Lines that are comments or docstrings mentioning paths as documentation are still flagged
# because even documented hardcoded paths encourage copy-paste. Only EXEMPT_DIRS get a pass.


def is_exempt(filepath: Path) -> bool:
    """Check if file is inside an exempt directory or is an exempt file."""
    parts = filepath.parts
    if any(exempt in parts for exempt in EXEMPT_DIRS):
        return True
    if filepath.name in EXEMPT_FILES:
        return True
    return False


def get_staged_py_files() -> list[Path]:
    """Get list of staged .py files from git."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True
    )
    return [Path(f) for f in result.stdout.strip().splitlines() if f.endswith(".py")]


def get_all_py_files(root: Path) -> list[Path]:
    """Get all .py files in repo, excluding exempt dirs and symlinks."""
    results = []
    try:
        for f in root.rglob("*.py"):
            try:
                if f.is_symlink():
                    continue
                if not is_exempt(f):
                    results.append(f)
            except OSError:
                continue
    except OSError:
        pass
    return results


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
        files = get_staged_py_files()
        files = [repo_root / f for f in files]
    else:
        files = get_all_py_files(repo_root)

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
