import sys
import os
import json
import shutil
import argparse
import pandas as pd
from pathlib import Path

# Project Root Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import REGISTRY_DIR, POOL_DIR, MASTER_FILTER_PATH, RUNS_DIR
from tools.system_registry import _load_registry
from tools.event_log import log_event

# Directive Folders
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_ROOT / "active"
ACTIVE_BACKUP_DIR = DIRECTIVES_ROOT / "active_backup"
COMPLETED_DIR = DIRECTIVES_ROOT / "completed"

# Purge audit — purge actions append JSON lines here so deletions are
# recoverable from logs even though the .txt is gone from disk.
PURGE_AUDIT_LOG = PROJECT_ROOT / "governance" / "directive_reconciler_audit.log"


def _directive_state_is_alive(directive_id: str) -> bool:
    """True if the directive has an intact state file showing progress past IDLE.

    Belt-and-suspenders guard against silent purge of PORTFOLIO_COMPLETE
    directives whose registry linkage is broken (e.g. directive_hash ==
    "recovered"). If directive_state.json exists and reports any status other
    than IDLE, the directive is treated as alive regardless of registry /
    master_filter presence. The .txt in completed/ is provenance for that
    state and must not be deleted.

    Failure policy: if the state file exists but is corrupt or unreadable,
    treat the directive as ALIVE (returns True). Destructive decisions must
    NEVER fire on evidence of corruption — better to leave a .txt in place
    for a dead directive than to purge a live one whose state file happens
    to be malformed. The violation is logged for follow-up.
    """
    state_file = RUNS_DIR / directive_id / "directive_state.json"
    if not state_file.exists():
        return False
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:
        try:
            log_event(
                action="INVARIANT_VIOLATION",
                target=f"directive:{directive_id}",
                actor="_directive_state_is_alive",
                reason="directive_state.json exists but is unreadable",
                error=str(exc),
                decision="shielding from purge (defensive)",
            )
        except Exception:
            pass
        # Defensive — corruption should not enable destruction.
        return True
    latest = data.get("latest_attempt")
    attempts = data.get("attempts", {})
    if latest and latest in attempts:
        status = attempts[latest].get("status")
    else:
        status = data.get("current_state")
    if not isinstance(status, str):
        # Malformed status — shield defensively for the same reason as above.
        try:
            log_event(
                action="INVARIANT_VIOLATION",
                target=f"directive:{directive_id}",
                actor="_directive_state_is_alive",
                reason="directive_state.json has non-string status",
                status_value=repr(status),
                decision="shielding from purge (defensive)",
            )
        except Exception:
            pass
        return True
    return status.strip().upper() not in {"", "IDLE"}

def get_master_filter_directive_names():
    """Extract directive names/IDs from both 'run_id' and 'strategy' columns.

    Fail-hard on read errors: silently returning empty sets when the master
    filter is unreadable combines with a silent empty registry to make every
    directive look orphan, triggering catastrophic purges (see FAKEBREAK
    P01/P02 incident). If the authority cannot be read, refuse to reconcile.
    """
    from tools.ledger_db import read_master_filter
    try:
        df = read_master_filter()
    except Exception as e:
        try:
            log_event(
                action="INVARIANT_VIOLATION",
                target="master_filter",
                actor="directive_reconciler.get_master_filter_directive_names",
                reason="master_filter read failed",
                error=str(e),
            )
        except Exception:
            pass
        raise RuntimeError(
            f"Failed to read Master Filter: {e}\n"
            f"Refusing to proceed with reconciliation against a missing "
            f"Master Filter — doing so would treat every directive as orphan "
            f"and may trigger catastrophic purges. Diagnose the read failure "
            f"and re-run."
        )
    if df.empty:
        return set(), set()
    run_ids = set(df["run_id"].unique()) if "run_id" in df.columns else set()
    strategy_names = set(df["strategy"].unique()) if "strategy" in df.columns else set()
    return run_ids, strategy_names

