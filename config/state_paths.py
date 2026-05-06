import os
from pathlib import Path

__all__ = [
    "PROJECT_ROOT",
    "STATE_ROOT",
    "RUNS_DIR",
    "STRATEGIES_DIR",
    "REGISTRY_DIR",
    "ARCHIVE_DIR",
    "QUARANTINE_DIR",
    "LOGS_DIR",
    "BACKTESTS_DIR",
    "POOL_DIR",
    "SELECTED_DIR",
    "RUN_DIRS_IN_LOOKUP_ORDER",
    "MASTER_FILTER_PATH",
    "CANDIDATE_FILTER_PATH",
    "LEDGER_DB_PATH",
    "initialize_state_directories",
    "resolve_base_strategy_dir",
    "resolve_run_dir",
    "iter_run_dirs",
    "_resolve_repo_root",
    "_resolve_state_root",
]


# ---------------------------------------------------------------------------
# Repo + state root resolution (worktree-safe)
# ---------------------------------------------------------------------------
# Anchored on config.path_authority — single source of truth for repo and
# sibling resolution (uses `.git.is_dir()` marker to distinguish the real
# repo root from a worktree mirror).
#
# Public-API compatibility: the legacy resolvers (_looks_like_repo_root,
# _resolve_repo_root, _resolve_state_root) are preserved as thin wrappers
# so existing callers (governance, tests, mocked unit tests) keep working.
# New code should import from config.path_authority directly.

from config.path_authority import (
    REAL_REPO_ROOT as _REAL_REPO_ROOT,
    WORKTREE_ROOT as _WORKTREE_ROOT,
    TRADE_SCAN_STATE as _TRADE_SCAN_STATE,
    find_real_repo_root as _path_authority_find,
)

_REPO_MARKER_DIRS = ("strategies", "engines", "governance")


def _looks_like_repo_root(p: Path) -> bool:
    """A directory is the repo root iff it has all three marker subdirs.

    Retained for backward compatibility — callers that historically used
    this predicate continue to work. New code should rely on
    `config.path_authority` which uses `.git.is_dir()` (strictly correct
    even when worktrees mirror the marker subdirs).
    """
    return all((p / m).is_dir() for m in _REPO_MARKER_DIRS)


def _resolve_repo_root() -> Path:
    """Resolve the repo root for this checkout.

    Honors TRADE_SCAN_ROOT env var at call time so tests can override.
    When not set, returns WORKTREE_ROOT (the dir containing this config/),
    preserving the historical semantic that PROJECT_ROOT is "where this
    code is running from". Sibling-repo paths (TradeScan_State, etc.)
    use REAL_REPO_ROOT internally regardless.
    """
    env = os.environ.get("TRADE_SCAN_ROOT")
    if env:
        candidate = Path(env).resolve()
        if _looks_like_repo_root(candidate):
            return candidate
    return _WORKTREE_ROOT


def _resolve_state_root(repo_root: Path) -> Path:
    """Resolve the TradeScan_State directory.

    Honors TRADE_SCAN_STATE env var, else returns the canonical sibling
    of the real repo root. The `repo_root` argument is accepted for
    backward compatibility but ignored when path_authority has already
    pinned the real root — passing a worktree dir here used to silently
    misroute to `worktrees/TradeScan_State` (a stale leftover); we now
    return the authoritative sibling regardless of what the caller
    happened to pass in.
    """
    env = os.environ.get("TRADE_SCAN_STATE")
    if env:
        return Path(env).resolve()
    return _TRADE_SCAN_STATE


# Repository Root (worktree-safe via path_authority)
PROJECT_ROOT = _resolve_repo_root()

# Research State Root (Sibling to Repository)
STATE_ROOT = _resolve_state_root(PROJECT_ROOT)

# Physical Lifecycle Directories (authoritative path definitions — do not rename folders)
# DEPRECATED (internal): _SANDBOX_DIR, CANDIDATES_DIR — access via POOL_DIR / SELECTED_DIR only
RUNS_DIR       = STATE_ROOT / "runs"
_SANDBOX_DIR   = STATE_ROOT / "sandbox"    # INTERNAL ONLY — not exported. Use POOL_DIR.
CANDIDATES_DIR = STATE_ROOT / "candidates" # physical folder: TradeScan_State/candidates
STRATEGIES_DIR = STATE_ROOT / "strategies"
REGISTRY_DIR   = STATE_ROOT / "registry"
ARCHIVE_DIR    = STATE_ROOT / "archive"
QUARANTINE_DIR = STATE_ROOT / "quarantine"
LOGS_DIR       = STATE_ROOT / "logs"
BACKTESTS_DIR  = STATE_ROOT / "backtests"

# Logical Aliases (semantic naming — the ONLY valid references for external code)
# pool     → TradeScan_State/sandbox     (filter output staging area)
# selected → TradeScan_State/candidates  (promotion-ready strategies)
POOL_DIR     = _SANDBOX_DIR   # strategies that have cleared the Master Filter
SELECTED_DIR = CANDIDATES_DIR # strategies selected for portfolio consideration

# Canonical run-directory lookup order.
#
# Runs begin life in RUNS_DIR (Stage 1 writes here), then migrate to POOL_DIR
# once they pass the Master Filter (see tools/filter_strategies.py), and may
# be staged in SELECTED_DIR as portfolio candidates. Every READER that needs
# to locate an existing run's artifacts MUST iterate this tuple (or go through
# resolve_run_dir / iter_run_dirs below) so lookups stay consistent across
# the codebase. Writers that always target RUNS_DIR (Stage-1 emit, reset,
# watchdog) continue to reference RUNS_DIR directly.
RUN_DIRS_IN_LOOKUP_ORDER = (RUNS_DIR, POOL_DIR, SELECTED_DIR)

