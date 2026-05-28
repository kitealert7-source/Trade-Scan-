"""registry_merge.py -- fold parallel-batch run-registry shards into the single
authoritative run_registry.json.

Design + hardening: outputs/system_reports/01_system_architecture/SHARD_REGISTRY_PLAN.md

RECOVERY INVARIANT (LOCKED, §7): run_registry.json is the ONLY authoritative
registry for runtime readers (dedup, reconcile, status). Shards are authoritative
ONLY for recovery/replay of the in-progress batch and are consulted ONLY here.
A batch is merged iff its batch_manifest.json carries merge_completed: true.

Properties:
  - conflict-free: each run_id is owned by one worker => shards never overlap.
  - uniqueness HARD FAIL: dup run_id across shards, or vs base with a differing
    payload, raises (loud signal that orchestration identity broke).
  - idempotent: fold(base ∪ shards) -> atomic write -> explicit monotonic
    completion marker -> delete shards LAST. Crash mid-merge => shards intact,
    base unchanged; re-run converges.
  - verified: post-merge reload + cardinality + materialization check BEFORE
    shards are deleted.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from tools.system_registry import REGISTRY_PATH, _load_registry

MANIFEST_NAME = "batch_manifest.json"


class RegistryMergeError(RuntimeError):
    """Raised on any integrity violation during shard merge — never silent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_base(registry_path: Path) -> dict:
    """Authoritative base load. For the real registry use system_registry's
    fail-hard reader; for a test path read directly (empty if absent)."""
    if Path(registry_path) == Path(REGISTRY_PATH):
        return _load_registry()
    p = Path(registry_path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def write_batch_manifest(shard_dir: Path, *, batch_id: str,
                         expected_run_ids: list[str], worker_count: int,
                         max_parallel: int) -> dict:
    """Parent writes this at batch start (before workers spawn)."""
    shard_dir = Path(shard_dir)
    shard_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "batch_id": batch_id,
        "expected_run_ids": sorted(set(expected_run_ids)),
        "expected_count": len(set(expected_run_ids)),
        "worker_count": worker_count,
        "max_parallel": max_parallel,
        "created_at": _now(),
        "merge_started_at": None,
        "merge_completed": False,
    }
    _atomic_write_json(shard_dir / MANIFEST_NAME, manifest)
    return manifest


def _shard_files(shard_dir: Path) -> list[Path]:
    return sorted(f for f in shard_dir.glob("*.json")
                  if f.name != MANIFEST_NAME and not f.name.endswith(".tmp"))


def merge_shards(shard_dir: Path, registry_path: Path = REGISTRY_PATH) -> dict:
    """Fold shards into the authoritative registry. Idempotent + verified.

    Returns the final manifest dict. Raises RegistryMergeError on any integrity
    violation (leaving base unchanged and shards intact for recovery).
    """
    shard_dir = Path(shard_dir)
    registry_path = Path(registry_path)
    manifest_path = shard_dir / MANIFEST_NAME
    manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists() else {"expected_run_ids": []})

    # Idempotent: already merged -> clean any leftover shards (crash between
    # mark-complete and delete) and return.
    if manifest.get("merge_completed") is True:
        for sf in _shard_files(shard_dir):
            sf.unlink()
        return manifest

    manifest["merge_started_at"] = _now()
    if manifest_path.exists():
        _atomic_write_json(manifest_path, manifest)  # persist "started" for diagnostics

    base = _load_base(registry_path)
    base_count = len(base)

    shard_files = _shard_files(shard_dir)
    new_entries: dict[str, dict] = {}
    for sf in shard_files:
        entry = json.loads(sf.read_text(encoding="utf-8"))
        rid = entry.get("run_id")
        if not rid:
            raise RegistryMergeError(f"shard {sf.name} has no run_id")
        if rid in new_entries:
            raise RegistryMergeError(
                f"duplicate run_id across shards: {rid} — orchestration identity "
                f"assumption broke (two workers claimed one run_id)")
        if rid in base and base[rid] != entry:
            raise RegistryMergeError(
                f"run_id {rid} already in base with a DIFFERING payload — refusing "
                f"to silently overwrite (orchestration identity broke)")
        new_entries[rid] = entry

    new_not_in_base = [r for r in new_entries if r not in base]
    merged = dict(base)
    merged.update(new_entries)
    _atomic_write_json(registry_path, merged)

    # ---- integrity verification (before deleting shards) ----
    reloaded = _load_base(registry_path)  # raises if not valid JSON
    expected_card = base_count + len(new_not_in_base)
    if len(reloaded) != expected_card:
        raise RegistryMergeError(
            f"cardinality mismatch after merge: expected {expected_card}, "
            f"got {len(reloaded)} (shards intact, base preserved)")
    for rid in new_entries:
        if rid not in reloaded:
            raise RegistryMergeError(f"shard run_id {rid} not materialized after merge")

    expected = set(manifest.get("expected_run_ids", []))
    missing = sorted(expected - set(reloaded.keys()))

    # ---- explicit monotonic completion marker ----
    manifest.update({
        "merge_completed": True,
        "merge_completed_at": _now(),
        "shard_count": len(shard_files),
        "merged_run_count": len(reloaded),
        "merged_registry_sha256": _sha256_file(registry_path),
        "missing_expected_run_ids": missing,
    })
    _atomic_write_json(manifest_path, manifest)

    # ---- delete shards LAST, only after completion is marked ----
    for sf in shard_files:
        sf.unlink()

    if missing:
        print(f"[REGISTRY_MERGE] WARN {len(missing)} expected run_id(s) produced "
              f"no shard (crashed/failed before terminal): "
              f"{missing[:5]}{'...' if len(missing) > 5 else ''}")
    print(f"[REGISTRY_MERGE] merged {len(shard_files)} shard(s) -> "
          f"{len(reloaded)} runs (sha {manifest['merged_registry_sha256'][:12]})")
    return manifest


__all__ = ["merge_shards", "write_batch_manifest", "RegistryMergeError",
           "MANIFEST_NAME"]
