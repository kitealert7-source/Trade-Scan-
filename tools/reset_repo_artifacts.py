import os
import shutil
import argparse
from pathlib import Path

# --- Configuration ---
# Directories to be deleted entirely if they exist
FULL_DELETE_DIRS = [
    "runs",
    "backtests",
    "results",
    "output",
    "sandbox",
    "reports",
    "strategies_experimental",
    "experiments",
]

# Directories to be emptied but kept
CLEAR_CONTENT_DIRS = [
    "directives",
    "backtest_directives",
]

# Critical infrastructure paths - Explicit protection
PROTECTED_PATHS = [
    "tools",
    "governance",
    "engine_dev",
    "pipeline",
    "indicators",
    "config",
    "registry",
    "vault",
    "data_access",
    "execution_engine",
    "regimes",
    "scanners",
    "signals",
    "strategies", # Note: 'strategies_experimental' is deleted, but 'strategies' is protected
    "tests",
    "validation",
    "research", # Research docs are permanent infrastructure
    "outputs/system_reports",
]

def reset_repository(repo_root: Path, force: bool):
    """
    Safely resets the repository by removing experiment artifacts.
    """
    print(f"--- Repository Reset Tool ---")
    print(f"Root: {repo_root}")
    print(f"Mode: {'FORCE' if force else 'DRY-RUN'}")
    print("-" * 30)

    # 1. Full Deletion Phase
    for dname in FULL_DELETE_DIRS:
        target = repo_root / dname
        if target.exists() and target.is_dir():
            # Safety check: is it protected?
            if dname in PROTECTED_PATHS:
                print(f"[SKIP] {dname} is PROTECTED.")
                continue
                
            if force:
                print(f"[DELETE] Removing directory: {dname}")
                shutil.rmtree(target)
            else:
                print(f"[DRY-RUN] Would delete directory: {dname}")

    # 2. Clear Contents Phase
    for dname in CLEAR_CONTENT_DIRS:
        target = repo_root / dname
        if target.exists() and target.is_dir():
            if force:
                print(f"[CLEAR] Emptying directory: {dname}")
                for item in target.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            else:
                print(f"[DRY-RUN] Would empty directory: {dname}")

    if not force:
        print("-" * 30)
        print("Dry-run complete. Use --force to execute changes.")
    else:
        print("-" * 30)
        print("Repository reset complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trade_Scan Repository Reset Tool")
    parser.add_argument("--force", action="store_true", help="Execute the deletion (DANGEROUS)")
    args = parser.parse_args()

    # Determine repo root (assuming script is in tools/)
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent

    reset_repository(repo_root, args.force)
