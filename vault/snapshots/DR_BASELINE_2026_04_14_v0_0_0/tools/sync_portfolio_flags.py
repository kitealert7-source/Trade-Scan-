"""
sync_portfolio_flags.py — REPAIR tool for IN_PORTFOLIO flag consistency.

ARCHITECTURE: promote_to_burnin.py is the single writer for IN_PORTFOLIO.
  promote_to_burnin.py → ledger.db (via set_in_portfolio) → Excel export

This tool exists ONLY for:
  1. Repair: reconcile Excel/JSON store with ledger.db after manual fixes
  2. Clear: remove a run_id from all stores                   (--clear)
  3. List: inspect current persisted selections                (--list)
  4. Apply: restore flags from store to Master Filter          (--apply)

The JSON store uses REPLACE semantics (not union). store = current_true.
No ghosts, no history, no accumulation.

Usage:
  python tools/sync_portfolio_flags.py --save          # repair: sync from FSP Excel
  python tools/sync_portfolio_flags.py --clear <run_id>
  python tools/sync_portfolio_flags.py --list
  python tools/sync_portfolio_flags.py --apply
"""

import json
import os
import sys
import argparse
import pandas as pd
from pathlib import Path
from filelock import FileLock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import POOL_DIR, SELECTED_DIR
from tools.pipeline_utils import ensure_xlsx_writable

MASTER_FILTER_PATH = POOL_DIR / "Strategy_Master_Filter.xlsx"
CANDIDATES_PATH    = SELECTED_DIR / "Filtered_Strategies_Passed.xlsx"
SELECTIONS_PATH    = POOL_DIR / "in_portfolio_selections.json"


def _sync_ledger_db(true_ids: set) -> None:
    """Propagate IN_PORTFOLIO flags to ledger.db via the single-writer function.
    This is a REPAIR tool — allows empty set (unlike pipeline path).
    """
    try:
        from config.state_paths import LEDGER_DB_PATH
        from tools.ledger_db import _connect, create_tables
    except ImportError:
        return
    if not LEDGER_DB_PATH.exists():
        return
    try:
        conn = _connect()
        create_tables(conn)
        # Direct SQL — bypasses set_in_portfolio() empty guard intentionally.
        # This is the repair path; pipeline uses set_in_portfolio() which rejects empty.
        conn.execute('UPDATE master_filter SET "IN_PORTFOLIO" = 0 WHERE "IN_PORTFOLIO" = 1')
        synced = 0
        if true_ids:
            placeholders = ", ".join("?" for _ in true_ids)
            conn.execute(
                f'UPDATE master_filter SET "IN_PORTFOLIO" = 1 WHERE "run_id" IN ({placeholders})',
                list(true_ids),
            )
            synced = conn.execute(
                'SELECT COUNT(*) FROM master_filter WHERE "IN_PORTFOLIO" = 1'
            ).fetchone()[0]
        conn.commit()
        conn.close()
        print(f"[SAVE] Synced {synced} IN_PORTFOLIO flag(s) to ledger.db.")
    except Exception as e:
        print(f"[WARN] Could not sync ledger.db ({e}).")


def _load_store() -> set:
    """Load persisted True run_ids from selections store. Returns empty set if missing."""
    if not SELECTIONS_PATH.exists():
        return set()
    try:
        data = json.loads(SELECTIONS_PATH.read_text(encoding="utf-8"))
        return set(str(x) for x in data.get("selections", []))
    except Exception as e:
        print(f"[WARN] Could not read selections store ({e}). Treating as empty.")
        return set()