# Derived Paths
MASTER_FILTER_PATH    = POOL_DIR     / "Strategy_Master_Filter.xlsx"
CANDIDATE_FILTER_PATH = SELECTED_DIR / "Filtered_Strategies_Passed.xlsx"
LEDGER_DB_PATH        = STATE_ROOT   / "ledger.db"

def resolve_base_strategy_dir(sid: str, artifact: str = "portfolio_evaluation") -> Path | None:
    """Resolve a per-symbol strategy ID to its base artifact directory.

    Multi-symbol strategies share artifacts under the base directive ID.
    E.g. ``22_CONT_..._P06_AUDUSD`` resolves to ``strategies/22_CONT_..._P06/``.

    Returns the first ``STRATEGIES_DIR / candidate / artifact`` that exists,
    walking backwards through underscore-separated tokens.  Returns *None*
    if no match is found.

    Usage::

        pe_dir = resolve_base_strategy_dir(sid, "portfolio_evaluation")
        deploy = resolve_base_strategy_dir(sid, "deployable")
    """
    # Direct match first (most common case — single-symbol or base ID itself)
    direct = STRATEGIES_DIR / sid / artifact
    if direct.exists() and any(direct.iterdir()):
        return direct

    # Walk backwards: strip trailing tokens until a base match is found
    parts = sid.split("_")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "_".join(parts[:i])
        candidate_dir = STRATEGIES_DIR / candidate / artifact
        if candidate_dir.exists() and any(candidate_dir.iterdir()):
            return candidate_dir

    return None


def resolve_run_dir(run_id: str, require_data: bool = True) -> Path:
    """Return the physical directory holding ``run_id``'s artifacts.

    Single source of truth for "where does this run live right now?". Probes
    RUN_DIRS_IN_LOOKUP_ORDER and returns the first match. Replaces callers
    that hardcoded a single location and silently broke after the run was
    migrated from RUNS_DIR to POOL_DIR (see 2026-04-21 portfolio_evaluator
    incident on run 56fdb79f... — the loader only checked RUNS_DIR even
    though every post-filter run lives in POOL_DIR).

    Args:
        run_id:       The atomic run UUID (folder name under one of the run dirs).
        require_data: If True, the returned path is the ``data/`` subdir and
                      the probe skips folders that lack it (guards against
                      partially-written runs). If False, returns the run home.

    Returns:
        ``<dir>/<run_id>/data`` when require_data, else ``<dir>/<run_id>``.

    Raises:
        FileNotFoundError: No location holds the run. Message lists every
            directory probed so a corrupt pipeline state is obvious.
    """
    for base in RUN_DIRS_IN_LOOKUP_ORDER:
        home = base / run_id
        if not home.exists():
            continue
        if require_data:
            data = home / "data"
            if data.exists():
                return data
            continue
        return home
    probed = ", ".join(str(d) for d in RUN_DIRS_IN_LOOKUP_ORDER)
    raise FileNotFoundError(
        f"Governance violation: run directory missing for {run_id!r} "
        f"(probed {probed}; require_data={require_data})"
    )


def iter_run_dirs():
    """Yield ``(run_id, home_path)`` for every run on disk, in lookup priority.

    Order mirrors RUN_DIRS_IN_LOOKUP_ORDER: RUNS_DIR first, then POOL_DIR,
    then SELECTED_DIR. First-seen wins, so a run that appears in multiple
    locations (should never happen outside a mid-migration window) is yielded
    exactly once from its highest-priority location. Only folders with a
    ``data/`` subdir are yielded — half-written run homes are skipped.

    Used by reconciliation and cleanup paths that need a full sweep; for a
    single-run lookup use resolve_run_dir.
    """
    seen: set[str] = set()
    for base in RUN_DIRS_IN_LOOKUP_ORDER:
        if not base.exists():
            continue
        for item in base.iterdir():
            if item.is_dir() and item.name not in seen and (item / "data").exists():
                seen.add(item.name)
                yield item.name, item


def initialize_state_directories():
    """Silent initialization of the research state infrastructure."""
    STATE_ROOT.mkdir(parents=True, exist_ok=True)

    directories = [
        RUNS_DIR,
        POOL_DIR,
        SELECTED_DIR,
        STRATEGIES_DIR,
        REGISTRY_DIR,
        ARCHIVE_DIR,
        QUARANTINE_DIR,
        LOGS_DIR,
        BACKTESTS_DIR,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Deprecation Guard — module-level __getattr__ (Python 3.7+)
# Triggered only for names NOT in this module's __dict__.
# SANDBOX_DIR is intentionally absent from __dict__ — any import or attribute
# access will hit this guard and raise immediately.
# ---------------------------------------------------------------------------
_DEPRECATED = {
    "SANDBOX_DIR": "SANDBOX_DIR is deprecated. Use POOL_DIR instead.",
}

def __getattr__(name: str):
    if name in _DEPRECATED:
        raise RuntimeError(
            f"[state_paths] {_DEPRECATED[name]}\n"
            f"  Deprecated:  config.state_paths.{name}\n"
            f"  Use instead: config.state_paths.POOL_DIR"
        )
    raise AttributeError(f"module 'config.state_paths' has no attribute {name!r}")
