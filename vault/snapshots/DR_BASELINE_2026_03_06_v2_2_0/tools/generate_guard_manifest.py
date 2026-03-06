"""
Guard-Layer Manifest Generator

Usage:
  python tools/generate_guard_manifest.py

Authority: AGENT.md — Protected Infrastructure Policy
Purpose: Compute SHA-256 hashes for all Critical Guard Set files
         and write tools/tools_manifest.json.

WARNING: This tool must ONLY be executed by a human operator.
         The agent is strictly forbidden from calling this script.
         Unauthorized manifest updates constitute a governance violation.
"""

import sys
import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_ROOT = PROJECT_ROOT / "tools"
MANIFEST_PATH = TOOLS_ROOT / "tools_manifest.json"

# Critical Guard Set — files that constitute the governance boundary
GUARD_FILES = [
    "run_pipeline.py",
    "run_stage1.py",
    "semantic_validator.py",
    "directive_schema.py",
    "strategy_provisioner.py",
    "exec_preflight.py",
    "strategy_dryrun_validator.py",
    "pipeline_utils.py",
    "portfolio_evaluator.py",
    "format_excel_artifact.py",
    "cleanup_reconciler.py",
    "run_portfolio_analysis.py",
]


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def main():
    print("=" * 60)
    print("GUARD-LAYER MANIFEST GENERATOR")
    print("=" * 60)

    file_hashes = {}
    missing = []

    for filename in GUARD_FILES:
        filepath = TOOLS_ROOT / filename
        if not filepath.exists():
            missing.append(filename)
            print(f"  [MISS] {filename}")
            continue

        file_hash = compute_sha256(filepath)
        file_hashes[filename] = file_hash
        print(f"  [HASH] {filename}: {file_hash[:16]}...")

    if missing:
        print(f"\n[WARN] {len(missing)} file(s) not found. Manifest will be incomplete.")

    now_utc = datetime.now(timezone.utc)
    manifest = {
        "generated_at": now_utc.isoformat(),
        "file_hashes": file_hashes,
    }

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)

    print(f"\n[DONE] Manifest written to {MANIFEST_PATH}")
    print(f"[INFO] {len(file_hashes)} files hashed.")
    print(f"[INFO] Generated at: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}")


if __name__ == "__main__":
    main()
