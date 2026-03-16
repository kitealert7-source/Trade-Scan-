"""
Directive Linter — Operator Workflow Entrypoint for TradeScan
This tool wraps the AdmissionStage governance gates to safely admit directives
from the INBOX to the ACTIVE queue.

Modes:
--check : run validation and report issues (does not move file)
--admit : run validation and atomically move to ACTIVE if successful
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
                tmp_path = Path("/tmp") / f"{directive_id}_canonical.yaml"
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


def main():
    parser = argparse.ArgumentParser(description="TradeScan Directive Linter")
    parser.add_argument("directive", nargs="?", help="Specific directive file to lint (optional)")
    parser.add_argument("--check", action="store_true", help="Report only, do not admit to ACTIVE")
    parser.add_argument("--admit", action="store_true", help="Admit to ACTIVE if validation passes")
    
    args = parser.parse_args()
    
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
