"""
Engine Manifest Generator

Usage:
  python tools/generate_engine_manifest.py

Authority: AGENT.md — Protected Infrastructure Policy
Purpose: Compute canonical (LF-normalized) SHA-256 hashes for all engine
         files in the active engine version and write engine_manifest.json.

Hashing: delegates to tools.verify_engine_integrity.canonical_sha256 so
         the same single LF-normalized implementation is used by both
         engine-manifest generation and integrity verification. Eliminates
         Windows CRLF false-failures on engine integrity.

WARNING: This tool must ONLY be executed by a human operator OR by an
         agent acting on an explicit, scoped, in-session human
         authorization. Unauthorized manifest updates constitute a
         governance violation.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
ENGINE_DEV_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"

sys.path.insert(0, str(PROJECT_ROOT))
from tools.verify_engine_integrity import canonical_sha256  # noqa: E402


def compute_sha256(filepath: Path) -> str:
    """Compute canonical (LF-normalized) SHA-256 hash of a file.

    Delegates to verify_engine_integrity.canonical_sha256 — single source
    of truth. Returns uppercase hex digest matching what the integrity
    verifier expects."""
    return canonical_sha256(filepath).upper()


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
