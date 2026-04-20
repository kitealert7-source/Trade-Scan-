"""
Directive Linter — Operator Workflow Entrypoint for TradeScan
This tool wraps the AdmissionStage governance gates to safely admit directives
from the INBOX to the ACTIVE queue.

Modes:
--check  : run validation and report issues (does not move file)
--admit  : run validation and atomically move to ACTIVE if successful
--status : read-only query — show sweep registration and run status for INBOX directives
"""

import argparse
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import PipelineContext
from tools.orchestration.admission_controller import AdmissionStage, CanonicalizationDriftError
from tools.orchestration.pipeline_errors import PipelineExecutionError

INBOX_DIR = PROJECT_ROOT / "backtest_directives" / "INBOX"
ACTIVE_DIR = PROJECT_ROOT / "backtest_directives" / "active"


def process_directive(file_path: Path, mode: str) -> bool:
    """Process a single directive file through the AdmissionStage."""
    print(f"\n--- Processing: {file_path.name} ---")
    
    directive_id = file_path.stem
    context = PipelineContext(
        directive_id=directive_id,
        directive_path=file_path,
        project_root=PROJECT_ROOT,
        python_exe=sys.executable
    )
    
    stage = AdmissionStage()
    
    try:
        stage.run(context)
        print(f"[OK] {file_path.name} passed all admission gates.")
        
        if mode == "admit":
            target_path = ACTIVE_DIR / file_path.name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic move
            os.replace(str(file_path), str(target_path))
            print(f"[ADMITTED] {file_path.name} moved to ACTIVE.")
        return True

    except CanonicalizationDriftError as e:
        print(e)
        if mode == "admit":
            # Canonicalization Diff Approval Safeguard
            response = input("\nType 'APPROVED' to accept structural drift and overwrite the directive: ").strip()
            if response == "APPROVED":
                tmp_path = PROJECT_ROOT / ".canonical_staging" / f"{directive_id}_canonical.yaml"
                if tmp_path.exists():
                    file_path.write_text(tmp_path.read_text(encoding="utf-8"), encoding="utf-8")
                    print("[APPROVED] Directive structure overwritten. Re-evaluating...")
                    # Re-run after approval
                    return process_directive(file_path, mode)
                else:
                    print(f"[ERROR] Corrected YAML not found at {tmp_path}.")
                    return False
            else:
                print(f"[HALT] Drift not approved for {file_path.name}.")
                return False
        else:
            print(f"\n[INFO] Run with --admit to approve this drift for {file_path.name}.")
            return False

    except PipelineExecutionError as e:
        print(f"[REJECTED] {file_path.name} failed admission: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error processing {file_path.name}: {e}")
        return False


