
"""
run_pipeline.py -- Master Execution Pipeline Orchestrator (v3.2 - State Gated)

Usage:
  python tools/run_pipeline.py <DIRECTIVE_ID>
  python tools/run_pipeline.py --all

Purpose:
  Orchestrates the deterministic multi-asset execution flow:

  0. Preflight (Safety & Governance Checks)
  1. Directive Parsing (Concurrency + Symbol Detection)
  2. Stage-1: Generation (RESEARCH Data Only)
  3. Stage-1.5: Portfolio Risk Constraints (Conditional)
  4. Stage-2: Compilation
  5. Stage-3: Aggregation
  6. Stage-4: Portfolio Evaluation

Execution Model -- Mandatory Compliance:

  - All execution gated by run_state.json (Audit Phase 7)
  - All Stage-1 executions MUST use RESEARCH market data.
  - CLEAN or derived datasets are non-authoritative and prohibited.
  - Directive must contain executable conditions.
  - STRATEGY_PLUGIN_CONTRACT.md must be satisfied.
  - SOP_INDICATOR.md must be enforced (repository-only indicators).
  - No inline indicator logic permitted.

Authority:
  governance/SOP/SOP_TESTING.md
  governance/SOP/STRATEGY_PLUGIN_CONTRACT.md
  governance/SOP/SOP_INDICATOR.md

"""


import sys
import shutil
import os
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_EXE = sys.executable
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_DIR / "active"
COMPLETED_DIR = DIRECTIVES_DIR / "completed"

# Governance Imports
sys.path.insert(0, str(PROJECT_ROOT))
from tools.pipeline_utils import (
    PipelineStateManager, 
    DirectiveStateManager,
)
from tools.orchestration.transition_service import (
    transition_directive_state,
    fail_run_best_effort,
    fail_directive_best_effort,
)
from tools.orchestration.pipeline_errors import (
    PipelineAdmissionPause,
    PipelineError,
    PipelineExecutionError,
)
from tools.orchestration.pipeline_stages import (
    run_preflight_semantic_checks,
    run_symbol_execution_stages,
    run_portfolio_and_post_stages,
)
from tools.orchestration.pre_execution import (
    find_directive_path,
    prepare_batch_directives_for_execution,
    prepare_single_directive_for_execution,
)
from tools.orchestration.execution_adapter import run_command
from tools.orchestration.run_planner import plan_runs_for_directive


def map_pipeline_error(err):
    """Single top-level mapper for pause/failure outcomes."""
    if isinstance(err, PipelineAdmissionPause):
        print(f"[ORCHESTRATOR] Execution Paused: {err}")
        return err.exit_code

    if isinstance(err, PipelineExecutionError):
        print(f"[ORCHESTRATOR] Execution Failed: {err}")
        if err.fail_directive and err.directive_id:
            fail_directive_best_effort(err.directive_id)

        if err.fail_runs and err.run_ids:
            print("[ORCHESTRATOR] Performing fail-safe state cleanup...")
            for rid in err.run_ids:
                try:
                    if fail_run_best_effort(rid):
                        print(f"[CLEANUP] Marking run {rid} as FAILED")
                except Exception as cleanup_err:
                    print(f"[WARN] Failed to cleanup run {rid}: {cleanup_err}")
        return err.exit_code

    print(f"[ORCHESTRATOR] Unhandled Error: {err}")
    return 1

def get_directive_path(directive_id):
    """Locate the directive file."""
    found = find_directive_path(ACTIVE_DIR, directive_id)
    if found:
        return found
    
    raise PipelineExecutionError(
        f"Directive file not found for ID: {directive_id}. Searched in: {ACTIVE_DIR}",
        directive_id=directive_id,
        fail_directive=False,
        fail_runs=False,
    )

def parse_concurrency_config(file_path):
    from tools.pipeline_utils import parse_directive
    config = parse_directive(file_path)
    # Extract symbols list -- support both cased key variants
    symbols = config.get("symbols", config.get("Symbols", []))
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    elif not isinstance(symbols, list):
        symbols = []
    max_concurrent = config.get("max_concurrent_positions", len(symbols))
    if isinstance(max_concurrent, str) and max_concurrent.isdigit():
        max_concurrent = int(max_concurrent)
    return max_concurrent, len(symbols)

