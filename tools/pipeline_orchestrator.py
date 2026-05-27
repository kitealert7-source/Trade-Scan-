"""pipeline_orchestrator.py — directive-level parallelism with permanent sequential fallback.

Dispatches a batch of directives either:
  * **Sequentially** (`max_parallel=1`) — direct loop, no subprocess
    overhead, bit-for-bit equivalent to the pre-Phase-3 semantics with
    telemetry attached. Permanent first-class operational mode:
    debugging / safe-mode / reproducibility / emergency recovery.
  * **Parallel** (`max_parallel>=2`) — `ProcessPoolExecutor` with N
    concurrent workers. Each worker runs one directive end-to-end in
    its own subprocess.

Cross-directive synchronization for shared Excel ledgers is handled by
the Phase 2 FileLocks inside Stage 3 (Strategy_Master_Filter.xlsx.lock)
and Stage 4 (Master_Portfolio_Sheet.xlsx.lock). The orchestrator does
NOT manage write coordination directly — the protected resources own
their mutexes.

Worker crash recovery:
  If a worker subprocess dies abnormally (segfault, OOM, SIGKILL,
  KeyboardInterrupt mid-Stage-4-wait), `ProcessPoolExecutor` raises
  `BrokenProcessPool` on the affected future. The orchestrator catches
  this, marks the directive as `worker_died` in telemetry, and continues
  processing the remaining directives. File locks held by the dead
  worker auto-release on process exit (OS-level guarantee).

Determinism:
  Results are returned in `directive_id` sort order regardless of
  worker completion order. Per the operator's rule #4 — even with
  parallel execution, the final report ordering is stable so humans
  debugging async batches don't suffer.

Failure semantics:
  * Sequential mode: fail-fast on first error (preserves pre-Phase-3
    `--all` semantics).
  * Parallel mode: every directive runs to completion; failures are
    collected and surfaced in the final result list. This matches
    Stage-1 backtest fail-handling — operator decides what to do with
    failures after seeing the full picture.

Stdout handling (current cut):
  Worker stdout streams live to the parent's stdout, interleaved by
  worker. Each line is NOT tagged with directive_id yet. If interleaved
  output becomes too noisy under your operational load (likely at >5
  concurrent directives), add buffered per-directive replay before
  Phase 4 flips the default. Telemetry events stay structured and
  unaffected.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DirectiveResult:
    """Outcome of one directive in a batch run.

    status:
        "completed"   — directive ran to completion
        "failed"      — directive raised a PipelineError or similar inside the worker
        "worker_died" — worker subprocess died abnormally (segfault, OOM, etc.)
    error: human-readable error string when status != "completed", else None.
    """
    directive_id: str
    status: str
    error: str | None = None


def _worker_entry(batch_id: str, directive_id: str, provision_only: bool) -> tuple[str, str, str | None]:
    """Subprocess worker entry point — runs one directive end-to-end.

    Each worker instantiates its own TelemetryWriter targeted at the
    batch_id sink directory. Per-pid filenames prevent collisions across
    workers. The worker is the one that emits `directive_started` and
    `directive_completed`/`directive_failed` (NOT the orchestrator) — so
    timestamps reflect actual worker-side wall time, not orchestrator
    enqueue/dequeue events.

    Returns: (directive_id, status, error_str or None)
    """
    # Workers re-import these — fresh state in each subprocess
    from tools.run_pipeline import run_single_directive
    from tools.pipeline_telemetry import TelemetryWriter

    tw = TelemetryWriter(batch_id=batch_id)
    tw.start_directive(directive_id)
    try:
        run_single_directive(directive_id, provision_only)
    except BaseException as e:
        err = f"{type(e).__name__}: {e}"
        tw.end_directive(directive_id, error=err)
        return (directive_id, "failed", err)
    tw.end_directive(directive_id)
    return (directive_id, "completed", None)


class PipelineOrchestrator:
    """Batch dispatcher with sequential fast-path + parallel ProcessPoolExecutor.

    Args:
        batch_id: From `pipeline_telemetry.generate_batch_id()`. Workers
            inherit it and write to the same sink directory.
        max_parallel: 1 (default) = sequential. >=2 = parallel.
        telemetry: Optional `TelemetryWriter` from the parent process for
            sequential-mode events. Parallel-mode workers create their own.
    """

    def __init__(
        self,
        batch_id: str,
        max_parallel: int = 1,
        telemetry=None,  # TelemetryWriter | None — soft-typed to avoid hard import
    ) -> None:
        if max_parallel < 1:
            raise ValueError(f"max_parallel must be >= 1, got {max_parallel}")
        self.batch_id = batch_id
        self.max_parallel = max_parallel
        self.telemetry = telemetry

    def run_batch(
        self, directive_ids: Iterable[str], provision_only: bool = False,
    ) -> list[DirectiveResult]:
        """Run all directives. Returns results sorted by `directive_id`.

        Sequential mode: fail-fast on first error — raises the exception
        from `run_single_directive` directly. Preserves pre-Phase-3
        `--all` semantics so existing operator scripts that catch
        PipelineError still work.

        Parallel mode: collects ALL outcomes (including failures) before
        returning. Operator gets the full picture from one call.
        """
        directive_ids = list(directive_ids)
        if self.max_parallel == 1:
            return self._run_sequential(directive_ids, provision_only)
        return self._run_parallel(directive_ids, provision_only)

    # --- sequential fast-path (--max-parallel 1) -----------------------

    def _run_sequential(
        self, directive_ids: list[str], provision_only: bool,
    ) -> list[DirectiveResult]:
        """Direct loop — NO subprocess, NO IPC, NO ProcessPoolExecutor.

        Bit-for-bit equivalent to the pre-Phase-3 sequential path with
        telemetry attached. Permanent first-class debug/safe-mode/
        reproducibility/emergency-recovery mode per operator's
        Phase 3 guardrail #3.

        Fail-fast on first error so existing scripts that catch
        PipelineError mid-batch still see the expected exception.
        """
        from tools.run_pipeline import run_single_directive

        results: list[DirectiveResult] = []
        for d_id in directive_ids:
            if self.telemetry is not None:
                self.telemetry.start_directive(d_id)
            try:
                run_single_directive(d_id, provision_only)
            except BaseException as e:
                err = f"{type(e).__name__}: {e}"
                if self.telemetry is not None:
                    self.telemetry.end_directive(d_id, error=err)
                results.append(DirectiveResult(d_id, "failed", err))
                print(f"[BATCH] FAILED: {d_id}")
                print("[FAIL-FAST] Stopping batch execution (sequential mode).")
                raise
            if self.telemetry is not None:
                self.telemetry.end_directive(d_id)
            results.append(DirectiveResult(d_id, "completed"))
            print(f"[BATCH] Completed: {d_id}")
        return sorted(results, key=lambda r: r.directive_id)

    # --- parallel path (--max-parallel >= 2) ---------------------------

    def _run_parallel(
        self, directive_ids: list[str], provision_only: bool,
    ) -> list[DirectiveResult]:
        """ProcessPoolExecutor — N workers run directives concurrently.

        Stage 3 + Stage 4 FileLocks (Phase 2) serialize the shared Excel
        ledger writes; the orchestrator does NOT need its own write lock.
        Each directive's failure is independent — the batch runs to
        completion regardless of individual outcomes.
        """
        print(
            f"[BATCH] Parallel mode: {self.max_parallel} worker(s), "
            f"{len(directive_ids)} directive(s)"
        )
        results: dict[str, DirectiveResult] = {}
        with ProcessPoolExecutor(max_workers=self.max_parallel) as executor:
            future_to_dir = {
                executor.submit(_worker_entry, self.batch_id, d_id, provision_only): d_id
                for d_id in directive_ids
            }
            for future in as_completed(future_to_dir):
                d_id = future_to_dir[future]
                try:
                    _, status, error = future.result()
                    results[d_id] = DirectiveResult(d_id, status, error)
                    if status == "completed":
                        print(f"[BATCH] Completed: {d_id}")
                    else:
                        print(f"[BATCH] FAILED:    {d_id} — {error}")
                except BrokenProcessPool as e:
                    # Worker died abnormally — segfault, OOM, SIGKILL.
                    # FileLocks held by the dead worker auto-release on
                    # process exit, so remaining directives proceed
                    # normally; only this one is lost.
                    err = f"BrokenProcessPool: {e}"
                    if self.telemetry is not None:
                        self.telemetry.emit(d_id, None, "worker_died", error=err)
                    results[d_id] = DirectiveResult(d_id, "worker_died", err)
                    print(f"[BATCH] WORKER DIED: {d_id} — {err}")
                except BaseException as e:
                    # Any other future-side exception (rare — most
                    # worker errors come back via future.result()
                    # returning a "failed" status from _worker_entry's
                    # try/except, not by raising here).
                    err = f"{type(e).__name__}: {e}"
                    if self.telemetry is not None:
                        self.telemetry.emit(d_id, None, "worker_died", error=err)
                    results[d_id] = DirectiveResult(d_id, "worker_died", err)
                    print(f"[BATCH] WORKER ERROR: {d_id} — {err}")
        # Sort by directive_id — deterministic output order per rule #4.
        # Missing entries (shouldn't happen but defensively guard) are
        # excluded rather than producing KeyError.
        return [
            results[d_id]
            for d_id in sorted(set(directive_ids))
            if d_id in results
        ]
