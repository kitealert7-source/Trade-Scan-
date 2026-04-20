"""
Engine Manifest Generator

Usage:
  python tools/generate_engine_manifest.py

Authority: AGENT.md — Protected Infrastructure Policy
Purpose: Compute SHA-256 hashes for all engine files in the active engine version
         and write engine_manifest.json.

WARNING: This tool must ONLY be executed by a human operator.
         The agent is strictly forbidden from calling this script.
         Unauthorized manifest updates constitute a governance violation.
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
ENGINE_DEV_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def find_active_version() -> Path:
    """Find the latest engine version directory."""
    versions = sorted(
        [d for d in ENGINE_DEV_ROOT.iterdir() if d.is_dir() and d.name.startswith("v")],
        key=lambda d: d.name,
        reverse=True
    )
    if not versions:
        print("[FATAL] No engine versions found under engine_dev/universal_research_engine/")
        sys.exit(1)
    return versions[0]


def main():
    print("=" * 60)
    print("ENGINE MANIFEST GENERATOR")
    print("=" * 60)

    version_dir = find_active_version()
    version_name = version_dir.name
    print(f"  Engine Version: {version_name}")
    print(f"  Path: {version_dir}")
    print()

    # Hash all .py files in the engine directory
    py_files = sorted(version_dir.glob("*.py"))
    if not py_files:
        print("[FATAL] No .py files found in engine directory.")
        sys.exit(1)

    file_hashes = {}
    for filepath in py_files:
        file_hash = compute_sha256(filepath)
        file_hashes[filepath.name] = file_hash
        print(f"  [HASH] {filepath.name}: {file_hash[:16]}...")

    manifest = {
        "engine_name": "Universal_Research_Engine",
        "engine_version": version_name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "file_hashes": file_hashes
    }

    manifest_path = version_dir / "engine_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)

    print(f"\n[DONE] Manifest written to {manifest_path}")
    print(f"[INFO] {len(file_hashes)} files hashed.")


if __name__ == "__main__":
    main()
