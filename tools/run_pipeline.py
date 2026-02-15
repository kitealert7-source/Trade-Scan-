
"""
run_pipeline.py — Master Execution Pipeline Orchestrator (v3.1)

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
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_EXE = sys.executable
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_DIR / "active"
COMPLETED_DIR = DIRECTIVES_DIR / "completed"


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
    
    # Also check if it's a full path or just name provided in non-standard way
    # But strictly speaking, it should be in active/ for execution.
    print(f"[ERROR] Directive file not found for ID: {directive_id}")
    print(f"Searched in: {ACTIVE_DIR}")
    sys.exit(1)

def parse_concurrency_config(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    max_concurrent = None
    symbols = []
    in_symbols_block = False
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "max concurrent positions" in line.lower():
            parts = line.split(":")
            if len(parts) > 1 and parts[1].strip().isdigit():
                max_concurrent = int(parts[1].strip())
        if line.lower().startswith("symbols:"):
            in_symbols_block = True
            continue
        if in_symbols_block:
            if ":" in line:
                in_symbols_block = False
            else:
                sym = line.replace("-", "").strip()
                if sym: symbols.append(sym)
    return max_concurrent, len(symbols)

def run_single_directive(directive_id):
    """Execution logic for a single directive."""
    # 1. Parsing
    d_path = get_directive_path(directive_id)
    # Norm ID
    clean_id = d_path.stem 
    
    # 0. Preflight (Now Mandatory)
    # run_pipeline assumes the directive is already ISOLATED in active/
    run_command([PYTHON_EXE, "tools/exec_preflight.py", clean_id], "Preflight")

    print(f"[CONFIG] Directive: {d_path.name}")
    max_conf, sym_count = parse_concurrency_config(d_path)
    
    run_constraints = False
    if max_conf is not None and sym_count > 1:
        run_constraints = True
        print(f"[DECISION] Stage-1.5 REQUIRED (Max {max_conf}, Sym {sym_count})")
    else:
        print("[DECISION] Stage-1.5 SKIPPED")

    # 2. Execution Loop
    run_command([PYTHON_EXE, "tools/run_stage1.py", clean_id], "Stage-1 Generator")
    
    if run_constraints:
        # directive_id is passed to script, script expects ID generally
        run_command([PYTHON_EXE, "tools/apply_portfolio_constraints.py", clean_id, str(max_conf)], "Stage-1.5 Constraints")
        
    run_command([PYTHON_EXE, "tools/stage2_compiler.py", "--scan", clean_id], "Stage-2 Compilation")
    run_command([PYTHON_EXE, "tools/stage3_compiler.py"], "Stage-3 Aggregation")
    run_command([PYTHON_EXE, "tools/portfolio_evaluator.py", clean_id], "Stage-4 Evaluation")

def run_batch_mode():
    """Sequential Batch Execution."""
    # 1. Scan
    directives = sorted(ACTIVE_DIR.glob("*.txt"))
    if not directives:
        print("[BATCH] No directives found in active/")
        return

    print(f"[BATCH] Found {len(directives)} directives: {[d.name for d in directives]}")
    
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Processing Loop
    try:
        for idx, d_path in enumerate(directives):
            d_name = d_path.name
            d_id = d_path.stem
            
            print(f"\n[BATCH] Processing Directive {idx+1}/{len(directives)}: {d_name}")
            
            try:
                # RUN PIPELINE
                run_single_directive(d_id)
                
                # Success: Move to completed
                final_dst = COMPLETED_DIR / d_name
                # If exists, overwrite? or fail? overwrite for now as per "Move processed..."
                if final_dst.exists():
                    os.remove(final_dst)
                shutil.move(str(d_path), str(final_dst))
                print(f"[BATCH] Completed: {d_name} -> {COMPLETED_DIR}")
                
            except Exception as e:
                print(f"[BATCH] FAILED: {d_name}")
                print(f"[FAIL-FAST] Stopping batch execution.")
                # Leave failed in active
                sys.exit(1)

        print("\n[BATCH] All directives processed successfully.")

    except Exception as e:
        print(f"\n[BATCH-ABORT] Batch aborted due to error.")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/run_pipeline.py <DIRECTIVE_ID> | --all")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--all":
        run_batch_mode()
    else:
        # Single mode
        directive_id = arg.replace(".txt", "")
        print(f"MASTER PIPELINE EXECUTION — {directive_id}")
        try:
            run_single_directive(directive_id)
            print("\n[SUCCESS] Pipeline Completed Successfully.")
        except Exception:
            sys.exit(1)

if __name__ == "__main__":
    main()
