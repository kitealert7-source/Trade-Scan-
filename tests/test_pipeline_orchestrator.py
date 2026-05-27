"""test_pipeline_orchestrator.py — Phase 3b orchestrator semantics.

Tests both paths through PipelineOrchestrator:
  * Sequential fast-path (max_parallel=1) — direct loop, fail-fast,
    permanent first-class operational mode per Phase 3 guardrail #3.
  * Parallel path (max_parallel>=2) — ProcessPoolExecutor, collect-all-
    outcomes semantics, BrokenProcessPool recovery.

Uses mocked `run_single_directive` (via monkeypatch) to avoid spinning
up the real pipeline for orchestrator unit tests. Real-pipeline
integration testing is a Phase 4 live-ramp activity (per Phase 3
guardrail #1).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_orchestrator import (
    DirectiveResult,
    PipelineOrchestrator,
    _worker_entry,
)


class _RecordingTelemetry:
    """Captures telemetry calls so tests can assert on lifecycle events."""
    def __init__(self):
        self.events = []

    def start_directive(self, d_id):
        self.events.append(("start", d_id))

    def end_directive(self, d_id, error=None):
        self.events.append(("end", d_id, error))

    def emit(self, d_id, stage_id, event, **kwargs):
        self.events.append(("emit", d_id, event, kwargs))


# ---------------------------------------------------------------------------
# Sequential fast-path (max_parallel=1)
# ---------------------------------------------------------------------------


class TestSequentialFastPath:

    def test_runs_directives_in_order(self, monkeypatch):
        calls = []
        def _fake_rsd(d_id, provision_only=False):
            calls.append(d_id)
        monkeypatch.setattr("tools.run_pipeline.run_single_directive", _fake_rsd)

        orc = PipelineOrchestrator(batch_id="b1", max_parallel=1)
        results = orc.run_batch(["DIR_A", "DIR_B", "DIR_C"])

        assert calls == ["DIR_A", "DIR_B", "DIR_C"], (
            "sequential mode must invoke directives in submitted order"
        )
        assert len(results) == 3
        assert all(r.status == "completed" for r in results)

    def test_results_sorted_by_directive_id(self, monkeypatch):
        monkeypatch.setattr(
            "tools.run_pipeline.run_single_directive",
            lambda d_id, provision_only=False: None,
        )
        orc = PipelineOrchestrator(batch_id="b1", max_parallel=1)
        results = orc.run_batch(["ZETA", "ALPHA", "MIDDLE"])
        ids = [r.directive_id for r in results]
        assert ids == sorted(ids), f"sequential results must be sorted, got {ids}"

    def test_fail_fast_on_first_error(self, monkeypatch):
        from tools.orchestration.pipeline_errors import PipelineError

        calls = []
        def _fake_rsd(d_id, provision_only=False):
            calls.append(d_id)
            if d_id == "DIR_B":
                raise PipelineError(f"boom at {d_id}")
        monkeypatch.setattr("tools.run_pipeline.run_single_directive", _fake_rsd)

        orc = PipelineOrchestrator(batch_id="b1", max_parallel=1)
        with pytest.raises(PipelineError, match="boom at DIR_B"):
            orc.run_batch(["DIR_A", "DIR_B", "DIR_C"])

        # DIR_C must NOT have run (fail-fast preserved)
        assert calls == ["DIR_A", "DIR_B"], (
            "sequential mode must fail-fast — DIR_C should not have run"
        )

    def test_telemetry_lifecycle_emitted(self, monkeypatch):
        monkeypatch.setattr(
            "tools.run_pipeline.run_single_directive",
            lambda d_id, provision_only=False: None,
        )
        rec = _RecordingTelemetry()
        orc = PipelineOrchestrator(batch_id="b1", max_parallel=1, telemetry=rec)
        orc.run_batch(["DIR_A", "DIR_B"])
        assert rec.events == [
            ("start", "DIR_A"),
            ("end", "DIR_A", None),
            ("start", "DIR_B"),
            ("end", "DIR_B", None),
        ]

    def test_telemetry_records_error_on_failure(self, monkeypatch):
        from tools.orchestration.pipeline_errors import PipelineError
        def _fake_rsd(d_id, provision_only=False):
            raise PipelineError("nope")
        monkeypatch.setattr("tools.run_pipeline.run_single_directive", _fake_rsd)
        rec = _RecordingTelemetry()
        orc = PipelineOrchestrator(batch_id="b1", max_parallel=1, telemetry=rec)
        with pytest.raises(PipelineError):
            orc.run_batch(["DIR_A"])
        # end_directive was called with the error message
        assert rec.events[0] == ("start", "DIR_A")
        assert rec.events[1][0] == "end"
        assert rec.events[1][1] == "DIR_A"
        assert "nope" in (rec.events[1][2] or "")


# ---------------------------------------------------------------------------
# Parallel path (max_parallel>=2)
# ---------------------------------------------------------------------------


def _worker_entry_for_test_completed(batch_id, directive_id, provision_only):
    """Picklable replacement worker that always returns 'completed'.
    Module-level so ProcessPoolExecutor can pickle it."""
    return (directive_id, "completed", None)


def _worker_entry_for_test_mixed(batch_id, directive_id, provision_only):
    """Half-success/half-fail picklable worker."""
    if "FAIL" in directive_id:
        return (directive_id, "failed", f"PipelineError: simulated failure of {directive_id}")
    return (directive_id, "completed", None)


class TestParallelPath:

    def test_results_sorted_by_directive_id(self, monkeypatch):
        """Parallel completion order is non-deterministic; orchestrator
        must sort results by directive_id before returning."""
        monkeypatch.setattr(
            "tools.pipeline_orchestrator._worker_entry",
            _worker_entry_for_test_completed,
        )
        orc = PipelineOrchestrator(batch_id="b1", max_parallel=2)
        # Submit in non-sorted order
        results = orc.run_batch(["ZETA", "ALPHA", "MIDDLE_B", "MIDDLE_A"])
        ids = [r.directive_id for r in results]
        assert ids == sorted(ids), f"parallel results must be sorted, got {ids}"
        assert all(r.status == "completed" for r in results)

    def test_collects_all_outcomes_not_fail_fast(self, monkeypatch):
        """Parallel mode runs every directive to completion (or to its
        own failure). Failures don't stop other directives."""
        monkeypatch.setattr(
            "tools.pipeline_orchestrator._worker_entry",
            _worker_entry_for_test_mixed,
        )
        orc = PipelineOrchestrator(batch_id="b1", max_parallel=2)
        results = orc.run_batch([
            "DIR_OK_001", "DIR_FAIL_001",
            "DIR_OK_002", "DIR_FAIL_002",
        ])
        # ALL directives produced a result (parallel mode doesn't fail-fast)
        assert len(results) == 4
        by_id = {r.directive_id: r for r in results}
        assert by_id["DIR_OK_001"].status == "completed"
        assert by_id["DIR_OK_002"].status == "completed"
        assert by_id["DIR_FAIL_001"].status == "failed"
        assert by_id["DIR_FAIL_002"].status == "failed"
        assert "simulated failure" in by_id["DIR_FAIL_001"].error

    def test_invalid_max_parallel_raises(self):
        with pytest.raises(ValueError, match="max_parallel must be"):
            PipelineOrchestrator(batch_id="b1", max_parallel=0)
        with pytest.raises(ValueError, match="max_parallel must be"):
            PipelineOrchestrator(batch_id="b1", max_parallel=-1)


# ---------------------------------------------------------------------------
# DirectiveResult value semantics
# ---------------------------------------------------------------------------


class TestDirectiveResult:

    def test_immutable_dataclass(self):
        r = DirectiveResult("DIR_001", "completed")
        with pytest.raises(Exception):
            r.status = "failed"  # frozen=True

    def test_default_error_is_none(self):
        r = DirectiveResult("DIR_001", "completed")
        assert r.error is None

    def test_status_values_documented(self):
        # Sanity — make sure the 3 documented statuses round-trip
        for status in ("completed", "failed", "worker_died"):
            r = DirectiveResult("DIR_001", status, error="x" if status != "completed" else None)
            assert r.status == status
