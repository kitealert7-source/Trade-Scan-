"""
admission_controller.py — Directive Admission Gates
Purpose: Encapsulates Idea Evaluation, Canonicalization, Namespace, and Sweep Registry gates.
Authority: Orchestrator Refactor Proposal v3.5
"""

from __future__ import annotations
from pathlib import Path
from tools.pipeline_utils import PipelineContext
from tools.orchestration.pipeline_errors import PipelineExecutionError, PipelineAdmissionPause


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
    - Stage -0.20: Idea Evaluation (Concept Reuse Gate)
    - Stage -0.25: Canonicalization
    - Stage -0.30: Namespace Governance
    - Stage -0.35: Sweep Registry Gate
    """
    stage_id = "ADMISSION"
    stage_name = "Directive Admission Gates"

    def run(self, context: PipelineContext) -> None:
        """Execute the quad-gate admission flow."""
        print(f"[{self.stage_id}] Starting admission sequence for: {context.directive_path.name}")

        # 0a. Stage -0.22: Single Asset Class Enforcement
        self._run_asset_class_gate(context)

        # 0. Stage -0.20: Idea Evaluation (Concept Reuse Gate)
        self._run_idea_evaluation(context)

        # 0b. Stage -0.21: Classifier Gate (Phase 4)
        #     Mechanical delta check + indicator content-hash vs prior matching
        #     directive. Fail-closed on UNCLASSIFIABLE; require signal_version
        #     increment when classifier marks change as SIGNAL.
        self._run_classifier_gate(context)

        # 1. Stage -0.25: Canonicalization
        self._run_canonicalization(context)

        # 2. Stage -0.30: Namespace Gate
        self._run_namespace_gate(context)

        # 3. Stage -0.35: Sweep Registry Gate
        self._run_sweep_gate(context)

        # Post-admission cleanup: remove from INBOX_hold (single source of truth in active_backup)
        self._cleanup_inbox_hold(context)

    def _run_asset_class_gate(self, context: PipelineContext) -> None:
        """Stage -0.22: Enforce single asset class per directive.

        PORT family is exempt (composites span multiple classes by design).
        Raises PipelineExecutionError on mixed or unknown symbols (fail loud).
        """
        import yaml
        from config.asset_classification import (
            infer_asset_class_from_symbols,
            MixedAssetClassError,
            UnknownSymbolError,
        )
        try:
            raw = yaml.safe_load(context.directive_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            raise PipelineExecutionError(
                f"STAGE -0.22 ASSET CLASS GATE: failed to read directive ({e})",
                directive_id=context.directive_id,
            ) from e

        test_block = raw.get("test") or {}
        family = str(test_block.get("family", "")).upper()
        if family == "PORT":
            print(f"[{self.stage_id}] Stage -0.22: Asset Class Gate SKIPPED (PORT exempt) [OK]")
            return

        symbols = raw.get("symbols") or []
        if not symbols:
            raise PipelineExecutionError(
                "STAGE -0.22 ASSET CLASS GATE: directive has no symbols",
                directive_id=context.directive_id,
            )

        try:
            asset_class = infer_asset_class_from_symbols([str(s) for s in symbols])
        except MixedAssetClassError as e:
            raise PipelineExecutionError(
                f"STAGE -0.22 ASSET CLASS GATE FAILED: mixed asset classes not permitted. {e}",
                directive_id=context.directive_id,
            ) from e
        except UnknownSymbolError as e:
            raise PipelineExecutionError(
                f"STAGE -0.22 ASSET CLASS GATE FAILED: unknown symbol. {e}",
                directive_id=context.directive_id,
            ) from e
        except ValueError as e:
            raise PipelineExecutionError(
                f"STAGE -0.22 ASSET CLASS GATE FAILED: {e}",
                directive_id=context.directive_id,
            ) from e

        print(f"[{self.stage_id}] Stage -0.22: Asset Class Gate PASSED "
              f"(class={asset_class}, symbols={list(symbols)}) [OK]")

    def _run_idea_evaluation(self, context: PipelineContext) -> None:
        """Stage -0.20: Non-blocking concept reuse gate.

        Checks whether the directive's MODEL+TF concept has been previously tested.
        REPEAT_FAILED: raises PipelineAdmissionPause (non-fatal, exit 0) with suggestions.
        REPEAT_WEAK: logs warning with suggestions, continues.
        NEW / REPEAT_PROMISING: passes silently.
        """
        from tools.idea_evaluation_gate import evaluate_idea, print_evaluation
        try:
            result = evaluate_idea(context.directive_path)
        except Exception as e:
            # Gate must never block the pipeline on internal errors
            print(f"[{self.stage_id}] Stage -0.20: Idea Gate internal error "
                  f"({type(e).__name__}: {e}) — skipping. [WARN]")
            return

        status = result.get("status", "NEW")
        rec = result.get("recommendation", "PROCEED")
        suggestions = result.get("suggestions", [])

        if status == "REPEAT_FAILED":
            # Print full evaluation before evaluating any structured override
            print_evaluation(result)

            # Structured override: test.repeat_override_reason >= 50 chars.
            # Allowed ONLY for genuine semantic shifts (signal-definition
            # change, data regime change, structural model change).
            # NOT for parameter tweaks / casual retries / low-PF retries.
            override_reason = self._read_repeat_override_reason(context.directive_path)
            if override_reason and len(override_reason.strip()) >= 50:
                model, asset_class = self._extract_model_and_asset_class(
                    context.directive_path
                )
                self._log_idea_gate_override(
                    directive_id=context.directive_id,
                    model=model,
                    asset_class=asset_class,
                    reason=override_reason.strip(),
                )
                print(
                    f"[{self.stage_id}] Stage -0.20: [IDEA_GATE_OVERRIDDEN] "
                    f"REPEAT_FAILED bypassed with justification. "
                    f"Reason logged to governance/idea_gate_overrides.csv. [!!]"
                )
                print(f"[{self.stage_id}]   Reason: {override_reason.strip()[:140]}"
                      f"{'...' if len(override_reason.strip()) > 140 else ''}")
                return

            suggestion_text = ""
            if suggestions:
                suggestion_text = (
                    "\n\nSuggested hypothesis changes (advisory only):\n"
                    + "\n".join(
                        f"  {i}. [{s.get('type','?')}] ({s.get('confidence','?')})  "
                        f"{s.get('text','')}"
                        for i, s in enumerate(suggestions, 1)
                    )
                )
            override_hint = (
                "\n\nIf this directive represents a genuine semantic shift (signal-definition "
                "change, data regime change, structural model change), add a "
                "'test.repeat_override_reason' field (>=50 chars) explaining why prior "
                "runs are no longer comparable. The override is audited in "
                "governance/idea_gate_overrides.csv."
            )
            raise PipelineAdmissionPause(
                f"STAGE -0.20 IDEA GATE: {status} — {result.get('summary', '')}"
                f"{suggestion_text}"
                f"{override_hint}"
                f"\n\nOtherwise, re-run with a structurally different hypothesis.",
                directive_id=context.directive_id,
            )

        if rec == "PROCEED_WITH_CAUTION":
            # Non-blocking warning: print evaluation + suggestions, then continue
            print_evaluation(result)
            print(f"[{self.stage_id}] Stage -0.20: Idea Gate WARNING — {status}. "
                  f"Proceeding with caution. [!!]")
        else:
            print(f"[{self.stage_id}] Stage -0.20: Idea Gate PASSED — "
                  f"{status} (matches={result.get('matches_found', 0)}). [OK]")

    def _run_classifier_gate(self, context: PipelineContext) -> None:
        """Stage -0.21: Phase 4 classifier gate.

        Compares the current directive against the most recent prior directive
        for the same (MODEL, ASSET_CLASS) and checks:
          1. UNCLASSIFIABLE delta  -> BLOCK (fail-closed).
          2. SIGNAL delta without strict signal_version increase -> BLOCK.
          3. Indicator content-hash drift with unchanged signal_version -> BLOCK.
          4. PARAMETER / COSMETIC / first-of-kind / properly-bumped SIGNAL -> PASS.

        Blocks raise PipelineAdmissionPause (non-fatal, exit 0) so the human
        can decide whether to amend the directive or bypass via override.
        Internal errors are swallowed as warnings — the gate must never take
        down the pipeline on its own bugs.
        """
        from tools.classifier_gate import evaluate as _classifier_evaluate

        try:
            verdict = _classifier_evaluate(context.directive_path)
        except Exception as e:
            print(
                f"[{self.stage_id}] Stage -0.21: Classifier Gate internal error "
                f"({type(e).__name__}: {e}) — skipping. [WARN]"
            )
            return

        if verdict.verdict == "BLOCK":
            raise PipelineAdmissionPause(
                f"STAGE -0.21 CLASSIFIER GATE: {verdict.reason}",
                directive_id=context.directive_id,
            )

        print(
            f"[{self.stage_id}] Stage -0.21: Classifier Gate PASSED "
            f"(classification={verdict.classification}, "
            f"prior={verdict.prior_directive or 'none'}, "
            f"sv={verdict.current_signal_version}). [OK]"
        )

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

    def _read_repeat_override_reason(self, directive_path: Path) -> str:
        """Extract test.repeat_override_reason from the directive, if present."""
        import yaml
        try:
            raw = yaml.safe_load(directive_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return ""
        test_block = raw.get("test") or {}
        reason = test_block.get("repeat_override_reason", "")
        return str(reason) if reason is not None else ""

    def _extract_model_and_asset_class(self, directive_path: Path) -> tuple[str, str]:
        """Extract (model_token, asset_class) from the directive for audit logging."""
        import yaml
        from config.asset_classification import (
            parse_strategy_name, infer_asset_class_from_symbols, classify_asset,
            MixedAssetClassError, UnknownSymbolError,
        )
        try:
            raw = yaml.safe_load(directive_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return ("", "")
        strategy_name = str((raw.get("test") or {}).get("strategy", ""))
        parsed = parse_strategy_name(strategy_name) if strategy_name else None
        model = (parsed or {}).get("model", "")
        symbols_list = raw.get("symbols") or []
        try:
            asset_class = infer_asset_class_from_symbols([str(s) for s in symbols_list])
        except (MixedAssetClassError, UnknownSymbolError, ValueError):
            asset_class = classify_asset(strategy_name)
        return (str(model), str(asset_class))

    def _log_idea_gate_override(
        self,
        directive_id: str,
        model: str,
        asset_class: str,
        reason: str,
    ) -> None:
        """Append a row to governance/idea_gate_overrides.csv. Creates header if missing."""
        import csv
        from datetime import datetime, timezone
        audit_path = (
            Path(__file__).resolve().parent.parent.parent
            / "governance" / "idea_gate_overrides.csv"
        )
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not audit_path.exists()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
        # Collapse newlines in reason to preserve CSV integrity
        safe_reason = " ".join(str(reason).split())
        with audit_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(["timestamp", "directive_id", "model", "asset_class", "reason"])
            writer.writerow([ts, directive_id, model, asset_class, safe_reason])

    def _cleanup_inbox_hold(self, context: PipelineContext) -> None:
        inbox_hold = Path(__file__).resolve().parent.parent.parent / "backtest_directives" / "INBOX_hold"
        hold_path = inbox_hold / context.directive_path.name
        if hold_path.exists():
            hold_path.unlink()
            print(f"[{self.stage_id}] INBOX_hold cleanup: removed {context.directive_path.name}")
