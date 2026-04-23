#!/usr/bin/env python3
"""
lint_check_exit_labels.py -- WARN-only: bare `return True` in check_exit()
==========================================================================
Engine contract v1.3 (2026-04-23) accepts `bool | str` from
Strategy.check_exit(). A bare `return True` is valid but yields
`STRATEGY_UNSPECIFIED` in the namespaced exit_source column, which
hides the strategy's exit reason from downstream attribution.

Recommended: return a `STRATEGY_<REASON>` string instead, e.g.
`STRATEGY_TIME_CAP`, `STRATEGY_OPPOSITE_FLIP`, `STRATEGY_Z_EXTENSION`.

This is a WARNING — exit code is always 0. Pre-commit will not block.

Usage:
    python tools/lint_check_exit_labels.py            # scan all strategies/
    python tools/lint_check_exit_labels.py --staged   # scan only staged .py files
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = REPO_ROOT / "strategies"

EXEMPT_DIRS = {"vault", "tmp", "archive", ".git", "__pycache__", "node_modules"}

CHECK_EXIT_DEF = re.compile(r"^\s*def\s+check_exit\s*\(")
BARE_RETURN_TRUE = re.compile(r"^\s*return\s+True\s*(#.*)?$")
DEDENT = re.compile(r"^\S")


def is_exempt(p: Path) -> bool:
    return any(part in EXEMPT_DIRS for part in p.parts)


def get_staged_py_files() -> list[Path]:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    )
    return [REPO_ROOT / f for f in r.stdout.strip().splitlines() if f.endswith(".py")]


def get_strategy_files() -> list[Path]:
    if not STRATEGIES_DIR.exists():
        return []
    return [p for p in STRATEGIES_DIR.rglob("strategy.py") if not is_exempt(p)]


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, source_line)] of bare `return True` inside check_exit()."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    hits: list[tuple[int, str]] = []
    in_check_exit = False
    base_indent: int | None = None

    for i, raw in enumerate(lines, start=1):
        if CHECK_EXIT_DEF.match(raw):
            in_check_exit = True
            base_indent = len(raw) - len(raw.lstrip())
            continue
        if in_check_exit:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            cur_indent = len(raw) - len(raw.lstrip())
            if base_indent is not None and cur_indent <= base_indent and DEDENT.search(raw):
                in_check_exit = False
                base_indent = None
                continue
            if BARE_RETURN_TRUE.match(raw):
                hits.append((i, raw.rstrip()))
    return hits


def main() -> None:
    staged_only = "--staged" in sys.argv
    if staged_only:
        files = [p for p in get_staged_py_files() if p.name == "strategy.py" and not is_exempt(p)]
    else:
        files = get_strategy_files()

    total = 0
    for f in sorted(files):
        hits = scan_file(f)
        if not hits:
            continue
        rel = f.relative_to(REPO_ROOT) if f.is_relative_to(REPO_ROOT) else f
        for lineno, line in hits:
            print(f"  WARN: {rel}:{lineno}  bare `return True` in check_exit()  -- {line.strip()}")
            total += 1

    if total > 0:
        print(f"\n  [WARN] {total} bare `return True` call(s) in check_exit().")
        print("  Recommend: return a 'STRATEGY_<REASON>' label so exit_source")
        print("  attributes the exit instead of falling back to STRATEGY_UNSPECIFIED.")
        print("  Example labels: STRATEGY_TIME_CAP, STRATEGY_OPPOSITE_FLIP, STRATEGY_Z_EXTENSION")
    elif not staged_only:
        print("  PASS: No bare `return True` in check_exit() detected.")

    sys.exit(0)  # warn-only


if __name__ == "__main__":
    main()
