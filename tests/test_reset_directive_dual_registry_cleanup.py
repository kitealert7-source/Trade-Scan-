"""Regression: reset_directive.py must clear the directive's run folder in BOTH
canonical-state and project-local locations.

Background
----------
`tools/orchestration/run_planner.py` writes the per-directive
``run_registry.json`` to ``project_root / "runs" / <directive_id> /`` when the
PipelineContext carries a project_root (the production path). The same file
also lives under ``RUNS_DIR / <directive_id>`` (canonical TradeScan_State).

`ensure_registry()` merges existing run entries by run_id and PRESERVES the
existing state (COMPLETE / FAILED / etc) rather than resetting to PLANNED.
Because run_ids are deterministic from the directive contents, this means a
stale ``COMPLETE`` entry left behind in the project-local registry causes
``claim_next_planned_run`` to return None on the next attempt — Stage-1 then
silently skips and the state machine reports a downstream state mismatch.

Until 2026-05-11, ``_clear_directive_run_folder`` only deleted the canonical
folder, missing the project-local one. This regression caught it on a re-run
of ``65_BRK_XAUUSD_5M_PSBRK_S02_V1_P01`` after an Excel-lock-driven failure.

This test pins the fix in place. It exercises:
  1. The targeted helper ``_clear_directive_run_folder`` directly, and
  2. The full ``reset_directive`` entry point end-to-end against a synthesized
     FAILED directive — verifying both folders are gone AND any subsequent
     DirectiveStateManager lookup sees IDLE (no stale state).
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DIRECTIVE_ID = "99_TEST_FAKE_5M_DUMMY_S00_V1_P00"


@pytest.fixture()
def isolated_state(tmp_path: Path, monkeypatch):
    """Build a tmp project + tmp state tree and redirect every module-level
    path constant reset_directive depends on.

    Returns a dict with paths for the test to populate.
    """
    project_root = tmp_path / "Trade_Scan"
    state_root = tmp_path / "TradeScan_State"
    state_runs = state_root / "runs"
    project_runs = project_root / "runs"
    audit_log = project_root / "governance" / "reset_audit_log.csv"

    project_root.mkdir(parents=True, exist_ok=True)
    state_runs.mkdir(parents=True, exist_ok=True)
    project_runs.mkdir(parents=True, exist_ok=True)
    audit_log.parent.mkdir(parents=True, exist_ok=True)

    # Import the modules whose constants we will redirect.
    import tools.reset_directive as rd
    import tools.pipeline_utils as pu

    monkeypatch.setattr(rd, "PROJECT_ROOT", project_root, raising=True)
    monkeypatch.setattr(rd, "RUNS_DIR", state_runs, raising=True)
    monkeypatch.setattr(rd, "AUDIT_LOG", audit_log, raising=True)
    monkeypatch.setattr(
        rd,
        "_DIRECTIVE_SEARCH_DIRS",
        [project_root / "backtest_directives" / d
         for d in ("INBOX", "active", "active_backup", "completed")],
        raising=True,
    )
    monkeypatch.setattr(pu, "RUNS_DIR", state_runs, raising=True)

    return {
        "project_root": project_root,
        "state_root": state_root,
        "state_runs": state_runs,
        "project_runs": project_runs,
        "audit_log": audit_log,
    }


def _seed_canonical_state(state_runs: Path, directive_id: str, status: str) -> Path:
    """Write a minimally-valid directive_state.json + run_registry.json under
    ``state_runs / <directive_id>``.
    """
    d = state_runs / directive_id
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "directive_id": directive_id,
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": status,
                "history": ["INITIALIZED", "PREFLIGHT_COMPLETE", status],
                "run_ids": ["deadbeefcafef00d12345678"],
                "run_id": "deadbeefcafef00d12345678",
            }
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    (d / "directive_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    (d / "directive_audit.log").write_text("seeded\n", encoding="utf-8")
    (d / "run_registry.json").write_text(
        json.dumps(
            {
                "version": 1,
                "directive_id": directive_id,
                "runs": [
                    {
                        "run_id": "deadbeefcafef00d12345678",
                        "strategy": directive_id,
                        "symbol": "XAUUSD",
                        "state": "COMPLETE",
                        "attempts": 1,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return d


def _seed_project_local_registry(project_runs: Path, directive_id: str) -> Path:
    """Write the project-local ``run_registry.json`` that ``run_planner`` would
    create. The fact that it carries state=COMPLETE is the whole point — that
    was the silent-skip trigger before the fix.
    """
    d = project_runs / directive_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run_registry.json").write_text(
        json.dumps(
            {
                "version": 1,
                "directive_id": directive_id,
                "runs": [
                    {
                        "run_id": "deadbeefcafef00d12345678",
                        "strategy": directive_id,
                        "symbol": "XAUUSD",
                        "state": "COMPLETE",
                        "attempts": 1,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_clear_directive_run_folder_deletes_both_locations(isolated_state):
    """Targeted unit test on the helper that does the cleanup."""
    import tools.reset_directive as rd

    state_dir = _seed_canonical_state(isolated_state["state_runs"], DIRECTIVE_ID, "FAILED")
    project_dir = _seed_project_local_registry(isolated_state["project_runs"], DIRECTIVE_ID)

    assert state_dir.exists()
    assert project_dir.exists()
    assert (state_dir / "run_registry.json").exists()
    assert (project_dir / "run_registry.json").exists()

    rd._clear_directive_run_folder(DIRECTIVE_ID)

    assert not state_dir.exists(), \
        "canonical state run folder must be deleted"
    assert not project_dir.exists(), \
        "project-local run folder must be deleted (regression: bug fix 2026-05-11)"


def test_clear_directive_run_folder_idempotent_when_clean(isolated_state):
    """Calling the helper when nothing exists must not raise."""
    import tools.reset_directive as rd

    # Neither folder exists.
    rd._clear_directive_run_folder(DIRECTIVE_ID)
    # If we got here without exception, the contract is honored.


def test_clear_directive_run_folder_handles_only_project_local(isolated_state):
    """If the canonical folder was already cleared but the project-local one
    survived (the exact pre-fix scenario), the helper must still clean it.
    """
    import tools.reset_directive as rd

    project_dir = _seed_project_local_registry(isolated_state["project_runs"], DIRECTIVE_ID)
    assert project_dir.exists()

    rd._clear_directive_run_folder(DIRECTIVE_ID)

    assert not project_dir.exists()


def test_reset_directive_end_to_end_cleans_both_locations(isolated_state):
    """Full ``reset_directive(...)`` entry point: seed FAILED + both registries,
    call reset, assert both folders gone and DirectiveStateManager reports
    no surviving state.
    """
    # Re-import to ensure the monkeypatched constants are visible to inner
    # imports (e.g. pipeline_utils.DirectiveStateManager).
    import tools.reset_directive as rd
    import tools.pipeline_utils as pu

    state_dir = _seed_canonical_state(isolated_state["state_runs"], DIRECTIVE_ID, "FAILED")
    project_dir = _seed_project_local_registry(isolated_state["project_runs"], DIRECTIVE_ID)

    # Sanity: DirectiveStateManager sees FAILED before reset.
    mgr_before = pu.DirectiveStateManager(DIRECTIVE_ID)
    assert mgr_before.get_state() == "FAILED"

    rd.reset_directive(DIRECTIVE_ID, reason="regression test — dual-registry cleanup")

    assert not state_dir.exists(), \
        "canonical run folder must be deleted by reset"
    assert not project_dir.exists(), \
        "project-local run folder must be deleted by reset (bug fix 2026-05-11)"

    # No residual registry artifacts anywhere.
    residuals = list(isolated_state["state_runs"].rglob("run_registry.json")) + \
                list(isolated_state["project_runs"].rglob("run_registry.json"))
    assert residuals == [], \
        f"residual run_registry.json files survived reset: {residuals}"

    # Next planner invocation would see no stale state — proxy: a fresh
    # DirectiveStateManager reads IDLE because the state file is gone.
    mgr_after = pu.DirectiveStateManager(DIRECTIVE_ID)
    assert mgr_after.get_state() == "IDLE", \
        "after reset, get_state() must report IDLE (no stale state survives)"

    # Audit row recorded.
    assert isolated_state["audit_log"].exists()
    audit_text = isolated_state["audit_log"].read_text(encoding="utf-8")
    assert DIRECTIVE_ID in audit_text
    assert "FAILED" in audit_text
    assert "INITIALIZED" in audit_text


def test_reset_blocks_when_state_is_idle(isolated_state):
    """Reset is only valid from FAILED or PORTFOLIO_COMPLETE. IDLE must error."""
    import tools.reset_directive as rd

    # No state seeded → DirectiveStateManager.get_state() returns IDLE → which
    # the reset_directive() entrypoint treats as "no state file" (line 184-186)
    # and exits non-zero. Confirm the cleanup is NOT performed in that case.
    _seed_project_local_registry(isolated_state["project_runs"], DIRECTIVE_ID)

    with pytest.raises(SystemExit):
        rd.reset_directive(DIRECTIVE_ID, reason="should not proceed")

    # Project-local folder must still exist — reset bailed before cleanup.
    assert (isolated_state["project_runs"] / DIRECTIVE_ID).exists()
