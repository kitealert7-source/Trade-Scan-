"""
stage_schema_validation.py — Stage-2 Schema Validation Gate
Purpose: Hard-fail the pipeline if any AK_Trade_Report is missing required metric rows
         or carries null values in required fields. Runs after Stage-2 (ReportingStage)
         and before Stage-3 (AggregationStage).

Schema source: tools/stage3_compiler.py (REQUIRED_METRICS, VOLATILITY_METRICS,
               TREND_METRICS, TRADE_DENSITY_LABEL) — imported directly to guarantee
               zero drift between validation and extraction.

Authority: SOP_OUTPUT §6
State Gated: No (read-only validation; no FSM transitions)
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path

from config.state_paths import BACKTESTS_DIR
from tools.orchestration.pipeline_errors import PipelineExecutionError
from tools.pipeline_utils import PipelineContext, PipelineStateManager

# ── Schema source of truth ────────────────────────────────────────────────────
# Import label sets directly from stage3_compiler so validation is always in
# sync with what Stage 3 actually reads. Any future label addition to stage3
# automatically tightens this gate on the next pipeline run.
from tools.stage3_compiler import (
    REQUIRED_METRICS,
    VOLATILITY_METRICS,
    TREND_METRICS,
    TRADE_DENSITY_LABEL,
)

# All labels that must be present AND non-null in "All Trades" column.
_REQUIRED_LABELS: frozenset[str] = frozenset(
    list(REQUIRED_METRICS.values())
    + list(VOLATILITY_METRICS.values())
    + list(TREND_METRICS.values())
    + [TRADE_DENSITY_LABEL]
)


def _check_report(report_path: Path, run_id: str, symbol: str) -> tuple[list[str], list[str]]:
    """
    Validate one AK_Trade_Report Performance Summary sheet.

    Returns:
        (missing_labels, null_labels)
        missing_labels: required labels absent from the Metric column entirely.
        null_labels:    labels present but whose "All Trades" value is NaN/None.
    """
    try:
        df = pd.read_excel(report_path, sheet_name="Performance Summary")
    except Exception as e:
        raise RuntimeError(
            f"Cannot open Performance Summary sheet in {report_path.name}: {e}"
        )

    if "Metric" not in df.columns or "All Trades" not in df.columns:
        raise RuntimeError(
            f"{report_path.name}: Performance Summary missing 'Metric' or 'All Trades' column."
        )

    metrics: dict = df.set_index("Metric")["All Trades"].to_dict()

    missing = [lbl for lbl in sorted(_REQUIRED_LABELS) if lbl not in metrics]
    null = [
        lbl for lbl in sorted(_REQUIRED_LABELS)
        if lbl in metrics and pd.isnull(metrics[lbl])
    ]
    return missing, null


class SchemaValidationStage:
    """
    Post-Stage-2 schema gate.

    Iterates every run's AK_Trade_Report, validates that all 32 required metric
    labels are present and non-null in the Performance Summary sheet. Collects
    failures across ALL runs before raising, so the operator sees the complete
    failure surface in one pass.
    """

    stage_id = "SCHEMA_VALIDATION"
    stage_name = "Stage-2 Schema Validation"

    def run(self, context: PipelineContext) -> None:
        directive_id = context.directive_id
        run_ids = context.run_ids
        symbols = context.symbols

        print(f"[{self.stage_id}] Validating AK_Trade_Report schema for: {directive_id}")

        # Pre-entry state check: if any run is FAILED, Stage 2 did not complete for
        # that run. Fail here with an explicit upstream attribution rather than
        # surfacing a confusing "AK_Trade_Report not found" artifact error below.
        failed_runs = [
            (run_id, symbol)
            for run_id, symbol in zip(run_ids, symbols)
            if PipelineStateManager(run_id).get_state_data().get("current_state", "IDLE") == "FAILED"
        ]
        if failed_runs:
            lines = [
                f"  {sym} ({rid[:8]}): Stage 2 marked FAILED — AK_Trade_Report will not exist"
                f" → Check stage2_compiler output or Stage 1 artifacts for this run"
                for rid, sym in failed_runs
            ]
            raise PipelineExecutionError(
                f"[{self.stage_id}] Stage 2 failed for {len(failed_runs)} run(s) "
                f"— fix Stage 2 before schema validation:\n" + "\n".join(lines),
                directive_id=directive_id,
                run_ids=[rid for rid, _ in failed_runs],
            )

        failures: list[str] = []       # human-readable lines
        failing_run_ids: list[str] = []

        for run_id, symbol in zip(run_ids, symbols):
            run_folder = BACKTESTS_DIR / f"{directive_id}_{symbol}"
            reports = list(run_folder.glob("AK_Trade_Report_*.xlsx"))
            reports = [r for r in reports if not r.name.startswith("~$")]

            if not reports:
                failures.append(
                    f"  {symbol} ({run_id[:8]}): AK_Trade_Report not found in {run_folder}"
                )
                failing_run_ids.append(run_id)
                continue

            report_path = reports[0]
            try:
                missing, null = _check_report(report_path, run_id, symbol)
            except RuntimeError as e:
                failures.append(f"  {symbol} ({run_id[:8]}): {e}")
                failing_run_ids.append(run_id)
                continue

            if missing or null:
                parts = []
                if missing:
                    parts.append(f"missing={missing}")
                if null:
                    parts.append(f"null={null}")
                failures.append(f"  {symbol} ({run_id[:8]}): {', '.join(parts)}")
                failing_run_ids.append(run_id)

        if failures:
            failure_block = "\n".join(failures)
            raise PipelineExecutionError(
                f"[{self.stage_id}] AK_Trade_Report schema failures in "
                f"{len(failing_run_ids)} run(s):\n{failure_block}\n"
                f"Stage 2 must be re-run or engine schema corrected before proceeding.",
                directive_id=directive_id,
                run_ids=failing_run_ids,
            )

        print(
            f"[{self.stage_id}] PASSED — {len(run_ids)} run(s) validated, "
            f"{len(_REQUIRED_LABELS)} labels each."
        )
