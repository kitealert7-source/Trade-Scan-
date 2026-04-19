"""Typed orchestration errors for centralized pipeline failure mapping."""

from __future__ import annotations

from collections.abc import Sequence


class PipelineError(Exception):
    """Base class for orchestration-level control-flow errors."""


class PipelineAdmissionPause(PipelineError):
    """Pause requested by an admission gate (non-fatal, exit code 0)."""

    def __init__(
        self,
        message: str,
        *,
        directive_id: str | None = None,
        run_ids: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.directive_id = directive_id
        self.run_ids = list(run_ids or [])
        self.exit_code = 0


class PipelineExecutionError(PipelineError):
    """Fatal orchestration failure with explicit cleanup policy."""

    def __init__(
        self,
        message: str,
        *,
        directive_id: str | None = None,
        run_ids: Sequence[str] | None = None,
        fail_directive: bool = True,
        fail_runs: bool = True,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.directive_id = directive_id
        self.run_ids = list(run_ids or [])
        self.fail_directive = fail_directive
        self.fail_runs = fail_runs
        self.exit_code = exit_code
