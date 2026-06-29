# Replay Admission — Second Admission Path into the Governed Pipeline

**Status:** FROZEN v1 (2026-06-29) — design approved to implement. Build proceeds atomically Phase 0→4
with a per-phase break-test and the global "directive path byte-identical" regression gate
(Protected Infrastructure, Invariant #6).
**Date:** 2026-06-29
**Author context:** surfaced by the legacy CORE/RESERVE re-validation arc (F6 schema-drift block), but
scoped as a **permanent, general capability** — NOT a legacy hack.

---

## 1. Principle

There is **one governed pipeline**. Today it has one front door (Directive Admission). This adds a
**second front door — Replay Admission** — into the *same* pipeline. After admission, there is **zero
difference**: one execution engine, one reporting system, one grading system, one ledger, one FSP, one
promotion path.

It is **not** "injection" (which implies bypassing safeguards). The pipeline does not ask *"can I
inject this?"* — it asks **"Is this a valid, executable experiment?"** If yes, admit it. The Admission
Contract IS the safeguard; replay satisfies it by a different route, it does not bypass it.

```
   Source:  Directive | Replay | Legacy | Future
                        │
                        ▼
                AdmissionProvider        (one contract; canonicalize+provision  OR  verify+resolve)
                        │
                        ▼
              ExperimentContext          (immutable; fully materialized before any stage runs)
                        │
                        ▼
                  StageRunner            (Stage 1 → 4 — the single execution pipeline)
                        │
                        ▼
          Reports · FSP · Ledger · Promotion
```

**No legacy-specific code.** We build `ReplayAdmission`, not `LegacyReplayPipeline`. Every future
experiment automatically becomes replayable. Today's research benefits immediately; nothing changes in
five years.

**Materialization invariant.** An admission provider **never executes source artifacts directly** — it
always materializes an immutable `ExperimentContext` *before* `StageRunner` begins. Every path therefore
has byte-for-byte identical execution semantics; admission only differs in *how* the context is built,
never in *what* runs.

---

## 2. The Admission Contract

Both paths converge on one **minimal** contract — *"is this a valid executable experiment?"* — before
`run_state.json` is created and Stage 0 is entered.

**Key distinction: `strategy.py` defines the *strategy*; it does not define the *experiment*.** An
experiment = strategy × **experiment-config** {symbols, broker, timeframe, start/end, cost model}. A
directive historically bundled (1) **signature blocks** that *provisioned* `strategy.py` — **redundant
at replay**, since `strategy.py` already holds them as `STRATEGY_SIGNATURE` + the real
`prepare_indicators/check_entry/check_exit` code; and (2) the **experiment-config** — the only
execution-critical part not in `strategy.py` (warmup is resolved from the strategy's own indicators).

**Minimal contract:**

| | Item | Notes |
|---|---|---|
| **Required** | `strategy.py` | valid `STRATEGY_SIGNATURE` markers — the compiled authority |
| **Required** | an **experiment definition** | symbols/broker/tf/window/cost — see normalization below |
| **Required** | indicators resolve | the strategy's `indicators.*` imports resolve against the live registry |
| Optional | `directive.txt` | provenance only — not executed, not re-canonicalized |
| Optional | original `run_id` | provenance / supersession link |
| Optional | original hashes | provenance / reproduction check |

The contract requires an **experiment *definition*, not a particular file.** It is normalized into a
single internal `ExperimentConfig` from any of three sources (recorded as `experiment_source`), in order:

1. **`experiment.json`** (when replaying a bundle),
2. **explicit CLI args** (`--symbols ... --start ... --end ... [--broker --tf]`),
3. **recovered from artifacts** (`batch_summary_*.csv` → symbols; `freshness_index.json` → window;
   broker default).

This removes any coupling to a file: "only `strategy.py`, no directive, no `experiment.json`" is a
**first-class supported case** — supply the definition via CLI (or let it be recovered). If none can
produce an `ExperimentConfig`, the contract fails loudly — a genuinely undefined experiment, not a
missing-file problem.

Only after the required items pass does either path call `PipelineStateManager.initialize()` and enter
Stage 0. **Replay deliberately skips canonicalization + provisioning** — `strategy.py` IS the compiled
authority; re-canonicalizing a byte-faithful legacy directive is exactly what fails on schema drift, and
re-provisioning risks behavior drift.

---

## 3. Experiment Bundle (immutable)

Formalizes what completed runs already contain (extends the existing **Execution Capsule Contract** /
`DIRECTIVE_SOURCE.txt` — `governance/SOP/EXECUTION_CAPSULE_CONTRACT.md`; do not duplicate, extend).

```
ExperimentBundle/
  strategy.py       # REQUIRED — the compiled authority (byte-immutable)
  experiment.json   # REQUIRED — symbols, broker, timeframe, start/end, cost_model, capital_profile (optional)
  directive.txt     # OPTIONAL — original directive, byte-preserved (PROVENANCE only; not executed)
```

`strategy.py` + `experiment.json` are the execution-critical members; `directive.txt` is
provenance-optional (a lost or schema-stale directive does not block replay).

> **CORRECTION (2026-06-29, supersedes the original "indicators resolve against live registry" line):**
> live resolution is **not** faithful — an indicator whose logic/params change later silently alters a
> replayed result. The bundle MUST carry **indicator provenance** (an `indicators_manifest.json` of
> module-id + content-hash, plus source copies for reproduction), and the contract must **verify
> indicators against the snapshot and fail loud on drift** — not resolve against live. Tracked as a chip
> task; full rationale: `outputs/system_reports/08_pipeline_audit/INDICATOR_SNAPSHOT_GAP_2026-06-29.md`.

**`experiment.json` is a first-class run artifact, not a replay add-on.** Every completed pipeline run
— directive-authored or replay — **MUST emit `experiment.json`** as part of normal Stage-completion
(alongside `run_metadata.json` / `STRATEGY_CARD.md`). This makes replay a **permanent property of the
system** rather than a legacy-recovery feature: every run is, by construction, a replayable bundle the
moment it finishes. (Phase 4 adds only the one-shot backfill for *pre-existing* runs.)

The bundle is the immutable unit of replay; Replay Admission consumes exactly one.

---

## 4. Architecture — one downstream, selected by an Admission Provider

The seam already exists. `run_single_directive` (`tools/run_pipeline.py:1708`):

```
verify_directive_uniqueness_guard(...)
_try_basket_dispatch(...)                       # basket front door (already a 2nd-path precedent)
ctx = BootstrapController.prepare_context(...)   # STAGE 0 (admission + provision) → ExperimentContext
StageRunner(ctx).run()                           # COMMON PIPELINE (Stages 1-4, reports, FSP, ledger)
```

The boundary is the **`ExperimentContext`** (today's `PipelineContext` — the immutable, fully-materialized
context `StageRunner` consumes). **Do not branch with if/else.** Define an `AdmissionProvider` interface —
`prepare_context(...) -> ExperimentContext` — with implementations selected once at the entry point:

```
provider = select_admission_provider(source)        # DirectiveAdmission | ReplayAdmission | (future)
experiment_ctx = provider.prepare_context(source)   # materialized + immutable BEFORE any stage runs
StageRunner(experiment_ctx).run()                   # exactly one downstream pipeline
```

- `DirectiveAdmission.prepare_context` = today's `BootstrapController` (canonicalize + provision), wrapped
  unchanged.
- `ReplayAdmission.prepare_context` = verify the minimal contract → normalize the experiment definition to
  `ExperimentConfig` → register provenance → `PipelineStateManager.initialize` → per-symbol
  run_ids/dirs/snapshots → `ExperimentContext`.

Per the materialization invariant (§1), neither provider hands raw source artifacts to `StageRunner` —
both produce a complete `ExperimentContext` first, so downstream semantics are identical.

Reused as-is (zero changes downstream of Stage 0): `StageRunner` + the whole `STAGE_REGISTRY` (Stage 1
already loads an existing `strategy.py` via `run_stage1.load_strategy`), Stage-2 (`AK_Trade_Report.xlsx`),
Stage-3 (`master_filter` + `filter_strategies` → **FSP grades**), capital wrapper, research index,
promotion. `PipelineStateManager` (`initialize`/`transition_to`/`verify_state`) reused verbatim — this is
what eliminates the manual `run_state` backfill done by hand in batch 1.

Reused for the contract verifier: `pre_execution._extract_signature_from_strategy`, the indicator
registry resolver, the engine-ABI loader. The basket path (`_try_basket_dispatch`) is precedent for a
non-directive route to an `ExperimentContext`; `AdmissionProvider` generalizes that precedent cleanly.

---

## 5. Provenance & audit (the safeguard, not a bypass)

Every replay run records, in `run_metadata.json` + the ledger row: `admission_kind = REPLAY`,
`experiment_source` (experiment.json | recovered | explicit), `source_strategy_hash`, `replay_reason`
(audited), `engine_version` (replay-time), and — when present — `original_run_id` / `directive_hash` /
`original_engine_version`. Replay runs are first-class but **distinguishable** from directive-authored
runs for audit/query. Append-only + artifact-authority + fail-fast invariants are untouched (replay only
changes how the `ExperimentContext` is built, never how results are produced or gated downstream).

---

## 6. Phased implementation (atomic, plan-first + break-test per phase)

**v1 target:** Replay Admission → existing `StageRunner`, working end-to-end. No new bundle types, no new
replay modes, no new pipeline stages.

- **Phase 0 — Contract module (read-only).** `replay_admission/contract.py`:
  `verify_experiment(strategy_dir, experiment=None) -> ContractResult`, including the experiment-config
  resolver (experiment.json → recover from `batch_summary`/`freshness` → explicit args). Pure validation,
  no writes. Unit tests over good/bad inputs incl. the "strategy.py only" case. *No pipeline change.*
- **Phase 1 — Bundle spec + loader.** `ExperimentBundle` (strategy.py + experiment.json required;
  directive.txt optional) + loader; reconcile with the Execution Capsule Contract. Tests.
- **Phase 2 — AdmissionProvider + ReplayAdmission.** Introduce the `AdmissionProvider` interface; wrap
  today's bootstrap as `DirectiveAdmission` (no behavior change); implement
  `ReplayAdmission.prepare_context` (contract → experiment-config → provenance →
  `PipelineStateManager.initialize` → `ctx`). Entry point selects the provider; `StageRunner(ctx).run()`
  unchanged. CLI: `run_pipeline.py --replay <bundle> [--symbols ... --start ... --end ...]`.
  **Break-tests:** (a) replay a known directive-run with its original experiment-config → byte-identical
  Stage-1 results + same ledger/FSP row; (b) replay a `strategy.py`-only bundle with explicit args →
  completes end-to-end with provenance recorded.
- **Phase 3 — Provenance plumbing.** `admission_kind` + provenance fields through run_metadata → ledger →
  FSP → research index. Tests assert directive runs are byte-unchanged (no regression).
- **Phase 4 — `experiment.json` as a first-class run artifact.** Wire `experiment.json` emission into
  Stage-completion for **all** paths (directive + replay), alongside `run_metadata.json` — so every new
  run is, by construction, a replayable bundle. Plus a one-shot backfill for pre-existing runs (mirroring
  `backfill_run_directives.py`). After this, replay is a permanent system property, not a recovery step.

**Global regression gate:** the entire directive path must be byte-identical before/after (existing
`tests/` + a golden directive run hash). Replay is additive; it must not perturb the directive door.

---

## 7. Capabilities unlocked (why this is permanent infra, not a one-off)

- **Legacy replay** — the F6/F5 situation, cleanly, with FSP rows.
- **Scientific reproducibility** — re-run any archived experiment exactly, months later.
- **Audit** — a questioned published strategy is replayed bit-for-bit.
- **Disaster recovery** — lost directives don't matter if the bundle exists.
- **Engine-upgrade regression** — replay N historical bundles after an engine bump, diff outputs. This
  is high-value automated regression testing the system currently lacks.

---

## 8. Risks / guardrails

- **Not a bypass:** the Admission Contract is mandatory; replay satisfies it, doesn't skip it. Document
  this explicitly so "replay" is never read as "ungated."
- **Idempotency / overwrite:** replay run_ids are deterministic (directive+engine+symbol); a replay that
  collides with an existing run must supersede-or-refuse, never silently overwrite (reuse rerun-backtest
  supersession discipline).
- **Engine-ABI mismatch:** if a bundle's engine ABI can't load under the current engine, the contract
  fails loudly (no silent fallback — cf. the v1_5_6 silent-fallback incident).
- **Indicator drift:** if a bundled indicator no longer exists/changed, contract fails with the exact
  module id (don't run a half-resolved strategy).
- **Scope discipline:** zero Stage 1-4 changes; no legacy-specific branches anywhere downstream of
  Stage 0.

---

## 9. Non-goals

- Not changing Directive Admission behavior.
- Not modifying the execution engine, reporting, grading, or ledger schemas (only adding provenance
  fields).
- Not a legacy-only tool.
- **v1 scope is fixed:** Replay Admission → existing `StageRunner` only. No new bundle types, no new
  replay modes (no fidelity-mode taxonomy), no new pipeline stages. Anything else layers on later, and
  only if it proves necessary — get the minimal path working first.
