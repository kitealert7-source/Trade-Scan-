#!/usr/bin/env python3
"""
lint_encoding.py -- Pre-commit gate: block bare .read_text() without encoding
=============================================================================
On Windows, Python defaults to cp1252 (not UTF-8). Any file containing
em-dashes, arrows, or other multi-byte UTF-8 characters will cause
UnicodeDecodeError when read without explicit encoding="utf-8".

Usage:
    python tools/lint_encoding.py          # scan all .py in repo
    python tools/lint_encoding.py --staged  # scan only git-staged .py files

Exit codes:
    0 = clean
    1 = bare .read_text() detected (prints file:line for each violation)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Directories exempt from scanning (frozen archives, throwaway scripts)
EXEMPT_DIRS = {"vault", "tmp", "archive", ".git", "__pycache__", "node_modules"}

# Files exempt (this lint script references the pattern in docstrings/messages)
EXEMPT_FILES = {"lint_encoding.py"}

# The pattern: .read_text() with no arguments, or .read_text( ) with only whitespace
# Does NOT flag .read_text(encoding="utf-8") or similar
BARE_READ_TEXT = re.compile(r'\.read_text\(\s*\)')


def is_exempt(filepath: Path) -> bool:
    parts = filepath.parts
    if any(exempt in parts for exempt in EXEMPT_DIRS):
        return True
    if filepath.name in EXEMPT_FILES:
        return True
    return False


def get_staged_py_files() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    )
    return [Path(f) for f in result.stdout.strip().splitlines() if f.endswith(".py")]


def get_all_py_files(root: Path) -> list[Path]:
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
    violations = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                if BARE_READ_TEXT.search(line):
                    violations.append((lineno, line.rstrip()))
    except (OSError, UnicodeDecodeError):
        pass
    return violations


def main() -> None:
    staged_only = "--staged" in sys.argv
    repo_root = Path(__file__).resolve().parent.parent

    if staged_only:
        files = [repo_root / f for f in get_staged_py_files()]
    else:
        files = get_all_py_files(repo_root)

    files = [f for f in files if not is_exempt(f)]

    total_violations = 0
    for filepath in sorted(files):
        violations = scan_file(filepath)
        if violations:
            rel = filepath.relative_to(repo_root) if filepath.is_relative_to(repo_root) else filepath
            for lineno, line in violations:
                print(f"  VIOLATION: {rel}:{lineno}  {line.strip()}")
                total_violations += 1

    if total_violations > 0:
        print(f"\n  BLOCKED: {total_violations} bare .read_text() call(s) found.")
        print('  Fix: use .read_text(encoding="utf-8") instead')
        sys.exit(1)
    else:
        if not staged_only:
            print("  PASS: No bare .read_text() calls detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
