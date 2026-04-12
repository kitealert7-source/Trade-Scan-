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

from config.state_paths import REGISTRY_DIR, POOL_DIR, MASTER_FILTER_PATH
from tools.system_registry import _load_registry

# Directive Folders
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_ROOT / "active"
ACTIVE_BACKUP_DIR = DIRECTIVES_ROOT / "active_backup"
COMPLETED_DIR = DIRECTIVES_ROOT / "completed"

def get_master_filter_directive_names():
    """Extract directive names/IDs from both 'run_id' and 'strategy' columns."""
    try:
        from tools.ledger_db import read_master_filter
        df = read_master_filter()
        if df.empty:
            return set(), set()
        run_ids = set(df["run_id"].unique()) if "run_id" in df.columns else set()
        strategy_names = set(df["strategy"].unique()) if "strategy" in df.columns else set()
        return run_ids, strategy_names
    except Exception as e:
        print(f"[WARN] Failed to read Master Filter: {e}")
    return set(), set()

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
        """Fuzzy check if a directive ID is alive in the system."""
        if d_id in raw_living_names:
            return True
        # Check if d_id is a prefix of any strategy name (e.g. S01 matches S01_XAUUSD)
        for name in raw_living_names:
            if name.startswith(d_id + "_"):
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
            print(f"  [PROMOTED] {d_path.name}")
            
        # Apply Redundancy Cleanup
        for d_path in redundancies:
            os.remove(d_path)
            print(f"  [DELETED] Redundant: {d_path.name}")
            
        # Apply Orphan Purge
        for d_path in orphans:
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
