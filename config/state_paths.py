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
    "MASTER_FILTER_PATH",
    "CANDIDATE_FILTER_PATH",
    "LEDGER_DB_PATH",
    "initialize_state_directories",
    "resolve_base_strategy_dir",
]

# Repository Root
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Research State Root (Sibling to Repository)
STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"

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
