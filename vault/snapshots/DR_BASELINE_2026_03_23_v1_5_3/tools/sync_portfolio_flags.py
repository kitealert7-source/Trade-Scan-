"""
sync_portfolio_flags.py — Operator tool for managing IN_PORTFOLIO persistent selections.

The IN_PORTFOLIO=True flag is sticky by design: once set in the Master Filter, it is
persisted to `TradeScan_State/sandbox/in_portfolio_selections.json` and restored on
every stage3_compiler run, even after a full Master Filter rebuild.

This tool is the ONLY mechanism to:
  1. Explicitly persist current True flags from Excel  (--save)
  2. Remove a True flag so it will not be restored     (--clear <run_id>)
  3. List all currently persisted True run_ids         (--list)
  4. Apply persisted flags back to the Master Filter   (--apply)

IMPORTANT: No pipeline code path may flip IN_PORTFOLIO True → False. Only --clear does.

Usage:
  python tools/sync_portfolio_flags.py --save
  python tools/sync_portfolio_flags.py --clear <run_id>
  python tools/sync_portfolio_flags.py --list
  python tools/sync_portfolio_flags.py --apply
"""

import json
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
    """Atomically write selections store."""
    SELECTIONS_PATH.write_text(
        json.dumps({"selections": sorted(true_ids)}, indent=2),
        encoding="utf-8",
    )


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
    merged = existing | current_true

    _save_store(merged)
    added = merged - existing
    print(f"[SAVE] {len(current_true)} True flag(s) in Filtered_Strategies_Passed.")
    if added:
        print(f"[SAVE] {len(added)} new run_id(s) added to store:")
        for rid in sorted(added):
            # Show strategy name if available
            name = df_cand.loc[df_cand["run_id"].astype(str) == rid, "strategy"]
            label = name.values[0] if len(name) else rid
            print(f"  + {label}")
    print(f"[SAVE] Store now contains {len(merged)} persisted selection(s).")

    # Mirror True values back into Master Filter so both sheets stay in sync
    if MASTER_FILTER_PATH.exists() and merged:
        lock = FileLock(str(MASTER_FILTER_PATH.with_suffix(".lock")), timeout=30)
        try:
            with lock:
                ensure_xlsx_writable(MASTER_FILTER_PATH)
                df_mf = pd.read_excel(MASTER_FILTER_PATH)
                mask = df_mf["run_id"].astype(str).isin(merged)
                before = int((df_mf["IN_PORTFOLIO"] == True).sum())
                df_mf.loc[mask, "IN_PORTFOLIO"] = True
                after = int((df_mf["IN_PORTFOLIO"] == True).sum())
                df_mf.to_excel(MASTER_FILTER_PATH, index=False)
                print(f"[SAVE] Mirrored {after} True flag(s) to Strategy_Master_Filter ({after - before} new).")
        except Exception as e:
            print(f"[WARN] Could not mirror flags to Master Filter ({e}).")


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Operator tool for managing IN_PORTFOLIO persistent selections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save",  action="store_true",  help="Persist current True flags from Master Filter to store")
    group.add_argument("--clear", metavar="RUN_ID",     help="Remove a run_id from store and clear its flag in Master Filter")
    group.add_argument("--list",  action="store_true",  help="List all persisted True run_ids")
    group.add_argument("--apply", action="store_true",  help="Apply persisted flags back to Master Filter")

    args = parser.parse_args()

    if args.save:
        cmd_save()
    elif args.clear:
        cmd_clear(args.clear)
    elif args.list:
        cmd_list()
    elif args.apply:
        cmd_apply()


if __name__ == "__main__":
    main()
