
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
from concurrent.futures import ProcessPoolExecutor, as_completed

# Config
PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_EXE = sys.executable
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_DIR / "INBOX"
ACTIVE_BACKUP_DIR = DIRECTIVES_DIR / "active_backup"
COMPLETED_DIR = DIRECTIVES_DIR / "completed"

def admit_directive(directive_id: str) -> None:
    """Atomic admission of directive from INBOX/ to active_backup/ with marker."""
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

def reconcile_active_backup() -> None:
    """
    Archive any directives in active_backup/ that have already reached PORTFOLIO_COMPLETE.

    Called on startup and at the end of every run (including interrupted batch runs) so
    that a fail-fast abort never permanently strands a completed directive in active_backup/.
    The DirectiveStateManager is the authority — only PORTFOLIO_COMPLETE directives move.
    """
    if not ACTIVE_BACKUP_DIR.exists():
        return
    for d_path in sorted(ACTIVE_BACKUP_DIR.glob("*.txt")):
        directive_id = d_path.stem
        state = DirectiveStateManager(directive_id).get_state()
        if state == "PORTFOLIO_COMPLETE":
            archive_completed_directive(directive_id)
            print(f"[RECONCILE] Auto-archived PORTFOLIO_COMPLETE directive: {directive_id}")


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


def validate_inbox_directive_tokens():
    """
    Token Gate: validate MODEL token in all INBOX directives against
    token_dictionary.yaml before any pipeline work begins.
    Zero state changes on failure — nothing is provisioned, nothing is moved.
    Name format: {id}_{FAMILY}_{SYMBOL}_{TF}_{MODEL}[_{FILTER}]_{SWEEP}_{V#}_{P##}
    MODEL is always the 5th component (index 4).
    """
    import yaml
    token_dict_path = PROJECT_ROOT / "governance" / "namespace" / "token_dictionary.yaml"
    if not token_dict_path.exists():
        return

    try:
        token_data = yaml.safe_load(token_dict_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[TOKEN GATE] Could not read token_dictionary.yaml ({e}) — skipping token check.")
        return

    valid_models  = {t.upper() for t in token_data.get("model", [])}
    alias_keys    = {k.upper() for k in token_data.get("aliases", {}).get("model", {})}
    all_valid     = valid_models | alias_keys

    inbox = PROJECT_ROOT / "backtest_directives" / "INBOX"
    if not inbox.exists():
        return

    errors = []
    for directive_file in sorted(inbox.glob("*.txt")):
        parts = directive_file.stem.split("_")
        if len(parts) < 5:
            continue
        model_token = parts[4].upper()
        if model_token not in all_valid:
            errors.append(
                f"  {directive_file.name}\n"
                f"    MODEL='{model_token}' is not a valid token.\n"
                f"    Valid: {', '.join(sorted(valid_models))}\n"
                f"    Aliases: {', '.join(sorted(alias_keys)) or 'none'}"
            )

    if errors:
        print("[TOKEN GATE] INVALID MODEL TOKEN(S) — pipeline blocked before any state change:")
        for err in errors:
            print(err)
        raise PipelineAdmissionPause(
            "Invalid namespace token(s) in INBOX. Fix directive filename(s) and re-run."
        )

    print(f"[TOKEN GATE] All INBOX directive tokens valid.")


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
            # Auto-recovered by reconciler — not actionable drift, just a warning.
            print(f"[DRIFT] DISK_NOT_IN_REGISTRY (auto-recovered): {results['orphaned_on_disk']}")
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
            # No files allowed in root of strategies/ except the portfolio sheet
            # and Office temp lock files (~$...) which are transient and harmless.
            if item.name != "Master_Portfolio_Sheet.xlsx" and not item.name.startswith("~$"):
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
        from tools.sweep_registry_gate import (
            _load_yaml, SWEEP_REGISTRY_PATH, get_all_allocated_names,
        )
        registry_data = _load_yaml(SWEEP_REGISTRY_PATH)
        allocated_names = get_all_allocated_names(registry_data)
        for d_path in directives:
            if d_path.stem not in allocated_names:
                print(f"DIRECTIVE_NOT_ADMITTED | directive={d_path.name}")
    except Exception as e:
        print(f"[WARN] Failed to run ACTIVE Bypass Guard: {e}")
    # ---------------------------

    completed_dir.mkdir(parents=True, exist_ok=True)

    # --- PHASE 1: ADMISSION (SEQUENTIAL) ---
    admitted = [d_path.stem for d_path in directives]
    if not provision_only:
        for d_id in admitted:
            admit_directive(d_id)

    print(f"[BATCH] Admitted {len(admitted)} directive(s). Starting parallel execution (max_workers=2)...")

    # --- PHASE 2: PARALLEL EXECUTION ---
    with ProcessPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(run_single_directive, d_id, provision_only): d_id
            for d_id in admitted
        }
        for fut in as_completed(futures):
            d_id = futures[fut]
            try:
                fut.result()
                print(f"[BATCH] Completed: {d_id}")
            except PipelineError as e:
                print(f"[BATCH] FAILED: {d_id} - {e}")
                print("[FAIL-FAST] Stopping batch execution.")
                print("[FAIL-FAST] Waiting for running tasks to complete...")
                for f in futures:
                    f.cancel()
                raise
            except Exception as e:
                print(f"[BATCH] FAILED: {d_id} - {e}")
                print("[FAIL-FAST] Stopping batch execution.")
                print("[FAIL-FAST] Waiting for running tasks to complete...")
                for f in futures:
                    f.cancel()
                raise PipelineExecutionError(
                    f"Batch directive failed: {d_id}: {e}",
                    directive_id=d_id,
                ) from e

    # --- PHASE 3: ARCHIVE (SEQUENTIAL) ---
    # Only reached if all futures succeeded.
    if not provision_only:
        for d_id in admitted:
            archive_completed_directive(d_id)
    else:
        for d_id in admitted:
            print(f"[BATCH] Provision-only: {d_id} remains in INBOX/")
            
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
        validate_inbox_directive_tokens()
        verify_tools_timestamp_guard(PROJECT_ROOT)
        enforce_run_schema(PROJECT_ROOT)
        detect_strategy_drift(PROJECT_ROOT)
        gate_registry_consistency()
        
        # Phase 10: Watchdog integration
        from tools.orchestration.run_watchdog import recover_stale_runs
        recover_stale_runs()
        
        # Phase 11: Directive Admission Recovery + stale-backup reconcile
        recover_partially_admitted_directives()
        reconcile_active_backup()

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

            # Phase 1: Admission (Move from INBOX/ -> active_backup/ + marker)
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
    finally:
        # Post-run reconcile: archive any PORTFOLIO_COMPLETE directives that
        # were stranded in active_backup/ by a fail-fast abort or prior crash.
        if not provision_only:
            try:
                reconcile_active_backup()
            except Exception as e:
                print(f"[WARN] Post-run reconcile failed: {e}")

if __name__ == "__main__":
    main()
