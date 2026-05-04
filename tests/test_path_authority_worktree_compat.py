"""Regression coverage for config/path_authority.py — the canonical
path-resolution authority that replaces ad-hoc PROJECT_ROOT.parent
sibling math across the codebase.

Bug class this guards against:
  Naive `STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"` from a
  worktree at `Trade_Scan/.claude/worktrees/<n>/` resolves to
  `.claude/worktrees/TradeScan_State` — a stale leftover from prior
  sessions exists at exactly that path, so the bug is silent: writes
  succeed against the wrong directory. The fix anchors on the real
  Trade_Scan repo root via `.git.is_dir()` (worktrees have `.git` as
  a *file* containing `gitdir:` — only the real repo has `.git/` as
  a directory).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixture: synthesize a Trade_Scan repo + worktree layout in tmp_path
# ---------------------------------------------------------------------------


def _seed_repo_and_worktree(tmp: Path) -> dict:
    """Lay down:
      <tmp>/Trade_Scan/                 ← real repo, .git is a directory
      <tmp>/Trade_Scan/.claude/worktrees/session-x/    ← worktree, .git is a file
      <tmp>/Trade_Scan/.claude/worktrees/TradeScan_State/  ← stale leftover (the trap)
      <tmp>/TradeScan_State/            ← real sibling
      <tmp>/TS_Execution/               ← real sibling
      <tmp>/DRY_RUN_VAULT/              ← real sibling
      <tmp>/Anti_Gravity_DATA_ROOT/     ← real sibling
    Returns a dict of all the paths for assertions.
    """
    main = tmp / "Trade_Scan"
    main.mkdir()
    (main / ".git").mkdir()  # marker: real repo

    worktree_root = main / ".claude" / "worktrees"
    worktree_root.mkdir(parents=True)

    worktree = worktree_root / "session-x"
    worktree.mkdir()
    (worktree / ".git").write_text(
        f"gitdir: {main / '.git' / 'worktrees' / 'session-x'}\n",
        encoding="utf-8",
    )

    # The trap — stale leftover at the path naive walk-up would land on.
    stale = worktree_root / "TradeScan_State"
    stale.mkdir()

    real_state = tmp / "TradeScan_State"
    real_state.mkdir()
    real_exec = tmp / "TS_Execution"
    real_exec.mkdir()
    real_vault = tmp / "DRY_RUN_VAULT"
    real_vault.mkdir()
    real_data = tmp / "Anti_Gravity_DATA_ROOT"
    real_data.mkdir()

    return {
        "main": main,
        "worktree": worktree,
        "stale": stale,
        "real_state": real_state,
        "real_exec": real_exec,
        "real_vault": real_vault,
        "real_data": real_data,
    }


def _import_path_authority_with_root(start: Path):
    """Reload path_authority with WORKTREE_ROOT pinned to `start`.

    path_authority resolves WORKTREE_ROOT from `__file__` at import
    time, so we can't easily relocate the module file. Instead, import
    the module then patch its WORKTREE_ROOT and recompute downstream
    constants — the same effect as if the module had been imported
    from the patched location.
    """
    import config.path_authority as pa

    pa.WORKTREE_ROOT = start.resolve()
    pa.REAL_REPO_ROOT = pa.find_real_repo_root(pa.WORKTREE_ROOT)
    pa.GIT_COMMON_DIR = pa.REAL_REPO_ROOT / ".git"
    pa.TRADE_SCAN_STATE = pa._resolve_sibling("TradeScan_State", "TRADE_SCAN_STATE")
    pa.TS_EXECUTION = pa._resolve_sibling("TS_Execution", "TS_EXECUTION_ROOT")
    pa.DRY_RUN_VAULT = pa._resolve_sibling("DRY_RUN_VAULT", "DRY_RUN_VAULT_ROOT")
    pa.ANTI_GRAVITY_DATA_ROOT = pa._resolve_sibling(
        "Anti_Gravity_DATA_ROOT", "ANTI_GRAVITY_DATA_ROOT"
    )
    pa.DATA_ROOT = pa.REAL_REPO_ROOT / "data_root"
    pa.FRESHNESS_INDEX = pa.DATA_ROOT / "freshness_index.json"
    return pa


# ---------------------------------------------------------------------------
# find_real_repo_root — `.git.is_dir()` marker
# ---------------------------------------------------------------------------


class TestFindRealRepoRoot:

    def test_from_main_repo_returns_main(self, tmp_path):
        layout = _seed_repo_and_worktree(tmp_path)
        from config.path_authority import find_real_repo_root

        assert find_real_repo_root(layout["main"]) == layout["main"]

    def test_from_worktree_walks_up_to_main(self, tmp_path):
        layout = _seed_repo_and_worktree(tmp_path)
        from config.path_authority import find_real_repo_root

        # From the worktree dir, walk-up should bypass `.claude/worktrees/`
        # (which has `.git` as a file, not a directory) and land on the
        # real repo where `.git` is a directory.
        assert find_real_repo_root(layout["worktree"]) == layout["main"], (
            "Resolver must walk past worktree dirs (where .git is a file) "
            "and stop only at the real repo (where .git is a directory). "
            "See config/path_authority.py:find_real_repo_root."
        )

    def test_worktree_dir_is_not_mistaken_for_repo_root(self, tmp_path):
        """Worktrees mirror tracked content. Old marker-by-tracked-files
        test (strategies/+engines/+governance/) returns True for the
        worktree dir itself. `.git.is_dir()` is the only correct
        marker — verify the resolver doesn't stop early."""
        layout = _seed_repo_and_worktree(tmp_path)
        # Add the marker triplet to the worktree to simulate a
        # tracked-file mirror — old resolver would have stopped here.
        (layout["worktree"] / "strategies").mkdir()
        (layout["worktree"] / "engines").mkdir()
        (layout["worktree"] / "governance").mkdir()

        from config.path_authority import find_real_repo_root

        assert find_real_repo_root(layout["worktree"]) == layout["main"], (
            "Resolver must not fall for tracked-file marker mirrors in "
            "worktrees. The discriminator is .git.is_dir(), not the "
            "presence of strategies/engines/governance subdirs."
        )

    def test_no_git_anywhere_falls_back_to_start(self, tmp_path):
        """Non-git checkouts (vendored snapshot, CI extract) should not
        raise — fall back to the start dir."""
        from config.path_authority import find_real_repo_root

        non_git = tmp_path / "snapshot"
        non_git.mkdir()
        assert find_real_repo_root(non_git) == non_git


