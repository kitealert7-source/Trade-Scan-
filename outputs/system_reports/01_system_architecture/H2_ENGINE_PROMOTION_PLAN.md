# H2 Engine Promotion Plan

**Status:** LOCKED — executable architecture.
**Revision:** 11 (single ABI on v1_5_9; v1_5_3 retired after TS_Execution intentionally migrated).
**Date:** 2026-05-13.
**Approval status:** human-approved as executable architecture.

**Change log:**
- v11 (2026-05-13): TS_Execution was intentionally migrated to `engine_abi.v1_5_9` in a parallel session, collapsing the dual-ABI arrangement to a single ABI. `engine_abi/v1_5_3/` package, `governance/engine_abi_v1_5_3_manifest.yaml`, `tests/test_engine_abi_v1_5_3.py`, and v1_5_3 references in `tools/abi_audit.py` + `.github/workflows/abi_audit.yml` + `tools/hooks/pre-commit` retired. Section 1l rewritten, Section 5.12 simplified, Phase 0a steps consolidated. No other architectural changes — corpus, decision protocol, phase map, and validator design are unchanged from v10. Recon record archived to `archive/2026-05-13_phase0a_v1_5_3_retirement/`.
- v10 (2026-05-13): Dual ABI for engine version isolation + link/junction prohibition on VALIDATION_DATASET.

---

## Framing

The H2 recycle engine has cleared the research bar (10/10 survival, +62.8% mean, USD_SYNTH compression gate load-bearing). This is no longer experimental — it is infrastructure-grade research awaiting promotion.

**Reframings that shape this plan:**

1. **No strategies are actually live.** portfolio.yaml entries are nominal.
2. **Burn-in retired due to architectural entanglement** inside TS_Execution. Re-introduction is a SEPARATE repo (TS_SignalValidator).
3. **Single-responsibility carve:** Trade_Scan → research. TS_SignalValidator → signal correctness gate. TS_Execution → order routing.
4. **Python upgrade is OUT of this cycle.** Cost/benefit doesn't justify bundling.
5. **The ABI is a contract, not a kitchen sink.** Scope-disciplined recon-first export list, CI-enforced at three layers.
6. **Validator inputs must be fully deterministic.** Frozen validation corpus is the missing piece. Without it, "replay" isn't replay.
7. **This plan respects ten documented prior-phase failure modes** (Section 1n).

The shape of the system after this engine cycle:

```
Trade_Scan                  TS_SignalValidator (NEW)        TS_Execution
─────────                   ───────────────────             ────────────
research + backtest         signal correctness gate         order routing
+ vault production          (consumes vault → emits         (consumes vault
                            decision.json)                  + decision.json)
                                    ↓
                            TS_SIGNAL_STATE/  (NEW state root)
                                    ↑
                            VALIDATION_DATASET/  (NEW frozen corpus, native FS only)
                                    ↑
           ↓                        ↓                              ↓
           ─────────────────  engine_abi/v1_5_9/  ──────────────────
           (TS_Execution + basket_runner + TS_SignalValidator —
            single shared ABI, manifest- + triple-gate-CI enforced)
                       ↑
                       │
                       Python 3.11 (unchanged)
```

Each repo answers exactly one question. All consumers pin to the same engine ABI (`v1_5_9`). The single-ABI shape is what landed in practice after v11; the dual-ABI provision from v10 is preserved by the versioning policy (Section 5.12) for whenever a future consumer needs to pin to a different engine. Failure modes are isolated. Every input to the validator is hash-bound or version-pinned.

---

## 1. Historical Constraints Found

### 1a–1k (unchanged from v6)

(Live execution contract, Protected Infrastructure, v1_5_9 evaluate_bar, basket_sim outside pipeline, PORT overload, informal cross-repo ABI, Deployment Unification Plan implementation, burn-in entanglement, engine contracts, ABI scope discipline, source/state separation.)

### 1l. Single ABI on v1_5_9 as governance artifact (UPDATED — v11)

The engine has one version in active use across all consumers:
- **v1_5_9** — frozen 2026-05-08 with `evaluate_bar()` callable. Consumed by TS_Execution, basket_runner (Phase 2), and TS_SignalValidator (Phase 7a).

**Decision: single shared ABI on v1_5_9.**

- `engine_abi/v1_5_9/` — re-exports the v1_5_9 surface. Thin wrapper over `engine_dev.universal_research_engine.v1_5_9.*` and `engines.*`.

**History (v10 → v11):** the v10 plan called for dual ABIs (`v1_5_3` for TS_Execution, `v1_5_9` for new consumers) on the assumption TS_Execution would stay on v1_5_3 for migration safety. During Phase 0a execution in a parallel session, TS_Execution was intentionally migrated to `engine_abi.v1_5_9` (deliberate decision, certified by `tests/test_engine_abi_ts_execution_boot.py`). With TS_Execution on v1_5_9 the dual-ABI rationale dissolved and the simpler single-ABI shape was adopted. The dual-ABI pattern remains the policy (Section 5.12) for the case where a future consumer needs a different engine version pinned.

**Governance artifact (one file):**

- `governance/engine_abi_v1_5_9_manifest.yaml`

Follows Section 6.8 schema. Hash-bound, structured, machine-readable.

**Triple-layer CI enforcement** applies to the manifest:
1. Pre-commit hook (`tools/abi_audit.py --pre-commit` — verifies hash, consumer paths, package `__all__` ordering)
2. CI pipeline check (`tools/abi_audit.py --ci` — same checks; on push to `main`, updates `last_verified_commit` + `last_verified_utc` via `abi-ci-bot`)
3. Runtime assertion at `engine_abi.v1_5_9` import (compares package `__all__` to manifest)

Rule: any divergence between manifest and its actual exports fails closed.

**Why single ABI is correct (post-v11):**
- Only one consumer-set exists (TS_Execution + Trade_Scan internals + future basket_runner + future validator) and they're all happy on v1_5_9.
- Maintaining a second manifest with no consumers is dead infrastructure that drifts silently.
- The dual-ABI pattern is preserved as a *policy* (Section 5.12), available the moment a real second consumer needs a different engine version. We don't pay for a contract surface we don't currently use.

### 1m. Validation corpus as hash-bound frozen dataset (NEW)

- The validator's output must be a deterministic function of its inputs. If "replay data" is the live RESEARCH layer, that's not deterministic — data corrections, backfills, schema checkpoints all change validator behavior silently.
- **Frozen corpus:** `VALIDATION_DATASET/h2_validator_baseline_v1/` with `manifest.json` (per-file sha256 + cumulative).
- Validator startup verifies corpus hash; FAIL-CLOSED on mismatch.
- New corpus versions are created side-by-side, never modified in place.
- Validator config pins corpus version. Moving to a new version = explicit operator action with audit trail.

### 1m-i. Corpus Immutability — BINDING INVARIANT (NEW)

A corpus marked `frozen: true` is permanently immutable. This is a hard rule, not a guideline.

