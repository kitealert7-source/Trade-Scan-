# Engine v1.5.8 Drift — Remediation Record

**Status:** RESOLVED (Phase 2 complete)
**Date:** 2026-05-03
**Authority:** Phase 1 commit `09443f4` (canonical hashing) + Phase 2 (this remediation)
**New authorized engine for backtest research:** `v1_5_8a`

---

## 1. Root cause

Two distinct, compounded mechanisms produced what appeared to be widespread engine integrity failure when running any v1.5.8 backtest from a Windows checkout in May 2026.

### Mechanism A — post-freeze source drift via commit `f3ae767`

| Field | Value |
|---|---|
| Commit | `f3ae767` |
| Date | 2026-04-23 (3 days after v1.5.8 freeze on 2026-04-20) |
| Author | kitealert7-source (Co-Authored-By: Claude Opus 4.7) |
| Subject | `contract: introduce check_exit() v1.3 — namespaced exit_source attribution` |
| Stated scope | "Engine v1.5.8 (no version bump — additive)" |

`f3ae767` modified three files in `engine_dev/universal_research_engine/v1_5_8/`:
- `execution_emitter_stage1.py` (+12 lines)
- `execution_loop.py` (+23 lines)
- `stage2_compiler.py` (+110 lines)

It did NOT regenerate `engine_manifest.json`, did NOT update the corresponding files in `vault/engines/Universal_Research_Engine/v1_5_8/`, and did NOT bump the engine version.

The "no version bump — additive" intent was operationally correct (the new exit_source contract is backwards-compatible). The execution was incorrect: any engine source change requires a fresh manifest, and the FROZEN+vaulted v1.5.8 should not have had its source mutated regardless.

Net effect: from 2026-04-23 onward, the v1.5.8 engine source did not match its vaulted manifest, and any integrity check against that manifest would fail.

### Mechanism B — Windows CRLF rendering vs LF-canonical hashing

`tools/verify_engine_integrity.py` and `tools/generate_engine_manifest.py` hashed raw on-disk bytes via `hashlib.sha256(file.read())`. Manifests were generated and committed to git on systems where files have LF line endings; the recorded `file_hashes` are LF-canonical.