# ---------------------------------------------------------------------------
# Sibling resolution
# ---------------------------------------------------------------------------


class TestSiblingResolution:

    def test_siblings_anchor_on_real_root_from_worktree(self, tmp_path, monkeypatch):
        """All four siblings must resolve to <real_root>.parent / <name>,
        regardless of whether import happened from main or from a
        worktree. This is the core regression: pre-fix, sibling reads
        from a worktree silently routed to `worktrees/<name>` (the trap)."""
        layout = _seed_repo_and_worktree(tmp_path)
        # Clear any env-var overrides that would shadow discovery.
        for var in (
            "TRADE_SCAN_ROOT",
            "TRADE_SCAN_STATE",
            "TS_EXECUTION_ROOT",
            "DRY_RUN_VAULT_ROOT",
            "ANTI_GRAVITY_DATA_ROOT",
        ):
            monkeypatch.delenv(var, raising=False)

        pa = _import_path_authority_with_root(layout["worktree"])

        assert pa.REAL_REPO_ROOT == layout["main"]
        assert pa.TRADE_SCAN_STATE == layout["real_state"], (
            f"Got {pa.TRADE_SCAN_STATE}, expected {layout['real_state']}. "
            f"Resolver picked the stale leftover at {layout['stale']} — "
            f"the bug class this module exists to eliminate."
        )
        assert pa.TS_EXECUTION == layout["real_exec"]
        assert pa.DRY_RUN_VAULT == layout["real_vault"]
        assert pa.ANTI_GRAVITY_DATA_ROOT == layout["real_data"]

    def test_siblings_anchor_on_real_root_from_main(self, tmp_path, monkeypatch):
        """Same expectation from main checkout — should be a no-op
        regression from old behavior, but assert it explicitly so a
        future refactor can't break the common case."""
        layout = _seed_repo_and_worktree(tmp_path)
        for var in (
            "TRADE_SCAN_ROOT",
            "TRADE_SCAN_STATE",
            "TS_EXECUTION_ROOT",
            "DRY_RUN_VAULT_ROOT",
            "ANTI_GRAVITY_DATA_ROOT",
        ):
            monkeypatch.delenv(var, raising=False)

        pa = _import_path_authority_with_root(layout["main"])
        assert pa.TRADE_SCAN_STATE == layout["real_state"]
        assert pa.TS_EXECUTION == layout["real_exec"]
        assert pa.DRY_RUN_VAULT == layout["real_vault"]

    def test_env_var_override_takes_precedence(self, tmp_path, monkeypatch):
        """TRADE_SCAN_STATE env var must override discovery — useful
        for CI / Docker / cross-checkout shells."""
        layout = _seed_repo_and_worktree(tmp_path)
        custom = tmp_path / "Custom_State"
        custom.mkdir()
        monkeypatch.setenv("TRADE_SCAN_STATE", str(custom))

        pa = _import_path_authority_with_root(layout["worktree"])
        assert pa.TRADE_SCAN_STATE == custom.resolve()


# ---------------------------------------------------------------------------
# DATA_ROOT anchors on REAL_REPO_ROOT
# ---------------------------------------------------------------------------


class TestDataRootAnchoring:

    def test_data_root_uses_real_root_not_worktree(self, tmp_path, monkeypatch):
        """data_root/ is a non-tracked symlink at the real repo. From a
        worktree we still want to read from the real repo's data_root
        (the worktree's data_root is either missing or stale). Anchor
        must be REAL_REPO_ROOT, not WORKTREE_ROOT."""
        layout = _seed_repo_and_worktree(tmp_path)
        for var in ("TRADE_SCAN_ROOT",):
            monkeypatch.delenv(var, raising=False)

        pa = _import_path_authority_with_root(layout["worktree"])

        assert pa.DATA_ROOT == layout["main"] / "data_root", (
            f"DATA_ROOT must anchor on REAL_REPO_ROOT (got {pa.DATA_ROOT}). "
            f"Anchoring on WORKTREE_ROOT would point at the worktree's "
            f"local data_root which is either missing or a stale copy."
        )
        assert pa.FRESHNESS_INDEX == pa.DATA_ROOT / "freshness_index.json"


# ---------------------------------------------------------------------------
# is_worktree
# ---------------------------------------------------------------------------


class TestIsWorktree:

    def test_true_when_in_worktree(self, tmp_path, monkeypatch):
        layout = _seed_repo_and_worktree(tmp_path)
        for var in ("TRADE_SCAN_ROOT",):
            monkeypatch.delenv(var, raising=False)
        pa = _import_path_authority_with_root(layout["worktree"])
        assert pa.is_worktree() is True

    def test_false_when_in_main(self, tmp_path, monkeypatch):
        layout = _seed_repo_and_worktree(tmp_path)
        for var in ("TRADE_SCAN_ROOT",):
            monkeypatch.delenv(var, raising=False)
        pa = _import_path_authority_with_root(layout["main"])
        assert pa.is_worktree() is False