def run_single_directive(directive_id, provision_only=False):
    """Execution logic for a single directive."""
    run_ids = []
    clean_id = directive_id
    registry_path = None

    # 1. Parsing
    d_path = get_directive_path(directive_id)
    clean_id = d_path.stem 
    
    print(f"[CONFIG] Directive: {d_path.name}")
    
    # Directive-to-run mapping rationale is documented in governance/directive_execution_model.md.
    
    # We need the symbol list pre-Stage-0.25 only to pre-calculate Run IDs.
    # Use a raw yaml.safe_load() to extract symbols without invoking parse_directive()
    # strict validation (which requires test: wrapper, collisions, etc.).
    # This ensures non-canonical directives still reach Stage -0.25 rather than
    # failing here with a confusing INVALID DIRECTIVE STRUCTURE error.
    import yaml as _yaml_pre
    try:
        _raw_pre = _yaml_pre.safe_load(d_path.read_text(encoding="utf-8")) or {}
    except Exception as _pre_err:
        raise PipelineExecutionError(
            f"YAML_PARSE_ERROR (pre-Stage-0.25): {_pre_err}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from _pre_err
    # Support both canonical (test: wrapper) and flat directives for symbol extraction only
    _test_block_pre = _raw_pre.get("test", {})
    symbols = (
        _raw_pre.get("symbols")
        or _raw_pre.get("Symbols")
        or _test_block_pre.get("symbols")
        or _test_block_pre.get("Symbols")
        or []
    )
    if isinstance(symbols, str):
        symbols = [symbols]

    if not symbols:
        raise PipelineExecutionError(
            "No symbols found in directive.",
            directive_id=clean_id,
            run_ids=run_ids,
        )

    print(f"[ORCHESTRATOR] Found {len(symbols)} symbols: {symbols}")

    # ----------------------------------------------------------
    # STAGE -0.25: DIRECTIVE CANONICALIZATION GATE
    # Must run before any state initialization or pipeline stage.
    # ----------------------------------------------------------
    from tools.canonicalizer import canonicalize, CanonicalizationError
    import yaml as _yaml

    try:
        raw_yaml = d_path.read_text(encoding="utf-8")
        parsed_raw = _yaml.safe_load(raw_yaml)
        canonical, canonical_yaml, diff_lines, violations, has_drift = \
            canonicalize(parsed_raw)
    except CanonicalizationError as e:
        raise PipelineExecutionError(
            f"STAGE -0.25 CANONICALIZATION FAILED: {e}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from e
    except _yaml.YAMLError as e:
        raise PipelineExecutionError(
            f"YAML_PARSE_ERROR: {e}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from e

    if violations:
        print("[STAGE -0.25] Structural changes detected:")
        for level, msg in violations:
            print(f"  [{level}] {msg}")

    if has_drift:
        print("\n[STAGE -0.25] STRUCTURAL DRIFT -- directive is not canonical.")
        print("  --- Unified Diff ---")
        for line in diff_lines:
            print(f"  {line}", end="")
        tmp_path = Path("/tmp") / f"{clean_id}_canonical.yaml"
        tmp_path.write_text(canonical_yaml, encoding="utf-8")
        print(f"\n  Corrected YAML written to: {tmp_path}")
        print("  Human must review and approve overwrite.")
        print("[HALT] Pipeline stopped. Fix directive and re-run.")
        raise PipelineExecutionError(
            "Stage -0.25 halted due to structural drift in directive.",
            directive_id=clean_id,
            run_ids=run_ids,
            fail_directive=False,
            fail_runs=False,
        )
    else:
        print("[STAGE -0.25] Directive is in canonical form. [OK]")

    # ----------------------------------------------------------
    # STAGE -0.30: NAMESPACE GOVERNANCE GATE (PHASE-1)
    # Enforces naming pattern, token dictionaries, alias policy,
    # filename/test identity equality, and idea registry match.
    # ----------------------------------------------------------
    try:
        from tools.namespace_gate import validate_namespace
        ns_details = validate_namespace(d_path)
        print(
            "[STAGE -0.30] Namespace Gate PASSED: "
            f"{ns_details['strategy_name']} "
            f"(ID={ns_details['idea_id']}, "
            f"FAMILY={ns_details['family']}, "
            f"MODEL={ns_details['model']}, "
            f"FILTER={ns_details.get('filter') or 'NONE'})"
        )
    except Exception as e:
        raise PipelineExecutionError(
            f"STAGE -0.30 NAMESPACE GATE FAILED: {e}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from e

    # ----------------------------------------------------------
    # STAGE -0.35: SWEEP REGISTRY GATE (PHASE-2)
    # Enforces unique sweep allocation per idea lineage.
    # ----------------------------------------------------------
    try:
        from tools.sweep_registry_gate import reserve_sweep
        sw_details = reserve_sweep(d_path, auto_advance=True)
        print(
            "[STAGE -0.35] Sweep Gate PASSED: "
            f"status={sw_details['status']} "
            f"idea={sw_details['idea_id']} "
            f"sweep={sw_details['sweep']}"
        )
    except Exception as e:
        raise PipelineExecutionError(
            f"STAGE -0.35 SWEEP GATE FAILED: {e}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from e

    # Stage -0.25 passed. Now safe to call parse_directive() with strict validation.
    # This is the earliest correct point: canonical structure is confirmed.
    # Fix 3: Previously parse_directive() ran before Stage -0.25, so non-canonical
    # directives failed with INVALID DIRECTIVE STRUCTURE before reaching the gate.
    from tools.pipeline_utils import parse_directive
    p_conf = parse_directive(d_path)
    # Authoritative symbol resolution from fully parsed config
    symbols = p_conf.get("Symbols", p_conf.get("symbols", symbols))
    if isinstance(symbols, str):
        symbols = [symbols]

    dir_state_mgr = DirectiveStateManager(clean_id)
    dir_state_mgr.initialize()
    
    current_dir_state = dir_state_mgr.get_state()
    print(f"[ORCHESTRATOR] Directive State: {current_dir_state}")
    
    # Resume Safety Logic
    if current_dir_state == "PORTFOLIO_COMPLETE":
         print(f"[ORCHESTRATOR] Directive {clean_id} is already COMPLETE. Aborting.")
         return
    elif current_dir_state == "FAILED":
         if provision_only:
             print(f"[ORCHESTRATOR] Directive {clean_id} is FAILED. Resetting for --provision-only run.")
             transition_directive_state(clean_id, "INITIALIZED")
             current_dir_state = dir_state_mgr.get_state()
             print(f"[ORCHESTRATOR] Directive State after reset: {current_dir_state}")
         else:
             print(f"[ORCHESTRATOR] Directive {clean_id} is FAILED.")
             print(f"[ORCHESTRATOR] To reset, run: python tools/reset_directive.py {clean_id} --reason \"<justification>\"")
             raise PipelineExecutionError(
                 f"Directive {clean_id} is FAILED and must be reset before rerun.",
                 directive_id=clean_id,
                 run_ids=run_ids,
                 fail_directive=False,
                 fail_runs=False,
             )

    strategy_id = p_conf.get("Strategy", p_conf.get("strategy")) or clean_id
    planned_runs, registry_path = plan_runs_for_directive(
        directive_id=clean_id,
        directive_path=d_path,
        strategy_id=strategy_id,
        symbols=symbols,
        project_root=PROJECT_ROOT,
    )
    run_ids = [run["run_id"] for run in planned_runs]
    symbols = [run["symbol"] for run in planned_runs]

    # 1. Initialize State for All Planned Runs
    print("[ORCHESTRATOR] Initializing symbol states...")
    for run in planned_runs:
        run_id = run["run_id"]
        symbol = run["symbol"]
        # Init individual run state (unless we are resuming later stages, but init is idempotent mostly)
        if current_dir_state not in ["SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"]:
             print(f"[ORCHESTRATOR] Managing Run ID: {run_id} ({symbol})")
             state_mgr = PipelineStateManager(run_id, directive_id=clean_id)
             state_mgr.initialize()

    try:
        # Resume Check
        if dir_state_mgr.get_state() == "SYMBOL_RUNS_COMPLETE":  # live fetch -- not stale var
             print("[ORCHESTRATOR] Resuming at Stage-4 (Portfolio)...")
        else:
            should_stop = run_preflight_semantic_checks(
                clean_id=clean_id,
                d_path=d_path,
                p_conf=p_conf,
                run_ids=run_ids,
                symbols=symbols,
                dir_state_mgr=dir_state_mgr,
                provision_only=provision_only,
                project_root=PROJECT_ROOT,
                python_exe=PYTHON_EXE,
                run_command=run_command,
            )
            if should_stop:
                return

            run_symbol_execution_stages(
                clean_id=clean_id,
                p_conf=p_conf,
                run_ids=run_ids,
                symbols=symbols,
                project_root=PROJECT_ROOT,
                python_exe=PYTHON_EXE,
                run_command=run_command,
                registry_path=registry_path,
            )

        run_portfolio_and_post_stages(
            clean_id=clean_id,
            p_conf=p_conf,
            run_ids=run_ids,
            symbols=symbols,
            project_root=PROJECT_ROOT,
            python_exe=PYTHON_EXE,
            run_command=run_command,
        )
    except PipelineError:
        raise
    except Exception as e:
        raise PipelineExecutionError(
            f"Unhandled orchestration failure: {e}",
            directive_id=clean_id,
            run_ids=run_ids,
        ) from e


def run_batch_mode(provision_only=False):
    """Sequential Batch Execution."""
    active_dir = PROJECT_ROOT / "backtest_directives" / "active"
    completed_dir = PROJECT_ROOT / "backtest_directives" / "completed"
    
    if not active_dir.exists():
        print(f"[BATCH] Active directory not found: {active_dir}")
        return

    directives = prepare_batch_directives_for_execution(
        active_dir=active_dir,
        python_exe=PYTHON_EXE,
        run_command=run_command,
    )
    if not directives:
        print("[BATCH] No directives found in active/")
        return

    print(f"[BATCH] Found {len(directives)} directives: {[d.name for d in directives]}")
    completed_dir.mkdir(parents=True, exist_ok=True)

    for idx, d_path in enumerate(directives):
        d_name = d_path.name
        d_id = d_path.stem
        print(f"\n[BATCH] Processing Directive {idx+1}/{len(directives)}: {d_name}")
        try:
            run_single_directive(d_id, provision_only=provision_only)
            if not provision_only:
                final_dst = completed_dir / d_name
                if final_dst.exists():
                    os.remove(final_dst)
                shutil.move(str(d_path), str(final_dst))
                print(f"[BATCH] Completed: {d_name} -> {completed_dir}")
            else:
                print(f"[BATCH] Provision-only: {d_name} remains in active/")
        except PipelineError:
            print(f"[FAIL-FAST] Stopping batch execution at directive: {d_name}")
            raise
        except Exception as e:
            print(f"[BATCH] FAILED: {d_name} - {e}")
            print("[FAIL-FAST] Stopping batch execution.")
            raise PipelineExecutionError(
                f"Batch directive failed: {d_name}: {e}",
                directive_id=d_id,
            ) from e
    print("\n[BATCH] All directives processed successfully.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/run_pipeline.py <DIRECTIVE_ID> | --all")
        sys.exit(1)

    arg = sys.argv[1]
    provision_only = "--provision-only" in sys.argv[2:]

    try:
        if arg == "--all":
            run_batch_mode(provision_only=provision_only)
            print("\n[SUCCESS] Batch Pipeline Completed Successfully.")
        else:
            directive_id = arg.replace(".txt", "")
            directive_id = prepare_single_directive_for_execution(
                directive_id=directive_id,
                active_dir=ACTIVE_DIR,
                python_exe=PYTHON_EXE,
                run_command=run_command,
            )

            print(f"MASTER PIPELINE EXECUTION -- {directive_id}")
            run_single_directive(directive_id, provision_only=provision_only)
            print("\n[SUCCESS] Pipeline Completed Successfully.")
    except PipelineError as err:
        sys.exit(map_pipeline_error(err))
    except Exception as err:
        wrapped = PipelineExecutionError(f"Unhandled pipeline error: {err}")
        sys.exit(map_pipeline_error(wrapped))

if __name__ == "__main__":
    main()

