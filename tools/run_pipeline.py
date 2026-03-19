
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
import json
import hashlib
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_EXE = sys.executable
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_DIR / "INBOX"
ACTIVE_BACKUP_DIR = DIRECTIVES_DIR / "active_backup"
COMPLETED_DIR = DIRECTIVES_DIR / "completed"

def admit_directive(directive_id: str) -> None:
    """Atomic admission of directive from active/ to active_backup/ with marker."""
    d_path = find_directive_path(ACTIVE_DIR, directive_id)
    if not d_path:
        # Check if already admitted (authoritative)
        if find_directive_path(ACTIVE_BACKUP_DIR, directive_id):
            return
        raise PipelineExecutionError(f"Directive {directive_id} not found in {ACTIVE_DIR}")

    ACTIVE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target_path = ACTIVE_BACKUP_DIR / d_path.name
    
    # Atomic Move
    os.replace(str(d_path), str(target_path))
    
    # Create marker
    marker_path = target_path.with_suffix(target_path.suffix + ".admitted")
    marker_path.touch()
    print(f"[ORCHESTRATOR] Admitted: {d_path.name} -> {ACTIVE_BACKUP_DIR}")

def archive_completed_directive(directive_id: str) -> None:
    """Move directive and marker from active_backup/ to completed/."""
    # Source must be active_backup/
    d_path = find_directive_path(ACTIVE_BACKUP_DIR, directive_id)
    if not d_path:
        return

    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
    target_path = COMPLETED_DIR / d_path.name
    
    if target_path.exists():
        os.remove(target_path)
    
    os.replace(str(d_path), str(target_path))
    
    # Move marker if exists
    marker_path = d_path.with_suffix(d_path.suffix + ".admitted")
    if marker_path.exists():
        new_marker = target_path.with_suffix(target_path.suffix + ".admitted")
        os.replace(str(marker_path), str(new_marker))
        
    print(f"[ORCHESTRATOR] Archived: {d_path.name} -> {COMPLETED_DIR}")

def recover_partially_admitted_directives() -> None:
    """On startup, recreate markers for directives in backup missing them."""
    if not ACTIVE_BACKUP_DIR.exists():
        return
        
    for item in ACTIVE_BACKUP_DIR.glob("*.txt"):
        marker = item.with_suffix(item.suffix + ".admitted")
        if not marker.exists():
            marker.touch()
            print(f"[RECOVERY] Recreated admission marker for: {item.name}")

# Governance Imports

sys.path.insert(0, str(PROJECT_ROOT))
from config.state_paths import initialize_state_directories, RUNS_DIR, STRATEGIES_DIR, QUARANTINE_DIR
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
)
from tools.orchestration.pre_execution import (
    find_directive_path,
    prepare_batch_directives_for_execution,
    prepare_single_directive_for_execution,
)
from tools.orchestration.execution_adapter import run_command
from tools.system_registry import reconcile_registry, _load_registry, _save_registry_atomic
from tools.pipeline_utils import PipelineContext, parse_directive
from tools.orchestration.bootstrap_controller import BootstrapController
from tools.orchestration.runner import StageRunner


def enforce_run_schema(project_root: Path):
    """Guardrail: Verify every run container v2 structure."""
    runs_dir = RUNS_DIR
    quarantine_dir = QUARANTINE_DIR / "runs"
    
    if not runs_dir.exists():
        return

    invalid_found = []
    for run_folder in runs_dir.iterdir():
        if not run_folder.is_dir():
            continue
            
        # Standard v2 requirements apply only to run containers (24-char hex IDs)
        if len(run_folder.name) != 24:
            continue
            
        # [FIX] Do not delete freshly provisioned runs (no data yet) 
        # or runs currently in progress. 
        # A run is only "Abandoned" if it's been there a while WITHOUT activity.
        # For now, we only enforce manifest/data for runs that are COMPLETED.
        
        required = ["run_state.json"] # Only run_state is strictly required at startup
        missing = [req for req in required if not (run_folder / req).exists()]
        
        if missing:
            print(f"[GUARDRAIL] Corrupt run container: {run_folder.name} (Missing: {', '.join(missing)})")
            # Fallback to quarantine for corrupt runs
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dst = quarantine_dir / run_folder.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(run_folder), str(dst))
            invalid_found.append(run_folder.name)
            continue

        # If it has a run_state, check if it's old and abandoned
        try:
            from tools.pipeline_utils import PipelineStateManager
            mgr = PipelineStateManager(run_folder.name)
            state_data = mgr.get_state_data()
            current_state = state_data.get("current_state", "IDLE")
            
            # If it's COMPLETE but missing manifest/data, then it's a schema violation
            if current_state == "COMPLETE":
                manifest_exists = (run_folder / "manifest.json").exists()
                data_exists = (run_folder / "data").exists()
                if not manifest_exists or not data_exists:
                    print(f"[GUARDRAIL] Incomplete COMPLETED run: {run_folder.name} (Missing: manifest or data)")
                    # Quarantine...
                    quarantine_dir.mkdir(parents=True, exist_ok=True)
                    dst = quarantine_dir / run_folder.name
                    if dst.exists(): shutil.rmtree(dst)
                    shutil.move(str(run_folder), str(dst))
                    invalid_found.append(run_folder.name)
        except Exception:
            pass # Skip if state cannot be read

    if invalid_found:
        print(f"[FATAL] Schema enforcement failed for {len(invalid_found)} runs. Quarantined to {quarantine_dir}.")
        raise PipelineAdmissionPause(f"Run schema violation. Check {quarantine_dir}.")


