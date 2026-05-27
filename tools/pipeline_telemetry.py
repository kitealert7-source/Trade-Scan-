"""pipeline_telemetry.py — structured telemetry for batch pipeline runs.

Emits one JSONL line per pipeline event (stage transitions, barrier
acquisitions, directive completions, worker deaths). Files land at
`outputs/.session_state/pipeline_telemetry/<batch_id>__pid_<pid>.jsonl`.

Design constraints (per the 2026-05-27 cross-directive parallelization
plan, Phase 1):

  1. **Multi-process-safe from day 1.** Each process writes to its own
     `pid`-suffixed file, so no cross-process append contention. Phase 3
     parallelism will add multiple worker processes; each gets its own
     writer instance and its own file.

  2. **Stable schema.** Every row carries:
        directive_id, stage_id, event, timestamp_utc,
        worker_pid, batch_id
     Plus event-specific extras: duration_ms, stage4_lock_wait_ms,
     directive_wall_ms, error, exit_code.

  3. **Append-only / never-overwrite.** Each batch produces a new
     timestamped batch_id, so two batches never collide in the same file.

  4. **Aggregator-ready.** `merge_batch_files(batch_id)` walks all
     per-pid files for a batch and yields one chronologically-ordered
     timeline. Used by post-batch reporting + diagnostics.

Schema events (event field values):
  - stage_start            — entering a pipeline stage
  - stage_end              — leaving a pipeline stage (carries duration_ms)
  - barrier_wait_start     — waiting on a cross-directive lock (Stage 3 / 4)
  - barrier_acquired       — lock acquired (carries stage4_lock_wait_ms)
  - barrier_released       — lock released
  - barrier_wait_stale     — lock wait exceeded 60s warning threshold
  - directive_queued       — orchestrator submitted directive to work pool (Phase 3+)
  - directive_started      — directive picked up and beginning execution
  - directive_completed    — directive finished cleanly (carries directive_wall_ms)
  - directive_failed       — directive raised an exception (carries error)
  - worker_died            — worker process exited abnormally (Phase 3)

Lifecycle decomposition (Phase 3+, derivable from these events):
  queue_time_ms = directive_started.ts − directive_queued.ts
  run_time_ms   = directive_completed.ts − directive_started.ts
  total_time_ms = directive_completed.ts − directive_queued.ts
                  (also recorded directly as directive_wall_ms)

The 60s `barrier_wait_stale` and 15min `barrier_wait_timeout` thresholds
are emitted by the lock-acquirer; this module just records what it's told.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# REPO ROOT discovery — same pattern as tools/cointegration_history_matrix.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent

TELEMETRY_DIR = PROJECT_ROOT / "outputs" / ".session_state" / "pipeline_telemetry"


def generate_batch_id() -> str:
    """Generate a human-readable batch identifier.

    Format: `YYYY-MM-DDTHH-MM-SSZ_<8-char uuid suffix>`
    Example: `2026-05-27T05-18-00Z_a1b2c3d4`

    Sortable lexicographically by start time (the leading timestamp);
    the uuid suffix disambiguates batches started in the same second.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{ts}_{suffix}"


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with microsecond resolution."""
    return datetime.now(timezone.utc).isoformat()


class TelemetryWriter:
    """Per-process JSONL telemetry sink for one batch run.

    Each process that runs pipeline work (parent orchestrator in Phase 1,
    worker subprocesses in Phase 3) instantiates one of these. The writer
    picks its own pid-suffixed filename so no two processes contend on the
    same file. The file is opened in append mode and flushed after each
    write — durable telemetry survives a worker crash.

    Usage:
        tw = TelemetryWriter(batch_id="2026-05-27T05-18-00Z_a1b2c3d4")
        tw.emit("ACME_DIRECTIVE_01", stage_id="PREFLIGHT", event="stage_start")
        # ... work happens ...
        tw.emit("ACME_DIRECTIVE_01", stage_id="PREFLIGHT", event="stage_end",
                duration_ms=423)

    Or use the higher-level helpers:
        tw.start_directive("ACME_DIRECTIVE_01")
        with tw.stage("ACME_DIRECTIVE_01", "PREFLIGHT"):
            ...
        tw.end_directive("ACME_DIRECTIVE_01")
    """

    def __init__(
        self,
        batch_id: str,
        sink_dir: Path | None = None,
    ) -> None:
        self.batch_id = batch_id
        self.worker_pid = os.getpid()
        self.sink_dir = Path(sink_dir) if sink_dir is not None else TELEMETRY_DIR
        self.sink_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.sink_dir / f"{batch_id}__pid_{self.worker_pid}.jsonl"
        # Track directive wall-time start so directive_end can compute the KPI.
        # Multiple directives may run sequentially through one writer (Phase 1)
        # or one directive per writer (Phase 3 — each worker handles one
        # directive at a time but might process several).
        self._directive_started: dict[str, float] = {}
        # Track stage start times for duration_ms on stage_end.
        self._stage_started: dict[tuple[str, str], float] = {}

    # --- core emit -----------------------------------------------------

    def emit(
        self,
        directive_id: str | None,
        stage_id: str | None,
        event: str,
        **extra: Any,
    ) -> None:
        """Write one JSONL row to the sink file.

        directive_id / stage_id may be None for batch-level events
        (e.g. batch_start, batch_end).
        """
        row: dict[str, Any] = {
            "timestamp_utc": _utcnow_iso(),
            "batch_id": self.batch_id,
            "worker_pid": self.worker_pid,
            "directive_id": directive_id,
            "stage_id": stage_id,
            "event": event,
        }
        # Merge event-specific extras LAST so they can't accidentally
        # overwrite the canonical fields above (defensive — extra is
        # under caller control).
        for k, v in extra.items():
            if k in row:
                # Preserve canonical fields; surface the conflict in
                # telemetry itself rather than silently dropping it.
                row[f"extra_{k}"] = v
            else:
                row[k] = v
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()

    # --- higher-level helpers ------------------------------------------

    def queue_directive(self, directive_id: str) -> None:
        """Emit directive_queued — the orchestrator has submitted the
        directive to the work pool but a worker has not yet picked it up.

        Phase 3+: only meaningful under parallel orchestration. In
        sequential mode (--max-parallel 1) emit immediately followed by
        `start_directive` for consistency, so queue_time_ms ≈ 0 but the
        event stream shape is invariant across modes.
        """
        self.emit(directive_id, stage_id=None, event="directive_queued")

    def start_directive(self, directive_id: str) -> None:
        """Emit directive_started — worker has picked up the directive
        and is beginning execution. Records the monotonic timestamp so
        end_directive can compute directive_wall_ms (= total_time_ms,
        directive_started → directive_completed/failed).
        """
        self._directive_started[directive_id] = time.monotonic()
        self.emit(directive_id, stage_id=None, event="directive_started")

    def end_directive(
        self,
        directive_id: str,
        error: str | None = None,
    ) -> None:
        """Emit directive_completed (success) or directive_failed (error)
        with directive_wall_ms = (now − directive_started)."""
        wall_ms = None
        start = self._directive_started.pop(directive_id, None)
        if start is not None:
            wall_ms = int((time.monotonic() - start) * 1000)
        if error is None:
            self.emit(
                directive_id, stage_id=None, event="directive_completed",
                directive_wall_ms=wall_ms,
            )
        else:
            self.emit(
                directive_id, stage_id=None, event="directive_failed",
                directive_wall_ms=wall_ms, error=error,
            )

    @contextmanager
    def stage(self, directive_id: str, stage_id: str) -> Iterator[None]:
        """Context manager emitting stage_start on enter, stage_end on exit.

        On exception, emits stage_end with duration_ms AND an error field,
        then re-raises so the caller still sees the failure. This keeps
        the duration KPI populated even on failed stages — important for
        diagnosing which stage was slow before a crash.
        """
        self._stage_started[(directive_id, stage_id)] = time.monotonic()
        self.emit(directive_id, stage_id, event="stage_start")
        try:
            yield
        except BaseException as e:
            duration_ms = self._compute_duration_ms(directive_id, stage_id)
            self.emit(
                directive_id, stage_id, event="stage_end",
                duration_ms=duration_ms, error=f"{type(e).__name__}: {e}",
            )
            raise
        else:
            duration_ms = self._compute_duration_ms(directive_id, stage_id)
            self.emit(
                directive_id, stage_id, event="stage_end",
                duration_ms=duration_ms,
            )

    def _compute_duration_ms(self, directive_id: str, stage_id: str) -> int | None:
        start = self._stage_started.pop((directive_id, stage_id), None)
        if start is None:
            return None
        return int((time.monotonic() - start) * 1000)

    # --- barrier helpers (used by Stage 3 / Stage 4 lock acquirers) ----

    def emit_barrier_wait_start(
        self, directive_id: str, stage_id: str, lock_name: str,
    ) -> None:
        self.emit(
            directive_id, stage_id, event="barrier_wait_start",
            lock_name=lock_name,
        )

    def emit_barrier_acquired(
        self,
        directive_id: str,
        stage_id: str,
        lock_name: str,
        lock_wait_ms: int,
    ) -> None:
        self.emit(
            directive_id, stage_id, event="barrier_acquired",
            lock_name=lock_name, stage4_lock_wait_ms=lock_wait_ms,
        )

    def emit_barrier_released(
        self, directive_id: str, stage_id: str, lock_name: str,
    ) -> None:
        self.emit(
            directive_id, stage_id, event="barrier_released",
            lock_name=lock_name,
        )

    def emit_barrier_wait_stale(
        self,
        directive_id: str,
        stage_id: str,
        lock_name: str,
        elapsed_ms: int,
    ) -> None:
        self.emit(
            directive_id, stage_id, event="barrier_wait_stale",
            lock_name=lock_name, stage4_lock_wait_ms=elapsed_ms,
        )


# ---------------------------------------------------------------------------
# Aggregator — merges per-pid files for a batch into a single timeline
# ---------------------------------------------------------------------------


def merge_batch_files(
    batch_id: str, sink_dir: Path | None = None,
) -> list[dict]:
    """Read all per-pid JSONL files for `batch_id` and return events
    in chronological order.

    Used by post-batch reporting + diagnostics. Returns a list of dicts
    (parsed JSONL rows) sorted by timestamp_utc ascending. Each row
    carries `worker_pid` so the caller can group by worker if needed.

    Robust to truncated final lines (worker crash mid-write) — partial
    JSON lines are skipped with a stderr warning, not raised.
    """
    sink_dir = Path(sink_dir) if sink_dir is not None else TELEMETRY_DIR
    if not sink_dir.is_dir():
        return []
    rows: list[dict] = []
    for f in sorted(sink_dir.glob(f"{batch_id}__pid_*.jsonl")):
        with f.open("r", encoding="utf-8") as fp:
            for line_no, line in enumerate(fp, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    import sys as _sys
                    print(
                        f"[telemetry] skipping malformed line {f.name}:{line_no}: {e}",
                        file=_sys.stderr,
                    )
    rows.sort(key=lambda r: r.get("timestamp_utc", ""))
    return rows


def batch_summary(batch_id: str, sink_dir: Path | None = None) -> dict:
    """One-line-per-directive summary of a batch run. Used by the
    end-of-batch report.

    Returns:
        {
          "batch_id": "...",
          "n_directives_started": int,
          "n_directives_completed": int,
          "n_directives_failed": int,
          "directives": [
            {
              "directive_id": "...",
              "wall_ms": int | None,
              "status": "completed" | "failed",
              "error": str | None,
              "stage4_lock_wait_ms": int | None,
            },
            ...
          ],
        }
    """
    rows = merge_batch_files(batch_id, sink_dir=sink_dir)
    by_dir: dict[str, dict] = {}
    for r in rows:
        d_id = r.get("directive_id")
        if d_id is None:
            continue
        slot = by_dir.setdefault(d_id, {
            "directive_id": d_id,
            "wall_ms": None,
            "status": "unknown",
            "error": None,
            "stage4_lock_wait_ms": None,
        })
        ev = r.get("event")
        if ev == "directive_completed":
            slot["status"] = "completed"
            slot["wall_ms"] = r.get("directive_wall_ms")
        elif ev == "directive_failed":
            slot["status"] = "failed"
            slot["wall_ms"] = r.get("directive_wall_ms")
            slot["error"] = r.get("error")
        elif ev == "barrier_acquired" and r.get("stage_id") == "PORTFOLIO":
            slot["stage4_lock_wait_ms"] = r.get("stage4_lock_wait_ms")

    n_started = sum(1 for r in rows if r.get("event") == "directive_started")
    n_completed = sum(1 for d in by_dir.values() if d["status"] == "completed")
    n_failed = sum(1 for d in by_dir.values() if d["status"] == "failed")
    return {
        "batch_id": batch_id,
        "n_directives_started": n_started,
        "n_directives_completed": n_completed,
        "n_directives_failed": n_failed,
        "directives": sorted(by_dir.values(), key=lambda d: d["directive_id"]),
    }
