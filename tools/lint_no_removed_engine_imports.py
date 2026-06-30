#!/usr/bin/env python3
"""
lint_no_removed_engine_imports.py — Pre-commit + CI gate: block imports of the
removed compute engines v1.5.3–v1.5.9
=========================================================================
The engine consolidation (2026-06-30) removed
``engine_dev/universal_research_engine/v1_5_3 … v1_5_9`` from the active tree —
they are defective (uncharged cost model; the charged/uncharged boundary is
exactly v1.5.10). See ENGINE_VAULT_CONTRACT.md §14. This lint enforces that no
live code re-introduces an import of them, so the single-active-engine state
cannot silently decay (per the enforceable-mechanisms doctrine —
feedback_enforceable_mechanisms_only).

Matches IMPORT statements only (AST-level `import` / `from … import`). Historical
references in comments, docstrings, and path strings (e.g. "originated in v1_5_8")
are intentionally NOT flagged — only an actual runtime import is a violation.

Kept engines v1_5_10 (rollback) and v1_5_11 (canonical) are allowed. vault/ and
archive/ are exempt (frozen historical snapshots legitimately self-reference old
versions).

Usage:
    python tools/lint_no_removed_engine_imports.py           # scan all .py (CI)
    python tools/lint_no_removed_engine_imports.py --staged  # staged .py (pre-commit)

Exit codes:
    0 = clean
    1 = import(s) of a removed engine detected (prints file:line for each)
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lint_helpers import get_staged_py_files, get_all_py_files, is_in_exempt_dir

# A module path is a violation iff it imports one of the REMOVED compute engines.
# `v1_5_[3-9]` followed by `.` or end-of-string matches exactly v1_5_3 … v1_5_9 and
# NOT v1_5_10 / v1_5_11 (the char after `v1_5_` would be `1`, not in [3-9]).
REMOVED_IMPORT = re.compile(r"^engine_dev\.universal_research_engine\.v1_5_[3-9](\.|$)")

# Frozen historical snapshots + non-pipeline scratch trees that legitimately
# reference (or still contain) old versions. The ACTIVE engine_dev/ is deliberately
# NOT exempt — a kept engine importing a removed one is exactly what we want to
# catch (the v1_5_[3-9] regex never matches the kept v1_5_10/v1_5_11 self-imports).
EXEMPT_DIRS = {
    "vault",          # frozen DR / engine snapshots (the removed engines live here in history)
    "archive",        # retired legacy code
    "tmp",            # throwaway one-off scripts (matches lint_no_hardcoded_paths)
    ".claude",        # agent infra + stale worktree snapshots (not live pipeline code)
    ".git",
    "__pycache__",
    "node_modules",
}
EXEMPT_FILES = {
    "lint_no_removed_engine_imports.py",  # this file (regex literal)
}


def is_exempt(filepath: Path) -> bool:
    return is_in_exempt_dir(filepath, EXEMPT_DIRS) or filepath.name in EXEMPT_FILES


def scan_file(filepath: Path) -> list[tuple[int, str]]:
    """Return [(lineno, module_path)] for every import of a removed engine."""
    violations: list[tuple[int, str]] = []
    try:
        src = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(filepath))
    except (OSError, SyntaxError):
        # Unparseable / unreadable files are out of scope for this lint.
        return violations
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom):
            # Absolute `from engine_dev...` only; level>0 is a relative import.
            if node.module and node.level == 0:
                modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        for mod in modules:
            if REMOVED_IMPORT.match(mod):
                violations.append((node.lineno, mod))
    return violations


def main() -> None:
    staged_only = "--staged" in sys.argv
    repo_root = Path(__file__).resolve().parent.parent

    if staged_only:
        files = get_staged_py_files(repo_root)
    else:
        files = get_all_py_files(repo_root, is_exempt)
    files = [f for f in files if not is_exempt(f)]

    total = 0
    for filepath in sorted(files):
        for lineno, mod in scan_file(filepath):
            rel = filepath.relative_to(repo_root) if filepath.is_relative_to(repo_root) else filepath
            print(f"  VIOLATION [REMOVED-ENGINE-IMPORT]: {rel}:{lineno}  ->  import {mod}")
            total += 1

    if total > 0:
        print(f"\n  BLOCKED: {total} import(s) of a removed compute engine (v1.5.3–v1.5.9).")
        print("  Those engines were removed by the 2026-06-30 consolidation")
        print("  (ENGINE_VAULT_CONTRACT.md §14 — defective/uncharged). Use the canonical")
        print("  engine v1_5_11 (or the rollback v1_5_10); a removed engine is restorable")
        print("  from git history if truly required, but never imported by live code.")
        sys.exit(1)

    if not staged_only:
        print("  PASS: No imports of removed engines v1.5.3–v1.5.9 detected.")
    sys.exit(0)


if __name__ == "__main__":
    main()
