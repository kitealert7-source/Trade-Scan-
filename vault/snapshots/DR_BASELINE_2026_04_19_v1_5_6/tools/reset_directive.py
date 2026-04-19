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
import shutil
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Project root setup
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import DirectiveStateManager
from config.state_paths import RUNS_DIR

AUDIT_LOG = PROJECT_ROOT / "governance" / "reset_audit_log.csv"

# Directive lookup locations — used by the ghost-INITIALIZED cleanup path.
_DIRECTIVE_SEARCH_DIRS = [
    PROJECT_ROOT / "backtest_directives" / "INBOX",
    PROJECT_ROOT / "backtest_directives" / "active",
    PROJECT_ROOT / "backtest_directives" / "active_backup",
    PROJECT_ROOT / "backtest_directives" / "completed",
]


def _directive_file_exists(directive_id: str) -> bool:
    """True if a directive file for this id lives anywhere the pipeline looks for it."""
    for base in _DIRECTIVE_SEARCH_DIRS:
        if (base / f"{directive_id}.txt").exists():
            return True
    return False


def _quarantine_ghost_state(directive_id: str) -> bool:
    """
    Quarantine an orphan directive state dir (state=INITIALIZED, no .txt anywhere).

    Moves <RUNS_DIR>/<directive_id> to
    <RUNS_DIR>/../quarantine/runs/<directive_id>.GHOST_<timestamp>
    and clears registry + active_backup markers via reuse of the new_pass cleaner.

    Returns True if cleanup ran, False if nothing to clean.
    """
    directive_dir = RUNS_DIR / directive_id
    if not directive_dir.exists():
        return False

    quarantine_root = RUNS_DIR.parent / "quarantine" / "runs"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = quarantine_root / f"{directive_id}.GHOST_{ts}"
    counter = 0
    while target.exists():
        counter += 1
        target = quarantine_root / f"{directive_id}.GHOST_{ts}_{counter}"

    shutil.move(str(directive_dir), str(target))
    print(f"[RESET][GHOST] Quarantined orphan state dir -> {target}")
    return True


def _detect_strategy_logic_change(directive_id: str) -> tuple[bool, str]:
    """
    Returns (was_modified, reason).

    Hash-based: the approval marker stores sha256(strategy.py). A logic change
    is detected only when the current file's content hash differs from the
    stored hash. Byte-identical rewrites — provisioner re-emits, --rehash,
    encoding round-trips — never register as logic changes.

    Returns (False, "") when the check cannot be performed (no strategy.py)
    — treated as an infra failure, reset allowed.
    """
    strategy_py = PROJECT_ROOT / "strategies" / directive_id / "strategy.py"
    if not strategy_py.exists():
        return (False, "")

    from tools.approval_marker import (
        compute_strategy_hash,
        is_approval_current,
        read_approved_marker,
    )

    approved = strategy_py.with_name("strategy.py.approved")

    if is_approval_current(strategy_py, approved):
        return (False, "")

    marker = read_approved_marker(approved)
    if marker is not None and marker.has_hash:
        current = compute_strategy_hash(strategy_py)
        return (
            True,
            f"strategy.py content hash {current[:12]} differs from approved "
            f"hash {marker.strategy_sha256[:12]}.",
        )

    # Marker missing or has no hash (should not occur after bulk upgrade).
    return (True, "strategy.py.approved marker missing or unreadable.")


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


def _clear_directive_run_folder(directive_id: str):
    """Delete the directive-level run folder, including run_registry.json and any latent state."""
    directive_run_dir = RUNS_DIR / directive_id
    if directive_run_dir.exists():
        shutil.rmtree(directive_run_dir)
        print(f"[RESET] Cleared directive run state: {directive_id} (including run_registry.json)")
    else:
        print(f"[RESET] No run state found for {directive_id} (already clean)")


def _extract_timeframe_from_id(directive_id: str) -> str | None:
    """Pull the timeframe token (e.g. '30m', '1h', '1d') out of a directive id.

    Directive ids encode timeframe at position 3 after splitting on '_'
    (FAM_CAT_ASSET_TF_MODEL_...). Returns a lowercase token like '30m' or
    None if the slot does not contain a well-formed timeframe.
    """
    import re
    parts = directive_id.split("_")
    if len(parts) >= 4:
        candidate = parts[3].lower()
        if re.fullmatch(r"\d+[mhdw]", candidate):
            return candidate
    return None


def _supersede_prior_runs(directive_id: str, reason: str) -> int:
    """Retire prior live master_filter rows for this directive + regen Excel views.

    Scope-safe: matches strategy LIKE '<directive_id>%' AND timeframe when
    extractable. Never touches other strategies or other timeframes.
    Idempotent: already-superseded rows are untouched by the underlying
    mark_superseded_pre_run() (its WHERE clause requires is_current=1/NULL).
    """
    from tools.ledger_db import (
        export_master_filter,
        export_mps,
        find_runs_for_stem,
        mark_superseded_pre_run,
    )

    timeframe = _extract_timeframe_from_id(directive_id)
    run_ids = find_runs_for_stem(directive_id, timeframe=timeframe)
    if not run_ids:
        print(f"[SUPERSEDE] No live prior runs for {directive_id} (tf={timeframe!r}). Nothing to retire.")
        return 0

    flipped = mark_superseded_pre_run(run_ids, reason=f"reset_directive: {reason}")
    print(f"[SUPERSEDE] Retired {flipped} prior run row(s) for {directive_id} (tf={timeframe!r}).")

    # Regenerate Excel views from the filtered DB (is_current=1 only).
    try:
        export_master_filter()
        export_mps()
    except Exception as e:
        # Non-fatal: DB supersedence succeeded; Excel regen can be retried later.
        print(f"[SUPERSEDE][WARN] Excel regeneration failed ({e}). Re-run exporters manually.")

    return flipped


