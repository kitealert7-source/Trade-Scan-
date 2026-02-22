
"""
run_pipeline.py — Master Execution Pipeline Orchestrator (v3.2 - State Gated)

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

Execution Model — Mandatory Compliance:

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
import subprocess
import time
import shutil
import os
import json
import hashlib
from datetime import datetime, timezone
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
    generate_run_id, 
    PipelineStateManager, 
    DirectiveStateManager,
    get_engine_version,
    parse_directive
)

def run_command(cmd_list, step_name):
    print(f"\n{'='*40}")
    print(f"[{step_name}] Executing: {' '.join(cmd_list)}")
    print(f"{'='*40}")
    
    start_time = time.time()
    try:
        subprocess.run(cmd_list, cwd=PROJECT_ROOT, check=True)
        duration = time.time() - start_time
        print(f"[{step_name}] COMPLETED (Time: {duration:.2f}s)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[FATAL] {step_name} FAILED with exit code {e.returncode}")
        # Propagate error up
        raise e
    except Exception as e:
        print(f"\n[FATAL] {step_name} FAILED with error: {e}")
        raise e

def get_directive_path(directive_id):
    """Locate the directive file."""
    candidates = [
        ACTIVE_DIR / directive_id,
        ACTIVE_DIR / f"{directive_id}.txt"
    ]
    for c in candidates:
        if c.exists():
            return c
    
    print(f"[ERROR] Directive file not found for ID: {directive_id}")
    print(f"Searched in: {ACTIVE_DIR}")
    sys.exit(1)

def parse_concurrency_config(file_path):
    from tools.pipeline_utils import parse_directive
    config = parse_directive(file_path)
    # Extract symbols list — support both cased key variants
    symbols = config.get("symbols", config.get("Symbols", []))
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    elif not isinstance(symbols, list):
        symbols = []
    max_concurrent = config.get("max_concurrent_positions", len(symbols))
    if isinstance(max_concurrent, str) and max_concurrent.isdigit():
        max_concurrent = int(max_concurrent)
    return max_concurrent, len(symbols)

def run_single_directive(directive_id):
    """Execution logic for a single directive."""
    # 1. Parsing
    d_path = get_directive_path(directive_id)
    clean_id = d_path.stem 
    
    print(f"[CONFIG] Directive: {d_path.name}")
    
    # 1.1 Generate Deterministic Run ID (Early Binding for State)
    # We need a run ID. For single directive, usually we have multiple symbols.
    # The current batch harness generates ONE run_id PER SYMBOL.
    # This creates a complexity: 
    #   - Directive = "SPX04"
    #   - Symbols = ["SPX500", "NAS100"]
    #   - Runs = 2 separate IDs?
    #
    # Current run_stage1.py architecture iterates symbols and emits artifacts.
    # It generates run_id inside the loop.
    # BUT Phase 7 requires ORCHESTRATOR to manage state.
    # If One Directive -> Multiple Runs, orchestrator must manage Multiple State Files?
    #
    # Audit Rule: "A run may start ONLY with a single explicit human directive." (Invariant 1)
    # But "One Directive -> One Atomic Run" (Invariant 1).
    # If a directive has multiple symbols, is it ONE run or MULTIPLE?
    # SOP_TESTING says: "Each iteration... is isolated... must independently satisfy RUN_COMPLETE".
    #
    # For Batch Mode (Multi-Symbol inside one directive), run_stage1 does the loop.
    # This implies run_stage1 is the "Run".
    # 
    # HOWEVER, Phase 7 requires "runs/<RUN_ID>/run_state.json".
    # If run_stage1 generates multiple RUN_IDs, then we have multiple state files?
    # Checks: run_stage1.py loops symbols.
    # If we want strict state gating *before* run_stage1, we need a parent Run ID for the *Directive Execution*?
    # OR we treat the Directive execution as the "Run" and the symbol-runs as sub-artifacts?
    #
    # Let's look at `pipeline_utils.generate_run_id`. It takes a `symbol`.
    # This implies Run ID is per-symbol.
    #
    # If run_stage1 loops 10 symbols, it generates 10 artifacts with 10 run_ids.
    #
    # PROBLEM: The Orchestrator calls run_stage1 ONCE for the directive.
    # If orchestrator must create state *before* stage1, it needs to know the IDs.
    #
    # SOLUTION:
    # We will enforce "Single Symbol per Run" architecture or "Master Run ID".
    # Given existing "Batch Harness", let's parse symbols here and managing state for each?
    #
    # BUT run_stage1.py does the lopp internally.
    # If we want strict State Gating, the Orchestrator should probably loop?
    #
    # Let's inspect `run_stage1.py` again. It loops `parsed_config.get("Symbols", [])`.
    #
    # Refactoring `run_stage1.py` to single-symbol execution is a large change.
    # ALTERNATIVE: The Orchestrator manages a "Directive Run State"?
    #
    # Re-reading Audit: 
    # "Create run_state.json inside runs/<RUN_ID>/."
    # "Only run_pipeline.py may mutate this file."
    #
    # IF run_stage1 produces multiple run_ids, the Orchestrator must know them ahead of time.
    #
    # Let's parsing symbols here.
    
    # max_conf, count = parse_concurrency_config(d_path) # Stage 1.5 Removed
    
    # We need to re-parse the directive to get the explicit symbol list 
    # used by generation logic to pre-calculate Run IDs.
    # Using pipeline_utils.parse_directive
    from tools.pipeline_utils import parse_directive
    p_conf = parse_directive(d_path)
    symbols = p_conf.get("Symbols", p_conf.get("symbols", []))
    if isinstance(symbols, str): symbols = [symbols]
    
    if not symbols:
        print("[FATAL] No symbols found in directive.")
        sys.exit(1)

    print(f"[ORCHESTRATOR] Found {len(symbols)} symbols: {symbols}")

    # Phase 10: Directive State Manager
    dir_state_mgr = DirectiveStateManager(clean_id)
    dir_state_mgr.initialize()
    
    current_dir_state = dir_state_mgr.get_state()
    print(f"[ORCHESTRATOR] Directive State: {current_dir_state}")
    
    # Resume Safety Logic
    if current_dir_state == "PORTFOLIO_COMPLETE":
         print(f"[ORCHESTRATOR] Directive {clean_id} is already COMPLETE. Aborting.")
         return
    elif current_dir_state == "FAILED":
         # Check for force flag? The tool definition didn't explicitly ask for CLI arg parsing for force,
         # just "Abort unless --force flag passed". 
         # I'll check sys.argv for now as a quick implementation, or just strict abort.
         if "--force" not in sys.argv:
             print(f"[ORCHESTRATOR] Directive {clean_id} is FAILED. Use --force to retry.")
             sys.exit(1)
         else:
             print(f"[ORCHESTRATOR] Force retry enabled. Resetting to INITIALIZED.")
             dir_state_mgr.transition_to("INITIALIZED")

    # 1. Initialize State for All Symbols
    print("[ORCHESTRATOR] Initializing symbol states...") 

    run_ids = []
    for symbol in symbols:
        run_id, _ = generate_run_id(d_path, symbol)
        run_ids.append(run_id)
        # Init individual run state (unless we are resuming later stages, but init is idempotent mostly)
        if current_dir_state not in ["SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"]:
             print(f"[ORCHESTRATOR] Managing Run ID: {run_id} ({symbol})")
             state_mgr = PipelineStateManager(run_id, directive_id=clean_id)
             state_mgr.initialize()

    try:
        # Resume Check
        if dir_state_mgr.get_state() == "SYMBOL_RUNS_COMPLETE":  # live fetch — not stale var
             print("[ORCHESTRATOR] Resuming at Stage-4 (Portfolio)...")
        else:
            # 2. Preflight (Directive Level - Runs Once)
            live_state = dir_state_mgr.get_state()
            _PREFLIGHT_SKIP = {"PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
                               "SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"}
            if live_state not in _PREFLIGHT_SKIP:
                print("[ORCHESTRATOR] Starting Preflight Checks...")
                
                # Execute Preflight
                run_command([PYTHON_EXE, "tools/exec_preflight.py", clean_id], "Preflight")
                
                # Transition ALL to PREFLIGHT_COMPLETE
                for rid in run_ids:
                    PipelineStateManager(rid).transition_to("PREFLIGHT_COMPLETE")
                
                dir_state_mgr.transition_to("PREFLIGHT_COMPLETE")
            else:
                 print(f"[ORCHESTRATOR] Preflight already complete (state={live_state}). Checking Semantic Status...")

            # --- STAGE 0.5: SEMANTIC VALIDATION ---
            # Gate: Must be PREFLIGHT_COMPLETE to enter.
            # Exit: PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
            
            # Semantic validation gate uses live state (fetched below)
            # No stale variable dependency.
            
            check_state = dir_state_mgr.get_state()
            if check_state == "PREFLIGHT_COMPLETE":
                print("[ORCHESTRATOR] Starting Stage-0.5: Semantic Validation...")
                from tools.semantic_validator import validate_semantic_signature
                
                try:
                    validate_semantic_signature(str(d_path))
                    
                    # Transition ALL to PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
                    for rid in run_ids:
                        PipelineStateManager(rid).transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
                        
                    dir_state_mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
                    print("[ORCHESTRATOR] Semantic Validation PASSED.")
                    
                except Exception as e:
                     print(f"[FATAL] Semantic Validation FAILED: {e}")
                     # Transition to FAILED
                     for rid in run_ids:
                        try: PipelineStateManager(rid).transition_to("FAILED")
                        except Exception as e_cleanup: print(f"[WARN] Failed to mark {rid} as FAILED: {e_cleanup}")
                     try: dir_state_mgr.transition_to("FAILED")
                     except Exception as e_cleanup: print(f"[WARN] Failed to mark directive as FAILED: {e_cleanup}")
                     sys.exit(1)
            elif check_state == "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID":
                print("[ORCHESTRATOR] Semantic Validation already COMPLETE. Resuming...")
            elif check_state not in ["SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"]:
                # If we are in some other state (should cover all valid forward states?), maybe error?
                # Actually if SYMBOL_RUNS_COMPLETE, we skip this.
                pass

            # Clean legacy summary CSV only if Stage-1 will rerun for at least one symbol
            _any_stage1_rerun = any(
                PipelineStateManager(rid).get_state_data()["current_state"]
                in ("IDLE", "PREFLIGHT_COMPLETE", "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")
                for rid in run_ids
            )
            summary_csv = PROJECT_ROOT / "backtests" / f"batch_summary_{clean_id}.csv"
            if summary_csv.exists() and _any_stage1_rerun:
                summary_csv.unlink()

            # Orchestrate Atomic Stage-1 Execution
            print("[ORCHESTRATOR] Launching Stage-1 Generator (Atomic)...")
            
            for symbol, rid in zip(symbols, run_ids):
                mgr = PipelineStateManager(rid)
                
                # Skip if symbol has already progressed past Stage-1.
                # Guard must cover all forward states, not just COMPLETE,
                # to prevent illegal re-execution on resume.
                _SKIP_STATES = {
                    "STAGE_1_COMPLETE", "STAGE_2_COMPLETE",
                    "STAGE_3_COMPLETE", "STAGE_3A_COMPLETE", "COMPLETE"
                }
                st = mgr.get_state_data()["current_state"]
                if st in _SKIP_STATES:
                    continue

                try:
                    # 1. Execute Atomic Stage-1
                    cmd = [
                        PYTHON_EXE, 
                        "tools/run_stage1.py", 
                        clean_id, 
                        "--symbol", symbol,
                        "--run_id", rid
                    ]
                    run_command(cmd, f"Stage-1: {symbol}")
                    
                    # 3. Transition to Complete
                    mgr.transition_to("STAGE_1_COMPLETE")
                    
                except Exception as e:
                    print(f"[ERROR] Stage-1 Failed for {symbol}: {e}")
                    try:
                        mgr.transition_to("FAILED")
                    except Exception as e_cleanup:
                        print(f"[WARN] Failed to mark {symbol} run as FAILED: {e_cleanup}")
                    raise e
            
            # End of Stage 1 Loop - Move to Stage 2
            
            # Stage 2
            run_command([PYTHON_EXE, "tools/stage2_compiler.py", "--scan", clean_id], "Stage-2 Compilation")
            
            # Per-run_id artifact existence gate before state transition
            for rid, symbol in zip(run_ids, symbols):
                mgr = PipelineStateManager(rid)
                current = mgr.get_state_data()["current_state"]
                if current == "STAGE_1_COMPLETE":
                    # Verify AK_Trade_Report exists before marking complete
                    run_folder = PROJECT_ROOT / "backtests" / f"{clean_id}_{symbol}"
                    ak_reports = list(run_folder.glob("AK_Trade_Report_*.xlsx"))
                    if ak_reports:
                        mgr.transition_to("STAGE_2_COMPLETE")
                    else:
                        print(f"[WARN] Stage-2 artifact missing for {symbol} ({rid[:8]}). Marking FAILED.")
                        mgr.transition_to("FAILED")

            # Stage 3
            run_command([PYTHON_EXE, "tools/stage3_compiler.py", clean_id], "Stage-3 Aggregation")
            
            for rid, symbol in zip(run_ids, symbols):
                mgr = PipelineStateManager(rid)
                current = mgr.get_state_data()["current_state"]
                
                if current == "STAGE_2_COMPLETE":
                    mgr.transition_to("STAGE_3_COMPLETE")
                    
                    # Stage 3A (Snapshot)
                    # mgr.transition_to("STAGE_3A_START") # Removed
                    
                    # 1. Verify Snapshot Existence
                    snapshot_path = mgr.run_dir / "strategy.py"
                    if not snapshot_path.exists():
                        mgr.transition_to("FAILED")
                        raise RuntimeError(f"Snapshot missing for {rid}")

                    # 2. Verify Snapshot Integrity (Hash Check)
                    strategy_id = p_conf.get("Strategy", p_conf.get("strategy"))
                    source_path = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
                    
                    if not source_path.exists():
                        mgr.transition_to("FAILED")
                        raise RuntimeError(f"Source strategy missing: {source_path}")

                    def get_file_hash(p):
                        return hashlib.sha256(p.read_bytes()).hexdigest()

                    if get_file_hash(snapshot_path) != get_file_hash(source_path):
                        mgr.transition_to("FAILED")
                        raise RuntimeError(f"Snapshot Integrity Mismatch! {rid}/strategy.py != strategies/{strategy_id}/strategy.py")
                    
                    print(f"[ORCHESTRATOR] Snapshot Verified: {rid} matches source.")
                    
                    # Phase 9: Log Snapshot
                    mgr._append_audit_log("SNAPSHOT_VERIFIED", {
                        "strategy_hash": get_file_hash(snapshot_path),
                        "source_hash": get_file_hash(source_path)
                    })
                    
                    # 3. Artifact Hash Binding (Phase 8)
                    bt_dir = PROJECT_ROOT / "backtests" / f"{clean_id}_{symbol}"
                    required_artifacts = {
                        "results_tradelevel.csv": bt_dir / "raw" / "results_tradelevel.csv",
                        "results_standard.csv": bt_dir / "raw" / "results_standard.csv",
                        "batch_summary.csv": PROJECT_ROOT / "backtests" / f"batch_summary_{clean_id}.csv"
                    }
                    
                    artifacts_manifest = {}
                    for name, path in required_artifacts.items():
                        if not path.exists():
                            mgr.transition_to("FAILED")
                            raise RuntimeError(f"Missing required artifact for binding: {path}")
                        artifacts_manifest[name] = get_file_hash(path)

                    manifest = {
                        "run_id": rid,
                        "strategy_hash": get_file_hash(snapshot_path),
                        "artifacts": artifacts_manifest,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }

                    manifest_path = mgr.run_dir / "STRATEGY_SNAPSHOT.manifest.json"
                    with open(manifest_path, "w") as f:
                        json.dump(manifest, f, indent=4)

                    print(f"[ORCHESTRATOR] Manifest Bound: {manifest_path}")

                    # Phase 9: Log Artifact Binding
                    mgr._append_audit_log("ARTIFACT_BOUND", {
                        "manifest_path": str(manifest_path),
                        "artifact_hashes": artifacts_manifest
                    })

                    mgr.transition_to("STAGE_3A_COMPLETE")
                    mgr.transition_to("COMPLETE")
                    
                    # Phase 9: Log Completion
                    mgr._append_audit_log("RUN_COMPLETE", {"status": "SUCCESS"})
            
            # End of Symbol Runs
            dir_state_mgr.transition_to("SYMBOL_RUNS_COMPLETE")


        # Verify Manifests before Stage-4
        print("[ORCHESTRATOR] Verifying Artifact Integrity before Portfolio Evaluation...")
        
        for rid, symbol in zip(run_ids, symbols):
             mgr = PipelineStateManager(rid)
             manifest_path = mgr.run_dir / "STRATEGY_SNAPSHOT.manifest.json"
             
             if not manifest_path.exists():
                mgr.transition_to("FAILED")
                raise RuntimeError(f"Manifest missing for run {rid}")

             with open(manifest_path, "r") as f:
                manifest = json.load(f)

             # Reconstruct paths
             bt_dir = PROJECT_ROOT / "backtests" / f"{clean_id}_{symbol}"
             required_artifacts = {
                "results_tradelevel.csv": bt_dir / "raw" / "results_tradelevel.csv",
                "results_standard.csv": bt_dir / "raw" / "results_standard.csv",
                "batch_summary.csv": PROJECT_ROOT / "backtests" / f"batch_summary_{clean_id}.csv"
             }
             
             # Check Artifacts
             manifest_keys = set(manifest["artifacts"].keys())
             required_keys = set(required_artifacts.keys())
             
             if manifest_keys != required_keys:
                 mgr.transition_to("FAILED")
                 raise RuntimeError(f"Manifest Tampering Detected! Key mismatch for run {rid}. Expected: {required_keys}, Found: {manifest_keys}")

             for name, expected_hash in manifest["artifacts"].items():
                 target_path = required_artifacts[name]
                 if not target_path.exists():
                     mgr.transition_to("FAILED")
                     raise RuntimeError(f"Artifact missing during verification: {target_path}")
                     
                 # Re-compute hash
                 current_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                 if current_hash != expected_hash:
                     mgr.transition_to("FAILED")
                     raise RuntimeError(f"Artifact Tampering Detected! {name} hash mismatch for run {rid}.")
             
             print(f"[ORCHESTRATOR] Verified Integrity: {rid}")

        # Stage 4 (Portfolio)
        run_command([PYTHON_EXE, "tools/portfolio_evaluator.py", clean_id], "Stage-4 Evaluation")
        
        dir_state_mgr.transition_to("PORTFOLIO_COMPLETE")

    except Exception as e:
        print(f"[ORCHESTRATOR] Execution Failed: {e}")
        
        # Directive Commit FAILED
        try:
            dir_state_mgr.transition_to("FAILED")
        except Exception as e_cleanup:
            print(f"[WARN] Failed to mark directive as FAILED: {e_cleanup}")

        # Crash Handling: Mark all non-terminal runs as FAILED
        print("[ORCHESTRATOR] Performing fail-safe state cleanup...")
        for rid in run_ids:
            try:
                mgr = PipelineStateManager(rid)
                if mgr.state_file.exists():
                     with open(mgr.state_file, 'r') as f:
                         data = json.load(f)
                     if data['current_state'] != 'COMPLETE' and data['current_state'] != 'FAILED':
                         print(f"[CLEANUP] Marking run {rid} as FAILED")
                         mgr.transition_to("FAILED")
            except Exception as cleanup_err:
                print(f"[WARN] Failed to cleanup run {rid}: {cleanup_err}")
                
        sys.exit(1)


def run_batch_mode():
    """Sequential Batch Execution."""
    active_dir = PROJECT_ROOT / "backtest_directives" / "active"
    completed_dir = PROJECT_ROOT / "backtest_directives" / "completed"
    
    if not active_dir.exists():
        print(f"[BATCH] Active directory not found: {active_dir}")
        return

    directives = sorted(active_dir.glob("*.txt"))
    if not directives:
        print("[BATCH] No directives found in active/")
        return

    print(f"[BATCH] Found {len(directives)} directives: {[d.name for d in directives]}")
    completed_dir.mkdir(parents=True, exist_ok=True)

    try:
        for idx, d_path in enumerate(directives):
            d_name = d_path.name
            d_id = d_path.stem
            print(f"\n[BATCH] Processing Directive {idx+1}/{len(directives)}: {d_name}")
            try:
                run_single_directive(d_id)
                final_dst = completed_dir / d_name
                if final_dst.exists(): 
                    os.remove(final_dst)
                shutil.move(str(d_path), str(final_dst))
                print(f"[BATCH] Completed: {d_name} -> {completed_dir}")
            except Exception as e:
                print(f"[BATCH] FAILED: {d_name} - {e}")
                print(f"[FAIL-FAST] Stopping batch execution.")
                sys.exit(1)
        print("\n[BATCH] All directives processed successfully.")
    except Exception as e:
        print(f"\n[BATCH-ABORT] Batch aborted due to error: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/run_pipeline.py <DIRECTIVE_ID> | --all")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--all":
        run_batch_mode()
    else:
        directive_id = arg.replace(".txt", "")
        print(f"MASTER PIPELINE EXECUTION — {directive_id}")
        run_single_directive(directive_id)
        print("\n[SUCCESS] Pipeline Completed Successfully.")

if __name__ == "__main__":
    main()
