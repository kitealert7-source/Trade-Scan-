# Engine Patch A — Design Doc (v1.5.10 → v1.5.11) — MINIMUM CORE, LOCKED

**Status:** DESIGN, scope LOCKED — minimum investigation-engine core. No further scope expansion. (Read-only; no engine files modified.) Precursor to an operator-approved unfreeze.
**Source:** [`ENGINE_AUDIT_v1_5_10_2026-06-23.md`](ENGINE_AUDIT_v1_5_10_2026-06-23.md) + scoping/contemplation (operator, 2026-06-23).
**Character:** **structural + minimum evidence — behaviour BYTE-IDENTICAL.** No trade moves.
**Principle:** *Retain only capabilities answering repeatedly observed questions. Prefer omission over speculation.*

---

## 0. Scope (LOCKED)

| KEEP (the whole of Patch A) | REMOVED / DEFERRED |
|---|---|
| **C2** shared position builder | rejected_signals.csv ledger + SUPPRESSED layer |
| **Health counters** (run-level) | trade tags / context sidecar |
| **`engine_events.csv`** (event log) | trace mode · severity levels · reserved event types |
| **Minimal `invalid_fill_policy` plumbing** (single flag) | event-schema versioning · capability blocks |
| **`signal_version` bump** for FAIL vs SKIP | generic `FLAG_SCHEMA` / `feature_set_hash` framework |
| **H6** Stage-2 fail-closed | new identity block · all decoration / future-proofing |

Six items. Everything else is deferred until its question is asked again.

---

## 1. Byte-identical contract (load-bearing)

Patch A only **moves code** (C2), **records events already happening** (health/log), **adds one flag defaulting to today**, and **closes a guard** (H6). A result delta can only be a bug.

**Rules:** (1) all telemetry → `run_metadata.json` + the single new sidecar `engine_events.csv`; **nothing added to `results_tradelevel.csv`**. (2) the flag defaults to current behaviour; **no flag alters a trade in Patch A** (the `SKIP` path is Patch B). (3) **no new path calls `check_entry`/`check_exit` differently** (state-mutation/byte-identity risk). (4) emitted `event_id`/timestamps are **deterministic** (reproducible sidecar).

**Acceptance = pure equality:** 3 sanity strategies + PSBRK `8faf348a` re-run + one cointegration basket → byte-identical trades, v1.5.11 vs v1.5.10; `engine_events.csv` reproducible across two identical runs.

---

## 2. Live fleet already decoupled — promotion is a pure research event

Promoting `v1_5_11` does **not** touch the supervised live fleet (verified): `config/engine_authority.py:17-18` (authority *"does NOT govern the TS_Execution live ABI… independently pinned to v1_5_9"*); TS_Execution `phase0_validation.py:30` allow-list `('v1_5_3','v1_5_9')` excludes everything newer; the live basket producer imports no engine module; [`UNIFIED_ENGINE_AUTHORITY_PLAN.md`](../01_system_architecture/UNIFIED_ENGINE_AUTHORITY_PLAN.md) calls the research/live split intentional. "Decouple the pointers" was already the architecture.

---

## 3. Version & rollback

`engine_dev/.../v1_5_11/` = byte-copy of `v1_5_10/` + Patch A. `engine_abi/v1_5_11` shim + manifest. Canonical pointer flips **only after** the gate; `v1_5_10/` stays frozen = one-line rollback. Byte-identical → swap safe either direction.

---

## 4. C2 — shared position builder *(C2-min)*

Extract pure `build_position_from_pending(pending, cfg, strategy, row, i) -> PositionInit`, called by **both engine paths** (single-asset inline `execution_loop.py:338-447`; basket `evaluate_bar._fill_from_pending:296-406`). Surrounding loop untouched. Audit's top structural finding (4 duplicated copies; v1.5.10 regressed v1.5.9's centralization) **and** the single seam C1 hooks in Patch B. Basket fast-path stays a deliberate perf inline, kept honest by a parity test.

---

## 5. Health counters + event log

**`engine_health` (run-level → `run_metadata.json`):** `rejected_entries`, `stop_mutation_rejected` (already computed, was dropped at the bridge), `pending_entries_expired`, `force_close_count`, `negative_spread_bars`, `nan_bar_count` (cheap per-bar `pd.isna` probe, count-only — does **not** open the H2/ContextView audit). `invalid_fill_skips` added in Patch B (no skip path now → no speculative field).

**`engine_events.csv` (single per-run sidecar):**
```
event_id,bar_index,timestamp,event_type,direction,detail
evt_000001,...,REJECTED_ENTRY,-1,"allow_direction=false"
evt_000002,...,STOP_MUTATION_REJECTED,1,"non-monotone new_sl"
evt_000003,...,PENDING_EXPIRED,1,"utc_day_roll discarded pending"
evt_000004,...,NEGATIVE_SPREAD,,"raw_spread<0 clamped to 0"
evt_000005,...,FORCE_CLOSE,1,"DATA_END mark-out"
```
- `event_id` = deterministic sequential (`evt_NNNNNN`), reproducible. **No severity, no schema-version, no reserved types.**
- Emits only the five types that actually fire in Patch A. `INVALID_FILL_SKIP` is added in Patch B when the skip path exists.
- Hard cap **50k rows** → final `LOG_TRUNCATED` row, then stop. `nan_bar` is count-only (never per-row).
- *(The genuine engine-level "why no trade?" cases — `REJECTED_ENTRY`, `PENDING_EXPIRED` — are answerable here by bar. The dedicated research ledger and the SUPPRESSED class are deferred; strategy-internal "no signal" was never engine-observable anyway.)*

