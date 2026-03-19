"""
runner.py — Centralized Stage Execution Engine
Purpose: Orchestrates the deterministic execution of registered pipeline stages.
Authority: Orchestrator Refactor Proposal v3.5
"""

from __future__ import annotations
from typing import List, Type, Protocol
from tools.pipeline_utils import PipelineContext
from tools.orchestration.transition_service import transition_directive_state
from tools.orchestration.pipeline_errors import PipelineError, PipelineExecutionError
try:
    from tools.system_logging.pipeline_failure_logger import log_pipeline_failure as _log_failure
except Exception:
    _log_failure = None

class PipelineStage(Protocol):
    """Protocol for a pipeline execution unit."""
    stage_id: str
    stage_name: str

    def run(self, context: PipelineContext) -> None:
        """Execute the stage logic using the provided context."""
        ...


class StageRunner:
    """
    The authoritative Stage Runner responsible for:
    - Iterating the STAGE_REGISTRY
    - Invoking stage callables
    - Propagating errors (fail-fast)

    FSM ownership: StageRunner does NOT perform FSM transitions.
    Stages may raise exceptions to signal failure; the orchestrator catches and maps them.
    Side note: resume skip logic remains in run_pipeline.py (orchestrator bootstrap),
    not here, per Phase-3 guardrail.
    """
    def __init__(self, context: PipelineContext, registry: List[Type[PipelineStage]] = None):
        self.context = context
        # Default to the authoritative registry if none provided
        self.registry = registry if registry is not None else STAGE_REGISTRY

    def run(self) -> None:
        """
        Execute registered stages sequentially.
        Skips stages already recorded in context.completed_stages (crash-restart safety).
        Marks each stage complete after successful execution.
        """
        print(f"[RUNNER] Starting stage execution for: {self.context.directive_id}")

        for stage_cls in self.registry:
            stage = stage_cls()

            # Idempotency guard: skip stages completed before a crash
            if stage.stage_id in self.context.completed_stages:
                print(f"[RUNNER] Skipping already-completed stage: {stage.stage_id}")
                continue

            print(f"[RUNNER] -> {stage.stage_name} ({stage.stage_id})")
            # Safe run_id and directive_id resolution for logging
            run_id = "N/A"
            if hasattr(self.context, "run_ids") and self.context.run_ids:
                run_id = self.context.run_ids[0]
            
            directive_id = getattr(self.context, "directive_id", "UNKNOWN")

            try:
                # Issue Heartbeat before heavy work blocking layer begins
                from tools.pipeline_utils import PipelineStateManager
                for rid in getattr(self.context, 'run_ids', []):
                    PipelineStateManager(rid).record_heartbeat()
                    
                stage.run(self.context)
                
                # Issue Heartbeat immediately after safe return
                for rid in getattr(self.context, 'run_ids', []):
                    PipelineStateManager(rid).record_heartbeat()
                    
            except PipelineError as e:
                # Rule 1: Pass through known errors without re-wrapping
                error_msg = str(e)
                log_msg = f"STAGE_FAILURE | directive={directive_id} | stage={stage.stage_id} | run_id={run_id} | error={error_msg}"
                print(f"[RUNNER] {log_msg}")
                
                if _log_failure:
                    _log_failure(
                        directive_id=directive_id,
                        run_id=run_id if run_id != "N/A" else None,
                        stage=stage.stage_id,
                        error_type="STAGE_FAILURE",
                        message=log_msg,
                    )
                raise

            except Exception as e:
                # Rule 2: Wrap unexpected exceptions in PipelineExecutionError
                wrapped = PipelineExecutionError(
                    f"Unhandled exception in stage {stage.stage_id}: {e}",
                    directive_id=directive_id,
                    run_ids=getattr(self.context, "run_ids", [])
                )
                log_msg = f"STAGE_FAILURE | directive={directive_id} | stage={stage.stage_id} | run_id={run_id} | error={str(wrapped)}"
                print(f"[RUNNER] {log_msg}")
                
                if _log_failure:
                    _log_failure(
                        directive_id=directive_id,
                        run_id=run_id if run_id != "N/A" else None,
                        stage=stage.stage_id,
                        error_type="STAGE_FAILURE",
                        message=log_msg,
                    )
                raise wrapped

            # Mark complete only after successful execution
            self.context.completed_stages.add(stage.stage_id)

        print(f"[RUNNER] All registered stages complete.")


# ---------------------------------------------------------------------------
# Placeholder stages removed in Phase 6 — extracted to dedicated files.
# ---------------------------------------------------------------------------

# Import active stages — done after placeholder removal to avoid circular import issues
from tools.orchestration.symbol_execution_controller import SymbolExecutionStage  # noqa: E402
from tools.orchestration.preflight_stage import PreflightStage  # noqa: E402
from tools.orchestration.reporting_stage import ReportingStage  # noqa: E402
from tools.orchestration.stage_schema_validation import SchemaValidationStage  # noqa: E402
from tools.orchestration.aggregation_stage import AggregationStage  # noqa: E402
from tools.orchestration.manifest_binding_stage import ManifestBindingStage  # noqa: E402
from tools.orchestration.portfolio_stage import PortfolioStage  # noqa: E402

# ---------------------------------------------------------------------------
# STAGE_REGISTRY: Authoritative execution order.
# All 6 stages ACTIVE as of Phase 7.
# ---------------------------------------------------------------------------
STAGE_REGISTRY: List[Type[PipelineStage]] = [
    PreflightStage,       # ACTIVE -- Phase 5: Semantic validation
    SymbolExecutionStage, # ACTIVE -- Phase 6: Stage-1 backtest execution
    ReportingStage,         # ACTIVE -- Phase 6: Stage-2 compilation
    SchemaValidationStage,  # ACTIVE -- Phase 6: Stage-2 schema gate (post-compile)
    AggregationStage,       # ACTIVE -- Phase 6: Stage-3 aggregation + cardinality gate
    ManifestBindingStage, # ACTIVE -- Phase 6: Stage-3a manifest binding + run close
    PortfolioStage,       # ACTIVE -- Phase 7: Stage-4 portfolio evaluation + post steps
]
