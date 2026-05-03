"""
Engine Manifest Generator

Usage:
  python tools/generate_engine_manifest.py                # latest engine version
  python tools/generate_engine_manifest.py --version v1_5_8a   # specific version

Authority: AGENT.md — Protected Infrastructure Policy
Purpose: Compute canonical (LF-normalized) SHA-256 hashes for all hashable
         engine files in the target version directory and write
         engine_manifest.json.

Hashing: delegates to tools.verify_engine_integrity.canonical_sha256 so the
         same single LF-normalized implementation is used by both manifest
         generation and integrity verification. This eliminates the prior
         class of CRLF false-failures on Windows checkouts where the
         generator hashed raw bytes (CRLF) but the verifier read the same
         file post-checkout (different bytes). Phase 1 of the v1.5.8
         engine-governance repair (commit 09443f4) introduced the canonical
         helper; this module now consumes it.

Hashed file scope: all *.py and *.json files in the version directory,
         EXCLUDING engine_manifest.json itself (a manifest cannot record
         its own hash).

WARNING: This tool must ONLY be executed by a human operator OR by an
         agent acting on an explicit, scoped, in-session human authorization
         (e.g. "execute Phase 2 v1.5.8 -> v1.5.8a fork"). Unauthorized
         manifest updates constitute a governance violation.
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
ENGINE_DEV_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"

sys.path.insert(0, str(PROJECT_ROOT))
from tools.verify_engine_integrity import canonical_sha256  # noqa: E402


def find_active_version() -> Path:
    """Find the latest engine version directory by lexicographic sort."""
    versions = sorted(
        [d for d in ENGINE_DEV_ROOT.iterdir() if d.is_dir() and d.name.startswith("v")],
        key=lambda d: d.name,
        reverse=True
    )
    if not versions:
        print("[FATAL] No engine versions found under engine_dev/universal_research_engine/")
        sys.exit(1)
    return versions[0]


def collect_hashable_files(version_dir: Path) -> list[Path]:
    """Return sorted list of files to hash: *.py and *.json, excluding the
    manifest file itself."""
    files = sorted(
        [p for p in version_dir.iterdir()
         if p.is_file()
         and (p.suffix == ".py" or p.suffix == ".json")
         and p.name != "engine_manifest.json"],
        key=lambda p: p.name,
    )
    return files


def main():
    parser = argparse.ArgumentParser(description="Engine manifest generator")
    parser.add_argument(
        "--version",
        help="Target engine version directory name (e.g. v1_5_8a). "
             "Default: latest version under engine_dev/universal_research_engine/.",
        default=None,
    )
    args = parser.parse_args()

    print("=" * 60)
    print("ENGINE MANIFEST GENERATOR (canonical-LF hashing)")
    print("=" * 60)

    if args.version:
        version_dir = ENGINE_DEV_ROOT / args.version
        if not version_dir.exists() or not version_dir.is_dir():
            print(f"[FATAL] Version directory not found: {version_dir}")
            sys.exit(1)
    else:
        version_dir = find_active_version()
    version_name = version_dir.name

    print(f"  Engine Version: {version_name}")
    print(f"  Path: {version_dir}")
    print()

    files = collect_hashable_files(version_dir)
    if not files:
        print("[FATAL] No hashable .py / .json files found in engine directory.")
        sys.exit(1)

    file_hashes = {}
    for filepath in files:
        file_hash = canonical_sha256(filepath).upper()
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
    print(f"[INFO] {len(file_hashes)} files hashed (canonical LF sha256).")


if __name__ == "__main__":
    main()
