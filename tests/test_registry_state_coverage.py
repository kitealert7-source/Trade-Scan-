"""Coverage CI test for registry status vocabulary + full reconciler matrix.

Plan: outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md Task E (E2).
Sibling: tests/test_state_lifecycle_sheet_coverage.py (E1).

Locks in the registry state-machine contract introduced 2026-05-28:

  1. tools.system_registry.REGISTRY_STATUS_VOCABULARY enumerates every
     valid status string with a terminal/non-terminal classification.
     Drift guard: every status string written into the live registry
     must appear in the vocabulary.

  2. reconcile_registry() must define behavior for every cell of the
     (status × physical_state) matrix. 8 reachable cells; the 9th —
     "no registry entry + folder missing" — is not reachable by
     definition. Each cell test sets up a synthetic fixture and asserts
     the reconciler's observable effect.

Cells covered (8 reachable):

  | status      | physical_state    | expected reconcile behavior     |
  |-------------|-------------------|---------------------------------|
  | complete    | runs/             | no-op                           |
  | complete    | missing           | transition: complete -> invalid |
  | complete    | quarantine/       | transition: complete -> quarantined |
  | invalid     | runs/             | transition: invalid -> complete |
  | invalid     | missing           | no-op (terminal tombstone)      |
  | invalid     | quarantine/       | transition: invalid -> quarantined |
  | quarantined | runs/             | move folder runs/ -> quarantine/runs/ |
  | quarantined | missing           | drop entry (operator-purged)    |
  | quarantined | quarantine/       | no-op                           |

Failure modes prevented:
  - Vocabulary drift (new status writers without reconciler awareness).
  - Matrix-completeness gaps (today's YELLOW: the 2026-05-27 basket
    cleanup left registry=quarantined but folder still in runs/; the
    reconciler had no cell-7 behavior, so preflight flagged forever).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import system_registry
from tools.system_registry import REGISTRY_STATUS_VOCABULARY


# ---------------------------------------------------------------------------
# Vocabulary contract tests
# ---------------------------------------------------------------------------

def test_vocabulary_has_required_keys_and_shape() -> None:
    assert REGISTRY_STATUS_VOCABULARY, "REGISTRY_STATUS_VOCABULARY is empty"
    for status, value in REGISTRY_STATUS_VOCABULARY.items():
        assert isinstance(status, str) and status, f"bad status key {status!r}"
        assert isinstance(value, tuple) and len(value) == 2, (
            f"vocabulary[{status!r}] must be (terminal:bool, description:str)"
        )
        terminal, desc = value
        assert isinstance(terminal, bool), f"terminal flag for {status!r} must be bool"
        assert isinstance(desc, str) and desc.strip(), (
            f"description for {status!r} must be non-empty"
        )


def test_live_registry_statuses_are_in_vocabulary() -> None:
    if not system_registry.REGISTRY_PATH.exists():
        pytest.skip(f"registry not present at {system_registry.REGISTRY_PATH}")
    reg = json.loads(system_registry.REGISTRY_PATH.read_text(encoding="utf-8"))
    live = {str(e.get("status")) for e in reg.values() if e.get("status")}
    unknown = sorted(s for s in live if s not in REGISTRY_STATUS_VOCABULARY)
    assert not unknown, (
        f"Live registry contains undocumented status(es) {unknown}. "
        f"Add to REGISTRY_STATUS_VOCABULARY in tools/system_registry.py "
        f"or fix the writer that introduced the drift."
    )


# ---------------------------------------------------------------------------
# Matrix-cell fixtures + helpers
# ---------------------------------------------------------------------------

def _install_isolated_state(tmp_path: Path, monkeypatch) -> dict:
    """Patch every directory reconcile reads from to a tmp fixture root."""
    fake = tmp_path / "state"
    runs_dir = fake / "runs"
    selected_dir = fake / "selected"
    quarantine_dir = fake / "quarantine"
    registry_dir = fake / "registry"
    for d in (runs_dir, selected_dir, quarantine_dir / "runs", registry_dir):
        d.mkdir(parents=True, exist_ok=True)

    reg_path = registry_dir / "run_registry.json"
    lock_path = reg_path.with_suffix(".lock")

    monkeypatch.setattr(system_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(system_registry, "LOCK_PATH", lock_path)
    monkeypatch.setattr(system_registry, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(system_registry, "SELECTED_DIR", selected_dir)
    monkeypatch.setattr(system_registry, "QUARANTINE_DIR", quarantine_dir)
    monkeypatch.setattr(
        system_registry, "RUN_DIRS_IN_LOOKUP_ORDER", (runs_dir, selected_dir)
    )
    return {
        "runs_dir": runs_dir,
        "quarantine_dir": quarantine_dir,
        "reg_path": reg_path,
    }


def _make_folder(parent: Path, run_id: str) -> Path:
    """Create a synthetic run folder shaped like real ones (has data/)."""
    folder = parent / run_id
    (folder / "data").mkdir(parents=True, exist_ok=True)
    return folder


def _seed_registry(reg_path: Path, run_id: str, status: str) -> None:
    reg_path.write_text(
        json.dumps(
            {
                run_id: {
                    "run_id": run_id,
                    "status": status,
                    "tier": "sandbox",
                    "directive_hash": "test_directive_hash",
                }
            }
        ),
        encoding="utf-8",
    )


def _run_reconcile() -> dict:
    """Run reconcile with the heavy side-effects patched out."""
    with patch.object(system_registry, "log_event"), \
         patch.object(system_registry, "get_active_portfolio_runs", return_value=set()):
        return system_registry.reconcile_registry()


def _load(reg_path: Path) -> dict:
    return json.loads(reg_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Matrix cell tests — 8 reachable cells
# ---------------------------------------------------------------------------

def test_cell_complete_in_runs_noop(tmp_path, monkeypatch):
    """status=complete + folder in runs/ -> no-op."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _make_folder(st["runs_dir"], "rid")
    _seed_registry(st["reg_path"], "rid", "complete")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "complete"