def main():
    parser = argparse.ArgumentParser(description="Authoritative Directive Lifecycle Reconciler")
    parser.add_argument("--execute", action="store_true", help="Execute planned movements/deletions")
    args = parser.parse_args()

    print("=== STARTING DIRECTIVE RECONCILIATION ===")
    
    reg_data = _load_registry()
    master_run_ids, master_strategy_names = get_master_filter_directive_names()
    
    # Authoritative set of directives that are "alive" in the system
    # (Extract exact names from Master Filter)
    raw_living_names = set(master_strategy_names)
    
    # Add all directives currently in the registry (even if not in Master Filter)
    for record in reg_data.values():
        d_id = record.get("directive_hash")
        if d_id:
            raw_living_names.add(d_id)

    def is_directive_living(d_id):
        """Fuzzy check if a directive ID is alive in the system.

        Three independent signals, any one is sufficient:
          1. Directive appears in master_filter or run_registry directive_hash
             (raw_living_names — built from authoritative ledgers above).
          2. Directive ID is a prefix of a known strategy name.
          3. Directive has an intact directive_state.json past IDLE — this
             guards PORTFOLIO_COMPLETE directives whose registry linkage was
             corrupted (e.g. directive_hash == "recovered") so they survive
             `--execute` even when (1) and (2) both fail.
        """
        if d_id in raw_living_names:
            return True
        # Check if d_id is a prefix of any strategy name (e.g. S01 matches S01_XAUUSD)
        for name in raw_living_names:
            if name.startswith(d_id + "_"):
                return True
        # State-file fallback — preserves directives with intact FSM evidence.
        if _directive_state_is_alive(d_id):
            return True
        return False

    promotions = [] # active_backup -> completed
    redundancies = [] # active -> [deleted]
    orphans = [] # Any -> [deleted]

    # 1. Scan active_backup for promotion and orphans
    if ACTIVE_BACKUP_DIR.exists():
        for d_path in ACTIVE_BACKUP_DIR.glob("*.txt"):
            d_id = d_path.stem
            
            # Eligible for promotion if it has at least one complete run 
            # AND that directive name is known to be in the Master Filter (fuzzy).
            best_status = "unknown"
            in_living = is_directive_living(d_id)
            
            for run_id, record in reg_data.items():
                if record.get("directive_hash") == d_id:
                    if record.get("status") == "complete":
                        best_status = "complete"
                        break
                    elif record.get("status") == "failed":
                        best_status = "failed"
                    elif record.get("status") == "invalid":
                        best_status = "invalid"

            if best_status == "complete" and in_living:
                promotions.append(d_path)
            elif best_status in ["invalid", "failed", "unknown"]:
                # If it's failed/invalid/unknown:
                # 1. If it's NOT in living (fuzzy), it's a legacy orphan.
                # 2. If it IS in living (fuzzy), it means it crossed the finish line later/elsewhere,
                #    so the failed version in active_backup is now redundant noise.
                orphans.append(d_path)

    # 2. Scan active for redundancy
    if ACTIVE_DIR.exists():
        for d_path in ACTIVE_DIR.glob("*.txt"):
            if (ACTIVE_BACKUP_DIR / d_path.name).exists() or (COMPLETED_DIR / d_path.name).exists():
                redundancies.append(d_path)

    # 3. Scan completed for orphans
    if COMPLETED_DIR.exists():
        for d_path in COMPLETED_DIR.glob("*.txt"):
            if not is_directive_living(d_path.stem):
                # If it's in completed we don't care about registry as much, 
                # but if it's not even a "living" strategy name, it's garbage.
                orphans.append(d_path)

    # Reporting
    if not any([promotions, redundancies, orphans]):
        print("[PASS] All directive folders are perfectly reconciled.")
    else:
        if promotions:
            print(f"\n[PLAN] {len(promotions)} directives to Promote (active_backup -> completed):")
            for p in promotions: print(f"  - {p.name}")
        
        if redundancies:
            print(f"\n[PLAN] {len(redundancies)} directives to Clean (Redundant in active/):")
            for r in redundancies: print(f"  - {r.name}")
            
        if orphans:
            print(f"\n[PLAN] {len(orphans)} directives to Purge (Orphaned in folders):")
            for o in orphans: print(f"  - {o.name}")

    if args.execute:
        print("\n[EXECUTE] Applying reconciliation...")
        
        # Apply Promotions
        COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
        for d_path in promotions:
            target = COMPLETED_DIR / d_path.name
            os.replace(str(d_path), str(target))
            # Marker handling
            marker = d_path.with_suffix(d_path.suffix + ".admitted")
            if marker.exists():
                os.replace(str(marker), str(target.with_suffix(target.suffix + ".admitted")))
            log_event(
                action="DIRECTIVE_PROMOTE",
                target=f"directive:{d_path.stem}",
                actor="directive_reconciler",
                before={"folder": "active_backup"},
                after={"folder": "completed"},
            )
            print(f"  [PROMOTED] {d_path.name}")

        # Apply Redundancy Cleanup
        for d_path in redundancies:
            os.remove(d_path)
            log_event(
                action="DIRECTIVE_DELETE_REDUNDANT",
                target=f"directive:{d_path.stem}",
                actor="directive_reconciler",
                reason="copy exists in active_backup/ or completed/",
                before={"folder": d_path.parent.name},
            )
            print(f"  [DELETED] Redundant: {d_path.name}")

        # Apply Orphan Purge — append an audit record BEFORE deletion so a
        # mid-purge crash still leaves evidence of what was targeted.
        # Records go to BOTH the legacy PURGE_AUDIT_LOG (for back-compat) and
        # the generalized governance/events.jsonl (forensic consolidation).
        from datetime import datetime, timezone
        PURGE_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        for d_path in orphans:
            # Record the directive's current state before we remove its .txt.
            # This makes post-hoc recovery tractable even when the state dir
            # later gets cleaned.
            state_snapshot = None
            try:
                sf = RUNS_DIR / d_path.stem / "directive_state.json"
                if sf.exists():
                    sd = json.loads(sf.read_text(encoding="utf-8"))
                    latest = sd.get("latest_attempt")
                    if latest and latest in sd.get("attempts", {}):
                        state_snapshot = sd["attempts"][latest].get("status")
            except Exception:
                pass
            audit_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "PURGE_ORPHAN",
                "directive_id": d_path.stem,
                "source_folder": d_path.parent.name,
                "directive_state_at_purge": state_snapshot,
            }
            with open(PURGE_AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(audit_record) + "\n")
            log_event(
                action="DIRECTIVE_PURGE",
                target=f"directive:{d_path.stem}",
                actor="directive_reconciler",
                reason="orphaned — not in master_filter, registry, or state",
                before={
                    "folder": d_path.parent.name,
                    "directive_state": state_snapshot,
                },
            )

            os.remove(d_path)
            # Marker cleanup for orphans
            marker = d_path.with_suffix(d_path.suffix + ".admitted")
            if marker.exists():
                os.remove(marker)
            print(f"  [PURGED] Orphan: {d_path.name}")
            
        print("\n[SUCCESS] Directive folders reconciled.")
    else:
        if any([promotions, redundancies, orphans]):
            print("\n[INFO] Dry-run complete. Use --execute to apply changes.")

if __name__ == "__main__":
    main()
