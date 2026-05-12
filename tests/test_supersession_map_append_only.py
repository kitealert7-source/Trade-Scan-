"""Regression — append-only enforcement on
`governance/supersession_map.yaml`.

The file's header documents an append-only invariant ("Never edit or
remove a mapping once published"). Patch 4 of
`outputs/GOVERNANCE_DRIFT_PREVENTION_PLAN.md` operationalises that
invariant with `tools/lint_supersession_map_append_only.py`, wired into
`tools/hooks/pre-commit`.

These tests pin the four cases the user specified:

  A — mapping DELETE in working tree → block
  B — existing mapping field MUTATION → block
  C — new mapping APPEND only → pass
  D — identical to HEAD (no-op) → pass

Plus a sanity case: file not in staging set → pass without inspection.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LINT_SCRIPT = PROJECT_ROOT / "tools" / "lint_supersession_map_append_only.py"
MAP_REL = "governance/supersession_map.yaml"


# ---------------------------------------------------------------------------
# Fixture — synthetic repo with the lint script and a baseline map at HEAD
# ---------------------------------------------------------------------------

_BASELINE_MAP = textwrap.dedent("""\
    # Test fixture supersession map.
    schema_version: "1.0"
    supersessions:
      OLD_ID_001:
        superseded_by: NEW_ID_001
        reason: example_reason
        superseded_at_utc: "2026-01-01T00:00:00+00:00"
        path_b_batch: "001"
      OLD_ID_002:
        superseded_by: NEW_ID_002
        reason: another_reason
        superseded_at_utc: "2026-02-01T00:00:00+00:00"
        path_b_batch: "001"