---

## 6. Minimal `invalid_fill_policy` plumbing + signal_version

Single flag, minimum mechanism — no framework.
```
engine_features:
    invalid_fill_policy: SKIP     # default FAIL
```
- **Resolve** from directive (default `FAIL`); **validate** (unknown key/value = hard `ValueError` at admission); **stamp** the resolved value into `run_metadata.json`.
- **`signal_version` bump:** when set in a directive, the flag bumps `signal_version` and routes through the existing classifier — so `SKIP` and `FAIL` can never be the same strategy (reproducible + distinguishable).
- Default `FAIL` = today → byte-identical. The `SKIP` code path is authored in Patch B (inside the C2 builder). **No `FLAG_SCHEMA` registry, `behavior_affecting` table, or `feature_set_hash`** — the second flag, if it ever comes, earns the generalization. Identity = the existing mechanism (`run_id`/`engine_version`/`content_hash`/`git_commit` + convergence gate) **plus** this flag stamp; no new identity block.

---

## 7. H6 — Stage-2 fail-closed *(structural guard fix)*

`stage2_compiler.py:353` skips the engine-version-mismatch check when the manifest is unreadable (`runtime_ver=="UNKNOWN"` → fail-open). Invert to **fail-closed** (raise). `stage2_compiler.py` only; cannot move trades.

---

## 8. Atomic commit sequence (byte-identity load-bearing on every commit)

1. **`v1_5_11` scaffold** — byte-copy, bump `ENGINE_VERSION`, ABI shim + manifest, fix L1 header drift. Gate: `test_engine_abi_v1_5_11` + byte-identical sanity trades.
2. **C2** shared builder. Gate: byte-identical sanity trades + fast-path parity. *(load-bearing)*
3. **`invalid_fill_policy` plumbing** (resolve/validate/stamp/`signal_version`, default FAIL). Gate: trades unchanged; metadata carries resolved flag; unknown key/value raises; directive flag bumps `signal_version`.
4. **Health counters** → `run_metadata`. Gate: present + populate on a known-trigger strategy; trades unchanged.
5. **Event log** (`engine_events.csv`; deterministic `event_id`; 50k cap). Gate: five event types emit; cap works; reproducible across two runs; trades unchanged.
6. **H6** fail-closed. Gate: absent-manifest raises; present unchanged.
7. **Promote + freeze** — flip pointer; convergence gate; stamp `vaulted/FROZEN/freeze_date`; refresh `tools_manifest`/`sweep_registry`.

---

## 9. Promotion gate

- [ ] **Byte-identical trades** — 3 sanity + PSBRK `8faf348a` + one basket (engine path) + fast-path parity. *(the contract)*
- [ ] `engine_events.csv` reproducible across two identical runs.
- [ ] `run_metadata` carries `engine_health` + resolved `invalid_fill_policy`.
- [ ] `engine_events.csv` emits the five Patch-A types; 50k cap + `LOG_TRUNCATED` verified.
- [ ] Unknown flag key/value raises at admission; a directive flag bumps `signal_version`.
- [ ] H6 fail-closed test green; `test_engine_abi_v1_5_11` + convergence gate green; no header/version drift.

---

## 10. Patch B (preview — own design doc once A is frozen)

Behavioural, evidence-first (A's event log already in place): **C1** — author the `invalid_fill_policy: SKIP` path inside the C2 builder (skip a trade whose N+1 fill is already past its stop / ATR≤0 / risk_distance≤0 / non-finite; emit `INVALID_FILL_SKIP` to `engine_events.csv`; increment `invalid_fill_skips`). **C3 (incremental)** — one `TradeAdmissionFailure(ValueError)` + change `run_stage1.py:1770` blanket `except Exception` to `except TradeAdmissionFailure: count+continue (SKIP)` / abort otherwise. Then re-run PSBRK P17 — the skip recorded per-bar in the event log.

---

## 11. NON-GOALS (recorded against scope-creep — no further expansion)

**DEFER (architecture satisfying itself; revisit only when the question recurs):** rejected_signals.csv ledger + SUPPRESSED layer · trade tags/context · trace mode · severity levels · reserved event types · event-schema versioning · capability blocks · generic `FLAG_SCHEMA`/`behavior_affecting`/`feature_set_hash` · new identity block.
**THINK HARD — not this cycle:** multiple pending entries · intrabar execution · partial-fill simulation · slippage-model plugins · H2 NaN/ContextView redesign · C3 Phase-2 full taxonomy · C2-full delegation revert.
**NEVER — out of charter:** ❌ multi-position · ❌ event-driven rewrite · ❌ async · ❌ tick simulation · ❌ order book · ❌ broker adapters · ❌ live-execution features · ❌ portfolio engine · ❌ v2.
**PROTECTED ASSUMPTIONS (audit §6) — change only via dedicated audit:** next-bar execution · gap-open stop fills · STOP precedence · direction-aware spread · day-close fill · pending-entry staleness · DATA_END force-close.

---

## 12. Decisions — LOCKED (2026-06-23)

C2-min · single `invalid_fill_policy` flag (no framework) · identity = existing + flag-stamp (no new block) · `signal_version` fold-in kept (FAIL≠SKIP) · 50k event cap · H6 fail-closed · evidence-before-behaviour (A → B) · land+freeze A before drafting B. **Minimum investigation-engine core; omission preferred over speculation; no further scope expansion.**

---

*Design LOCKED (minimum core) — read-only planning artifact. No engine files modified. Implementation requires operator approval to unfreeze (Invariant #6 + active infra-freeze). Live fleet (TS_Execution v1_5_9) unaffected by construction (§2).*
