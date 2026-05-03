#!/usr/bin/env python3
"""
lint_encoding.py -- Pre-commit gate: block I/O calls missing encoding="utf-8"
=============================================================================
On Windows, Python defaults to cp1252 (not UTF-8). Any file containing
em-dashes, arrows, or other multi-byte UTF-8 characters will cause
UnicodeDecodeError when read without explicit encoding="utf-8".

Detects three classes of violation:
    1. Bare .read_text() — Path.read_text() with no arguments
    2. Bare .write_text(...) — Path.write_text() with content arg but no encoding=
    3. Bare open(...) in text mode without encoding= (excludes binary modes)

INFRA-AUDIT H2 closure 2026-05-03 added open()/write_text() coverage.

Usage:
    python tools/lint_encoding.py          # scan all .py in repo
    python tools/lint_encoding.py --staged  # scan only git-staged .py files

Exit codes:
    0 = clean
    1 = violation detected (prints file:line for each)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Windows consoles default to cp1252 — violation lines may contain → or other
# multi-byte chars that crash the print itself. Force stdout to UTF-8 so the
# lint can report on the very content it's trying to police.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# Directories exempt from scanning (frozen archives, throwaway scripts)
EXEMPT_DIRS = {"vault", "tmp", "archive", ".git", "__pycache__", "node_modules"}

# Files exempt: this lint script references the patterns in docstrings/messages,
# and the regression test embeds them in fixture strings to verify detection.
EXEMPT_FILES = {"lint_encoding.py", "test_lint_encoding_extended.py"}

# Pattern 1: bare .read_text() with no args
BARE_READ_TEXT = re.compile(r'\.read_text\(\s*\)')

# Pattern 2: .write_text(...) — flag if call args do NOT contain encoding=
# Match the .write_text(...) span allowing nested parens (one level deep).
RE_WRITE_TEXT = re.compile(r'\.write_text\s*\(((?:[^()]|\([^()]*\))*)\)')

# Pattern 3: open(...) at use-site — flag if text-mode and missing encoding=
# Excludes os.open (returns int fd, not file object). Match span up to first
# unmatched ')'. Allows one level of nested parens (typical: open(Path(x))).
RE_BUILTIN_OPEN = re.compile(r'(?<![\.\w])open\s*\(((?:[^()]|\([^()]*\))*)\)')

# Mode arg detection inside open()/write_text() argstring
RE_MODE_ARG = re.compile(r"['\"]([rwxabt+]+)['\"]")


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


def _arg_has_encoding(args: str) -> bool:
    """True iff the argstring of an open()/write_text() call contains a
    keyword 'encoding=' (any value)."""
    return bool(re.search(r"\bencoding\s*=", args))


def _arg_is_binary_mode(args: str) -> bool:
    """True iff the argstring contains a binary-mode literal ('rb', 'wb', etc.)."""
    m = RE_MODE_ARG.search(args)
    if not m:
        return False
    return "b" in m.group(1)


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Return list of (lineno, kind, line) tuples for each violation."""
    violations: list[tuple[int, str, str]] = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                # Pattern 1: bare .read_text()
                if BARE_READ_TEXT.search(line):
                    violations.append((lineno, "read_text", line.rstrip()))
                # Pattern 2: .write_text(...) without encoding=
                for m in RE_WRITE_TEXT.finditer(line):
                    if not _arg_has_encoding(m.group(1)):
                        violations.append((lineno, "write_text", line.rstrip()))
                # Pattern 3: open(...) text-mode without encoding=
                for m in RE_BUILTIN_OPEN.finditer(line):
                    args = m.group(1)
                    if _arg_is_binary_mode(args):
                        continue
                    if _arg_has_encoding(args):
                        continue
                    violations.append((lineno, "open", line.rstrip()))
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
    by_kind: dict[str, int] = {}
    for filepath in sorted(files):
        violations = scan_file(filepath)
        if violations:
            rel = filepath.relative_to(repo_root) if filepath.is_relative_to(repo_root) else filepath
            for lineno, kind, line in violations:
                print(f"  VIOLATION ({kind}): {rel}:{lineno}  {line.strip()}")
                total_violations += 1
                by_kind[kind] = by_kind.get(kind, 0) + 1

    if total_violations > 0:
        breakdown = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
        print(f"\n  BLOCKED: {total_violations} encoding-missing call(s) found ({breakdown}).")
        print('  Fix: add encoding="utf-8" to read_text(), write_text(), and open() calls in text mode.')
        sys.exit(1)
    else:
        if not staged_only:
            print("  PASS: No encoding-missing I/O calls detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
