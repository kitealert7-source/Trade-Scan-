"""Lock: a QUARANTINED run releases identity ownership in BOTH ownership gates.

A run marked ``status='quarantined'`` in run_registry.json is the operator's
"preserved-but-analytically-invalid" signal (config.status_enums.REGISTRY_QUARANTINED,
now a member of REGISTRY_RECLAIMABLE). Its run_id, artifacts, and ledger row are
kept forever (append-only, auditable), but it must NOT own its strategy/sweep
identity — so the concept can be re-tested under its own identity.

This pins the two ownership gates that previously keyed on raw run existence:
  1. sweep reclaim     -> tools.sweep_registry_gate._can_reclaim_sweep
  2. first-exec anchor -> tools.system_registry._get_directive_first_execution_timestamp

Control cases assert a live 'complete' run STILL owns (regression guard) and that
the pre-existing failure states are unchanged.
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.sweep_registry_gate as G  # noqa: E402
import tools.system_registry as SR  # noqa: E402

DIRECTIVE = "11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S04_V1_P00"


def _entry(run_id, status, created_at="2026-06-24T16:59:20+00:00"):
    # Distinctive run_ids so is_zero_artifact_terminal_run (which reads the real
    # runs/ dir) never matches an on-disk run and interferes with the assertion.
    return {
        "run_id": run_id,
        "directive_hash": DIRECTIVE,
        "status": status,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Gate 1 — sweep reclaim (_can_reclaim_sweep reads the run registry via
# _load_registry, imported into the gate module).
# ---------------------------------------------------------------------------
def test_quarantined_run_releases_sweep_slot(monkeypatch):
    reg = {"qid_quar_1": _entry("qid_quar_1", "quarantined")}
    monkeypatch.setattr(G, "_load_registry", lambda: reg)
    assert G._can_reclaim_sweep(DIRECTIVE) is True


def test_complete_run_still_blocks_sweep_reclaim(monkeypatch):
    reg = {"qid_comp_1": _entry("qid_comp_1", "complete")}
    monkeypatch.setattr(G, "_load_registry", lambda: reg)
    assert G._can_reclaim_sweep(DIRECTIVE) is False


def test_one_live_complete_among_quarantined_still_blocks(monkeypatch):
    reg = {
        "qid_quar_2": _entry("qid_quar_2", "quarantined"),
        "qid_comp_2": _entry("qid_comp_2", "complete"),
    }
    monkeypatch.setattr(G, "_load_registry", lambda: reg)
    assert G._can_reclaim_sweep(DIRECTIVE) is False


def test_failed_run_reclaimable_regression(monkeypatch):
    # Pre-existing behaviour must be unchanged for the original failure states.
    reg = {"qid_fail_1": _entry("qid_fail_1", "failed")}
    monkeypatch.setattr(G, "_load_registry", lambda: reg)
    assert G._can_reclaim_sweep(DIRECTIVE) is True


# ---------------------------------------------------------------------------
# Gate 2 — first-exec anchor (_get_directive_first_execution_timestamp reads
# REGISTRY_PATH directly; RUNS_DIR is the fallback scan root).
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_registry(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    reg_path = tmp_path / "run_registry.json"
    monkeypatch.setattr(SR, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(SR, "RUNS_DIR", runs)

    def _write(reg):
        reg_path.write_text(json.dumps(reg), encoding="utf-8")

    return _write


def test_quarantined_run_clears_first_exec_anchor(temp_registry):
    temp_registry({"qid_quar_3": _entry("qid_quar_3", "quarantined")})
    assert SR._get_directive_first_execution_timestamp(DIRECTIVE) is None


def test_complete_run_anchors_first_exec_control(temp_registry):
    temp_registry({"qid_comp_3": _entry("qid_comp_3", "complete")})
    assert SR._get_directive_first_execution_timestamp(DIRECTIVE) is not None


def test_quarantined_earlier_run_does_not_anchor_over_complete(temp_registry):
    # The quarantined run is the EARLIER timestamp; without the skip it would win
    # the min() and anchor first-exec at 06-24. With the skip, the anchor is the
    # live complete run at 06-25.
    temp_registry({
        "qid_quar_4": _entry("qid_quar_4", "quarantined", "2026-06-24T16:00:00+00:00"),
        "qid_comp_4": _entry("qid_comp_4", "complete", "2026-06-25T10:00:00+00:00"),
    })
    ts = SR._get_directive_first_execution_timestamp(DIRECTIVE)
    assert ts is not None
    assert ts.isoformat().startswith("2026-06-25")
