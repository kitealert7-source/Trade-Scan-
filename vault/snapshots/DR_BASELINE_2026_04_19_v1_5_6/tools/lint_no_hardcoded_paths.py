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


def scan_file(filepath: Path) -> list[tuple[int, str]]:
    """Scan a single file. Returns list of (line_number, line_text) violations."""
    violations = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                for pattern in VIOLATION_PATTERNS:
                    if pattern.search(line):
                        violations.append((lineno, line.rstrip()))
                        break  # one match per line is enough
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
    for filepath in sorted(files):
        violations = scan_file(filepath)
        if violations:
            rel = filepath.relative_to(repo_root) if filepath.is_relative_to(repo_root) else filepath
            for lineno, line in violations:
                print(f"  VIOLATION: {rel}:{lineno}  →  {line.strip()}")
                total_violations += 1

    if total_violations > 0:
        print(f"\n  BLOCKED: {total_violations} hardcoded path(s) found.")
        print("  Fix: use Path(__file__).resolve().parents[N] or import from config/path_config.py")
        sys.exit(1)
    else:
        if not staged_only:
            print("  PASS: No hardcoded user paths detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