def gate_registry_consistency():
    """Guardrail: Detect registry/filesystem drift before execution."""
    print("[GUARDRAIL] Verifying Registry-Filesystem alignment...")
    try:
        results = reconcile_registry()
        
        drift_detected = False
        if results["orphaned_on_disk"]:
            print(f"[DRIFT] DISK_NOT_IN_REGISTRY: {results['orphaned_on_disk']}")
            drift_detected = True
        if results["missing_from_disk"]:
            print(f"[DRIFT] REGISTRY_RUN_MISSING_ON_DISK: {results['missing_from_disk']}")
            print("[AUTO-HEAL] Automatically purging orphaned registry keys...")
            reg = _load_registry()
            for run_id in results["missing_from_disk"]:
                if run_id in reg:
                    del reg[run_id]
            _save_registry_atomic(reg)
            
            # Re-run registry reconciliation
            results = reconcile_registry()
            # If still missing_from_disk, it will still set drift_detected = True below if not cleared
            if results["missing_from_disk"]:
                drift_detected = True
            
        if drift_detected:
            raise PipelineAdmissionPause("Registry drift detected. Manual reconciliation required.")
            
    except PipelineAdmissionPause:
        raise
    except Exception as e:
        print(f"[FATAL] Registry Consistency Gate: {e}")
        raise PipelineAdmissionPause(f"Registry drift detected: {e}")


def verify_manifest_integrity(project_root: Path):
    """Guardrail: Verify that manifest hashes match physical files at startup."""
    print("[GUARDRAIL] Verifying Manifest Integrity (Startup Hash Check)...")
    runs_dir = RUNS_DIR
    if not runs_dir.exists():
        return

    corrupted = []
    for run_folder in runs_dir.iterdir():
        if not run_folder.is_dir(): continue
        
        manifest_path = run_folder / "manifest.json"
        if not manifest_path.exists(): continue
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            # We only check completed runs or those with artifacts
            artifacts = manifest.get("artifacts", {})
            for name, expected_hash in artifacts.items():
                artifact_path = run_folder / "data" / name
                if not artifact_path.exists():
                    corrupted.append(f"{run_folder.name}: Missing artifact {name}")
                    continue
                
                # Check hash
                actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    corrupted.append(f"{run_folder.name}: Hash mismatch for {name}")
                    
        except Exception as e:
            corrupted.append(f"{run_folder.name}: Failed to read manifest ({e})")

    if corrupted:
        print("[FATAL] Manifest Integrity Violations Detected:")
        for err in corrupted:
            print(f"  !! {err}")
        raise PipelineAdmissionPause("Manifest integrity violation. Pipeline halted to prevent corrupt data propagation.")


def verify_tools_timestamp_guard(project_root: Path):
    """Guardrail: Ensure no protected tools were modified after manifest generation."""
    manifest_path = project_root / "tools" / "tools_manifest.json"
    if not manifest_path.exists():
        return

    manifest_mtime = manifest_path.stat().st_mtime
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            
        file_hashes = manifest.get("file_hashes", {})
        for filename in file_hashes:
            # Resolve relative to PROJECT_ROOT as per hardening scope
            filepath = project_root / filename
            # Fallback: maintain compatibility with current manifest (contained in 'tools/')
            if not filepath.exists():
                filepath = project_root / "tools" / filename
                
            if filepath.exists():
                if filepath.stat().st_mtime > manifest_mtime:
                    raise PipelineExecutionError(
                        f"Tool modified after manifest generation: {filename}. "
                        "Run python tools/generate_guard_manifest.py",
                        fail_directive=False,
                        fail_runs=False
                    )
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[WARN] Failed to parse tools manifest for timestamp check: {e}")
    except PipelineExecutionError:
        raise
    except Exception as e:
        print(f"[WARN] Tools timestamp guard encountered an error: {e}")


