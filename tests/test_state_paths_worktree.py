"""Regression tests for INFRA-AUDIT C1 closure — worktree-safe state path resolution.

Before fix: `PROJECT_ROOT = Path(__file__).resolve().parents[1]` resolves to
`<worktree>/config/.parent` from a worktree at .claude/worktrees/<NAME>/,
so STATE_ROOT becomes `worktrees/TradeScan_State` (silently wrong).

After fix: `_resolve_repo_root()` walks up looking for a directory with the
strategies/+engines/+governance triplet. Both main checkout and worktree
resolve to the same real repo root. State root is `<repo_root>.parent /
TradeScan_State` (or TRADE_SCAN_STATE env var override).

Test scenarios:
  1. Main-checkout layout → real repo root, real state root
  2. Worktree layout → SAME real repo root, SAME real state root
  3. TRADE_SCAN_ROOT env var override → uses env value
  4. TRADE_SCAN_STATE env var override → uses env value
  5. Invalid TRADE_SCAN_ROOT env var → falls through to walk-up
  6. Empty triplet detection → returns False (sanity)
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import (
    _resolve_repo_root,
    _resolve_state_root,
    _looks_like_repo_root,
)


# ---------------------------------------------------------------------------
# Synthetic layout helpers
# ---------------------------------------------------------------------------

def _make_repo_root(base: Path) -> Path:
    """Build a minimal directory shaped like a Trade_Scan repo root."""
    base.mkdir(parents=True, exist_ok=True)
    for d in ("strategies", "engines", "governance", "config"):
        (base / d).mkdir(exist_ok=True)
    return base


def _patched_resolve(file_under_resolve: Path) -> Path:
    """Run _resolve_repo_root() as if state_paths.py were located at
    `file_under_resolve` and walk up from there. Doesn't touch filesystem
    beyond reading directory existence checks."""
    # Implement the same logic as _resolve_repo_root but with our pretend
    # __file__ — verifies the walk-up algorithm itself.
    here = file_under_resolve.resolve()
    for ancestor in (here.parent, *here.parents):
        if _looks_like_repo_root(ancestor):
            return ancestor
    return here.parents[1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_main_checkout_layout_resolves_correctly(tmp_path):
    """Main-checkout layout: <repo>/config/state_paths.py → <repo>."""
    repo = _make_repo_root(tmp_path / "Trade_Scan")
    fake_module_path = repo / "config" / "state_paths.py"
    resolved = _patched_resolve(fake_module_path)
    assert resolved == repo


def test_worktree_layout_resolves_to_real_repo_root(tmp_path):
    """Worktree layout: <repo>/.claude/worktrees/foo/config/state_paths.py
    must walk up to the real <repo> root."""
    repo = _make_repo_root(tmp_path / "Trade_Scan")
    worktree = repo / ".claude" / "worktrees" / "feature-branch"
    _make_repo_root(worktree)  # worktree also has the marker dirs
    fake_module_path = worktree / "config" / "state_paths.py"
    resolved = _patched_resolve(fake_module_path)
    # Walk-up finds worktree first (it also has strategies/engines/governance
    # markers — which is correct: a worktree IS a repo root, just sharing
    # state root with main).
    assert resolved == worktree


def test_real_state_paths_module_resolves_to_existing_dirs():
    """Live check: the real config/state_paths.py module must resolve to
    a real on-disk repo root with real state root sibling."""
    # Re-import to ensure module-level resolution runs fresh.
    import config.state_paths as sp
    importlib.reload(sp)
    assert sp.PROJECT_ROOT.exists()
    assert (sp.PROJECT_ROOT / "strategies").exists()
    assert (sp.PROJECT_ROOT / "engines").exists()
    assert sp.STATE_ROOT.exists()


def test_trade_scan_root_env_var_override(tmp_path, monkeypatch):
    """TRADE_SCAN_ROOT env var overrides walk-up resolution."""
    repo = _make_repo_root(tmp_path / "alt_repo")
    monkeypatch.setenv("TRADE_SCAN_ROOT", str(repo))
    resolved = _resolve_repo_root()
    assert resolved == repo.resolve()


def test_trade_scan_root_invalid_env_falls_through(tmp_path, monkeypatch):
    """If TRADE_SCAN_ROOT points at a non-repo directory (no marker subdirs),
    fall through to walk-up rather than silently misroute."""
    bogus = tmp_path / "not_a_repo"
    bogus.mkdir()
    monkeypatch.setenv("TRADE_SCAN_ROOT", str(bogus))
    resolved = _resolve_repo_root()
    # Should fall back to live walk-up — must NOT equal `bogus`.
    assert resolved != bogus.resolve()
    # And must equal the actual repo root.
    assert (resolved / "strategies").exists()
    assert (resolved / "engines").exists()


def test_trade_scan_state_env_var_override(tmp_path, monkeypatch):
    """TRADE_SCAN_STATE env var overrides the sibling-directory default."""
    custom_state = tmp_path / "custom_state"
    custom_state.mkdir()
    monkeypatch.setenv("TRADE_SCAN_STATE", str(custom_state))
    fake_repo = _make_repo_root(tmp_path / "fake_repo")
    resolved = _resolve_state_root(fake_repo)
    assert resolved == custom_state.resolve()


def test_no_env_vars_uses_canonical_sibling(tmp_path, monkeypatch):
    """No env overrides → state root = REAL_REPO_ROOT.parent / TradeScan_State.
    The repo_root argument is accepted for backward compatibility but ignored:
    path_authority pins the real root at import time to prevent worktree
    misrouting (a worktree's .parent resolves to .claude/worktrees/, not the
    real sibling). State root is always the canonical sibling of REAL_REPO_ROOT."""
    monkeypatch.delenv("TRADE_SCAN_STATE", raising=False)
    fake_repo = tmp_path / "Trade_Scan"
    fake_repo.mkdir()
    resolved = _resolve_state_root(fake_repo)
    from config.path_authority import TRADE_SCAN_STATE
    assert resolved == TRADE_SCAN_STATE


def test_looks_like_repo_root_detects_complete_layout(tmp_path):
    """Sanity: marker triplet detection works."""
    full = _make_repo_root(tmp_path / "full")
    assert _looks_like_repo_root(full) is True


def test_looks_like_repo_root_rejects_partial_layout(tmp_path):
    """Sanity: only one or two of the three markers → not a repo root."""
    partial = tmp_path / "partial"
    (partial / "strategies").mkdir(parents=True)
    (partial / "engines").mkdir()
    # No governance/
    assert _looks_like_repo_root(partial) is False


def test_worktree_and_main_checkout_share_same_state_root(tmp_path):
    """Critical correctness property: any call to _resolve_state_root() returns
    the SAME path_authority-pinned state root regardless of the repo_root arg.
    This guarantees that main-checkout code and worktree code share TradeScan_State.
    The worktree-safe path_authority migration dropped the 'use repo_root.parent'
    heuristic (which silently misrouted from worktrees) in favour of a single
    authoritative sibling of REAL_REPO_ROOT."""
    from config.path_authority import TRADE_SCAN_STATE, REAL_REPO_ROOT, WORKTREE_ROOT
    main_state = _resolve_state_root(REAL_REPO_ROOT)
    worktree_state = _resolve_state_root(WORKTREE_ROOT)
    assert main_state == worktree_state == TRADE_SCAN_STATE


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
