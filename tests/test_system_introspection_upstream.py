"""Regression tests for system_introspection upstream resolution.

Before fix: `collect_git()` hard-coded `origin/main..HEAD` for the
unpushed-commit count. On any feature branch, this reported phantom
"N commits not pushed" even when the branch was fully in sync with its
own upstream — leading to a false `SESSION STATUS: BROKEN` flag at
session-close.

After fix: the unpushed count is computed against the CURRENT branch's
actual `@{u}` upstream. Detached HEAD and no-upstream cases return
non-int sentinels so they don't trigger the BROKEN gate.

These tests build minimal local-only git repos (no network) and exercise
the four scenarios the user called out:
    1. main branch with upstream
    2. feature branch with upstream
    3. detached HEAD
    4. branch with no upstream configured
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTRO_PATH = PROJECT_ROOT / "tools" / "system_introspection.py"

_spec = importlib.util.spec_from_file_location("system_introspection", INTRO_PATH)
_intro = importlib.util.module_from_spec(_spec)
sys.modules["system_introspection"] = _intro
_spec.loader.exec_module(_intro)


def _git(cwd: Path, *args: str) -> str:
    """Run git in `cwd` with deterministic identity. Returns stdout."""
    env_overrides = {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    import os
    env = {**os.environ, **env_overrides}
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=15)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout


def _make_remote_and_clone(tmp_path: Path, default_branch: str = "main") -> tuple[Path, Path]:
    """Create a bare 'remote' repo and a working clone tracking it.

    Returns (remote_path, clone_path). The clone has one commit on
    `default_branch` and that branch tracks `origin/<default_branch>`.
    """
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", f"--initial-branch={default_branch}")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", f"--initial-branch={default_branch}")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", default_branch)

    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(remote), "clone")
    return remote, clone


# ---------------------------------------------------------------------------
# 1. main branch with upstream
# ---------------------------------------------------------------------------

def test_main_branch_with_upstream_resolves_to_origin_main(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path, default_branch="main")
    ref, kind = _intro._resolve_upstream(clone)
    assert kind == "tracked"
    assert ref == "origin/main"


def test_main_branch_in_sync_reports_zero_ahead(tmp_path, monkeypatch):
    _, clone = _make_remote_and_clone(tmp_path, default_branch="main")
    monkeypatch.setattr(_intro, "PROJECT_ROOT", clone)
    git = _intro.collect_git()
    assert git["upstream_kind"] == "tracked"
    assert git["upstream"] == "origin/main"
    assert git["commits_ahead"] == 0


# ---------------------------------------------------------------------------
# 2. feature branch with upstream  (the original bug class)
# ---------------------------------------------------------------------------

def test_feature_branch_with_upstream_uses_its_own_upstream(tmp_path, monkeypatch):
    """The bug: previous code compared HEAD to origin/main, so on a feature
    branch this falsely reported "N commits not pushed" even when the
    branch was fully in sync with origin/<branch>.

    After the fix, the count is against the feature branch's own upstream.
    """
    remote, clone = _make_remote_and_clone(tmp_path, default_branch="main")
    # Create a feature branch with its own upstream, divergent from main
    _git(clone, "checkout", "-b", "spike/foo")
    (clone / "feature.txt").write_text("x\n", encoding="utf-8")
    _git(clone, "add", "feature.txt")
    _git(clone, "commit", "-m", "feature work")
    _git(clone, "push", "-u", "origin", "spike/foo")

    monkeypatch.setattr(_intro, "PROJECT_ROOT", clone)
    git = _intro.collect_git()
    assert git["upstream_kind"] == "tracked"
    assert git["upstream"] == "origin/spike/foo"
    # In sync with its own upstream → 0
    assert git["commits_ahead"] == 0, (
        f"Expected 0 ahead of origin/spike/foo (the branch's upstream), "
        f"got {git['commits_ahead']}. The bug being regressed: comparing "
        f"to origin/main would have returned 1 (the unique feature commit)."
    )


def test_feature_branch_one_local_commit_ahead_of_its_upstream(tmp_path, monkeypatch):
    """Sanity: when there genuinely IS an unpushed commit on the feature
    branch, we still see it (the fix isn't masking real unpushed work)."""
    _, clone = _make_remote_and_clone(tmp_path, default_branch="main")
    _git(clone, "checkout", "-b", "spike/foo")
    (clone / "f1.txt").write_text("a\n", encoding="utf-8")
    _git(clone, "add", "f1.txt")
    _git(clone, "commit", "-m", "pushed")
    _git(clone, "push", "-u", "origin", "spike/foo")
    # Now make a local commit that is NOT pushed
    (clone / "f2.txt").write_text("b\n", encoding="utf-8")
    _git(clone, "add", "f2.txt")
    _git(clone, "commit", "-m", "local-only")

    monkeypatch.setattr(_intro, "PROJECT_ROOT", clone)
    git = _intro.collect_git()
    assert git["upstream_kind"] == "tracked"
    assert git["upstream"] == "origin/spike/foo"
    assert git["commits_ahead"] == 1


# ---------------------------------------------------------------------------
# 3. detached HEAD
# ---------------------------------------------------------------------------

def test_detached_head_reports_na_not_int(tmp_path, monkeypatch):
    _, clone = _make_remote_and_clone(tmp_path, default_branch="main")
    # Make a second commit so we have something to detach onto
    (clone / "x.txt").write_text("x\n", encoding="utf-8")
    _git(clone, "add", "x.txt")
    _git(clone, "commit", "-m", "second")
    head_sha = _git(clone, "rev-parse", "HEAD").strip()
    # Detach
    _git(clone, "checkout", "--detach", head_sha)

    ref, kind = _intro._resolve_upstream(clone)
    assert kind == "detached"
    assert ref is None

    monkeypatch.setattr(_intro, "PROJECT_ROOT", clone)
    git = _intro.collect_git()
    assert git["upstream_kind"] == "detached"
    # CRITICAL: must not be an int — that would trigger the BROKEN gate in
    # compute_session_status (line "isinstance(commits_ahead, int) and >0").
    assert not isinstance(git["commits_ahead"], int)
    assert "detached" in git["commits_ahead"].lower()


# ---------------------------------------------------------------------------
# 4. branch with no upstream configured
# ---------------------------------------------------------------------------

def test_no_upstream_configured_reports_na_not_int(tmp_path, monkeypatch):
    _, clone = _make_remote_and_clone(tmp_path, default_branch="main")
    # Create a branch but DO NOT push or set upstream
    _git(clone, "checkout", "-b", "local-only-branch")
    (clone / "z.txt").write_text("z\n", encoding="utf-8")
    _git(clone, "add", "z.txt")
    _git(clone, "commit", "-m", "no-upstream")

    ref, kind = _intro._resolve_upstream(clone)
    assert kind == "no_upstream"
    assert ref is None

    monkeypatch.setattr(_intro, "PROJECT_ROOT", clone)
    git = _intro.collect_git()
    assert git["upstream_kind"] == "no_upstream"
    assert not isinstance(git["commits_ahead"], int)
    assert "upstream" in git["commits_ahead"].lower()


# ---------------------------------------------------------------------------
# Cross-cut: compute_session_status does NOT flag BROKEN on non-int sentinels
# ---------------------------------------------------------------------------

def _ok_engine_freshness():
    """Stub engine + freshness dicts that wouldn't trigger BROKEN on their own."""
    engine = {"manifest": "VALID", "version": "v1_5_8a"}
    freshness = {"status": "OK", "latest_bar": "2026-05-03", "stale_symbols": 0}
    return engine, freshness


def test_session_status_ok_when_branch_in_sync():
    engine, freshness = _ok_engine_freshness()
    git = {"commits_ahead": 0, "working_tree": "clean", "upstream_kind": "tracked"}
    status, _ = _intro.compute_session_status(engine, freshness, git)
    assert status == "OK"


def test_session_status_not_broken_on_detached_head():
    engine, freshness = _ok_engine_freshness()
    git = {"commits_ahead": "n/a (detached HEAD)", "working_tree": "clean",
           "upstream_kind": "detached"}
    status, reasons = _intro.compute_session_status(engine, freshness, git)
    assert status != "BROKEN", f"detached HEAD must not flag BROKEN; got {status}: {reasons}"


def test_session_status_not_broken_on_no_upstream():
    engine, freshness = _ok_engine_freshness()
    git = {"commits_ahead": "n/a (no upstream configured)", "working_tree": "clean",
           "upstream_kind": "no_upstream"}
    status, reasons = _intro.compute_session_status(engine, freshness, git)
    assert status != "BROKEN", f"no-upstream branch must not flag BROKEN; got {status}: {reasons}"


def test_session_status_broken_on_real_unpushed_commits():
    """The BROKEN gate is still active when commits_ahead is a real positive int."""
    engine, freshness = _ok_engine_freshness()
    git = {"commits_ahead": 3, "working_tree": "clean", "upstream_kind": "tracked"}
    status, reasons = _intro.compute_session_status(engine, freshness, git)
    assert status == "BROKEN"
    assert any("3 commits not pushed" in r for r in reasons)


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