""")


def _run(cwd: Path, *cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), cwd=str(cwd),
        capture_output=True, text=True, check=check, encoding="utf-8",
    )


@pytest.fixture()
def repo_with_baseline_map(tmp_path):
    """Initialize a git repo, copy the lint into it, commit a baseline
    supersession map as HEAD.
    """
    _run(tmp_path, "git", "init", "-q")
    _run(tmp_path, "git", "config", "user.email", "ci@local")
    _run(tmp_path, "git", "config", "user.name", "ci")

    # Copy the lint script into <tmp>/tools/ so its
    # `Path(__file__).resolve().parent.parent` lands at <tmp>.
    (tmp_path / "tools").mkdir()
    shutil.copy(LINT_SCRIPT, tmp_path / "tools" / "lint_supersession_map_append_only.py")

    # Baseline map at HEAD.
    map_path = tmp_path / "governance"
    map_path.mkdir()
    (map_path / "supersession_map.yaml").write_text(
        _BASELINE_MAP, encoding="utf-8",
    )
    _run(tmp_path, "git", "add", "-A")
    _run(tmp_path, "git", "commit", "-q", "-m", "baseline supersession map")
    return tmp_path


def _run_lint(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "tools/lint_supersession_map_append_only.py", "--staged"],
        cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Case A — DELETE existing mapping → block
# ---------------------------------------------------------------------------

def test_delete_existing_mapping_is_blocked(repo_with_baseline_map):
    """Removing a published mapping violates the invariant. The lint
    must return 1 with a specific failure message naming the deleted key.
    """
    repo = repo_with_baseline_map
    # Remove OLD_ID_001 from the map.
    raw = yaml.safe_load((repo / MAP_REL).read_text(encoding="utf-8"))
    del raw["supersessions"]["OLD_ID_001"]
    (repo / MAP_REL).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    _run(repo, "git", "add", MAP_REL)

    result = _run_lint(repo)
    assert result.returncode == 1, (
        f"Deleting an existing mapping must block. stdout:\n{result.stdout}"
    )
    assert "DELETED" in result.stdout
    assert "OLD_ID_001" in result.stdout


# ---------------------------------------------------------------------------
# Case B — MUTATE existing mapping field → block
# ---------------------------------------------------------------------------

def test_mutating_existing_mapping_field_is_blocked(repo_with_baseline_map):
    """Changing the value of any field on a published mapping violates
    the invariant — even if the change looks cosmetic. Pin both the
    block AND the diagnostic listing the field-level delta.
    """
    repo = repo_with_baseline_map
    raw = yaml.safe_load((repo / MAP_REL).read_text(encoding="utf-8"))
    raw["supersessions"]["OLD_ID_001"]["reason"] = "edited_reason"
    (repo / MAP_REL).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    _run(repo, "git", "add", MAP_REL)

    result = _run_lint(repo)
    assert result.returncode == 1
    assert "mutation" in result.stdout.lower()
    assert "OLD_ID_001" in result.stdout
    assert "reason" in result.stdout
    # Both old and new values must surface so the operator sees what
    # changed without re-running git diff.
    assert "example_reason" in result.stdout
    assert "edited_reason" in result.stdout


# ---------------------------------------------------------------------------
# Case C — APPEND new mapping only → pass
# ---------------------------------------------------------------------------

def test_appending_new_mapping_passes(repo_with_baseline_map):
    """Adding a NEW supersession entry without touching existing ones is
    the intended legal mutation. Must pass.
    """
    repo = repo_with_baseline_map
    raw = yaml.safe_load((repo / MAP_REL).read_text(encoding="utf-8"))
    raw["supersessions"]["OLD_ID_999"] = {
        "superseded_by": "NEW_ID_999",
        "reason": "fresh_supersession",
        "superseded_at_utc": "2026-05-12T00:00:00+00:00",
        "path_b_batch": "002",
    }
    (repo / MAP_REL).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    _run(repo, "git", "add", MAP_REL)

    result = _run_lint(repo)
    assert result.returncode == 0, (
        f"Appending a new mapping must pass. stdout:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Case D — IDENTICAL to HEAD (no-op) → pass
# ---------------------------------------------------------------------------

def test_no_op_change_passes(repo_with_baseline_map):
    """If the file is in the staged change set but the parsed
    `supersessions:` block is unchanged (e.g., whitespace tidy elsewhere
    in the file), the lint must pass.
    """
    repo = repo_with_baseline_map
    # Touch the file with a comment-only change — the supersessions
    # block remains structurally identical.
    text = (repo / MAP_REL).read_text(encoding="utf-8")
    (repo / MAP_REL).write_text(
        text + "\n# tidying comment — no semantic change\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", MAP_REL)

    result = _run_lint(repo)
    assert result.returncode == 0, (
        f"No-op change must pass. stdout:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Sanity — file not staged → pass without inspection
# ---------------------------------------------------------------------------

def test_lint_passes_when_map_not_in_staged_changes(repo_with_baseline_map):
    """If the supersession map is not in the staging area, the lint
    must do nothing and return 0 — it should not gratuitously inspect
    every unrelated commit.
    """
    repo = repo_with_baseline_map
    # Stage an unrelated file.
    (repo / "unrelated.txt").write_text("hello", encoding="utf-8")
    _run(repo, "git", "add", "unrelated.txt")

    result = _run_lint(repo)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# File-level delete (working tree removes the file entirely) → block
# ---------------------------------------------------------------------------

def test_deleting_the_file_entirely_is_blocked(repo_with_baseline_map):
    """File-level deletion is morally equivalent to deleting every
    mapping. Pin the block on this case so a `git rm` doesn't slip
    through as 'no mappings to compare'.
    """
    repo = repo_with_baseline_map
    _run(repo, "git", "rm", MAP_REL)

    result = _run_lint(repo)
    assert result.returncode == 1
    assert "deleted" in result.stdout.lower() or "DELETED" in result.stdout


# ---------------------------------------------------------------------------
# Document-level guard — pre-commit hook actually wires the lint in
# ---------------------------------------------------------------------------

def test_pre_commit_hook_wires_the_lint_in():
    """Patch 4 wires the lint into tools/hooks/pre-commit. Guard against
    a future refactor that drops the wiring.
    """
    hook_path = PROJECT_ROOT / "tools" / "hooks" / "pre-commit"
    text = hook_path.read_text(encoding="utf-8")
    assert "lint_supersession_map_append_only.py" in text, (
        "Pre-commit hook must invoke lint_supersession_map_append_only.py. "
        "Patch 4 of GOVERNANCE_DRIFT_PREVENTION_PLAN was reverted or never landed."
    )
    assert "Verifying supersession_map append-only invariant" in text, (
        "Pre-commit hook log line for the supersession check is missing."
    )