def run_status_mode(directive_arg: str | None) -> int:
    """Read-only status query: sweep registration + run status for INBOX directives."""
    from tools.sweep_registry_gate import _load_yaml, SWEEP_REGISTRY_PATH
    from tools.system_registry import _load_registry

    # Determine target files
    if directive_arg:
        target = Path(directive_arg)
        if not target.exists():
            print(f"File not found: {target}")
            return 1
        files = [target]
    else:
        if not INBOX_DIR.exists():
            print(f"INBOX directory not found: {INBOX_DIR}")
            return 1
        files = sorted(INBOX_DIR.glob("*.txt")) + sorted(INBOX_DIR.glob("*.yaml"))
        if not files:
            print(f"No directives found in {INBOX_DIR}")
            return 0

    # Load sweep registry
    try:
        registry_data = _load_yaml(SWEEP_REGISTRY_PATH)
    except Exception as e:
        print(f"[WARN] Could not load sweep registry: {e}")
        registry_data = {}

    # Build sweep lookup: directive_name -> {idea_id, sweep, attempt}
    sweep_index: dict = {}
    ideas = registry_data.get("ideas", {})
    if isinstance(ideas, dict):
        for idea_id, idea_data in ideas.items():
            if not isinstance(idea_data, dict):
                continue
            sweeps = idea_data.get("sweeps", idea_data.get("allocated", {}))
            if not isinstance(sweeps, dict):
                continue
            for sweep_key, sweep_data in sweeps.items():
                if not isinstance(sweep_data, dict):
                    continue
                d_name = sweep_data.get("directive_name")
                if d_name:
                    sweep_index[d_name] = {
                        "idea_id": idea_id,
                        "sweep": sweep_key,
                        "attempt": sweep_data.get("attempt", 1),
                    }
                for patch_data in sweep_data.get("patches", {}).values():
                    if isinstance(patch_data, dict):
                        p_name = patch_data.get("directive_name")
                        if p_name:
                            sweep_index[p_name] = {
                                "idea_id": idea_id,
                                "sweep": sweep_key,
                                "attempt": patch_data.get("attempt", 1),
                            }

    # Build run lookup: directive_name -> (most recent status, timestamp)
    try:
        run_reg = _load_registry()
    except Exception as e:
        print(f"[WARN] Could not load run registry: {e}")
        run_reg = {}

    run_index: dict = {}
    for run_data in run_reg.values():
        d_hash = run_data.get("directive_hash", "")
        if not d_hash:
            continue
        status = run_data.get("status", "unknown")
        ts = run_data.get("created_at", "")
        if d_hash not in run_index or ts > run_index[d_hash][1]:
            run_index[d_hash] = (status, ts)

    # Print report
    print("\n" + "=" * 72)
    print("DIRECTIVE STATUS REPORT")
    print("=" * 72)

    any_unregistered = False
    for f in files:
        name = f.stem
        sweep_info = sweep_index.get(name)
        run_info = run_index.get(name)

        if sweep_info:
            sweep_str = (
                f"REGISTERED  "
                f"idea={sweep_info['idea_id']}  "
                f"sweep={sweep_info['sweep']}  "
                f"attempt={sweep_info['attempt']}"
            )
        else:
            sweep_str = "NOT REGISTERED"
            any_unregistered = True

        if run_info:
            status, ts = run_info
            run_str = f"{status.upper()}  (ts={ts[:19]})" if ts else status.upper()
        else:
            run_str = "NO RUNS"

        print(f"\n  {name}")
        print(f"    sweep  : {sweep_str}")
        print(f"    run    : {run_str}")

    print("\n" + "=" * 72)
    if any_unregistered:
        print("[WARN] One or more INBOX directives are not sweep-registered.")
    return 1 if any_unregistered else 0


def main():
    parser = argparse.ArgumentParser(description="TradeScan Directive Linter")
    parser.add_argument("directive", nargs="?", help="Specific directive file to lint (optional)")
    parser.add_argument("--check", action="store_true", help="Report only, do not admit to ACTIVE")
    parser.add_argument("--admit", action="store_true", help="Admit to ACTIVE if validation passes")
    parser.add_argument("--status", action="store_true", help="Read-only: show sweep and run status for INBOX directives")

    args = parser.parse_args()

    if args.status:
        return run_status_mode(args.directive)

    if args.admit and args.check:
        print("Error: Cannot specify both --check and --admit.")
        return 1

    mode = "admit" if args.admit else "check"
    
    if args.directive:
        target_path = Path(args.directive)
        if not target_path.exists():
            print(f"File not found: {target_path}")
            return 1
        files_to_process = [target_path]
    else:
        if not INBOX_DIR.exists():
            print(f"INBOX directory not found: {INBOX_DIR}")
            return 1
        files_to_process = list(INBOX_DIR.glob("*.txt")) + list(INBOX_DIR.glob("*.yaml"))
        
        if not files_to_process:
            print(f"No directives found in {INBOX_DIR}")
            return 0
            
    success_count = 0
    fail_count = 0
    
    for f in files_to_process:
        if process_directive(f, mode):
            success_count += 1
        else:
            fail_count += 1
            
    print(f"\nCompleted: {success_count} passed, {fail_count} failed.")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