On Windows checkouts where `core.autocrlf=true` is active (this repo's default; no `.gitattributes` override) every text file is materialized with CRLF endings. The on-disk byte hash differs from the LF-canonical hash even when the file is byte-identical at the git-blob level.

Verified at audit on `engine_dev/v1_5_8/main.py` (clean at git-blob level — never touched by `f3ae767`):
- Manifest expects: `47825FA2F0526B26` (LF canonical)
- Git HEAD blob hash: `47825FA2F0526B26` ✓
- Windows on-disk bytes (CRLF rendering): `286BF66AF3C88987` ✗
- Phase-1 canonical helper: `47825FA2F0526B26` ✓

Net effect: even FILES NOT TOUCHED BY `f3ae767` failed integrity on Windows checkouts. This was the larger "noise" hiding the real Mechanism A drift.

### Compounded blast radius

The compound made the problem look catastrophic:
- Every text file in every engine version directory failed the integrity check on Windows
- The 3 actually-drifted files would have failed even on Linux
- Diagnostic output couldn't distinguish the two failure modes — both showed as "HASH MISMATCH"

This blocked all v1.5.8 backtest runs (engine resolver fired at admission gate).

### Vault-side `execution_loop.py` historical anomaly (separate from above, unresolved)

During audit, a third discrepancy was discovered in `vault/engines/Universal_Research_Engine/v1_5_8/execution_loop.py`:
- Manifest expects: `3004095B83D11D09…`
- Vault disk (canonical LF): `30252572 9C198AA0…`
- engine_dev disk after `f3ae767` (canonical LF): `1A0077CD7A3A43BC…`

Three distinct hashes. The manifest's recorded value matches neither vault nor engine_dev at any commit visible in `git log -- vault/engines/.../v1_5_8/execution_loop.py` (which shows only the freeze commit `b63e94f`). This is consistent with the manifest having been generated against an uncommitted working-tree state at freeze time, OR the manifest having been hand-edited after generation. Origin cannot be determined from available history.

**Treatment: HISTORICAL ANOMALY, NO MUTATION** (per directive). Documented in `governance/engine_lineage.yaml` under `v1_5_8.historical_anomalies`. The vault directory is preserved as-shipped (`b63e94f`). `v1_5_8a` is generated cleanly from current source and does not inherit this anomaly.

---

## 2. Corrective action

### Phase 1 — Commit `09443f4` (committed previously)

Canonical-LF hashing in [tools/verify_engine_integrity.py](tools/verify_engine_integrity.py):
- Added `canonical_sha256(filepath)` module-level helper that normalizes `\r\n` → `\n` before hashing
- Replaced both raw-byte hash blocks (`verify_hashes` + `verify_tools_integrity`) with the helper
- 10 regression tests including LF/CRLF identity, live manifest contract, and real-drift detection

This eliminated Mechanism B entirely. After Phase 1, "clean" files passed integrity on Windows; "drifted" files (Mechanism A) still failed correctly.

### Phase 2 — This remediation

#### 2.1 Single source of truth for canonical hashing

[tools/generate_engine_manifest.py](tools/generate_engine_manifest.py) now imports and uses the same `canonical_sha256` helper from Phase 1. Manifest generation and integrity verification share one hash implementation. No more "manifest generated against state X, verified against state Y" divergence.

Generator additions:
- `--version` CLI flag for targeting a specific engine version
- Hash scope expanded from `*.py` to `*.py + *.json` (excluding `engine_manifest.json` itself)
- Updated docstring permits agent execution under explicit scoped human authorization (closes the loop with the human-only warning so Phase 2 work could legitimately invoke the generator)

#### 2.2 Pre-commit guard against recurrence

[tools/hooks/pre-commit](tools/hooks/pre-commit) gains an "engine-dev manifest sync guard": any staged change under `engine_dev/universal_research_engine/<version>/` that isn't accompanied by a same-commit update to that version's `engine_manifest.json` blocks the commit. The error message points the user at the regeneration command.

This makes `f3ae767`-class drift impossible going forward at the pre-commit layer — any future engine source modification MUST stage the regenerated manifest in the same commit or the commit fails.

#### 2.3 New engine lineage `v1_5_8a` (post-`f3ae767` source state, fresh manifest)

Source: `engine_dev/universal_research_engine/v1_5_8a/` — full copy of `engine_dev/v1_5_8/` after `f3ae767`'s changes, with two edits:
- `main.py:41` `ENGINE_VERSION = "1.5.8a"` (was `"1.5.8"`)
- `contract.json` `engine_version: "v1_5_8a"` (was `"v1_5_8"`)

Manifest: `engine_dev/v1_5_8a/engine_manifest.json` generated by the patched generator, then enriched with full production-schema fields (`engine_status: FROZEN`, `vaulted: true`, `freeze_date: 2026-05-03`, `predecessor: v1_5_8`, `supersession_reason`, `capabilities`, `contract_id`, `adds`, `invariants`).

Vault: `vault/engines/Universal_Research_Engine/v1_5_8a/` — byte-for-byte copy from engine_dev/v1_5_8a/, fidelity-verified via canonical hash on every file.

`v1_5_8/` (both `engine_dev` and `vault`) — UNTOUCHED. The drift is preserved as a historical fact in the source tree and git log.

#### 2.4 Authoritative supersession registry

New file: [governance/engine_lineage.yaml](governance/engine_lineage.yaml) records every engine version's status, vault state, predecessor, and (where applicable) supersession. Lives under `governance/` so it can be updated as future versions land without mutating any vaulted engine directory.

Entries:
- `v1_5_6`: frozen, vaulted, superseded_by `v1_5_7`
- `v1_5_7`: frozen, vaulted, superseded_by `v1_5_8`
- `v1_5_8`: frozen, vaulted, superseded_by `v1_5_8a` (with full `supersession_reason` and `historical_anomalies` block on the vault execution_loop.py discrepancy)
- `v1_5_8a`: frozen, vaulted, superseded_by null (current authorized engine for backtest research)
- `v1_5_9`: experimental, not vaulted, purpose: TS_Execution / Trade_Scan parity work for burn-in pipeline (informational; resolver excludes EXPERIMENTAL via status filter)

#### 2.5 Resolver policy update

[tools/engine_resolver.py](tools/engine_resolver.py) `resolve_engine()` updated:

| Change | Before | After |
|---|---|---|
| Hashing | Raw bytes (CRLF false-fail) | `canonical_sha256` helper (LF-normalized, single source of truth) |
| Manifest file_hashes | Not validated at resolution time | Every entry validated; failures named in F9 diagnostic |
| Supersession check | Not consulted | Reads `engine_lineage.yaml`; rejects engines listed with non-null `superseded_by` |
| Sort order | Lowest version wins ("least change") | Highest version wins ("latest production-ready") — supersession registry now carries the per-version intent explicitly |
| Suffix-aware semver | `int('8a')` would crash | New `_semver_key` returns `((maj, ''), (min, ''), (patch, suffix))` tuples for correct ordering |
| Visibility log event | `NEWER_ENGINE_AVAILABLE` | `ENGINE_RESOLVED` with `older_eligible_candidates` list |

Failure code semantics preserved (F8 contract drift, F9 no FROZEN candidate, F10 only EXPERIMENTAL). F9 diagnostic now enumerates per-candidate rejection reasons (`capability_mismatch`, `contract_id_not_whitelisted`, `superseded_in_lineage`, `manifest_drift(N_files)`).

#### 2.6 Resolver regression test suite

New file: [tests/test_engine_resolver_policy.py](tests/test_engine_resolver_policy.py) — 15 tests, all pass.

| Test | Asserts |
|---|---|
| `test_only_v158_clean_resolves_v158` | Single eligible engine selected |
| `test_v158_dirty_v158a_clean_resolves_v158a` | Manifest drift skips that engine, picks clean successor |
| `test_both_clean_v158a_wins_by_version` | Descending sort: highest eligible wins |
| `test_skips_experimental_v159` | EXPERIMENTAL filter excludes v1.5.9 |
| `test_skips_unvaulted` | (documents current contract: vaulted is informational, supersession is the gate) |
| `test_skips_superseded_when_listed_in_lineage` | Lineage supersession is enforced |
| `test_canonical_hash_validates_crlf_files` | Phase 1 canonical helper used by resolver — CRLF files validate cleanly |
| `test_no_eligible_engine_raises_f9` | F9 with rejection diagnostic when nothing eligible |
| `test_only_experimental_raises_f10` | F10 when only EXPERIMENTAL satisfies |
| `test_contract_drift_raises_f8` | F8 (existing behavior preserved) on contract drift |
| `test_plain_versions_ascend` | semver: v1_5_7 < v1_5_8 < v1_5_9 |
| `test_suffix_is_successor_within_patch` | semver: v1_5_8 < v1_5_8a < v1_5_8b |
| `test_suffix_below_next_patch` | semver: v1_5_8a < v1_5_9 |
| `test_double_digit_patch` | semver: v1_5_8 < v1_5_10, v1_5_8a < v1_5_10 |
| `test_live_resolver_picks_v158a` | **Live integration**: real engine_dev/, real vault, real lineage → resolver picks `v1_5_8a` |

---

## 3. Future guardrails (now in place)

| Guardrail | Location | Prevents |
|---|---|---|
| Single canonical hash implementation | `tools/verify_engine_integrity.canonical_sha256` (Phase 1, commit `09443f4`) | Mechanism B (CRLF false-failures across all tooling) |
| Pre-commit manifest-sync hook | `tools/hooks/pre-commit` (Phase 2) | Mechanism A (engine source modified without manifest update) recurring |
| Manifest-clean check at resolution time | `tools/engine_resolver._manifest_file_hashes_clean` (Phase 2) | Drifted engine being silently selected even when present in directory |
| Lineage-based supersession | `governance/engine_lineage.yaml` (Phase 2) | Pre-supersession engine (e.g. drifted `v1_5_8`) being selected when a clean successor exists |
| Suffix-aware version ordering | `tools/engine_resolver._semver_key` (Phase 2) | Resolver crashing on the `v1_5_8a` naming convention; future `v1_5_8b`, `v1_5_9a` etc. handled cleanly |
| Resolver regression test suite | `tests/test_engine_resolver_policy.py` (Phase 2) | Future resolver changes silently breaking selection policy |

---

## 4. Outcome — Idea 64 (NEWSBRK) and other v1.5.8-era research can resume

After this remediation:

- Backtest research runs resolve to `v1_5_8a` automatically (verified by `test_live_resolver_picks_v158a` and by the orchestrator log line `[ENGINE] Running ... on engine v1.5.8a` once Phase 2 lands)
- The functional behavior of `v1_5_8a` is identical to `v1_5_8`'s post-`f3ae767` state — strategies that worked under "informally-modified v1.5.8" will produce byte-identical trade ledgers under `v1_5_8a` (because the source is the same; only the formal manifest changed)
- The NEWSBRK directive (`64_BRK_IDX_30M_NEWSBRK_S01_V1_P00`) preserved unchanged in INBOX per directive can be re-run without modification once Phase 2 commits land
- v1.5.9 EXPERIMENTAL parity work continues unblocked on its separate track (resolver's `engine_status: FROZEN` filter has always excluded it)

---

## 5. Files changed in Phase 2

| Path | Action |
|---|---|
| `tools/generate_engine_manifest.py` | Patched: canonical hashing + `--version` flag + `.json` scope |
| `tools/hooks/pre-commit` | Patched: engine-dev manifest-sync guard |
| `tools/engine_resolver.py` | Patched: canonical hash + supersession + manifest-clean + descending sort + suffix-aware semver |
| `engine_dev/universal_research_engine/v1_5_8a/` | NEW: source directory (6 files) |
| `engine_dev/universal_research_engine/v1_5_8a/engine_manifest.json` | NEW: generated + enriched |
| `vault/engines/Universal_Research_Engine/v1_5_8a/` | NEW: vault copy (7 files including manifest) |
| `governance/engine_lineage.yaml` | NEW: authoritative supersession registry |
| `tests/test_engine_resolver_policy.py` | NEW: 15 regression tests |
| `outputs/ENGINE_DRIFT_REMEDIATION.md` | NEW: this document |
| `engine_dev/universal_research_engine/v1_5_8/` | UNTOUCHED |
| `vault/engines/Universal_Research_Engine/v1_5_8/` | UNTOUCHED |
