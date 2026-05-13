"""Canonical path authority for Trade_Scan and its sibling repos.

Every tool that needs to locate the real repo root, a sibling repo,
the git common dir, or shared data must import from here. No tool
should compute these paths inline. Inline computation is the bug
class this module was created to eliminate.

Bug class — naive sibling resolution from a worktree:
  `STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"`
  In a worktree at `Trade_Scan/.claude/worktrees/<n>/`, PROJECT_ROOT
  is the worktree dir, so PROJECT_ROOT.parent is `.claude/worktrees/`,
  not the user's container folder. Sibling reads return MISSING and
  writes go to a stale `worktrees/TradeScan_State/` leftover (which
  exists because prior sessions created it), silently diverging from
  the real shared state.

Marker discipline:
  Real repo root = the directory whose `.git` is a *directory* (the
  actual gitdir). In a worktree, `.git` is a *file* containing a
  `gitdir:` pointer. Worktrees mirror tracked content, so any
  marker-by-tracked-files test (strategies/, engines/, governance/)
  produces a false positive on the worktree dir itself. `.git.is_dir()`
  is the only marker git itself can't fake.

Env-var overrides:
  Each sibling has an env-var escape hatch for CI / Docker / cross-
  checkout shells where the canonical layout doesn't apply. Set the
  variable to an absolute path; it takes precedence over discovery.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    # Resolved roots
    "REAL_REPO_ROOT",
    "WORKTREE_ROOT",
    "GIT_COMMON_DIR",
    # Active siblings
    "TRADE_SCAN_STATE",
    "TS_EXECUTION",
    "DRY_RUN_VAULT",
    "ANTI_GRAVITY_DATA_ROOT",
    "VALIDATION_DATASET",
    # Shared data layer (anchored on REAL_REPO_ROOT, not WORKTREE_ROOT)
    "DATA_ROOT",
    "FRESHNESS_INDEX",
    # Helpers
    "find_real_repo_root",
    "is_worktree",
]


# ---------------------------------------------------------------------------
# Repo root resolution
# ---------------------------------------------------------------------------


def find_real_repo_root(start: Path) -> Path:
    """Walk up from `start` until `.git` is a directory.

    `.git is_dir()` is True only at the real repo root. Inside a
    worktree, `.git` is a file (`gitdir: <repo>/.git/worktrees/<n>`)
    so the walk-up continues past the worktree dir until it lands on
    the real Trade_Scan root.

    Falls back to `start` so a non-git checkout (rare — vendored
    snapshot, CI extract) still has a usable anchor instead of
    raising at import time.
    """
    cur = start
    for _ in range(8):
        if (cur / ".git").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


# This file lives at <repo>/config/path_authority.py — `parent.parent`
# is the dir containing config/, i.e. the worktree dir (in a worktree)
# or the real repo root (in main).
WORKTREE_ROOT: Path = Path(__file__).resolve().parent.parent


def _resolve_real_repo_root() -> Path:
    """Honor TRADE_SCAN_ROOT env override, else discover via marker."""
    env = os.environ.get("TRADE_SCAN_ROOT")
    if env:
        candidate = Path(env).resolve()
        if (candidate / ".git").is_dir():
            return candidate
        # If env is set but invalid, fall through (don't silently misroute).
    return find_real_repo_root(WORKTREE_ROOT)


REAL_REPO_ROOT: Path = _resolve_real_repo_root()
GIT_COMMON_DIR: Path = REAL_REPO_ROOT / ".git"


def is_worktree() -> bool:
    """True iff we're imported from a git worktree (not the main checkout)."""
    return WORKTREE_ROOT != REAL_REPO_ROOT


# ---------------------------------------------------------------------------
# Sibling repo resolution
# ---------------------------------------------------------------------------


def _resolve_sibling(name: str, env_var: str) -> Path:
    """Sibling repo adjacent to REAL_REPO_ROOT.

    Env var override takes precedence. The path is returned whether
    or not it exists on disk so downstream callers can surface
    'MISSING' meaningfully instead of getting a silently-wrong
    fallback.
    """
    env = os.environ.get(env_var)
    if env:
        return Path(env).resolve()
    return REAL_REPO_ROOT.parent / name


# Active siblings — referenced by current Trade_Scan tooling.
TRADE_SCAN_STATE: Path = _resolve_sibling("TradeScan_State", "TRADE_SCAN_STATE")
TS_EXECUTION: Path = _resolve_sibling("TS_Execution", "TS_EXECUTION_ROOT")
DRY_RUN_VAULT: Path = _resolve_sibling("DRY_RUN_VAULT", "DRY_RUN_VAULT_ROOT")
ANTI_GRAVITY_DATA_ROOT: Path = _resolve_sibling(
    "Anti_Gravity_DATA_ROOT", "ANTI_GRAVITY_DATA_ROOT"
)
# Immutable frozen corpus root — sibling to DRY_RUN_VAULT (Section 1m, Phase 7a.0).
# Each corpus is a subdirectory: VALIDATION_DATASET/{corpus_id}/ with manifest.json.
# Never create a junction or symlink pointing at this path — Section 1m-iii.
VALIDATION_DATASET: Path = _resolve_sibling("VALIDATION_DATASET", "VALIDATION_DATASET_ROOT")

# Reserved peer projects — not currently referenced from Trade_Scan code.
# Uncomment + add the env-var override the first time tooling needs them:
#   DATA_INGRESS = _resolve_sibling("DATA_INGRESS", "DATA_INGRESS_ROOT")
#   TS_ENGINE    = _resolve_sibling("TS_Engine",    "TS_ENGINE_ROOT")
#   TS_PINE      = _resolve_sibling("TS_Pine",      "TS_PINE_ROOT")


# ---------------------------------------------------------------------------
# Shared data layer
# ---------------------------------------------------------------------------
# `data_root/` at the repo root is a local-only symlink (not tracked)
# pointing at Anti_Gravity_DATA_ROOT. Worktrees do not inherit it, so
# a worktree's `WORKTREE_ROOT / "data_root"` is either missing or a
# stale local copy. Always anchor on REAL_REPO_ROOT for shared data.

DATA_ROOT: Path = REAL_REPO_ROOT / "data_root"
# DATA_INGRESS writes freshness_index.json into the MASTER_DATA subdirectory;
# Trade_Scan reads from there directly to avoid the manual copy step.
FRESHNESS_INDEX: Path = ANTI_GRAVITY_DATA_ROOT / "MASTER_DATA" / "freshness_index.json"
