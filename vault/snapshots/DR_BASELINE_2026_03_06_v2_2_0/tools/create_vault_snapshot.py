"""
Vault Snapshot Creator — creates a point-in-time archive of the workspace.

Copies governance, tools, engine_dev, broker specs, and strategy metadata
into vault/snapshots/<SNAPSHOT_NAME>/ with a SHA-256 hash manifest for
tamper evidence.

Usage:
    python tools/create_vault_snapshot.py
    python tools/create_vault_snapshot.py --name CUSTOM_SNAPSHOT_NAME

The snapshot name defaults to DR_BASELINE_<DATE>_v<ENGINE_VERSION>.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def copy_tree(src: Path, dst: Path, manifest: dict, manifest_prefix: str):
    """Recursively copy a directory, skipping __pycache__ and .pyc files."""
    if not src.exists():
        print(f"  [SKIP] Missing: {src}")
        return
    for item in sorted(src.rglob("*")):
        if item.is_dir():
            continue
        if "__pycache__" in str(item) or item.suffix == ".pyc":
            continue
        rel_to_src = item.relative_to(src)
        dest = dst / rel_to_src
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        manifest_key = f"{manifest_prefix}/{str(rel_to_src).replace(chr(92), '/')}"
        manifest[manifest_key] = sha256(dest)


def main():
    parser = argparse.ArgumentParser(description="Create a vault snapshot of the workspace")
    parser.add_argument("--name", default=None, help="Snapshot name (auto-generated if omitted)")
    args = parser.parse_args()

    # Determine snapshot name
    date_str = datetime.now().strftime("%Y_%m_%d")
    # Try to read robustness version as the engine version marker
    try:
        from tools.robustness import __version__ as rob_ver
        ver_tag = rob_ver.replace(".", "_")
    except ImportError:
        ver_tag = "0_0_0"

    snapshot_name = args.name or f"DR_BASELINE_{date_str}_v{ver_tag}"
    snapshot_dir = PROJECT_ROOT / "vault" / "snapshots" / snapshot_name

    if snapshot_dir.exists():
        print(f"[ERROR] Snapshot already exists: {snapshot_dir}")
        print("Remove it first or use --name to specify a different name.")
        return

    snapshot_dir.mkdir(parents=True)
    manifest = {}

    # 1. Governance (SOPs, scripts, schemas)
    print("[1/5] Governance...")
    gov_src = PROJECT_ROOT / "governance"
    copy_tree(gov_src, snapshot_dir / "governance", manifest, "governance")

    # 2. Tools (all core scripts)
    print("[2/5] Tools...")
    tools_src = PROJECT_ROOT / "tools"
    copy_tree(tools_src, snapshot_dir / "tools", manifest, "tools")

    # 3. Engine dev (versioned engines)
    print("[3/5] Engine dev...")
    eng_src = PROJECT_ROOT / "engine_dev"
    copy_tree(eng_src, snapshot_dir / "engine_dev", manifest, "engine_dev")

    # 4. Data access (broker specs)
    print("[4/5] Data access (broker specs)...")
    da_src = PROJECT_ROOT / "data_access" / "broker_specs"
    if da_src.exists():
        copy_tree(da_src, snapshot_dir / "data_access" / "broker_specs", manifest, "data_access/broker_specs")

    # 5. Strategies (metadata only: strategy.py, portfolio_evaluation/)
    print("[5/5] Strategies (metadata only)...")
    strat_root = PROJECT_ROOT / "strategies"
    if strat_root.exists():
        # Copy Master_Portfolio_Sheet.xlsx
        mps = strat_root / "Master_Portfolio_Sheet.xlsx"
        if mps.exists():
            dest = snapshot_dir / "strategies" / "Master_Portfolio_Sheet.xlsx"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mps, dest)
            manifest["strategies/Master_Portfolio_Sheet.xlsx"] = sha256(dest)

        for sdir in sorted(strat_root.iterdir()):
            if not sdir.is_dir():
                continue
            sname = sdir.name
            # strategy.py
            spy = sdir / "strategy.py"
            if spy.exists():
                dest = snapshot_dir / "strategies" / sname / "strategy.py"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(spy, dest)
                manifest[f"strategies/{sname}/strategy.py"] = sha256(dest)
            # portfolio_evaluation/
            pe = sdir / "portfolio_evaluation"
            if pe.exists():
                copy_tree(
                    pe,
                    snapshot_dir / "strategies" / sname / "portfolio_evaluation",
                    manifest,
                    f"strategies/{sname}/portfolio_evaluation",
                )

    # Write manifest
    vault_meta = {
        "snapshot_name": snapshot_name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_files": len(manifest),
        "engine_version": f"v{ver_tag}",
        "file_hashes": manifest,
    }

    manifest_path = snapshot_dir / "vault_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(vault_meta, f, indent=4)

    print(f"\n{'=' * 60}")
    print(f"Snapshot: {snapshot_name}")
    print(f"Files:    {len(manifest)}")
    print(f"Manifest: {manifest_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