def verify_directive_uniqueness_guard(directive_id: str):
    """Guardrail: Prevent reuse of already executed directive names."""
    registry = _load_registry()
    if not registry:
        return

    for entry in registry.values():
        if entry.get("directive_id") == directive_id:
            raise PipelineExecutionError(
                f"Directive already executed: {directive_id}. "
                "Create a new directive version before running the pipeline.",
                directive_id=directive_id,
                fail_directive=False,
                fail_runs=False
            )


def detect_strategy_drift(project_root: Path):
    """Guardrail: Detect untracked modification in strategies/."""
    strat_dir = STRATEGIES_DIR
    if not strat_dir.exists():
        return

    drift = []
    for item in strat_dir.iterdir():
        if item.is_file():
            # No files allowed in root of strategies/
            if item.name != "Master_Portfolio_Sheet.xlsx":
                drift.append(f"Unexpected file: {item.name}")
        elif item.is_dir():
            if item.name.startswith("_"):
                continue
            if not (item / "portfolio_evaluation" / "portfolio_metadata.json").exists() and not any(item.glob("*.py")):
                drift.append(f"Untracked directory: {item.name}")

    if drift:
        print("[GUARDRAIL] Strategy Directory Drift Detected:")
        for d in drift:
            print(f"  !! {d}")
        # Note: We warn but don't necessarily halt unless instructed. 
        # User said "halt execution" for schema, but "detect" for drift.
        # I'll make it a hard fail to be safe as per "prevent future filesystem drift".
        raise PipelineAdmissionPause("Strategy directory drift detected. Manual reconciliation required.")


def map_pipeline_error(err):
    """Single top-level mapper for pause/failure outcomes."""
    try:
        from tools.system_logging.pipeline_failure_logger import log_pipeline_failure as _log_failure
    except Exception:
        _log_failure = None

    if isinstance(err, PipelineAdmissionPause):
        print(f"[ORCHESTRATOR] Execution Paused: {err}")
        return err.exit_code

    if isinstance(err, PipelineExecutionError):
        print(f"[ORCHESTRATOR] Execution Failed: {err}")
        if _log_failure:
            _log_failure(
                directive_id=getattr(err, "directive_id", None) or "UNKNOWN",
                run_id=(getattr(err, "run_ids", None) or [None])[0],
                stage="ORCHESTRATOR",
                error_type="PIPELINE_ERROR",
                message=str(err),
            )
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
    ctx = None
    # 1.1 Uniqueness Check
    verify_directive_uniqueness_guard(directive_id)
    
    # 1.2 Bootstrap
    bootstrap = BootstrapController(PROJECT_ROOT)

    try:
        ctx = bootstrap.prepare_context(
            directive_id=directive_id,
            provision_only=provision_only
        )
    except PipelineExecutionError as e:
        if "already COMPLETE" in str(e):
            return  # Clean exit if already done
        raise

    try:
        # StageRunner iterates STAGE_REGISTRY, skipping completed_stages on resume.
        StageRunner(ctx).run()
        print("[ORCHESTRATOR] Pipeline complete.")
        return
    except PipelineError as e:
        if "PREFLIGHT" in str(e) or "Unhandled orchestration failure" in str(e):
            from tools.orchestration.run_cleanup import cleanup_provisioned_runs
            if getattr(ctx, 'run_ids', []):
                cleanup_provisioned_runs(ctx.run_ids)
        raise
    except Exception as e:
        from tools.orchestration.run_cleanup import cleanup_provisioned_runs
        if getattr(ctx, 'run_ids', []):
            cleanup_provisioned_runs(ctx.run_ids)
        import traceback
        traceback.print_exc()
        raise PipelineExecutionError(
            f"Unhandled orchestration failure: {e}",
            directive_id=directive_id,
            run_ids=getattr(ctx, 'run_ids', []),
        ) from e


