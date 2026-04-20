"""
rehash_directive.py — Sweep Hash Recompute CLI

Purpose:
    Recompute the signature hash for a directive after edits and atomically
    update sweep_registry.yaml to prevent sweep gate collisions on re-run.

Usage:
    python tools/rehash_directive.py <directive_path>
    python tools/rehash_directive.py <directive_path> --dry-run
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.sweep_registry_gate import (
    _hash_signature,
    _extract_namespace_info,
    _load_yaml,
    _write_yaml_atomic,
    _acquire_lock,
    _release_lock,
    _get_stored_hash,
    _hashes_match,
    SWEEP_REGISTRY_PATH,
    SWEEP_LOCK_PATH,
)


def rehash_directive(directive_path: str, dry_run: bool = False) -> int:
    d_path = Path(directive_path)
    if not d_path.exists():
        print(f"[REHASH] ERROR: Directive not found: {d_path}")
        return 1

    try:
        ns = _extract_namespace_info(d_path)
    except Exception as e:
        print(f"[REHASH] ERROR: Cannot parse directive namespace: {e}")
        return 1

    idea_id = ns["idea_id"]
    directive_name = ns["strategy_name"]
    sweep_key = f"S{int(ns['sweep']):02d}"

    try:
        new_hash = _hash_signature(d_path)
    except Exception as e:
        print(f"[REHASH] ERROR: Failed to compute signature hash: {e}")
        return 1

    new_short = new_hash[:16]

    lock_fd = _acquire_lock(SWEEP_LOCK_PATH)
    try:
        registry = _load_yaml(SWEEP_REGISTRY_PATH)
        ideas = registry.get("ideas", {})
        idea_block = ideas.get(idea_id)
        if not isinstance(idea_block, dict):
            print(f"[REHASH] ERROR: idea_id='{idea_id}' not found in sweep_registry.yaml")
            return 1

        sweeps = idea_block.get("sweeps", idea_block.get("allocated", {}))
        entry = sweeps.get(sweep_key)
        if not isinstance(entry, dict):
            print(f"[REHASH] ERROR: sweep='{sweep_key}' not found under idea_id='{idea_id}'")
            print(f"  Registered sweeps: {list(sweeps.keys())}")
            return 1

        existing_hash = _get_stored_hash(entry)

        if _hashes_match(existing_hash, new_hash):
            print(f"[REHASH] No change: hash already matches for {directive_name} @ {sweep_key}")
            print(f"  hash: {new_short}")
            return 0

        print(f"[REHASH] Drift detected for {directive_name} @ {sweep_key}:")
        print(f"  old: {existing_hash[:16] if existing_hash else '(none)'}")
        print(f"  new: {new_short}")

        if dry_run:
            print("[REHASH] DRY RUN — no changes written.")
            return 0

        entry["signature_hash"] = new_short
        entry["signature_hash_full"] = new_hash
        sweeps[sweep_key] = entry
        idea_block["sweeps"] = sweeps
        ideas[idea_id] = idea_block
        registry["ideas"] = ideas
        _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
        print(f"[REHASH] sweep_registry.yaml updated: {directive_name} @ {sweep_key} -> {new_short}")
        return 0

    finally:
        _release_lock(lock_fd, SWEEP_LOCK_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute sweep signature hash and update sweep_registry.yaml"
    )
    parser.add_argument("directive_path", help="Path to directive YAML (.txt) file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to registry",
    )
    args = parser.parse_args()
    return rehash_directive(args.directive_path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
