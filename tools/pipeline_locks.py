"""pipeline_locks.py — cross-process file locks with stale-wait observability.

Wraps `filelock.FileLock` with two operational guarantees that infinite
waits don't provide:

  1. **15-minute hard timeout** — surfaces deadlocks instead of hiding
     them behind unbounded waits. If a lock is held longer than 15 min,
     something is wrong (a worker died holding the lock; a misbehaving
     subprocess re-entered; a stale lock file).

  2. **60-second stale-wait warning** — prints a one-time warning when
     a lock wait exceeds 60 seconds. Gives the operator early visibility
     into contention WITHOUT raising. Stage 4 writes are typically
     <2 seconds, so a 60s wait is itself a strong signal that something
     unusual is happening.

Telemetry integration (optional): if a TelemetryWriter is passed, the
helper emits `barrier_wait_start`, `barrier_acquired`, `barrier_released`,
`barrier_wait_stale` events with the lock_name + wait_ms fields. The
emit pattern matches the schema set up in Phase 1 of the cross-directive
parallelization plan (2026-05-27).

Used by Phase 2 (Stage 3 transactional refactor, Stage 4 portfolio lock)
and Phase 3 onward (any worker-side lock acquisition).
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from filelock import FileLock, Timeout as FileLockTimeout

DEFAULT_LOCK_TIMEOUT_S = 15 * 60   # 15 min hard ceiling
DEFAULT_STALE_WARN_S = 60          # 1 min observability warning


class _TelemetryProtocol(Protocol):
    """Structural protocol for the subset of TelemetryWriter we use here.

    Lets pipeline_locks.py work with anything that provides the four
    emit methods — including no-op stubs in tests or richer custom sinks
    in future. Doesn't import pipeline_telemetry to keep the dependency
    arrow pointing the right way (telemetry can use locks; locks don't
    require telemetry to be present).
    """
    def emit_barrier_wait_start(self, directive_id: str, stage_id: str, lock_name: str) -> None: ...
    def emit_barrier_acquired(self, directive_id: str, stage_id: str, lock_name: str, lock_wait_ms: int) -> None: ...
    def emit_barrier_released(self, directive_id: str, stage_id: str, lock_name: str) -> None: ...
    def emit_barrier_wait_stale(self, directive_id: str, stage_id: str, lock_name: str, elapsed_ms: int) -> None: ...


@contextmanager
def acquire_with_stale_warn(
    lock_path: Path | str,
    *,
    lock_name: str,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
    warn_after_s: float = DEFAULT_STALE_WARN_S,
    telemetry: _TelemetryProtocol | None = None,
    directive_id: str | None = None,
    stage_id: str | None = None,
    poll_interval_s: float = 1.0,
) -> Iterator[int]:
    """Acquire `lock_path` as a FileLock with stale-wait observability.

    Yields the lock_wait_ms (how long acquisition took, in milliseconds)
    so callers can record their own metrics if needed.

    Behavior:
      * Polls `FileLock.acquire(timeout=poll_interval_s)` in a loop
      * If `warn_after_s` elapses without acquisition, emits one
        stale-wait warning (stdout + telemetry if present)
      * If `timeout_s` elapses, raises `FileLockTimeout`
      * On successful acquire: prints lock_wait_ms + emits telemetry
      * On context exit: releases lock + emits release telemetry

    The polling-based pattern is required to support the stale-wait
    warning — a single `FileLock.acquire(timeout=timeout_s)` would
    block silently for up to 15 minutes with no operator visibility.

    Args:
        lock_path: Filesystem path for the .lock sidecar file
        lock_name: Short label used in log lines and telemetry
        timeout_s: Hard timeout; raises FileLockTimeout if exceeded
        warn_after_s: Emit one stale-wait warning at this point
        telemetry: Optional TelemetryWriter for structured events
        directive_id: Directive owning this lock acquisition (telemetry only)
        stage_id: Pipeline stage owning this lock acquisition (telemetry only)
        poll_interval_s: How frequently to poll the lock (1s default)
    """
    lock = FileLock(str(lock_path))
    start = time.monotonic()
    if telemetry is not None:
        telemetry.emit_barrier_wait_start(directive_id, stage_id, lock_name)
    warned = False
    while True:
        try:
            lock.acquire(timeout=poll_interval_s)
            break
        except FileLockTimeout:
            elapsed = time.monotonic() - start
            if not warned and elapsed >= warn_after_s:
                print(
                    f"[{lock_name}] WARNING: still waiting for lock after "
                    f"{int(elapsed)}s (timeout in {int(timeout_s - elapsed)}s)"
                )
                if telemetry is not None:
                    telemetry.emit_barrier_wait_stale(
                        directive_id, stage_id, lock_name,
                        elapsed_ms=int(elapsed * 1000),
                    )
                warned = True
            if elapsed >= timeout_s:
                raise FileLockTimeout(
                    f"[{lock_name}] lock timeout after {int(elapsed)}s "
                    f"(hard limit {int(timeout_s)}s) — a worker likely died "
                    f"holding the lock, or a deadlock developed. Inspect "
                    f"{lock_path} and any stale process holding it."
                )
    lock_wait_ms = int((time.monotonic() - start) * 1000)
    print(f"[{lock_name}] acquired after {lock_wait_ms}ms")
    if telemetry is not None:
        telemetry.emit_barrier_acquired(
            directive_id, stage_id, lock_name, lock_wait_ms=lock_wait_ms,
        )
    try:
        yield lock_wait_ms
    finally:
        try:
            lock.release()
        except Exception:
            # Best-effort release — never let cleanup failure mask the
            # actual exception that may already be propagating.
            pass
        if telemetry is not None:
            try:
                telemetry.emit_barrier_released(directive_id, stage_id, lock_name)
            except Exception:
                pass
