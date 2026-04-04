"""
Centralized status constants for the Trade_Scan pipeline.

Single source of truth for all status strings used across modules.
Import from here — never hardcode status strings in tool code.

Grouped by domain:
  - RUN_*        : PipelineStateManager FSM states (run_state.json)
  - PORTFOLIO_*  : Portfolio ledger status (Master_Portfolio_Sheet.xlsx)
  - REGISTRY_*   : System registry run status (run_registry.json)
  - DIRECTIVE_*  : Directive lifecycle states (directive_state.json)
  - LIFECYCLE_*  : portfolio.yaml lifecycle field
"""

# ---------------------------------------------------------------------------
# Run FSM states (PipelineStateManager.ALLOWED_TRANSITIONS)
# ---------------------------------------------------------------------------
RUN_IDLE = "IDLE"
RUN_PREFLIGHT_COMPLETE = "PREFLIGHT_COMPLETE"
RUN_PREFLIGHT_SEMANTICALLY_VALID = "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID"
RUN_STAGE_1_COMPLETE = "STAGE_1_COMPLETE"
RUN_STAGE_2_COMPLETE = "STAGE_2_COMPLETE"
RUN_STAGE_3_COMPLETE = "STAGE_3_COMPLETE"
RUN_STAGE_3A_COMPLETE = "STAGE_3A_COMPLETE"
RUN_COMPLETE = "COMPLETE"
RUN_FAILED = "FAILED"
RUN_ABORTED = "ABORTED"

RUN_TERMINAL_STATES = frozenset({RUN_COMPLETE, RUN_FAILED, RUN_ABORTED})
RUN_ACTIVE_STATES = frozenset({
    RUN_PREFLIGHT_COMPLETE,
    RUN_PREFLIGHT_SEMANTICALLY_VALID,
    RUN_STAGE_1_COMPLETE,
    RUN_STAGE_2_COMPLETE,
    RUN_STAGE_3_COMPLETE,
    RUN_STAGE_3A_COMPLETE,
})
RUN_ALL_STATES = frozenset({RUN_IDLE}) | RUN_ACTIVE_STATES | RUN_TERMINAL_STATES

# ---------------------------------------------------------------------------
# Portfolio ledger status (Master_Portfolio_Sheet.xlsx :: portfolio_status)
# ---------------------------------------------------------------------------
PORTFOLIO_CORE = "CORE"
PORTFOLIO_WATCH = "WATCH"
PORTFOLIO_FAIL = "FAIL"
PORTFOLIO_PROFILE_UNRESOLVED = "PROFILE_UNRESOLVED"

PORTFOLIO_STATUSES = frozenset({
    PORTFOLIO_CORE,
    PORTFOLIO_WATCH,
    PORTFOLIO_FAIL,
    PORTFOLIO_PROFILE_UNRESOLVED,
})

# Statuses that block execution / require operator attention
PORTFOLIO_BLOCKED_STATUSES = frozenset({
    PORTFOLIO_FAIL,
    PORTFOLIO_PROFILE_UNRESOLVED,
})

# ---------------------------------------------------------------------------
# System registry run status (run_registry.json :: status)
# ---------------------------------------------------------------------------
REGISTRY_COMPLETE = "complete"
REGISTRY_FAILED = "failed"
REGISTRY_INVALID = "invalid"
REGISTRY_ABORTED = "aborted"
REGISTRY_QUARANTINED = "quarantined"

REGISTRY_RECLAIMABLE = frozenset({
    REGISTRY_FAILED,
    REGISTRY_INVALID,
    REGISTRY_ABORTED,
    "interrupted",
})

# ---------------------------------------------------------------------------
# Directive lifecycle states (directive_state.json :: status)
# ---------------------------------------------------------------------------
DIRECTIVE_PORTFOLIO_COMPLETE = "PORTFOLIO_COMPLETE"
DIRECTIVE_FAILED = "FAILED"

DIRECTIVE_TERMINAL = frozenset({DIRECTIVE_PORTFOLIO_COMPLETE, DIRECTIVE_FAILED})

# ---------------------------------------------------------------------------
# portfolio.yaml lifecycle field
# ---------------------------------------------------------------------------
LIFECYCLE_LEGACY = "LEGACY"
LIFECYCLE_BURN_IN = "BURN_IN"
LIFECYCLE_WAITING = "WAITING"
LIFECYCLE_LIVE = "LIVE"
LIFECYCLE_DISABLED = "DISABLED"
