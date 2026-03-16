"""
admission_controller.py — Directive Admission Gates
Purpose: Encapsulates Canonicalization, Namespace, and Sweep Registry gates.
Authority: Orchestrator Refactor Proposal v3.5
"""

from __future__ import annotations
from pathlib import Path
from tools.pipeline_utils import PipelineContext
from tools.orchestration.pipeline_errors import PipelineExecutionError


class CanonicalizationDriftError(PipelineExecutionError):
    """Raised when structural drift requires explicit operator approval."""
    def __init__(self, directive_id: str, diff_lines: list[str], canonical_yaml: str):
        super().__init__(
            "Stage -0.25 halted due to structural drift in directive. Validation blocked.",
            directive_id=directive_id,
            fail_directive=False,
            fail_runs=False,
        )
        self.diff_lines = diff_lines
        self.canonical_yaml = canonical_yaml

class AdmissionStage:
    """
    Admission Phase (Bootstrap):
    - Stage -0.25: Canonicalization
    - Stage -0.30: Namespace Governance
    - Stage -0.35: Sweep Registry Gate
    """
    stage_id = "ADMISSION"
    stage_name = "Directive Admission Gates"

    def run(self, context: PipelineContext) -> None:
        """Execute the triple-gate admission flow."""
        print(f"[{self.stage_id}] Starting admission sequence for: {context.directive_path.name}")
        
        # 1. Stage -0.25: Canonicalization
        self._run_canonicalization(context)
        
        # 2. Stage -0.30: Namespace Gate
        self._run_namespace_gate(context)
        
        # 3. Stage -0.35: Sweep Registry Gate
        self._run_sweep_gate(context)

    def _run_canonicalization(self, context: PipelineContext) -> None:
        from tools.canonicalizer import canonicalize, CanonicalizationError
        import yaml
        
        try:
            raw_yaml = context.directive_path.read_text(encoding="utf-8")
            parsed_raw = yaml.safe_load(raw_yaml)
            canonical, canonical_yaml, diff_lines, violations, has_drift = canonicalize(parsed_raw)
            
            if violations:
                print(f"[{self.stage_id}] Structural changes detected:")
                for level, msg in violations:
                    print(f"  [{level}] {msg}")
            
            if has_drift:
                print(f"\n[{self.stage_id}] STRUCTURAL DRIFT -- directive is not canonical.")
                print("  --- Unified Diff ---")
                for line in diff_lines:
                    print(f"  {line}", end="")
                
                tmp_path = Path("/tmp") / f"{context.directive_id}_canonical.yaml"
                try:
                    tmp_path.write_text(canonical_yaml, encoding="utf-8")
                    print(f"\n  Corrected YAML written to: {tmp_path}")
                except Exception as tmp_err:
                    print(f"\n  [WARN] Failed to write corrected YAML to /tmp: {tmp_err}")
                
                print("  Human must review and approve overwrite.")
                print("[HALT] Pipeline stopped. Fix directive and re-run.")
                
                raise CanonicalizationDriftError(
                    directive_id=context.directive_id,
                    diff_lines=diff_lines,
                    canonical_yaml=canonical_yaml
                )
            else:
                print(f"[{self.stage_id}] Stage -0.25: Directive is in canonical form. [OK]")
            
        except CanonicalizationError as e:
            raise PipelineExecutionError(f"STAGE -0.25 CANONICALIZATION FAILED: {e}", directive_id=context.directive_id) from e
        except Exception as e:
            raise PipelineExecutionError(f"STAGE -0.25 UNEXPECTED ERROR: {e}", directive_id=context.directive_id) from e

    def _run_namespace_gate(self, context: PipelineContext) -> None:
        from tools.namespace_gate import validate_namespace
        try:
            ns_details = validate_namespace(context.directive_path)
            print(f"[{self.stage_id}] Stage -0.30: Namespace Gate PASSED ({ns_details['strategy_name']})")
        except Exception as e:
            raise PipelineExecutionError(f"STAGE -0.30 NAMESPACE GATE FAILED: {e}", directive_id=context.directive_id) from e

    def _run_sweep_gate(self, context: PipelineContext) -> None:
        from tools.sweep_registry_gate import reserve_sweep
        try:
            sw_details = reserve_sweep(context.directive_path, auto_advance=True)
            print(f"[{self.stage_id}] Stage -0.35: Sweep Gate PASSED (sweep={sw_details['sweep']})")
        except Exception as e:
            raise PipelineExecutionError(f"STAGE -0.35 SWEEP GATE FAILED: {e}", directive_id=context.directive_id) from e