def _save_store(true_ids: set) -> None:
    """Atomically write selections store (tmp → fsync → replace)."""
    tmp_path = SELECTIONS_PATH.with_suffix(".json.tmp")
    payload = json.dumps({"selections": sorted(true_ids)}, indent=2)
    with open(str(tmp_path), "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp_path), str(SELECTIONS_PATH))


def cmd_save() -> None:
    """Read IN_PORTFOLIO=True rows from Filtered_Strategies_Passed, persist their run_ids,
    and mirror the True values back to Strategy_Master_Filter by run_id.
    Operator marks True in the candidates sheet (68 rows) — the source of truth for selection.
    """
    if not CANDIDATES_PATH.exists():
        print(f"[ABORT] Candidates sheet not found: {CANDIDATES_PATH}")
        sys.exit(1)

    df_cand = pd.read_excel(CANDIDATES_PATH)
    if "IN_PORTFOLIO" not in df_cand.columns or "run_id" not in df_cand.columns:
        print("[ABORT] Candidates sheet missing IN_PORTFOLIO or run_id column.")
        sys.exit(1)

    current_true = set(df_cand.loc[df_cand["IN_PORTFOLIO"] == True, "run_id"].astype(str).tolist())
    existing = _load_store()

    # REPLACE, not union. Current truth = what's True NOW. No ghosts.
    _save_store(current_true)
    added = current_true - existing
    removed = existing - current_true
    print(f"[SAVE] {len(current_true)} True flag(s) in Filtered_Strategies_Passed.")
    if added:
        print(f"[SAVE] {len(added)} new run_id(s):")
        for rid in sorted(added):
            name = df_cand.loc[df_cand["run_id"].astype(str) == rid, "strategy"]
            label = name.values[0] if len(name) else rid
            print(f"  + {label}")
    if removed:
        print(f"[SAVE] {len(removed)} run_id(s) removed (no longer True):")
        for rid in sorted(removed):
            print(f"  - {rid}")
    print(f"[SAVE] Store now contains {len(current_true)} selection(s).")

    # Mirror to Master Filter: set matching rows True, clear removed rows False
    if MASTER_FILTER_PATH.exists():
        lock = FileLock(str(MASTER_FILTER_PATH.with_suffix(".lock")), timeout=30)
        try:
            with lock:
                ensure_xlsx_writable(MASTER_FILTER_PATH)
                df_mf = pd.read_excel(MASTER_FILTER_PATH)
                # Reset all to False, then set current_true
                df_mf["IN_PORTFOLIO"] = False
                if current_true:
                    mask = df_mf["run_id"].astype(str).isin(current_true)
                    df_mf.loc[mask, "IN_PORTFOLIO"] = True
                after = int((df_mf["IN_PORTFOLIO"] == True).sum())
                df_mf.to_excel(MASTER_FILTER_PATH, index=False)
                print(f"[SAVE] Master Filter: {after} IN_PORTFOLIO=True flag(s).")
        except Exception as e:
            print(f"[WARN] Could not mirror flags to Master Filter ({e}).")

    _sync_ledger_db(current_true)


def cmd_clear(run_id: str) -> None:
    """Remove a run_id from the persistent store AND clear IN_PORTFOLIO in the Master Filter.

    This is the ONLY operator-sanctioned way to flip IN_PORTFOLIO True → False.
    """
    existing = _load_store()
    if run_id not in existing:
        print(f"[CLEAR] run_id '{run_id}' not found in selections store. No action taken.")
        return

    updated = existing - {run_id}
    _save_store(updated)
    print(f"[CLEAR] Removed '{run_id}' from selections store ({len(updated)} remaining).")

    # Also clear in the Master Filter file if it exists
    if MASTER_FILTER_PATH.exists():
        lock = FileLock(str(MASTER_FILTER_PATH.with_suffix(".lock")), timeout=30)
        try:
            with lock:
                ensure_xlsx_writable(MASTER_FILTER_PATH)
                df = pd.read_excel(MASTER_FILTER_PATH)
                mask = df["run_id"].astype(str) == run_id
                if mask.any():
                    df.loc[mask, "IN_PORTFOLIO"] = False
                    df.to_excel(MASTER_FILTER_PATH, index=False)
                    print(f"[CLEAR] IN_PORTFOLIO set to False in Master Filter for '{run_id}'.")
                else:
                    print(f"[CLEAR] run_id '{run_id}' not found in Master Filter (store cleared only).")
        except Exception as e:
            print(f"[WARN] Could not update Master Filter ({e}). Store was cleared but Excel not updated.")
    else:
        print("[CLEAR] Master Filter not found — store cleared only.")

    _sync_ledger_db(updated)


def cmd_clear_batch(run_ids: list[str]) -> None:
    """Remove multiple run_ids from the persistent store AND clear IN_PORTFOLIO in the Master Filter.

    Atomic: updates the store once, updates the Master Filter once.
    """
    existing = _load_store()
    to_remove = set(run_ids) & existing
    not_found = set(run_ids) - existing
    if not_found:
        print(f"[CLEAR-BATCH] Not in store (skipped): {sorted(not_found)}")
    if not to_remove:
        print(f"[CLEAR-BATCH] No matching run_ids in store. No action taken.")
        return

    updated = existing - to_remove
    _save_store(updated)
    print(f"[CLEAR-BATCH] Removed {len(to_remove)} run_id(s) from store ({len(updated)} remaining).")
    for rid in sorted(to_remove):
        print(f"  - {rid}")

    if MASTER_FILTER_PATH.exists():
        lock = FileLock(str(MASTER_FILTER_PATH.with_suffix(".lock")), timeout=30)
        try:
            with lock:
                ensure_xlsx_writable(MASTER_FILTER_PATH)
                df = pd.read_excel(MASTER_FILTER_PATH)
                mask = df["run_id"].astype(str).isin(to_remove)
                cleared = int(mask.sum())
                if cleared:
                    df.loc[mask, "IN_PORTFOLIO"] = False
                    df.to_excel(MASTER_FILTER_PATH, index=False)
                    print(f"[CLEAR-BATCH] IN_PORTFOLIO set to False for {cleared} row(s) in Master Filter.")
                else:
                    print(f"[CLEAR-BATCH] No matching run_ids in Master Filter (store cleared only).")
        except Exception as e:
            print(f"[WARN] Could not update Master Filter ({e}). Store was cleared but Excel not updated.")
    else:
        print("[CLEAR-BATCH] Master Filter not found — store cleared only.")

    _sync_ledger_db(updated)


def cmd_list() -> None:
    """List all run_ids currently persisted as IN_PORTFOLIO=True."""
    ids = _load_store()
    if not ids:
        print("[LIST] Selections store is empty (no persisted True flags).")
        return
    print(f"[LIST] {len(ids)} persisted IN_PORTFOLIO=True selection(s):")
    for rid in sorted(ids):
        print(f"  {rid}")


def cmd_apply() -> None:
    """Apply persisted True flags back to the Master Filter. Useful for manual recovery."""
    ids = _load_store()
    if not ids:
        print("[APPLY] Selections store is empty — nothing to apply.")
        return
    if not MASTER_FILTER_PATH.exists():
        print(f"[ABORT] Master Filter not found: {MASTER_FILTER_PATH}")
        sys.exit(1)

    lock = FileLock(str(MASTER_FILTER_PATH.with_suffix(".lock")), timeout=30)
    try:
        with lock:
            ensure_xlsx_writable(MASTER_FILTER_PATH)
            df = pd.read_excel(MASTER_FILTER_PATH)
            mask = df["run_id"].astype(str).isin(ids)
            before = int((df["IN_PORTFOLIO"] == True).sum())
            df.loc[mask, "IN_PORTFOLIO"] = True
            after = int((df["IN_PORTFOLIO"] == True).sum())
            df.to_excel(MASTER_FILTER_PATH, index=False)
            print(f"[APPLY] Restored {after - before} flag(s). Total True: {after} / {len(df)}.")
    except Exception as e:
        print(f"[FATAL] Could not apply flags to Master Filter: {e}")
        sys.exit(1)

    _sync_ledger_db(ids)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Operator tool for managing IN_PORTFOLIO persistent selections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save",  action="store_true",  help="Persist current True flags from Master Filter to store")
    group.add_argument("--clear", metavar="RUN_ID",     help="Remove a run_id from store and clear its flag in Master Filter")
    group.add_argument("--clear-batch", nargs="+", metavar="RUN_ID",
                       help="Remove multiple run_ids from store and clear their flags (atomic)")
    group.add_argument("--list",  action="store_true",  help="List all persisted True run_ids")
    group.add_argument("--apply", action="store_true",  help="Apply persisted flags back to Master Filter")

    args = parser.parse_args()

    if args.save:
        cmd_save()
    elif args.clear:
        cmd_clear(args.clear)
    elif args.clear_batch:
        cmd_clear_batch(args.clear_batch)
    elif args.list:
        cmd_list()
    elif args.apply:
        cmd_apply()


if __name__ == "__main__":
    main()
