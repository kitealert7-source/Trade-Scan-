import os
import shutil
import argparse
from pathlib import Path

# --- Configuration ---
# Directories inside TradeScan_State to be cleared (contents removed, folder kept)
CLEAR_TARGETS = [
    "runs",
    "logs",
    "ledgers",
    "cache",
    "registry",
]

def reset_runtime_state(state_root: Path, confirm: bool):
    """
    Safely resets the runtime state by clearing contents of specified directories.
    """
    print(f"--- Runtime State Reset Tool ---")
    print(f"State Root: {state_root}")
    print(f"Mode: {'CONFIRM (Delete)' if confirm else 'DRY-RUN'}")
    print("-" * 30)

    # 1. Root Verification
    if not state_root.exists() or not state_root.is_dir():
        print(f"ERROR: State root '{state_root}' not found. Aborting.")
        return

    # Check for validity markers
    valid_markers = ["runs", "logs", "ledgers"]
    found_marker = any((state_root / m).exists() for m in valid_markers)
    if not found_marker:
        print(f"ERROR: No valid state markers {valid_markers} found in '{state_root}'. Aborting.")
        return

    # 2. Cleanup Logic
    total_dirs_cleared = 0
    total_files_removed = 0

    for dname in CLEAR_TARGETS:
        target_dir = state_root / dname
        if not target_dir.exists():
            continue

        print(f"Processing: {dname}/")
        
        # Count contents
        contents = list(target_dir.iterdir())
        if not contents:
            print(f"  (Directory already empty)")
            continue

        if confirm:
            for item in contents:
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                        total_dirs_cleared += 1
                        print(f"  [DELETED] Dir: {item.name}")
                    else:
                        item.unlink()
                        total_files_removed += 1
                        print(f"  [DELETED] File: {item.name}")
                except Exception as e:
                    print(f"  [ERROR] Could not remove {item.name}: {e}")
        else:
            # Dry run stats
            dir_count = sum(1 for item in contents if item.is_dir())
            file_count = sum(1 for item in contents if not item.is_dir())
            print(f"  [DRY-RUN] Detected: {dir_count} directories, {file_count} files.")
            total_dirs_cleared += dir_count
            total_files_removed += file_count

    print("-" * 30)
    if not confirm:
        print(f"Summary (DRY-RUN): {total_dirs_cleared} directories and {total_files_removed} files would be removed.")
        print("Use --confirm to execute reset.")
    else:
        print(f"Summary: {total_dirs_cleared} directories and {total_files_removed} files removed.")
        print("Runtime state reset complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TradeScan Runtime State Reset Tool")
    parser.add_argument("--confirm", action="store_true", help="Execute the deletion (IRREVERSIBLE)")
    args = parser.parse_args()

    # Determine state root (one level up from parent of current repo root)
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    state_root = repo_root.parent / "TradeScan_State"

    reset_runtime_state(state_root, args.confirm)
