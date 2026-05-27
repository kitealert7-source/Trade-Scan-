"""test_pipeline_telemetry.py — schema, durability, and aggregator coverage.

Phase 1 of the cross-directive parallelization plan. These tests must pass
before Phase 2/3 add the Stage-3/4 file locks and the orchestrator. The
telemetry sink is the diagnostic instrument for everything that follows —
if it's wrong, every later phase loses its diagnosability.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_telemetry import (
    TelemetryWriter,
    batch_summary,
    generate_batch_id,
    merge_batch_files,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tw(tmp_path):
    """Fresh TelemetryWriter pointing at an isolated tmp sink."""
    return TelemetryWriter(batch_id="testbatch", sink_dir=tmp_path)


# ---------------------------------------------------------------------------
# batch_id generator
# ---------------------------------------------------------------------------


class TestGenerateBatchId:

    def test_format_is_iso_timestamp_with_uuid_suffix(self):
        bid = generate_batch_id()
        # YYYY-MM-DDTHH-MM-SSZ_xxxxxxxx — 20 + 1 + 8 = 29 chars total
        assert len(bid) == 29
        assert bid[4] == "-" and bid[7] == "-" and bid[10] == "T"
        assert bid[19] == "Z" and bid[20] == "_"
        # Suffix is 8 hex chars
        assert all(c in "0123456789abcdef" for c in bid[21:])

    def test_two_calls_in_same_second_differ(self):
        a = generate_batch_id()
        b = generate_batch_id()
        # Even if timestamps match (same-second), the uuid suffix makes
        # collisions astronomically unlikely.
        assert a != b


# ---------------------------------------------------------------------------
# Schema correctness
# ---------------------------------------------------------------------------


class TestEmitSchema:

    def test_canonical_fields_present_on_every_emit(self, tw):
        tw.emit("DIR_001", "PREFLIGHT", "stage_start")
        rows = _read_rows(tw.path)
        assert len(rows) == 1
        row = rows[0]
        for required in (
            "timestamp_utc", "batch_id", "worker_pid",
            "directive_id", "stage_id", "event",
        ):
            assert required in row, f"missing required field {required!r}"
        assert row["batch_id"] == "testbatch"
        assert row["worker_pid"] == os.getpid()
        assert row["directive_id"] == "DIR_001"
        assert row["stage_id"] == "PREFLIGHT"
        assert row["event"] == "stage_start"

    def test_extra_fields_merge_alongside_canonical(self, tw):
        tw.emit("DIR_001", "PORTFOLIO", "barrier_acquired",
                lock_name="stage4.lock", stage4_lock_wait_ms=42)
        rows = _read_rows(tw.path)
        row = rows[0]
        assert row["lock_name"] == "stage4.lock"
        assert row["stage4_lock_wait_ms"] == 42

    def test_extra_field_collision_with_canonical_is_renamed(self, tw):
        """Defensive: if caller passes batch_id=... in extras, the
        canonical batch_id stays authoritative and the conflict is
        surfaced under `extra_batch_id` rather than silently dropped."""
        tw.emit("DIR_001", "PREFLIGHT", "stage_start", batch_id="wrong")
        row = _read_rows(tw.path)[0]
        assert row["batch_id"] == "testbatch"  # canonical preserved
        assert row["extra_batch_id"] == "wrong"  # conflict surfaced

    def test_batch_level_event_allows_null_directive_stage(self, tw):
        tw.emit(None, None, "batch_start")
        row = _read_rows(tw.path)[0]
        assert row["directive_id"] is None
        assert row["stage_id"] is None
        assert row["event"] == "batch_start"


# ---------------------------------------------------------------------------
# JSONL file durability
# ---------------------------------------------------------------------------


class TestFileDurability:

    def test_file_is_jsonl_parseable(self, tw):
        tw.emit("DIR_001", "PREFLIGHT", "stage_start")
        tw.emit("DIR_001", "PREFLIGHT", "stage_end", duration_ms=100)
        text = tw.path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # raises on malformed

    def test_filename_includes_pid_suffix(self, tw):
        assert f"__pid_{os.getpid()}" in tw.path.name

    def test_separate_pid_files_dont_collide(self, tmp_path):
        """Two writers with the same batch_id but different pid suffixes
        (simulating Phase 3 workers) write to separate files."""
        tw1 = TelemetryWriter(batch_id="x", sink_dir=tmp_path)
        tw1.worker_pid = 1001
        tw1.path = tmp_path / f"x__pid_1001.jsonl"
        tw2 = TelemetryWriter(batch_id="x", sink_dir=tmp_path)
        tw2.worker_pid = 2002
        tw2.path = tmp_path / f"x__pid_2002.jsonl"

        tw1.emit("D1", "PREFLIGHT", "stage_start")
        tw2.emit("D2", "PREFLIGHT", "stage_start")
        assert tw1.path.exists() and tw2.path.exists()
        assert tw1.path != tw2.path
        assert len(_read_rows(tw1.path)) == 1
        assert len(_read_rows(tw2.path)) == 1


# ---------------------------------------------------------------------------
# Stage context manager
# ---------------------------------------------------------------------------


class TestStageContextManager:

    def test_emits_start_then_end_with_duration(self, tw):
        # 30ms sleep + 20ms floor — Windows time.sleep granularity (~15ms)
        # makes shorter intervals register as 0ms intermittently.
        with tw.stage("DIR_001", "PREFLIGHT"):
            time.sleep(0.030)
        rows = _read_rows(tw.path)
        assert len(rows) == 2
        assert rows[0]["event"] == "stage_start"
        assert rows[1]["event"] == "stage_end"
        assert isinstance(rows[1]["duration_ms"], int)
        assert rows[1]["duration_ms"] >= 20

    def test_records_duration_even_on_exception(self, tw):
        # Sleep 30ms — comfortably above Windows time.sleep granularity
        # (~15ms on some configs) so duration_ms is reliably non-zero.
        with pytest.raises(RuntimeError, match="boom"):
            with tw.stage("DIR_001", "PORTFOLIO"):
                time.sleep(0.030)
                raise RuntimeError("boom")
        rows = _read_rows(tw.path)
        assert len(rows) == 2
        end_row = rows[1]
        assert end_row["event"] == "stage_end"
        assert isinstance(end_row["duration_ms"], int)
        assert end_row["duration_ms"] >= 20  # generous floor for clock granularity
        assert "RuntimeError: boom" in end_row["error"]


# ---------------------------------------------------------------------------
# Directive lifecycle helpers
# ---------------------------------------------------------------------------


class TestDirectiveLifecycle:

    def test_end_directive_records_wall_ms(self, tw):
        tw.start_directive("DIR_001")
        time.sleep(0.050)  # 50ms — well above Windows time.sleep granularity
        tw.end_directive("DIR_001")
        rows = _read_rows(tw.path)
        assert rows[0]["event"] == "directive_started"
        assert rows[1]["event"] == "directive_completed"
        assert isinstance(rows[1]["directive_wall_ms"], int)
        assert rows[1]["directive_wall_ms"] >= 30  # generous floor

    def test_end_directive_with_error_emits_directive_failed(self, tw):
        tw.start_directive("DIR_001")
        tw.end_directive("DIR_001", error="PipelineError: stage 1 blew up")
        rows = _read_rows(tw.path)
        assert rows[1]["event"] == "directive_failed"
        assert rows[1]["error"] == "PipelineError: stage 1 blew up"

    def test_queued_started_completed_lifecycle(self, tw):
        """Phase 3+ full lifecycle: orchestrator queues, worker starts,
        worker completes. Queue time = started - queued; run time =
        completed - started; total = directive_wall_ms (started→completed).
        """
        tw.queue_directive("DIR_001")
        time.sleep(0.020)
        tw.start_directive("DIR_001")
        time.sleep(0.030)
        tw.end_directive("DIR_001")
        rows = _read_rows(tw.path)
        events = [r["event"] for r in rows]
        assert events == ["directive_queued", "directive_started", "directive_completed"]
        # directive_wall_ms covers only started→completed, not queued→completed
        assert isinstance(rows[2]["directive_wall_ms"], int)
        assert rows[2]["directive_wall_ms"] >= 20  # ≥ the 30ms run sleep (with floor)


# ---------------------------------------------------------------------------
# Aggregator — merge_batch_files
# ---------------------------------------------------------------------------


class TestMergeBatchFiles:

    def test_chronological_merge_across_pid_files(self, tmp_path):
        # Two writers simulating two worker processes
        tw1 = TelemetryWriter(batch_id="b1", sink_dir=tmp_path)
        tw1.worker_pid = 100
        tw1.path = tmp_path / "b1__pid_100.jsonl"
        tw2 = TelemetryWriter(batch_id="b1", sink_dir=tmp_path)
        tw2.worker_pid = 200
        tw2.path = tmp_path / "b1__pid_200.jsonl"

        # Interleave emissions across writers in real time order
        tw1.emit("D_A", "PREFLIGHT", "stage_start")
        time.sleep(0.001)
        tw2.emit("D_B", "PREFLIGHT", "stage_start")
        time.sleep(0.001)
        tw1.emit("D_A", "PREFLIGHT", "stage_end", duration_ms=1)
        time.sleep(0.001)
        tw2.emit("D_B", "PREFLIGHT", "stage_end", duration_ms=1)

        merged = merge_batch_files("b1", sink_dir=tmp_path)
        assert len(merged) == 4
        # Timestamps must be monotonically non-decreasing
        timestamps = [r["timestamp_utc"] for r in merged]
        assert timestamps == sorted(timestamps)
        # Each row preserves its writer's pid
        pids = [r["worker_pid"] for r in merged]
        assert set(pids) == {100, 200}

    def test_skips_truncated_lines_without_raising(self, tmp_path):
        """Worker crash mid-write could leave a partial JSON line.
        Aggregator must skip it with a warning, not raise."""
        f = tmp_path / "b2__pid_999.jsonl"
        f.write_text(
            '{"timestamp_utc": "2026-01-01T00:00:00", "event": "stage_start"}\n'
            '{"timestamp_utc": "2026-01-01T00:00:01", "event": "stage_e',  # truncated
            encoding="utf-8",
        )
        merged = merge_batch_files("b2", sink_dir=tmp_path)
        assert len(merged) == 1  # only the well-formed row

    def test_empty_sink_dir_returns_empty_list(self, tmp_path):
        assert merge_batch_files("nonexistent", sink_dir=tmp_path) == []


# ---------------------------------------------------------------------------
# Batch summary
# ---------------------------------------------------------------------------


class TestBatchSummary:

    def test_summary_counts_completed_and_failed(self, tmp_path):
        tw = TelemetryWriter(batch_id="b3", sink_dir=tmp_path)
        tw.start_directive("OK_DIRECTIVE")
        tw.end_directive("OK_DIRECTIVE")
        tw.start_directive("FAIL_DIRECTIVE")
        tw.end_directive("FAIL_DIRECTIVE", error="PipelineError: nope")

        s = batch_summary("b3", sink_dir=tmp_path)
        assert s["n_directives_started"] == 2
        assert s["n_directives_completed"] == 1
        assert s["n_directives_failed"] == 1
        # directives sorted alphabetically by directive_id
        ids = [d["directive_id"] for d in s["directives"]]
        assert ids == ["FAIL_DIRECTIVE", "OK_DIRECTIVE"]
        # status fields
        statuses = {d["directive_id"]: d["status"] for d in s["directives"]}
        assert statuses == {"OK_DIRECTIVE": "completed", "FAIL_DIRECTIVE": "failed"}

    def test_stage4_lock_wait_surfaced_in_summary(self, tmp_path):
        tw = TelemetryWriter(batch_id="b4", sink_dir=tmp_path)
        tw.start_directive("D1")
        tw.emit_barrier_acquired("D1", "PORTFOLIO", "stage4.lock", lock_wait_ms=125)
        tw.end_directive("D1")
        s = batch_summary("b4", sink_dir=tmp_path)
        assert s["directives"][0]["stage4_lock_wait_ms"] == 125


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