def test_cell_complete_missing_to_invalid(tmp_path, monkeypatch):
    """status=complete + folder missing -> transition to invalid."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _seed_registry(st["reg_path"], "rid", "complete")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "invalid"


def test_cell_complete_in_quarantine_to_quarantined(tmp_path, monkeypatch):
    """status=complete + folder in quarantine/runs/ -> transition to quarantined."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _make_folder(st["quarantine_dir"] / "runs", "rid")
    _seed_registry(st["reg_path"], "rid", "complete")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "quarantined"


def test_cell_invalid_in_runs_restored_to_complete(tmp_path, monkeypatch):
    """status=invalid + folder reappears in runs/ -> restore to complete."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _make_folder(st["runs_dir"], "rid")
    _seed_registry(st["reg_path"], "rid", "invalid")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "complete"


def test_cell_invalid_missing_noop_tombstone(tmp_path, monkeypatch):
    """status=invalid + folder missing -> no-op (terminal tombstone)."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _seed_registry(st["reg_path"], "rid", "invalid")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "invalid"


def test_cell_invalid_in_quarantine_to_quarantined(tmp_path, monkeypatch):
    """status=invalid + folder in quarantine/runs/ -> transition to quarantined."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _make_folder(st["quarantine_dir"] / "runs", "rid")
    _seed_registry(st["reg_path"], "rid", "invalid")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "quarantined"


def test_cell_quarantined_in_runs_moves_folder_to_quarantine(tmp_path, monkeypatch):
    """status=quarantined + folder in runs/ -> filesystem move to quarantine/runs/.

    Closes today's persistent YELLOW: registry intent (quarantined) was
    set but the folder move never happened. Reconcile completes the move.
    Registry status stays quarantined; physical location catches up.
    """
    st = _install_isolated_state(tmp_path, monkeypatch)
    src = _make_folder(st["runs_dir"], "rid")
    _seed_registry(st["reg_path"], "rid", "quarantined")
    _run_reconcile()
    post = _load(st["reg_path"])
    assert post["rid"]["status"] == "quarantined", "status must remain quarantined"
    assert not src.exists(), "source folder in runs/ should have been moved"
    assert (st["quarantine_dir"] / "runs" / "rid").exists(), (
        "folder should have been moved to quarantine/runs/"
    )


def test_cell_quarantined_missing_drops_entry(tmp_path, monkeypatch):
    """status=quarantined + folder absent everywhere -> drop entry."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _seed_registry(st["reg_path"], "rid", "quarantined")
    _run_reconcile()
    assert "rid" not in _load(st["reg_path"]), (
        "reconcile should drop quarantined entries whose physical folder "
        "is absent from both runs/ and quarantine/runs/"
    )


def test_cell_quarantined_in_quarantine_noop(tmp_path, monkeypatch):
    """status=quarantined + folder in quarantine/runs/ -> no-op."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    _make_folder(st["quarantine_dir"] / "runs", "rid")
    _seed_registry(st["reg_path"], "rid", "quarantined")
    _run_reconcile()
    assert _load(st["reg_path"])["rid"]["status"] == "quarantined"


# ---------------------------------------------------------------------------
# Pathological case: folder in BOTH runs/ AND quarantine/runs/
# ---------------------------------------------------------------------------

def test_quarantined_dual_location_does_not_clobber(tmp_path, monkeypatch):
    """Folder in BOTH runs/ AND quarantine/runs/ -> reconcile must NOT
    silently overwrite the quarantine copy. Leave both, log, defer triage."""
    st = _install_isolated_state(tmp_path, monkeypatch)
    src = _make_folder(st["runs_dir"], "rid")
    dst = _make_folder(st["quarantine_dir"] / "runs", "rid")
    _seed_registry(st["reg_path"], "rid", "quarantined")
    _run_reconcile()
    assert src.exists(), "source must not be moved when destination already exists"
    assert dst.exists(), "destination must not be overwritten"
