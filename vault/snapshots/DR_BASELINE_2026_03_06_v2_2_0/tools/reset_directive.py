"""
Governance-Authorized Directive Reset Tool

Usage:
  python tools/reset_directive.py <DIRECTIVE_ID> --reason "<justification>"
  python tools/reset_directive.py <DIRECTIVE_ID> --reason "<justification>" --to-stage4

Authority: AGENT.md — Protected Infrastructure Policy
Purpose: Reset a FAILED or PORTFOLIO_COMPLETE directive state with mandatory audit logging.

Flags:
  --to-stage4   Reset to SYMBOL_RUNS_COMPLETE instead of INITIALIZED.
                Preserves completed run states. Pipeline resumes at Stage-4.
                Only valid from FAILED or PORTFOLIO_COMPLETE.

This tool MUST NOT be called by the agent autonomously.
It is a human-initiated governance intervention tool only.
"""

import sys
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Project root setup
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import DirectiveStateManager

AUDIT_LOG = PROJECT_ROOT / "governance" / "reset_audit_log.csv"
RUNS_DIR = PROJECT_ROOT / "runs"


def _archive_run_states(directive_id: str, timestamp_suffix: str):
    """Scan runs/ and archive run_state.json files belonging to this directive."""
    if not RUNS_DIR.exists():
        return

    cleaned = 0
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        state_file = run_dir / "run_state.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("directive_id") == directive_id:
                bak_name = f"run_state.json.bak.{timestamp_suffix}"
                bak_path = run_dir / bak_name
                # Never overwrite existing backups
                counter = 0
                while bak_path.exists():
                    counter += 1
                    bak_path = run_dir / f"run_state.json.bak.{timestamp_suffix}_{counter}"
                state_file.rename(bak_path)
                print(f"[RESET] Archived run state: {run_dir.name} -> {bak_path.name}")
                cleaned += 1
        except json.JSONDecodeError as e:
            # Corrupted state file — log explicitly, still archive
            print(f"[WARN] Corrupted run_state.json in {run_dir.name}: {e}")
            bak_name = f"run_state.json.CORRUPTED.bak.{timestamp_suffix}"
            bak_path = run_dir / bak_name
            try:
                state_file.rename(bak_path)
                print(f"[RESET] Archived corrupted state: {run_dir.name} -> {bak_path.name}")
                cleaned += 1
            except Exception as rename_err:
                print(f"[ERROR] Failed to archive corrupted state in {run_dir.name}: {rename_err}")
        except Exception as e:
            print(f"[WARN] Could not process run state in {run_dir.name}: {e}")

    if cleaned:
        print(f"[RESET] Cleaned {cleaned} associated run state(s)")
    else:
        print(f"[RESET] No associated run states found")


def reset_directive(directive_id: str, reason: str, to_stage4: bool = False):
    """Reset a directive state with mandatory audit logging."""
    mgr = DirectiveStateManager(directive_id)
    previous_state = mgr.get_state()

    if previous_state is None:
        print(f"[ERROR] No state file found for directive: {directive_id}")
        sys.exit(1)

    if previous_state == "INITIALIZED":
        print(f"[INFO] Directive {directive_id} is already INITIALIZED. No reset needed.")
        return

    # Determine target state
    if to_stage4:
        target_state = "SYMBOL_RUNS_COMPLETE"
        # --to-stage4 only valid from FAILED or PORTFOLIO_COMPLETE
        if previous_state not in ("FAILED", "PORTFOLIO_COMPLETE"):
            print(f"[ERROR] --to-stage4 only valid from FAILED or PORTFOLIO_COMPLETE.")
            print(f"[ERROR] Current state: '{previous_state}'. Cannot resume Stage-4.")
            sys.exit(1)
    else:
        target_state = "INITIALIZED"

    # Transition path: PORTFOLIO_COMPLETE -> FAILED first (if needed)
    if previous_state == "PORTFOLIO_COMPLETE":
        print(f"[RESET] Transitioning {directive_id}: {previous_state} -> FAILED")
        try:
            mgr.transition_to("FAILED")
        except Exception as e:
            print(f"[ERROR] Could not transition to FAILED: {e}")
            sys.exit(1)

    current = mgr.get_state()
    if current != "FAILED":
        print(f"[ERROR] Directive is in state '{current}'. Only FAILED or PORTFOLIO_COMPLETE can be reset.")
        sys.exit(1)

    # Perform reset
    print(f"[RESET] Transitioning {directive_id}: FAILED -> {target_state}")
    mgr.transition_to(target_state)

    # Deterministic UTC timestamp for archive suffixes
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    timestamp_suffix = now.strftime("%Y%m%dT%H%M%S")

    # Clean associated run states (only for full reset, not stage-4 resume)
    if not to_stage4:
        _archive_run_states(directive_id, timestamp_suffix)
    else:
        print(f"[RESET] Stage-4 resume: preserving run states")

    # Audit logging
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    write_header = not AUDIT_LOG.exists()
    with open(AUDIT_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "directive_id", "previous_state", "new_state", "reason"])
        writer.writerow([timestamp, directive_id, previous_state, target_state, reason])

    print(f"[AUDIT] Reset logged to {AUDIT_LOG}")
    print(f"[DONE] Directive {directive_id} reset to {target_state}.")
    print(f"[REASON] {reason}")


def main():
    parser = argparse.ArgumentParser(
        description="Governance-Authorized Directive Reset Tool"
    )
    parser.add_argument("directive_id", help="Directive ID to reset (e.g., SPX04)")
    parser.add_argument(
        "--reason",
        required=True,
        help="Mandatory justification for the reset (logged to audit trail)"
    )
    parser.add_argument(
        "--to-stage4",
        action="store_true",
        help="Reset to SYMBOL_RUNS_COMPLETE (skip Stages 0-3 on re-run). "
             "Only valid from FAILED or PORTFOLIO_COMPLETE."
    )
    args = parser.parse_args()

    reset_directive(args.directive_id, args.reason, to_stage4=args.to_stage4)


if __name__ == "__main__":
    main()
