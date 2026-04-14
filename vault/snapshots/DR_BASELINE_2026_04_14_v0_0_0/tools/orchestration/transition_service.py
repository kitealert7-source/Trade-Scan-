"""Centralized transition helpers for run/directive state machines."""

from __future__ import annotations

from typing import Iterable

from tools.pipeline_utils import DirectiveStateManager, PipelineStateManager
from config.status_enums import RUN_TERMINAL_STATES


def get_run_state(run_id: str) -> str:
    """Return current run state, defaulting to IDLE when absent/corrupt."""
    return PipelineStateManager(run_id).get_state_data().get("current_state", "IDLE")


def get_directive_state(directive_id: str) -> str:
    """Return current directive state, defaulting to IDLE when absent/corrupt."""
    return DirectiveStateManager(directive_id).get_state()


def transition_run_state(run_id: str, new_state: str) -> None:
    """Strict transition for a symbol run."""
    PipelineStateManager(run_id).transition_to(new_state)


def transition_directive_state(directive_id: str, new_state: str) -> None:
    """Strict transition for a directive."""
    DirectiveStateManager(directive_id).transition_to(new_state)


def transition_run_state_if(
    run_id: str,
    new_state: str,
    allowed_current_states: Iterable[str],
) -> bool:
    """
    Transition only when current state is in allowed_current_states.
    Returns True when transitioned, False when skipped.
    """
    allowed = set(allowed_current_states)
    current = get_run_state(run_id)
    if current not in allowed:
        return False
    transition_run_state(run_id, new_state)
    return True


def transition_run_states_if(
    run_ids: Iterable[str],
    new_state: str,
    allowed_current_states: Iterable[str],
) -> list[str]:
    """Bulk conditional transition. Returns transitioned run IDs."""
    transitioned: list[str] = []
    for run_id in run_ids:
        if transition_run_state_if(run_id, new_state, allowed_current_states):
            transitioned.append(run_id)
    return transitioned


def transition_run_state_sequence(run_id: str, sequence: Iterable[str]) -> None:
    """Apply a strict ordered transition sequence to one run."""
    for state in sequence:
        transition_run_state(run_id, state)


def fail_run_best_effort(run_id: str, warn_prefix: str = "[WARN]") -> bool:
    """
    Mark run as FAILED when non-terminal.
    Returns True when transitioned, False when skipped/failed.
    """
    mgr = PipelineStateManager(run_id)
    if not mgr.state_file.exists():
        return False
    current = get_run_state(run_id)
    if current in RUN_TERMINAL_STATES:
        return False
    try:
        transition_run_state(run_id, "FAILED")
        return True
    except Exception as exc:
        print(f"{warn_prefix} Failed to mark run {run_id} as FAILED: {exc}")
        return False


def fail_runs_best_effort(run_ids: Iterable[str], warn_prefix: str = "[WARN]") -> list[str]:
    """Best-effort FAILED transition for many runs. Returns transitioned run IDs."""
    transitioned: list[str] = []
    for run_id in run_ids:
        if fail_run_best_effort(run_id, warn_prefix=warn_prefix):
            transitioned.append(run_id)
    return transitioned


def fail_directive_best_effort(directive_id: str, warn_prefix: str = "[WARN]") -> bool:
    """
    Mark directive as FAILED where allowed.
    Returns True when transitioned, False when skipped/failed.
    """
    current = get_directive_state(directive_id)
    if current == "FAILED":
        return False
    try:
        transition_directive_state(directive_id, "FAILED")
        return True
    except Exception as exc:
        print(f"{warn_prefix} Failed to mark directive as FAILED: {exc}")
        return False