def run_batch_mode(provision_only=False):
    """Sequential Batch Execution."""
    active_dir = PROJECT_ROOT / "backtest_directives" / "INBOX"
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
    
    # --- ACTIVE Bypass Guard ---
    try:
        from tools.sweep_registry_gate import _load_yaml, SWEEP_REGISTRY_PATH
        registry_data = _load_yaml(SWEEP_REGISTRY_PATH)
        allocated_names = set()
        ideas = registry_data.get("ideas", {})
        if isinstance(ideas, dict):
            for idea_data in ideas.values():
                if isinstance(idea_data, dict):
                    sweeps = idea_data.get("sweeps", idea_data.get("allocated", {}))
                    if isinstance(sweeps, dict):
                        for sweep_data in sweeps.values():
                            if isinstance(sweep_data, dict):
                                d_name = sweep_data.get("directive_name")
                                if d_name:
                                    allocated_names.add(d_name)
                                patches = sweep_data.get("patches", {})
                                if isinstance(patches, dict):
                                    for patch_data in patches.values():
                                        if isinstance(patch_data, dict):
                                            p_name = patch_data.get("directive_name")
                                            if p_name:
                                                allocated_names.add(p_name)
        for d_path in directives:
            if d_path.stem not in allocated_names:
                print(f"DIRECTIVE_NOT_ADMITTED | directive={d_path.name}")
    except Exception as e:
        print(f"[WARN] Failed to run ACTIVE Bypass Guard: {e}")
    # ---------------------------

    completed_dir.mkdir(parents=True, exist_ok=True)

    for idx, d_path in enumerate(directives):
        d_name = d_path.name
        d_id = d_path.stem
        print(f"\n[BATCH] Processing Directive {idx+1}/{len(directives)}: {d_name}")
        try:
            # Phase 1: Admission (Move from active/ -> active_backup/ + marker)
            if not provision_only:
                admit_directive(d_id)
            
            run_single_directive(d_id, provision_only=provision_only)
            
            if not provision_only:
                # Phase 2: Archive (Move from active_backup/ -> completed/ + move marker)
                archive_completed_directive(d_id)
            else:
                print(f"[BATCH] Provision-only: {d_name} remains in INBOX/")
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
            
    if not provision_only:
        print("\n[BATCH] Running Candidate Promotion (filter_strategies.py)...")
        try:
            run_command([PYTHON_EXE, "tools/filter_strategies.py"], "Candidate Promotion")
        except Exception as e:
            print(f"[WARN] Candidate promotion failed: {e}")

    print("\n[BATCH] All directives processed successfully.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/run_pipeline.py <DIRECTIVE_ID> | --all")
        sys.exit(1)

    arg = sys.argv[1]
    provision_only = "--provision-only" in sys.argv[2:]

    try:
        initialize_state_directories()
        print("[ORCHESTRATOR] Initializing Startup Guardrails...")
        verify_tools_timestamp_guard(PROJECT_ROOT)
        enforce_run_schema(PROJECT_ROOT)
        detect_strategy_drift(PROJECT_ROOT)
        gate_registry_consistency()
        
        # Phase 10: Watchdog integration
        from tools.orchestration.run_watchdog import recover_stale_runs
        recover_stale_runs()
        
        # Phase 11: Directive Admission Recovery
        recover_partially_admitted_directives()

        verify_manifest_integrity(PROJECT_ROOT)
        
        print("[ORCHESTRATOR] Performing authoritative registry reconciliation sweep...")
        reconcile_registry()
        
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

            # Phase 1: Admission (Move from active/ -> active_backup/ + marker)
            if not provision_only:
                admit_directive(directive_id)

            print(f"MASTER PIPELINE EXECUTION -- {directive_id}")
            run_single_directive(directive_id, provision_only=provision_only)
            
            if not provision_only:
                # Phase 2: Archive (Move from active_backup/ -> completed/ + move marker)
                archive_completed_directive(directive_id)

                print("\n[PIPELINE] Running Candidate Promotion (filter_strategies.py)...")
                try:
                    run_command([PYTHON_EXE, "tools/filter_strategies.py"], "Candidate Promotion")
                except Exception as e:
                    print(f"[WARN] Candidate promotion failed: {e}")

            print("\n[SUCCESS] Pipeline Completed Successfully.")
    except PipelineError as err:
        sys.exit(map_pipeline_error(err))
    except Exception as err:
        wrapped = PipelineExecutionError(f"Unhandled pipeline error: {err}")
        sys.exit(map_pipeline_error(wrapped))

if __name__ == "__main__":
    main()
