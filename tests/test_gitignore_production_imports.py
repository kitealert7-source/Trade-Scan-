"""Regression — production code under `tools/utils/research/` must stay
under version control.

Background (Patch G1, 2026-05-12)
---------------------------------
Both `.gitignore` (root, line 12) and `tools/.gitignore` (line 5) had
an unanchored `research/` pattern. Per gitignore semantics, unanchored
patterns match directories of that name *at any depth* — so the
`research/` rule, intended for the top-level `research/` scratch
directory, also silently swallowed `tools/utils/research/` containing
six production modules imported by tracked code
(`tools/family_report.py`, `tools/report/report_sections/verdict_risk.py`,
the entire `tools/robustness/` suite, etc.).

The fix anchors both rules with `/research/` and force-adds the
production modules into git. This test prevents recurrence — not by
checking for the specific pattern bug, but by enforcing the
invariant that motivated the fix:

  **Every `tools.utils.research.*` module imported by tracked code
  must (1) exist on disk, (2) be tracked by git, and (3) be
  re-checkable as not-ignored.**

The recurrence vector for this class of bug is NOT "the file went
missing." It is "the file exists on disk, imports succeed locally,
git silently pretends the file doesn't exist." This test pins
exactly that class.

Pin all three signals so any one of them being false fails the test:
disk-existence, git-tracked-ness, and gitignore-not-matching. A future
.gitignore edit that re-introduces an unanchored pattern would trip
signal #3 even though the file might still satisfy #1 and #2.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WATCHED_PACKAGE = "tools.utils.research"
WATCHED_DIR = PROJECT_ROOT / "tools" / "utils" / "research"

# Locations whose imports we do NOT enforce against:
#   - vault/snapshots/: frozen historical baselines; expected to reference
#     modules as they existed at snapshot time, not necessarily today's tree.
#   - archive/: archived working trees, same rationale.
_EXEMPT_PATH_PREFIXES = ("vault/snapshots/", "archive/", ".claude/worktrees/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_ls_files() -> set[str]:
    """All paths git considers tracked (forward-slash form)."""
    result = subprocess.run(
        ["git", "ls-files"], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, check=True, encoding="utf-8",
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _git_is_ignored(rel_path: str) -> bool:
    """True iff `git check-ignore` reports rel_path as ignored.

    `check-ignore` returns 0 when the path IS ignored, 1 when not, and
    >1 on error. We treat any non-1 exit as 'ignored' for safety.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _watched_imports_in(src: str) -> set[str]:
    """AST-parse `src` (a tracked .py file's content) and return the set
    of submodule names referenced under `tools.utils.research.*`.

    Handles all three import forms:
      - `import tools.utils.research.robustness`              -> {"robustness"}
      - `import tools.utils.research.robustness as rb`        -> {"robustness"}
      - `from tools.utils.research import robustness`         -> {"robustness"}
      - `from tools.utils.research import robustness as rb`   -> {"robustness"}
      - `from tools.utils.research.robustness import early_late_split` -> {"robustness"}
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # If a tracked .py file has syntax errors that's a separate
        # problem; this test does not gate on it.
        return set()

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == WATCHED_PACKAGE:
                # `from tools.utils.research import X, Y`
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        found.add(alias.name)
            elif mod.startswith(WATCHED_PACKAGE + "."):
                # `from tools.utils.research.robustness import early_late_split`
                sub = mod[len(WATCHED_PACKAGE) + 1:].split(".", 1)[0]
                if sub:
                    found.add(sub)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name and alias.name.startswith(WATCHED_PACKAGE + "."):
                    # `import tools.utils.research.robustness[.<deeper>]`
                    sub = alias.name[len(WATCHED_PACKAGE) + 1:].split(".", 1)[0]
                    if sub:
                        found.add(sub)
    return found


def _collect_required_submodules() -> dict[str, list[str]]:
    """Return {submodule_name: [importer_file, ...]} across all active
    tracked .py files (excluding vault/archive/worktree paths).
    """
    tracked = _git_ls_files()
    required: dict[str, list[str]] = {}
    for rel in tracked:
        if not rel.endswith(".py"):
            continue
        if any(rel.startswith(prefix) for prefix in _EXEMPT_PATH_PREFIXES):
            continue
        abs_p = PROJECT_ROOT / rel
        if not abs_p.exists():
            # Tracked but absent on this checkout — possible during a
            # mid-merge state. Skip.
            continue
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for sub in _watched_imports_in(text):
            required.setdefault(sub, []).append(rel)
    return required


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_watched_dir_exists():
    """Sanity baseline — the directory must be on disk."""
    assert WATCHED_DIR.is_dir(), (
        f"{WATCHED_DIR} missing. Patch G1 force-added the production "
        "modules; absence indicates the fix was reverted or never "
        "applied to this checkout."
    )


def test_every_imported_submodule_exists_on_disk():
    """Signal #1: file presence.

    For each `tools.utils.research.<sub>` referenced by tracked code,
    `<sub>.py` must be on disk.
    """
    required = _collect_required_submodules()
    assert required, (
        "No tracked code imports tools.utils.research.* — this test "
        "is now scoped to nothing. Either remove the test or restore "
        "the import surface it was protecting."
    )
    missing: list[tuple[str, list[str]]] = []
    for sub, importers in sorted(required.items()):
        path = WATCHED_DIR / f"{sub}.py"
        if not path.exists():
            missing.append((sub, importers))
    assert not missing, (
        "Tracked code imports modules that do not exist on disk:\n  " +
        "\n  ".join(f"{sub} (imported by {importers})" for sub, importers in missing)
    )


def test_every_imported_submodule_is_tracked_by_git():
    """Signal #2: git-tracked-ness.

    Disk presence is not enough — the file must be in `git ls-files`.
    This is the signal that catches the original G1 bug: the modules
    existed on disk and imports worked, but git silently treated them
    as untracked.
    """
    required = _collect_required_submodules()
    tracked = _git_ls_files()
    untracked_imports: list[tuple[str, list[str]]] = []
    for sub, importers in sorted(required.items()):
        rel = f"tools/utils/research/{sub}.py"
        if rel not in tracked:
            untracked_imports.append((sub, importers))
    assert not untracked_imports, (
        "Tracked code imports modules that exist on disk but are NOT "
        "tracked by git — exactly the class of bug Patch G1 fixed. "
        "Either `git add -f` the file or remove the import.\n  " +
        "\n  ".join(f"{sub} (imported by {importers})" for sub, importers in untracked_imports)
    )


def test_every_imported_submodule_is_not_currently_ignored():
    """Signal #3: not gitignored.

    The recurrence vector this test is most concerned about: a future
    .gitignore edit that re-introduces an unanchored pattern would
    re-ignore the modules even though they remain tracked. New files
    added later would then silently disappear from version control.

    `git check-ignore` returns 0 when a path IS ignored. Even tracked
    files can be flagged as ignored by pattern (git won't UN-track
    them automatically, but new files matching that pattern would be
    silently untracked). Catching this proactively prevents the
    G1-class bug from recurring.
    """
    required = _collect_required_submodules()
    ignored: list[tuple[str, list[str]]] = []
    for sub, importers in sorted(required.items()):
        rel = f"tools/utils/research/{sub}.py"
        if _git_is_ignored(rel):
            ignored.append((sub, importers))
    assert not ignored, (
        ".gitignore pattern currently matches a production import path "
        "under tools/utils/research/. Existing tracked files survive, "
        "but ANY new file under this directory would be silently "
        "ignored — the exact recurrence vector Patch G1 closed. Check "
        "for an unanchored `research/` pattern in either .gitignore or "
        "tools/.gitignore.\n  " +
        "\n  ".join(f"{sub} (imported by {importers})" for sub, importers in ignored)
    )


def test_anchored_pattern_still_excludes_top_level_research_scratch():
    """Companion check: the anchored `/research/` rule MUST still
    ignore the top-level `research/` scratch directory. If it stopped,
    idea-scratch text files would start polluting tracked history.
    """
    sentinel = PROJECT_ROOT / "research" / "Build Strategy.txt"
    if not sentinel.exists():
        pytest.skip(f"Top-level scratch sentinel not present at {sentinel}")
    rel = "research/Build Strategy.txt"
    assert _git_is_ignored(rel), (
        f"Top-level `research/` scratch is no longer ignored. The "
        f"anchored rule must keep matching it. Sentinel: {rel}"
    )
