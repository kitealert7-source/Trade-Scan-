#!/usr/bin/env python3
"""
lint_helpers.py -- shared utilities for tools/lint_*.py pre-commit gates
=========================================================================
Centralizes the mechanics that previously appeared identically (or
near-identically) in lint_no_hardcoded_paths.py, lint_encoding.py, and
lint_check_exit_labels.py.

Exports:
  - get_staged_py_files(repo_root: Path | None = None) -> list[Path]
      Returns staged .py files. If repo_root is provided, paths are
      absolute (repo_root / relpath); otherwise relative.
  - get_all_py_files(root, is_exempt) -> list[Path]
      Walk root for *.py, skipping symlinks and entries flagged by the
      caller-supplied is_exempt predicate.
  - is_in_exempt_dir(path, exempt_dirs) -> bool
      True iff any path part matches an entry in exempt_dirs.

Each lint script keeps its own EXEMPT_DIRS / EXEMPT_FILES / is_exempt
because the exempt policy is lint-specific. This module provides only
the lint-policy-agnostic mechanics.

Consumers (because tools/ is not a Python package):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lint_helpers import get_staged_py_files, get_all_py_files, is_in_exempt_dir
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


def get_staged_py_files(repo_root: Path | None = None) -> list[Path]:
    """Return git-staged .py file paths.

    If repo_root is provided, returned paths are absolute (repo_root / f);
    otherwise they are relative as git reports them.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    )
    rels = [f for f in result.stdout.strip().splitlines() if f.endswith(".py")]
    if repo_root is not None:
        return [repo_root / f for f in rels]
    return [Path(f) for f in rels]


def get_all_py_files(
    root: Path,
    is_exempt: Callable[[Path], bool],
) -> list[Path]:
    """Walk root for *.py files, skipping symlinks and exempt entries."""
    results: list[Path] = []
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


def is_in_exempt_dir(path: Path, exempt_dirs: set[str]) -> bool:
    """True iff any part of `path` matches an entry in `exempt_dirs`."""
    return any(d in path.parts for d in exempt_dirs)