**Prohibitions (no exceptions):**

- **Never overwrite** any file in a frozen corpus directory.
- **Never patch** (edit, modify, correct) any file in a frozen corpus directory.
- **Never replace files in-place.**
- **Never modify the manifest** of a frozen corpus (no field edits, no cumulative-hash recomputation, nothing).
- **Never re-use a corpus_id.** Once `h2_validator_baseline_v1` exists, `v1` is permanently taken — even if the v1 corpus is later deemed flawed.
- **Never delete a frozen corpus** except in Phase 7a.0 rollback where no consumers exist yet.
- **Never use symlinks or NTFS directory junctions** anywhere in the corpus path. VALIDATION_DATASET/ must be a native directory tree on the same filesystem as Trade_Scan. No `mklink /J`, no `ln -s`, no indirection of any kind. See Section 1m-iii.

**The only legal change to a corpus is to create a new version next to it.** If `v1` has a problem, the fix is `v2` — never `v1` modified.

**Why this is invariant, not policy:**

- A validator decision file references its corpus by `corpus_id`. If `v1` is mutated, every historical decision file referencing `v1` becomes silently invalid — the hash they were computed against no longer exists, but the decision file's record still names `v1`.
- Audit trail dies. "What did the validator see when it emitted decision X on date Y?" becomes unanswerable.
- The whole determinism stack collapses (the validator's output is supposed to be a function of frozen inputs; if inputs change, attribution becomes impossible).

**Enforcement:**

1. **Filesystem permissions:** after freeze, run `chmod -R a-w VALIDATION_DATASET/{corpus_id}/`. Files are read-only at the OS level.
2. **Validator startup check:** before processing any bar, validator verifies every file in the corpus is `a-w` (write bit unset). Mismatch → FAIL-CLOSED + operator alert.
3. **Manifest hash re-verification:** validator computes cumulative sha256 on each startup; if anything ever differs from the manifest, FAIL-CLOSED.
4. **CI / pre-commit hook:** `tools/corpus_audit.py --check-immutability` rejects any commit that modifies `VALIDATION_DATASET/{corpus_id}/` where `manifest.frozen == true`.

**Audit invariant:** historical validator decision files MUST remain reproducible. Given (vault_id, corpus_id, ABI version, validator code commit), re-running the validator MUST produce the same decision. This invariant is the system-level test for whether the immutability rules are being respected.

### 1m-iii. Junction/symlink prohibition on VALIDATION_DATASET — BINDING INVARIANT (NEW — v10)

The 2026-05-07 NTFS directory junction incident (silent loss of 21,043 research files / 4.04 GB when a worktree junction target was deleted) is the load-bearing precedent for this rule.

**Binding:**

- `VALIDATION_DATASET/` MUST be a native directory tree on the same physical filesystem as Trade_Scan.
- Never accessed via `mklink /J`, `ln -s`, NTFS reparse points, or any filesystem-level indirection.
- Never inside a Claude worktree path.
- Never the target of any junction or symlink from elsewhere.

**Enforcement:**

1. **Creation-time check** in `tools/corpus_audit.py --check-immutability`: scans the corpus path for symlinks/junctions. Any present → reject creation.
2. **Validator startup check** (added to protocol in Section 6.9): `os.path.realpath(VALIDATION_DATASET/{corpus_id})` MUST equal the literal config path. If realpath differs (indicates a link/junction in the chain) → FAIL-CLOSED + operator alert.
3. **CI hook**: if commit introduces a symlink/junction creation script targeting VALIDATION_DATASET/, hard-fail.

**Failure mode prevented:** someone creates a junction "for convenience" (e.g., to map a worktree-relative path to the real corpus). Junction target gets deleted as part of an unrelated cleanup. Corpus contents follow the junction and are lost. Hash check would catch it on next validator startup, but by then the corpus is gone — recoverable only from backup, and the historical decisions referencing it become un-reverifiable.

### 1m-ii. Minimal-corpus sizing rule (NEW)

A corpus must be sized to the **exact validation task** that consumes it. Not to "the dataset universe." Not to "what might be useful later."

**Rule (binding):**

Each new corpus declares its scope as the minimal set of `(symbols × date_range × timeframes)` required by the specific strategy or basket it validates.

**For H2 (the first corpus, `h2_validator_baseline_v1`):**

- Symbols: **EURUSD, USDJPY** (the two trading legs). NOT the 19-symbol universe.
- Regime factors: **USD_SYNTH** (compression_5d is load-bearing for the gate; vol_20d, autocorr_20d, stretch_z20 included for diagnostic context only).
- Date range: **the actual validation window** — Phase 7a observation window, not all of historical research data.
- Timeframes: **5m** (trading); **daily** (USD_SYNTH features).

**Estimated size for H2 corpus:** roughly 1–3 GB. Acceptable storage cost; tiny in absolute terms.

**Why minimal:**

- Frozen storage cost compounds: each new strategy gets its own corpus, never mutating others. If every corpus contains the whole universe, storage cost spirals.
- Operational baggage: a 50GB corpus is harder to copy, verify, back up, audit.
- Honest scope: a corpus that contains data the strategy never reads is sloppy. "Frozen what was needed" is provable; "frozen what was lying around" is not.

**Different validator instances → different corpora.** When the next basket strategy ships (e.g., GBP+JPY), it gets its own corpus (`gbpjpy_validator_baseline_v1`) with GBPUSD + USDJPY + relevant factors only. If two corpora happen to overlap in source data (both need USDJPY 2024-2026 5m), they each freeze it separately. Storage cost is trivial; operational simplicity is high.

**Corpus manifest enhancement:** add `scope.rationale` field documenting why this scope is what it is. Future operators understand the boundaries.

```json
"scope": {
  "symbols": ["EURUSD", "USDJPY", "USD_SYNTH"],
  "date_range": {"start": "2024-09-02", "end": "2026-05-09"},
  "timeframes": ["5m", "daily"],
  "rationale": "H2 recycle strategy trades EURUSD + USDJPY legs; uses USD_SYNTH compression_5d as load-bearing regime gate; validation window = Phase 7a observation window."
}
```

### 1n. Historical incident patterns from prior phases (NEW)

Distilled from prior memory — 10 documented failure modes in deployment/promotion/validation phases. Each shaped a design decision in this plan.

| # | Prior incident | Failure pattern | Design choice in this plan |
|---|---|---|---|
| 1 | Ledger stale-row silent no-op — pipeline runs, CSV writes, but spreadsheet rows refuse duplicates and operator sees no error (`feedback_freshness_rerun_ledger_cleanup`) | Silent success | Validator's seq_no protocol (6.5.1) + heartbeat (6.5.4) make staleness explicit. No "ran but didn't update" outcome possible. |
| 2 | Multi-symbol strategy name mismatch — Phase 1 startup fails on `strategy.name == slot.strategy_id` (`feedback_multisymbol_deployment`) | Cross-repo contract enforcement at runtime | Phase 0a ABI runtime assertion (Section 7) follows the same fail-closed pattern. |
| 3 | Removing `atr` field caused 0 trades — `atr` was NOT engine-owned but assumed so (`feedback_engine_owned_fields`) | Immutability violation (false assumption about contract ownership) | ABI manifest enumerates exactly what's exported. No "implicit" engine ownership. |
| 4 | Dry-run skipping `apply_regime_model()` produced 0 signals while looking fine to inspection (`feedback_dryrun_regime_model`) | Validation harness diverged from execution harness | TS_SignalValidator uses `engine_abi.v1_5_9.apply_regime_model` in same order as execution. ABI manifest includes it. |
| 5 | S11/S12 promoted on aggregate PF; reverted on per-symbol inspection (96.1% top-5 concentration) (`feedback_promote_quality_gate`) | Aggregate-metric concealment of per-symbol failure | Decision file's `per_symbol` block (6.5.1) ensures per-leg verdicts, not just basket-level. |
| 6 | Orphan-folder check false-positive flagged 86 legitimate multi-symbol bases (`feedback_orphan_folder_is_multisymbol_base`) | Single-signal check missed coupling across state containers | Vault structure (Section 6.3) uses three-signal detection pattern; TS_SIGNAL_STATE/ is partitioned by vault_id explicitly. |
| 7 | check_entry() schema change not replay-validated; signals diverged silently (`feedback_check_entry_replay`) | ABI-like surface drift without replay equivalence test | Phase 0a byte-identity test + frozen corpus = replay-equivalent gate for every ABI change. |
| 8 | Execution-state classifier fail-closed blocked legitimate variants (`feedback_classifier_execution_state_policy`) | Fail-closed without override path | All fail-closed checks in this plan have explicit override/escalation paths (heartbeat alerts, operator review). |
| 9 | Pre-FSM run folders missing → promote tool fails (`project_promote_blockers`) | Hash/manifest drift from historical state | Frozen corpus + immutable vault means validation cannot operate on incomplete state — fail-closed at the door. |
| 10 | Capital model misalignment between research and execution masked edge failure (`project_deployment_policy_raw_min_lot`) | Cross-repo coupling via implicit configuration | RAW_MIN_LOT_V1 is the locked deployment profile. ABI exposes capital model parameters; no implicit divergence. |

**Meta-pattern recurring across all 10 incidents:** silent success — "the thing ran without error but didn't do what you thought." Architectural response: every contract surface in this plan has an explicit failure signal. No "ran clean but produced nothing" outcomes.

---

## 2. Current Architecture Map

(Unchanged from v6 — directive → planner → engine → portfolio_evaluator → DRY_RUN_VAULT, with target state roots: DRY_RUN_VAULT/immutable, TradeScan_State/mutable-research, TS_SIGNAL_STATE/mutable-validator, VALIDATION_DATASET/immutable-frozen-corpus.)

```
POST-PROMOTION STATE ROOTS (target architecture):

  DRY_RUN_VAULT/         ── immutable promotion artifacts (hash-bound)
  TradeScan_State/       ── mutable research-pipeline outputs
  TS_SIGNAL_STATE/       ── mutable validator outputs                ★ NEW
    decisions/{vault_id}/
    heartbeats/{vault_id}/
    events/{vault_id}/
    summary/{vault_id}/
  VALIDATION_DATASET/    ── immutable frozen corpus, hash-bound      ★ NEW
    {corpus_id}/
      manifest.json
      bars/
  TS_Execution-side logs ── (already exists informally)
```

---

## 3. Risks / Hidden Traps

(Carries forward 3a–3x from v6, adds:)

| # | Risk | Mitigation |
|---|---|---|
| **3y** | **ABI export manifest drift caught only by warning/log = irreversible scope creep** | **Triple-gate CI: pre-commit + CI pipeline + runtime assertion. All three fail-closed.** |
| **3z** | **Validator running on live RESEARCH layer = non-deterministic across data corrections/backfills/schema-checkpoint events** | **Frozen VALIDATION_DATASET/ with manifest.json hash verification at validator startup. Re-runnable forever.** |
| **3aa** | **Silent-success pattern (Section 1n meta-pattern): "ran clean but produced nothing" hides in N corners of the new architecture** | **Every protocol step has an explicit failure signal. No silent skips. No silent no-ops. Cross-checked against the 10 prior incidents.** |
| **3ab** | **Frozen corpus mutation ("fix one bad CSV later") silently invalidates ALL historical validator decisions referencing that corpus** | **Section 1m-i — Corpus Immutability invariant. Filesystem read-only after freeze. Runtime hash verification. CI rejects modifications. ONLY legal change is creating a new version.** |
| **3ac** | **Over-sized corpora become operational baggage; storage scales linearly with strategies × versions** | **Section 1m-ii — Minimal-corpus sizing rule. Freeze only the (symbols × date_range × timeframes) the specific strategy uses. H2 corpus = EURUSD + USDJPY + USD_SYNTH only.** |
| **3ad** | **Naming the ABI v1_5_9 while TS_Execution imports v1_5_3 would create a hidden engine upgrade in Phase 0a (massive scope creep, byte-identity risk across 6 engine versions)** | **Resolved in v11: TS_Execution explicitly migrated to v1_5_9 in Phase 0a with a dedicated boot smoke test (`tests/test_engine_abi_ts_execution_boot.py`); migration was NOT hidden, it was the deliberate work of Phase 0a Step 5. Single ABI on v1_5_9. The dual-ABI provision survives as a policy (Section 5.12) for the moment a future consumer needs a different engine version pinned.** |
| **3ae** | **Symlink or NTFS junction in VALIDATION_DATASET path = silent multi-GB corpus loss when target gets deleted (precedent: 2026-05-07 incident)** | **Section 1m-iii — Junction/symlink prohibition. Native FS tree only. realpath check at validator startup. CI rejects junction-creation in corpus paths.** |

---

## 4. Design Options (recap)

Option C remains recommended (parallel basket orchestrator over v1_5_9 via ABI). Unchanged.

---

## 5. Future-Proofing Provisions

(5.1–5.10 unchanged from v6. 5.11 unchanged: DataFeed abstraction with ReplayDataFeed for Phase 7a, BrokerDataFeed for Phase 8.5.)

### 5.12 ABI versioning policy (NEW — v10, refined — v11)

Multiple engine ABI versions MAY coexist side-by-side. Each consumer pins its own version. The policy is general; the current instantiation happens to use a single ABI (`v1_5_9`) because all consumers converged on it during Phase 0a.

- New engine version → new ABI namespace (`engine_abi/v1_5_10/`, etc.) created alongside existing.
- Each ABI has its own manifest, its own CI gates, its own runtime assertion.
- Promoting a consumer from one ABI version to another = deliberate phase with byte-identity testing.
- Old ABIs retired ONLY when no consumer pins to them. Retirement is itself a deliberate governance action — exactly what plan v11 did to `v1_5_3` (consumer count fell to zero after TS_Execution migration, so the package + manifest + tool plumbing were removed in the same commit).

This pattern absorbs future engine refactors gracefully: each consumer migrates on its own schedule, never forced into a flag day. The single ABI in this plan (`v1_5_9`) is the current state; the policy is the general rule and is enforced by `tools/abi_audit.py --dead-exports` flagging zero-consumer entries.

---

## 6. TS_SignalValidator — New Repo Design

### 6.1–6.2 (unchanged from v6)

### 6.3 Input contract (UPDATED — corpus-bound)

```
input/
├── DRY_RUN_VAULT/{vault_id}/                     ← READ-ONLY; immutable hash-bound vault
│   ├── strategy.py
│   ├── deployable/{PROFILE}/deployable_trade_log.csv   ← reference signal_hash
│   └── meta.json
├── VALIDATION_DATASET/{corpus_id}/               ← READ-ONLY; immutable hash-bound corpus  ★ NEW
│   ├── manifest.json
│   └── bars/                                     ← replay bars for all symbols in scope
└── (for baskets) basket_config                   ← legs, recycle_rule, regime gate
```

All three input sources are hash-bound. Validator output is a pure deterministic function of these.

### 6.4 Output contract (TS_SIGNAL_STATE/, unchanged from v6)

### 6.5 Inter-repo handoff protocol — locked in v6, unchanged in v7

### 6.6 Resolved design decisions

| Question | Decision |
|---|---|
| Live data source? | **Replay first.** Phase 7a uses frozen corpus only. Broker is Phase 8.5. |
| Validator state directory? | **TS_SIGNAL_STATE/** (new state root). |
| Decision-file location? | **TS_SIGNAL_STATE/decisions/{vault_id}/decision.json** — never inside vault. |
| **Replay data source?** | **VALIDATION_DATASET/{corpus_id}/ — frozen, hash-bound, immutable.** ★ NEW |
| **ABI export contract?** | **`governance/engine_abi_manifest.yaml` — structured, CI-enforced at three layers.** ★ NEW |

### 6.7 Open design questions and deferred runbook items

**Design questions (resolve before Phase 7a execution):**

1. **Timing contract.** How long can a strategy sit in BURN_IN? Hard deadline / soft / human-review-after-N days?
2. **Re-validation cadence for LIVE.** Periodic re-check against fresh references?
3. **Corpus refresh policy.** When do you create a `_v2` corpus? After N months of live data accumulation? On a specific governance event?

**Deferred runbook items (out of scope at plan level; resolved during Phase 7a setup):**

These are operational decisions that must be made before TS_SignalValidator goes live, but they are NOT architectural — they don't change the contracts or interfaces in this plan. They live in the operational runbook, not the architecture document.

- **Validator process lifecycle.** How TS_SignalValidator actually starts, stays running, and restarts on crash. Supervisor mechanism (cron / systemd / Windows Task Scheduler / watchdog) is operational choice. The plan assumes a long-lived process exists; the runbook specifies how.
- **Operator alert routing.** All `FAIL-CLOSED + operator alert` flows in this plan emit alerts. Where they go (console log, file, email, push notification, dashboard) is operational choice. Single-operator setup → likely console + log file. Multi-operator → ticketing system. Runbook specifies the channel.

If these are NOT specified in the operational runbook before Phase 7a goes live, the system runs but its safety signals reach nobody. Plan flags them; runbook addresses them.

### 6.8 ABI manifest structure (NEW — locked)

`governance/engine_abi_manifest.yaml`:

```yaml
abi_version: "v1_5_9"
recon_source_commit: "<commit_hash>"        # commit when recon performed
recon_date: "2026-05-13"
recon_doc: "tmp/ABI_RECON.md"               # human-readable rationale
manifest_sha256: "<sha256>"                  # of all fields below
exports:
  - name: evaluate_bar
    source_module: engine_dev.universal_research_engine.v1_5_9.evaluate_bar
    type: function
    consumed_by:
      - TS_Execution.strategy_loader
      - TS_Execution.signal_bridge
    consumer_count: 2                            # derived from len(consumed_by); CI verifies consistency
    last_verified_commit: "<commit_hash>"        # commit at last successful CI verification; CI-maintained
    last_verified_utc: "2026-05-15T12:00:00Z"   # timestamp of last successful verification
  - name: ContextView
    source_module: engine_dev.universal_research_engine.v1_5_9.execution_loop
    type: class
    consumed_by:
      - TS_Execution.signal_bridge
    consumer_count: 1
    last_verified_commit: "<commit_hash>"
    last_verified_utc: "2026-05-15T12:00:00Z"
  - name: apply_regime_model
    source_module: engine_dev.universal_research_engine.v1_5_9.regime_adapter
    type: function
    consumed_by:
      - TS_Execution.signal_bridge
    consumer_count: 1
    last_verified_commit: "<commit_hash>"
    last_verified_utc: "2026-05-15T12:00:00Z"
  # ... (filled in by Phase 0a recon)
```

**Rules:**
- Every export must name at least one `consumed_by` consumer. Orphan exports forbidden.
- `consumed_by` must be a real, verifiable import path in a consumer repo. Phantoms rejected.
- `consumer_count` MUST equal `len(consumed_by)` — CI verifies. Manual edits that miscount are caught.
- `last_verified_commit` is CI-maintained. Each successful CI pass:
  1. Walks each consumer path, confirms the import actually exists.
  2. Updates `last_verified_commit` and `last_verified_utc` for each verified export.
  3. Commits the update via a dedicated `abi-ci-bot` author (separate from human commits in git log).
- New entries require deliberate manifest update (signed commit), which surfaces via the three CI gates.

**Dead-export detection** (audit subcommand on `tools/abi_audit.py`):
- `consumer_count == 0` → dead export candidate (should never happen if manifest is rule-conformant; flagged loudly).
- `last_verified_utc` older than threshold (e.g., 90 days) → stale export candidate; either re-verify or remove.
- Audit report at `tmp/ABI_DEAD_EXPORTS.md` lists candidates; human reviews quarterly.

### 6.9 Validation corpus management (NEW — locked)

**Corpus creation protocol:**

1. Identify **minimal** scope per Section 1m-ii (symbols × date_range × timeframes). Document rationale.
2. Copy from `Anti_Gravity_DATA_ROOT/MASTER_DATA/{SYMBOL}_OCTAFX_MASTER/RESEARCH/` into `VALIDATION_DATASET/{corpus_id}/bars/{SYMBOL}/`.
3. For each file: compute sha256, record in `manifest.json`.
4. Compute cumulative sha256 across all files.
5. Mark `manifest.frozen: true`.
6. **Apply filesystem read-only permissions:** `chmod -R a-w VALIDATION_DATASET/{corpus_id}/`. Verify with `find ... -writable`.
7. Commit manifest path + cumulative hash to a governance tracker.
8. **From this point: corpus is immutable per Section 1m-i. No mutations under any circumstances.**

**Corpus manifest schema (UPDATED — broker reconciliation metadata added):**

```json
{
  "corpus_id": "h2_validator_baseline_v1",
  "created_utc": "2026-05-15T00:00:00Z",
  "source": {
    "broker": "OctaFX",
    "timezone": "UTC",
    "source_dataset_root": "Anti_Gravity_DATA_ROOT/MASTER_DATA/",
    "source_dataset_snapshot_date": "2026-05-15",
    "symbol_aliases": {
      "EURUSD": "EURUSD",
      "USDJPY": "USDJPY",
      "USD_SYNTH": "USD_SYNTH"
    },
    "session_definitions": {
      "weekly_close_utc": "Friday 21:00",
      "weekly_open_utc": "Sunday 22:00",
      "holiday_calendar_ref": "OctaFX_2024_2026"
    }
  },
  "scope": {
    "symbols": ["EURUSD", "USDJPY", "USD_SYNTH"],
    "date_range": {"start": "2024-09-02", "end": "2026-05-09"},
    "timeframes": ["5m", "daily"]
  },
  "files": [
    {"path": "bars/EURUSD/EURUSD_OCTAFX_5m_2024_RESEARCH.csv", "sha256": "...", "bytes": 12345678}
  ],
  "cumulative_sha256": "abc...",
  "frozen": true
}
```

**Why the `source` block matters:**

Phase 8.5 (broker validation) needs to reconcile a live broker feed against this corpus. Without explicit metadata:
- Symbol mismatch (broker "EUR/USD" vs corpus "EURUSD") looks like strategy drift.
- Timezone mismatch (broker local vs corpus UTC) shifts bar timestamps and creates fake signal misses.
- Session boundary differences (broker Friday 22:00 vs corpus 21:00) make weekly-close exits look misfired.

By recording the corpus's normalization assumptions explicitly:
- Broker validator reads `source.symbol_aliases` to translate its feed.
- Broker validator reads `source.timezone` to align timestamps.
- Broker validator reads `source.session_definitions` to interpret session-bounded events.
- Disagreements that remain after this reconciliation are real strategy/feed drift, not naming or clock artifacts.

**Validator startup protocol (binding):**

```
1. Read corpus_id from validator config.
2. Read VALIDATION_DATASET/{corpus_id}/manifest.json.
3. Verify manifest.frozen == true. If false → FAIL-CLOSED.
4. Verify filesystem permissions: every file in the corpus tree must be NOT-writable.
   Any writable file → FAIL-CLOSED + operator alert (corpus has been tampered with).
5. For each file in manifest.files: compute sha256, compare. Mismatch → FAIL-CLOSED + operator alert.
6. Compute cumulative sha256 over all files, compare to manifest.cumulative_sha256. Mismatch → FAIL-CLOSED.
7. ONLY THEN start emitting decisions.
```

**Corpus versioning rule:**

- Corpora are immutable after `frozen: true`. Never modify in-place.
- Extending validation scope → new `corpus_id_v2` created side-by-side. Old corpus kept (audit trail).
- Validator config explicitly names corpus_id. Moving to v2 = config change = deliberate operator action.
- Old corpora kept forever (storage is cheap; audit is priceless).

---

## 7. Revised Migration Phase Map

```
Phase 0a    ABI extraction (recon-first, manifest, triple-gate CI)
Phase 0b    Compatibility audit (read-only)
Phase 1     Schema + namespace + RECYCLE token
Phase 2     basket_runner skeleton (via ABI only)
Phase 3     H2 recycle logic port (pluggable RecycleRule)
Phase 4     Pipeline integration (stage3/4, MPS execution_mode)
Phase 5     First basket directive
Phase 6     Vault packaging for baskets
Phase 7a.0  Freeze validation corpus                                  ★ NEW
Phase 7a    TS_SignalValidator MVP (replay-only, observer)
Phase 7b    Executor shadow-read mode (flag OFF)
Phase 8     Executor gated mode (flag ON)
Phase 8.5   Broker data source (cross-check vs replay)
Phase 9     Matrix extension
Phase 10    LIVE deployment (DEFERRED)
```

### Phase 0a — ABI extraction (recon-first, manifest, triple-gate CI) — single ABI on v1_5_9 (UPDATED v11)

**Outcome (post-v11):** TS_Execution intentionally migrated to `engine_abi.v1_5_9` during Phase 0a, so the original dual-ABI work was collapsed to a single ABI before commit. The historical recon for v1_5_3 is archived but not retained as active governance. Steps below describe the work as actually executed.

**Step 1: Recon (READ-ONLY)**

```bash
# What does TS_Execution import? → drives engine_abi/v1_5_9/ consumer list
grep -rn 'from engine_abi\.v1_5_9'                TS_Execution/
grep -rn 'from engine_dev.universal_research_engine.v1_5_9' TS_Execution/

# What does basket_runner + validator need? → ditto
grep -rn 'from engine_dev.universal_research_engine.v1_5_9' tools/research/
```

Outputs:
- `tmp/ABI_RECON_v1_5_9.md` (human rationale for the unified surface)
- `archive/2026-05-13_phase0a_v1_5_3_retirement/ABI_RECON_v1_5_3.md` (historical — the dual-ABI alternative that was considered and dropped)

**Step 2: Author the manifest**

- `governance/engine_abi_v1_5_9_manifest.yaml` — derived from `ABI_RECON_v1_5_9.md`. Section 6.8 schema. Every export pinned with `consumed_by` reference.

**Step 3: Create the package**

- `engine_abi/v1_5_9/` — re-exports the v1_5_9 manifest list. Thin wrapper around `engine_dev.universal_research_engine.v1_5_9.*` and `engines.*`. NO new code, NO logic, NO restructuring. Re-exports only.

**Step 4: Install triple-gate CI**

1. **Pre-commit hook** (`tools/hooks/pre-commit` → `tools/abi_audit.py --pre-commit`):
   - Block commits that change `engine_abi/v1_5_9/__init__.py` without manifest update.
   - Verify `consumer_count == len(consumed_by)` for every entry.
   - Verify manifest_sha256 matches recomputed hash.

2. **CI pipeline check** (`.github/workflows/abi_audit.yml` → `tools/abi_audit.py --ci`): run on every PR and push to main.
   - Hard-fail on manifest drift.
   - For each export, walk each `consumed_by` path and confirm the import exists in the named consumer (checks both Trade_Scan and TS_Execution sibling checkout).
   - On success: update `last_verified_commit` and `last_verified_utc` via `abi-ci-bot` auto-commit.
   - On any failure: fail-closed.

3. **Runtime assertion** (`engine_abi/v1_5_9/__init__.py`): on import, read manifest, compare `__all__` to declared exports list, fail at import time on mismatch.

4. **Periodic dead-export audit** (`tools/abi_audit.py --dead-exports`):
   - Outputs `tmp/ABI_DEAD_EXPORTS.md` listing orphans (consumer_count==0) and stale entries (last_verified > 90 days).
   - Not fail-closed (informational); feeds governance cleanup. This is what would catch a future `v1_5_3`-style retirement candidate.

All three primary layers fail-closed.

**Step 5: TS_Execution import migration**

`from engines.X import Y` → `from engine_abi.v1_5_9 import Y`.
`from engine_dev.universal_research_engine.v1_5_9.evaluate_bar import Y` → `from engine_abi.v1_5_9 import Y`.

Done in a parallel session; verified by `tests/test_engine_abi_ts_execution_boot.py` (runs in CI via the abi-audit workflow). `harness/replay.py` lost its legacy `v1_5_3 → v1_5_9 ImportError` fallback; the boot test enforces no active `engine_abi.v1_5_3` imports exist in TS_Execution code.

basket_runner (Phase 2+) and TS_SignalValidator (Phase 7a+) import from `engine_abi.v1_5_9` only.

**Step 6: Acceptance tests**

- TS_Execution boots via `engine_abi.v1_5_9` — verified by `tests/test_engine_abi_ts_execution_boot.py` (7 tests).
- Trade_Scan ABI identity verified by `tests/test_engine_abi_v1_5_9.py` (20 tests covering every export's `is`-identity to source module).
- `python tools/abi_audit.py --pre-commit` exits 0 with the manifest declaring all 8 real consumers (`TS_Execution.src.execution_adapter`, `TS_Execution.src.main`, `TS_Execution.src.pipeline`, `TS_Execution.src.strategy_loader`, `TS_Execution.harness.replay`, `Trade_Scan.tests.test_engine_abi_v1_5_9`, `Trade_Scan.tests.test_engine_abi_ts_execution_boot`).
- **Adversarial test:** deliberately add unauthorized export to `engine_abi/v1_5_9/__init__.py` → all three CI layers fail-closed.
- **Adversarial test:** deliberately remove authorized export from manifest while keeping the export in `__all__` → all three CI layers fail-closed.

**Acceptance artifacts published:**
- `tmp/ABI_RECON_v1_5_9.md` (rationale for the unified surface)
- `governance/engine_abi_v1_5_9_manifest.yaml` (machine contract)
- `tools/abi_audit.py` (enforcement tool, `--abi-version v1_5_9`)
- `.github/workflows/abi_audit.yml` (CI gate)
- `tests/test_engine_abi_v1_5_9.py` + `tests/test_engine_abi_ts_execution_boot.py` (identity + boot)
- `archive/2026-05-13_phase0a_v1_5_3_retirement/` (historical recon record + retirement rationale)

**Scope discipline rule (binding):** if a reviewer cannot point to a current `consumed_by` reference that justifies an export, it doesn't go in the ABI. Period.

### Phase 0b — Compatibility audit (unchanged from v6)

### Phase 1 — Schema + namespace + RECYCLE token (unchanged from v6)

### Phase 2–6 (unchanged from v6)

### Phase 7a.0 — Freeze validation corpus (NEW)

**Scope:** create `VALIDATION_DATASET/h2_validator_baseline_v1/` per Section 6.9.

**Initial corpus scope (locked — per Section 1m-ii minimal rule):**
- Symbols: **EURUSD, USDJPY** (the H2 trading legs only).
- Regime factors: **USD_SYNTH** (compression_5d load-bearing; vol/autocorr/stretch included for diagnostic context).
- Date range: **Phase 7a observation window** (specific dates, not full historical range).
- Timeframes: **5m** (primary), **daily** (USD_SYNTH).
- `scope.rationale` documented in manifest.

**Subsequent corpora** (`h2_validator_baseline_v2`, future-strategy corpora) created side-by-side, never in place. Section 1m-i is binding.

**Acceptance gate:**
- Manifest produced, `frozen: true` set, `scope.rationale` populated.
- Cumulative sha256 stable across re-verification runs.
- Filesystem permissions enforce read-only (`chmod -R a-w` applied; verified by `find ... -writable` returning empty).
- `tools/corpus_audit.py` (NEW) verifies manifest integrity in seconds.
- **Adversarial test:** deliberately attempt to modify a corpus file → OS rejects (read-only); pre-commit hook also rejects.

### Phase 7a — TS_SignalValidator MVP (UPDATED — corpus-bound)

**Scope:** new repo at `../TS_SignalValidator/`. Reads frozen corpus. Boots only if corpus hash verifies. Writes to `TS_SIGNAL_STATE/`.

**Inputs (all hash-bound):**
- `DRY_RUN_VAULT/{vault_id}/` (immutable; verified by vault contract)
- `engine_abi/v1_5_9/` (CI-enforced manifest)
- `VALIDATION_DATASET/{corpus_id}/` (frozen corpus manifest)

**Outputs:** TS_SIGNAL_STATE/ tree per protocol 6.5.

**Acceptance gate (≥ 14 calendar days):**
- Validator emits decisions continuously on at least one promoted vault.
- Decision file always present, never stale beyond TTL, no checksum failures, seq_no monotone.
- Heartbeat continuity.
- **Determinism check:** re-running validator over the same corpus on a different day produces byte-identical decisions for the same vault. Any divergence = critical investigation.

### Phase 7b — Executor shadow-read mode (unchanged from v6)

### Phase 8 — Executor gated mode (unchanged from v6)

### Phase 8.5 — Broker data source (unchanged from v6)

### Phase 9–10 (unchanged from v6)

---

## 8. Affected Repos / Modules

| Repo / Path | Module | Change | Phase |
|---|---|---|---|
| Trade_Scan | `tmp/ABI_RECON_v1_5_9.md` (NEW audit artifact) | Recon rationale for the unified v1_5_9 surface (TS_Execution + basket_runner + validator) | 0a |
| Trade_Scan | `archive/2026-05-13_phase0a_v1_5_3_retirement/` (NEW historical record) | Retired v1_5_3 recon doc + retirement rationale (v11) | 0a |
| Trade_Scan | `governance/engine_abi_v1_5_9_manifest.yaml` (NEW) | Machine-readable ABI contract for v1_5_9 | 0a |
| Trade_Scan | `engine_abi/v1_5_9/` (NEW) | Re-exports v1_5_9 surface for ALL consumers | 0a |
| Trade_Scan | `engine_dev/v1_5_9/` | UNCHANGED — ABI re-exports from this | 0a |
| Trade_Scan | `tools/abi_audit.py` (NEW) | Triple-gate enforcement: pre-commit, CI (with last_verified maintenance), runtime; --dead-exports audit subcommand; `--abi-version v1_5_9` (single ABI post-v11) | 0a |
| Trade_Scan | `tools/hooks/pre-commit` | NEW hook entry: `abi_audit.py --pre-commit` (loops over `_SUPPORTED_ABIS`) | 0a |
| Trade_Scan | `.github/workflows/abi_audit.yml` (NEW) | CI step: identity tests + `abi_audit.py --ci`; on-push auto-commit via `abi-ci-bot` | 0a |
| Trade_Scan | `tests/test_engine_abi_v1_5_9.py` (NEW) | 20 identity tests covering every export | 0a |
| Trade_Scan | `tests/test_engine_abi_ts_execution_boot.py` (NEW) | 7 boot-smoke tests asserting TS_Execution actually imports from `engine_abi.v1_5_9` | 0a |
| TS_Execution | imports across `src/main.py`, `src/execution_adapter.py`, `src/pipeline.py`, `src/strategy_loader.py`, `harness/replay.py` | `engines.*` / `engine_dev.universal_research_engine.v1_5_9.*` → `engine_abi.v1_5_9.*` (intentional migration, certified by boot test) | 0a |
| TS_Execution | `portfolio.yaml` | NEW field: `abi_version: v1_5_9` | 0a |
| TS_Execution | `phase0_validation.py` | NEW: ABI assertion at startup (checks v1_5_9) | 0a |
| Trade_Scan | `governance/namespace/token_dictionary.yaml` | Add `RECYCLE` | 1 |
| Trade_Scan | `governance/recycle_rules/registry.yaml` (NEW) | Rule version registry | 1 |
| Trade_Scan | `tools/namespace_gate.py`, `tools/exec_preflight.py` | Multi-leg schema guards | 1 |
| Trade_Scan | `tools/basket_runner.py` (NEW) | Orchestrator; imports ONLY from `engine_abi.v1_5_9` | 2 |
| Trade_Scan | `tools/stage3_compiler.py`, `tools/portfolio_evaluator.py` | Recognize basket runs | 4 |
| Trade_Scan | `strategies/90_RECYCLE_*/` (NEW) | First basket strategy | 5 |
| DRY_RUN_VAULT | vault folder spec | Extension for N-symbol slot | 6 |
| **VALIDATION_DATASET/** (NEW immutable state root, sibling to DRY_RUN_VAULT) | corpus directory tree | `{corpus_id}/manifest.json`, `{corpus_id}/bars/{symbol}/*` | 7a.0 |
| Trade_Scan | `tools/corpus_audit.py` (NEW) | Verifies VALIDATION_DATASET integrity (manifest + filesystem perms + cumulative hash); subcommand `--check-immutability` for CI hook | 7a.0 |
| Trade_Scan | `.pre-commit-config.yaml` | NEW hook: corpus_audit --check-immutability — rejects any modification to frozen corpora | 7a.0 |
| **TS_SIGNAL_STATE/** (NEW mutable state root) | directory tree | `decisions/`, `heartbeats/`, `events/`, `summary/` | 7a |
| **TS_SignalValidator** (NEW REPO) | full repo skeleton | ABI client, ReplayDataFeed bound to corpus, validator core, decision emitter, heartbeat | 7a |
| TS_SignalValidator | `data_feeds/replay.py` | Loads from VALIDATION_DATASET/; verifies manifest hash before yielding bars | 7a |
| TS_SignalValidator | `data_feeds/broker.py` (NEW) | MT5 read-only adapter | 8.5 |
| TS_SignalValidator | `validators/signal_validator.py` | Two-tier signal validation | 7a |
| TS_SignalValidator | `validators/kill_switch.py` | Kill-switch decision logic | 7a |
| TS_SignalValidator | `decision_emitter.py` | Atomic write protocol (6.5.2) | 7a |
| TS_SignalValidator | `heartbeat.py` | 60s heartbeat writer | 7a |
| TS_Execution | `decision_reader.py` (NEW) | Atomic read protocol (6.5.3); reads from TS_SIGNAL_STATE/ | 7b |
| TS_Execution | `config.yaml` | `enable_validator_gating` feature flag | 7b/8 |
| Trade_Scan | LIFECYCLE_PLAN.md | Update: burn-in lives in TS_SignalValidator | 7a |
| Anti_Gravity_DATA_ROOT, DATA_INGRESS | — | NO CHANGE | — |

---

## 9. Migration Risk Table

(Carries forward 0a–10 rows from v6 with additions for 7a.0 and updated 7a inputs.)

| Phase | Touches active? | Risk | Hard validation gate | Mitigation if gate fails |
|---|---|---|---|---|
| 0a | YES (TS_Execution boot) | HIGH — wrong ABI shape; scope creep | Manifest matches exports across all 3 CI layers; adversarial tests fail-closed; 1 directive byte-identical | Revert; delete `engine_abi/` |
| 0b | NO | None | GREEN-LIGHT report | RED-FLAG → spec patch + re-cert |
| 1 | NO | LOW | Existing directives still admit | Revert schema + tokens |
| 2 | NO | LOW | N-leg no-rules basket_runner == N indep runs | Delete basket_runner.py |
| 3 | NO | MEDIUM | Bit-for-bit basket_sim vs basket_runner H2 EUR+JPY × 10 windows | Freeze on basket_sim until closed |
| 4 | NO | MEDIUM | Per-symbol directives unchanged; basket produces expected row | Feature flag; default off |
| 5 | NO | LOW | MPS row matches basket_sim benchmark | Reset directive; investigate diff |
| 6 | NO | MEDIUM | Existing promotions still work; basket vault produced | Revert vault extension |
| **7a.0** | **NO** | **LOW — read-only copy** | **Manifest produced, `frozen: true`, cumulative sha256 stable across 3 verification runs** | **Delete corpus; recreate from source** |
| 7a | NO (executor ignores) | LOW — isolated repo, corpus-bound | ≥14 days clean; heartbeat continuity; **determinism check passes (same corpus → identical decisions over time)** | Discard repo state; iterate |
| 7b | YES (TS_Execution adds reader) | LOW — flag OFF | ≥14 days clean shadow-read; diff log clean | Disable feature flag |
| 8 | YES (validator gates execution) | MEDIUM — first time validator can disable slots | Real decisions correctly enable/disable; auto-escalation on >1 disable in 24h | Single flag flip back to false |
| 8.5 | NO direct execution change | MEDIUM — broker feed adds new failure surface | ≥14 days; disagreements with replay characterized | Disable broker feed; replay-only remains canonical |
| 9 | NO | LOW | Research output only | Park; iterate |
| 10 | YES (eventually) | OUT OF SCOPE | Separate planning pass | N/A |

---

## 10. Rollback Plan

### Pre-merge snapshots (mandatory)

- Before **Phase 0a:** 30-day baseline of all 9 nominal LIVE entries' output.
- Before **Phase 4:** Master_Portfolio_Sheet.xlsx + ledger.db.
- Before **Phase 6:** DRY_RUN_VAULT snapshot.
- Before **Phase 7a.0:** N/A — corpus creation is purely additive.
- Before **Phase 7b:** TS_Execution loop output + portfolio.yaml.
- Before **Phase 8:** confirm `enable_validator_gating: false` default; document flag-flip authorization.

### Per-phase rollback

**Phase 0a:** revert imports; delete `engine_abi/v1_5_9/`; revert manifest; remove CI hooks; restore relocated files. Validate byte-identical baseline.

**Phase 0b:** read-only.

**Phase 1:** revert namespace/token additions.

**Phase 2:** delete basket_runner.py.

**Phase 3:** revert to Phase 2 skeleton.

**Phase 4:** revert stage3/4; restore MPS + ledger.db from snapshot.

**Phase 5:** delete basket strategy folder + MPS row.

**Phase 6:** restore DRY_RUN_VAULT; revert vault contract extension.

**Phase 7a.0 (corpus freeze):** delete corpus directory. No downstream consumers yet exist. Recreate as needed. (Note: corpus is additive; rollback has no effect on anything else.)

**Phase 7a (NEW REPO + state root):** archive repo; `rm -rf TS_SIGNAL_STATE/`. TS_Execution unaffected.

**Phase 7b:** disable feature flag; revert decision_reader integration; restore portfolio.yaml from snapshot.

**Phase 8:** flag flip `true → false`. No code revert.

**Phase 8.5:** disable broker feed in validator config.

### Corpus-specific rollback rule

Frozen corpora are never deleted (except in Phase 7a.0 rollback, where there are no consumers yet). If validator behavior on a new corpus version is unexpected, the rollback is "pin validator config to previous corpus version." This means:
- Multiple corpus versions exist side-by-side (storage cost is trivial).
- Configuration switch is single-line.
- Audit trail preserved: which corpus was used at which date is recorded in every decision file's metadata.

### Universal principles

- Every phase has single-commit (or single-flag) rollback point.
- Phase 0a, 4, 6 require pre-merge snapshots.
- Phase 7a.0 + 7a's new state roots make rollback trivial: archive the repo, delete the directory.
- Phase 8 rollback is config-only flag flip.
- 14-day observation windows are HARD. Validator earns trust before gating execution.

---

## Summary

**Recommended path (v7):** Option C with full determinism stack:

| Layer | Mechanism | Phase |
|---|---|---|
| Strategy code | Vault hash-bound | (existing) |
| Engine code | engine_manifest.json hash-bound | (existing) |
| ABI exports | governance/engine_abi_manifest.yaml + triple-gate CI | 0a |
| Validator code | git-tagged | (standard) |
| Validation corpus | VALIDATION_DATASET/{corpus_id}/manifest.json hash-bound | 7a.0 |

After 0a + 7a.0 land, the validator's output is a pure deterministic function of five hash-bound or version-pinned inputs. Output drift uniquely identifies which input drifted. Attribution is mechanical.

**Architectural improvements through v7 + v8 + v9 + v10:**

1. **ABI export manifest** as structured governance artifact, not free-form markdown.
2. **Triple-gate CI** — pre-commit, CI pipeline, runtime assertion — all fail-closed.
3. **Frozen validation corpus** with cryptographic manifest. Validator startup verifies hash before emitting any decision.
4. **Phase 7a.0** — corpus freeze precedes validator MVP. Validator boots only against a hash-verified corpus.
5. **Historical incident patterns surfaced** (Section 1n) — 10 prior failure modes mapped to design choices.
6. **ABI dead-export detection (v8):** `consumer_count` + `last_verified_commit` + `last_verified_utc` per export. CI maintains them; quarterly audit identifies stale or orphan exports.
7. **Corpus source metadata (v8):** `source.broker`, `source.timezone`, `source.symbol_aliases`, `source.session_definitions` in manifest. Phase 8.5 broker validation reconciles via these fields explicitly.
8. **Corpus immutability invariant (v9):** Section 1m-i — never overwrite, never patch, never replace in-place, never modify manifest, never re-use corpus_id, never delete. Enforced by filesystem permissions + runtime check + CI hook.
9. **Minimal-corpus sizing rule (v9):** Section 1m-ii — freeze only the (symbols × date_range × timeframes) needed for the specific validation task. H2 corpus = EURUSD + USDJPY + USD_SYNTH only.
10. **Single ABI on v1_5_9 (v11; replaces v10 dual ABI):** Section 1l — `engine_abi/v1_5_9/` is shared by TS_Execution + basket_runner + TS_SignalValidator. TS_Execution was intentionally migrated to v1_5_9 during Phase 0a, certified by a dedicated boot smoke test. The dual-ABI option remains the policy for any future second consumer.
11. **ABI versioning policy (v10, refined v11):** Section 5.12 — multiple ABI versions MAY coexist side-by-side; per-consumer migration is a deliberate phase with byte-identity testing; old ABIs retired only when no consumer pins to them. `dead-exports` audit subcommand flags retirement candidates.
12. **Junction/symlink prohibition on VALIDATION_DATASET (v10):** Section 1m-iii — native filesystem only, no `mklink /J`, no `ln -s`, no NTFS reparse points. Enforced by creation-time scan + runtime realpath check + CI hook. Precedent: 2026-05-07 incident.

**Invariants preserved:**
- Invariant #11 (Protected Infrastructure): all modifications plan-+-approval bounded.
- Invariant #27 (Per-Symbol Deployment Contract): unchanged at LIVE level.
- v1_5_9 (all consumers) engine hash: unchanged.

**Human approvals (LOCKED — current state as of v11):**

✅ Phase 0a (recon-first, manifest, triple-gate CI) — built and verified
✅ TS_Execution migration to v1_5_9 — deliberate, certified by boot smoke test
✅ Single ABI on v1_5_9 (v11; replaces v10 dual ABI after migration eliminated the second consumer)
✅ TS_SignalValidator carve-out (separate repo)
✅ Handoff protocol (Section 6.5) as binding spec
✅ 7a → 7b → 8 phasing with ≥14-day observation windows
✅ Replay-first data source (Phase 8.5 for broker)
✅ TS_SIGNAL_STATE/ as new mutable state root
✅ VALIDATION_DATASET/ as new immutable state root, Phase 7a.0 corpus freeze
✅ Future-proofing provisions in Section 5
✅ `RECYCLE` as new model token
✅ Junction/symlink prohibition on VALIDATION_DATASET (v10)
✅ Operational concerns deferred to runbook (v10): validator process lifecycle, alert routing

**Open items resolved during Phase 7a setup, not before plan execution:**

- Timing contract for BURN_IN
- LIVE re-validation cadence
- Corpus refresh policy
- Operational runbook items (process supervisor, alert routing)

---

## LOCK NOTICE

This plan is locked as executable architecture as of v10 (2026-05-13).

No further architectural revisions before Phase 0a execution. Operational details (Section 6.7 deferred runbook items) resolved during phase setup, not before.

The plan respects:
- Invariant #11 (Protected Infrastructure): all modifications plan-+-approval bounded.
- Invariant #27 (Per-Symbol Deployment Contract): unchanged at LIVE level.
- 29 invariants in AGENT.md
- 10 historical incident patterns (Section 1n)
- Source vs state separation
- Determinism stack (5 hash-bound/version-pinned input layers)
- Single-responsibility carve across three repos
- Failure-isolation between repos

Implementation begins at Phase 0a recon. No code changes were made during planning.

---

*Plan document v10 — LOCKED. No code changes were made during planning. All changes remain on paper until each phase receives its own implementation approval per Invariant #11.*