def reset_directive(
    directive_id: str,
    reason: str,
    to_stage4: bool = False,
    *,
    supersede: bool = False,
):
    """Reset a directive state with mandatory audit logging."""
    mgr = DirectiveStateManager(directive_id)
    previous_state = mgr.get_state()

    if previous_state is None:
        print(f"[ERROR] No state file found for directive: {directive_id}")
        sys.exit(1)

    if previous_state == "INITIALIZED":
        # Ghost-INITIALIZED: state exists but the directive .txt is gone from every
        # lookup location. These orphans block the pipeline with PIPELINE_BUSY and
        # must be removed before any new directive can admit. Idempotent: the
        # quarantine step is a no-op if the state dir is already clean.
        if not _directive_file_exists(directive_id):
            cleaned = _quarantine_ghost_state(directive_id)
            # Also clean run_state.json files + directive run folder so the
            # registry stops reporting the ghost as live.
            now = datetime.now(timezone.utc)
            ts_suffix = now.strftime("%Y%m%dT%H%M%S")
            _archive_run_states(directive_id, ts_suffix)
            _clear_directive_run_folder(directive_id)

            # Audit trail for the ghost cleanup
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            write_header = not AUDIT_LOG.exists()
            with open(AUDIT_LOG, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["timestamp", "directive_id", "previous_state", "new_state", "reason"])
                writer.writerow([
                    now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    directive_id,
                    "INITIALIZED_GHOST",
                    "QUARANTINED",
                    reason,
                ])

            if cleaned:
                print(f"[DONE] Ghost INITIALIZED state for {directive_id} quarantined.")
            else:
                print(f"[INFO] Directive {directive_id} is INITIALIZED and already clean. No-op.")
            return

        print(f"[INFO] Directive {directive_id} is already INITIALIZED. No reset needed.")
        return

    # --- EXPERIMENT DISCIPLINE GUARD ---
    # If strategy.py was modified after the run's preflight completed, this is a
    # logic change — not an infra failure.  Reset is forbidden; a new directive
    # version must be created instead.
    modified, mod_reason = _detect_strategy_logic_change(directive_id)
    if modified:
        next_ver = directive_id.replace("_V1_", "_V2_") if "_V1_" in directive_id else directive_id + "_V2"
        print()
        print("=" * 66)
        print("[EXPERIMENT DISCIPLINE] RESET BLOCKED — LOGIC CHANGE DETECTED")
        print("=" * 66)
        print(f"  Directive : {directive_id}")
        print(f"  Reason    : {mod_reason}")
        print()
        print("  Each directive is an immutable experiment.")
        print("  Re-running the same directive after a logic change corrupts results.")
        print()
        print("  REQUIRED ACTION:")
        print(f"    1. Create a new directive: {next_ver}")
        print( "    2. Run the pipeline with the NEW directive only.")
        print( "    3. Abandon or archive the failed directive.")
        print()
        print("  Reset is only allowed for infra failures (crash / missing file)")
        print("  where strategy.py is completely unchanged.")
        print("=" * 66)
        sys.exit(1)

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
        _clear_directive_run_folder(directive_id)
    else:
        print(f"[RESET] Stage-4 resume: preserving run states")

    # Supersede prior ledger rows (opt-in). Retires live master_filter rows
    # for this directive_id + timeframe scope, then regenerates Excel views
    # from the filtered DB so downstream Stage-3 cardinality gates see a
    # clean baseline. Append-only invariant preserved — rows are flagged, not
    # deleted. See governance/reset_audit_log.csv for the full audit trail.
    superseded_count = 0
    if supersede:
        superseded_count = _supersede_prior_runs(directive_id, reason)

    # Audit logging
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    write_header = not AUDIT_LOG.exists()
    with open(AUDIT_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "directive_id", "previous_state", "new_state", "reason"])
        audit_reason = reason
        if supersede:
            audit_reason = f"{reason} [supersede: retired {superseded_count} prior rows]"
        writer.writerow([timestamp, directive_id, previous_state, target_state, audit_reason])

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
    parser.add_argument(
        "--supersede",
        action="store_true",
        help="Retire prior live master_filter rows for this directive "
             "(is_current -> 0) and regenerate Excel views from the filtered "
             "DB. Eliminates manual Stage-3 cardinality cleanup before rerun. "
             "Scope: strategy LIKE '<directive_id>%%' AND timeframe from id. "
             "Idempotent + append-only (no row deletion)."
    )
    args = parser.parse_args()

    reset_directive(
        args.directive_id,
        args.reason,
        to_stage4=args.to_stage4,
        supersede=args.supersede,
    )


if __name__ == "__main__":
    main()
