# Shard-Merge Run Registry — Design & Hardening Plan

**Status:** PLANNED — awaiting implementation sign-off.
**Date:** 2026-05-28
**Motivation:** `run_registry.json` is not parallel-safe. Under `run_pipeline --all --max-parallel N`, multiple worker processes do read-modify-write on the single 568 KB dict via fixed temp names (`system_registry.py` → `run_registry.tmp`; `orchestration/run_registry.py` → `run_registry.json.tmp`) with non-shared locks. A 50-directive / 8-worker batch corrupted it (`WinError 5` on rename; concatenated JSON), failing 6 runs. This is the blocker for parallel large-batch workflows (e.g. the 339-episode cointegration corpus).

---

## 1. Core idea

Each parallel run writes its registry entry to its **own immutable shard file**; the **parent process merges** shards into `run_registry.json` once, after the batch. Because **every `run_id` is owned by exactly one worker**, shards never overlap → the merge is a **conflict-free union** (no last-writer-wins data loss).

Registry topology stays a `{run_id: entry}` dict (unchanged on disk). Sharding is an **opt-in parallel write path**; sequential mode is untouched.

---

## 2. Hardening requirements (operator spec, 2026-05-28) → mechanism

| # | Requirement | Mechanism |
|---|---|---|
| 1 | **Shards append-only immutable** — write once, atomic rename once, never reopen | In shard mode the worker accumulates its run's entry in-memory and writes the **terminal** entry **once** to `shards/<run_id>.json` via temp+`os.replace`. No shard is ever reopened or rewritten. (A run that never reaches terminal writes no shard — surfaced by #4/#5, not silently patched.) |
| 2 | **Merge validates uniqueness — explode loudly** | At merge: duplicate `run_id` **across shards** → `HARD FAIL`. `run_id` in a shard that already exists in base **with a differing payload** → `HARD FAIL`. Identical payload (re-merge) → idempotent no-op. Never silently overwrite — duplicate ownership means orchestration identity broke. |
| 3 | **Merge idempotent** | Merge = pure fold of (immutable base snapshot ∪ immutable shards) → atomic write of `run_registry.json` → **explicit monotonic completion marker** (see #4: `merge_completed: true` + sha + count) → **only then** delete shards. Shards are **never** deleted incrementally. A crash mid-merge leaves shards intact + base unchanged (atomic write); rerun re-folds to the same result. The completion marker — not a timestamp alone — is the authority on whether a batch merged. |
| 4 | **Persist batch manifest** | Parent writes `batch_shards/<batch_id>/batch_manifest.json`. **At batch start:** `batch_id`, `expected_run_ids`, `worker_count`, `max_parallel`, `merge_started_at=null`, `merge_completed=false`. **At successful merge:** `shard_count`, `merge_started_at`, `merge_completed_at`, and the **explicit monotonic completion record** `merge_completed: true`, `merged_registry_sha256`, `merged_run_count`. Reconciliation + recovery + corruption diagnostics + postmortem comparison surface. |
| 5 | **Integrity verification after merge, before deleting shards** | After the atomic write: reload `run_registry.json` → valid JSON → every `expected_run_id` materialized → cardinality increased by exactly the new-shard count → compute `merged_registry_sha256` + `merged_run_count`, set `merge_completed: true` → **only then** delete shards. Any failure: keep shards, leave base authoritative, raise. |
| 6 | **Sequential mode preserved permanently** | `--max-parallel 1` keeps the existing direct registry write verbatim — canonical safe / debug / recovery / deterministic fallback. Sharding activates **only** when `max_parallel >= 2` (env flag set by `run_batch_mode` before workers spawn). Parallel is an optimization layer over the canonical path. |
| 7 | **Recovery invariant (authoritative-source rule)** | `run_registry.json` is the **only** authoritative registry for all normal runtime readers (dedup guard, reconcile, status). Shards are authoritative **only** for recovery/replay of the in-progress batch and **must never be consulted by normal runtime readers**. A batch is "merged" iff its manifest has `merge_completed: true`; until then base is unchanged and shards hold the unmerged delta. This prevents creep: readers scanning shards, partially-merged state leaking into runtime logic, or batch internals becoming externally-observable state. |

---

## 3. Lifecycle

1. **Batch start (parent):** if `max_parallel >= 2`, create `registry/batch_shards/<batch_id>/`, write `batch_manifest.json` (expected run_ids from admitted directives), set `TS_REGISTRY_SHARD_DIR=<dir>` before spawning workers.
2. **During run (worker):** registry mutations for the worker's `run_id` are held in-memory; reads see the immutable base `run_registry.json`. On the run's terminal transition, write `shards/<run_id>.json` once (atomic).
3. **Batch end (parent):** `merge_shards(batch_id)` — fold base ∪ shards with #2 validation → atomic write → #5 integrity verify → mark complete → delete shards. Then clear the env flag.
4. **Recovery:** a leftover `batch_shards/<batch_id>/` without a completion marker means a merge didn't finish — `merge_shards` is safe to re-run (idempotent).

---

## 4. Files touched (Protected Infra)

- `tools/system_registry.py` — the active runtime writer: add shard-mode write path (`TS_REGISTRY_SHARD_DIR`), keep the direct write for sequential.
- `tools/orchestration/run_registry.py` — same shard-mode gate if/where it writes during runs (audit which writer is live).
- New `tools/orchestration/registry_merge.py` — `merge_shards()`, manifest, integrity verify (single-purpose, testable).
- `tools/run_pipeline.py::run_batch_mode` — set shard dir + manifest before workers; call `merge_shards` in `finally` after the batch (parent only).

---

## 5. Phases

| # | Deliverable |
|---|---|
| P0 | This design doc + sign-off |
| P1 | Shard-write path in the live registry writer (terminal, immutable, atomic) |
| P2 | `registry_merge.py`: fold + uniqueness HARD-FAIL + idempotent + manifest + integrity verify + delete-last |
| P3 | Wire into `run_batch_mode` (set shard mode for N>=2; merge in finally; sequential untouched) |
| P4 | Tests: concurrent shard writes (no collision), merge uniqueness/idempotency/integrity, crash-recovery (re-merge), sequential-unchanged regression |
| P5 | **Validation gate:** tiny parallel batch (~8) → verify registry integrity + manifest + recovery → only then the full 339 |

---

## 6. Failure-mode note (why this beats today)

Today: concurrent writers corrupt a shared file (silent until a reader explodes). Shard-merge confines each writer to its own immutable file, makes the merge a validated, idempotent, verified single-process step, and keeps shards authoritative until success — so the worst case is "merge re-run needed," never "registry corrupted." Sequential remains the always-safe fallback.

## 7. Recovery invariant (LOCKED)

> `run_registry.json` remains the **only** authoritative registry until merge integrity verification succeeds. Shards are authoritative **only** for recovery/replay of the in-progress batch and **must never be consulted by normal runtime readers** (dedup guard, reconcile, status, any other consumer).

A batch is considered merged **iff** its `batch_manifest.json` carries the explicit monotonic marker `merge_completed: true` (with `merged_registry_sha256` + `merged_run_count`). Until that marker is set, the base registry is unchanged and the shards hold the unmerged delta for that batch alone.

This invariant is load-bearing — it prevents the architecture from degrading into: readers scanning shards directly, partially-merged state leaking into runtime logic, or batch internals becoming externally-observable state. Any future code that reads a shard outside `registry_merge` / recovery tooling violates this and must be rejected in review.
