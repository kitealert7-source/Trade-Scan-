# Promotion Pipeline Friction Audit

**Date:** 2026-04-12
**Scope:** End-to-end flow from directive creation through backtest execution to burn-in promotion
**Trigger:** Attempted promotion of CORE strategies from MPS + FSP revealed multiple friction points and process gaps
**Status:** AUDIT ONLY -- no code changes

---

## Executive Summary

The directive-to-promotion pipeline has **8 structural friction points** that make promotion unreliable for agents and operators. The root causes are:

1. **No unified strategy discovery** -- run_id resolution depends on `run_state.json` files that may not exist for older runs, with no fallback
2. **Composite portfolios (PF_*) have no promotion path** -- they achieve CORE status but the promote tool hard-gates on `strategy.py`
3. **Quality gates are applied inconsistently** across entity types (single strategies vs multi-symbol portfolios vs composites)
4. **Post-pipeline artifacts are non-blocking** -- the directive reaches PORTFOLIO_COMPLETE before capital profiles are generated, creating incomplete promotion artifacts
5. **strategy.py authority copy lost during iterative research** -- the provisioner creates strategy.py before backtest and Stage 1 snapshots it to `runs/{run_id}/strategy.py` (write-once). But during sweeps, agents delete/overwrite old pass folders. The promote tool only checks the authority path, never the surviving run snapshot. **41 directives and 4 CORE candidates affected.**
5b. **Per-symbol strategy.py sync is manual** -- multi-symbol strategies require folder creation + sync before promotion
6. **Edge metrics are misapplied** -- `edge_quality` (mean(R)/stdev(R)) gates the WATCH classification for single-asset composites even though it was designed for multi-asset portfolios only
7. **Two classification systems with different criteria** -- `filter_strategies.py` (per-symbol) and `portfolio_evaluator.py` (composite) use different gates and thresholds

---

## Friction Point 1: Strategy & Run Discovery

### The Problem

`find_run_id_for_directive()` (`tools/pipeline_utils.py:288-304`) has exactly one resolution strategy: linear scan of all `TradeScan_State/runs/*/run_state.json` matching on `directive_id`. No fallback.

### What Breaks

| Scenario | Cause | Impact |
|----------|-------|--------|
| Pre-FSM strategies | Runs created before FSM system; no `run_state.json` exists | Promote aborts: "No completed pipeline run found" |
| Cleaned-up runs | `lineage_pruner.py` or manual cleanup deleted run folders | Same abort -- Master Filter still has run_id but folder is gone |
| Multi-symbol ambiguity | Multiple runs share same directive_id; returns arbitrary first match | Vault_id is non-deterministic across promote retries |

### Evidence

- **104 orphaned run_id references** across directive_state.json files point to deleted folders
- **S09_V1_P00**: 7-symbol portfolio, all 7 run folders missing from disk. Master Filter has run_ids but none resolve.
- **S07_V1_P03**: Similarly missing

### Unused Fallback Data

| Source | Has run_id? | Consulted by `find_run_id_for_directive`? |
|--------|-------------|------------------------------------------|
| `runs/{DIRECTIVE_ID}/directive_state.json` → `run_ids[]` | YES | NO |
| `Strategy_Master_Filter.xlsx` → `run_id` column | YES | NO |
| `backtests/{ID}_{SYM}/metadata/run_metadata.json` | YES (but no `directive_id` back-reference) | NO |

### Recommendation

Add fallback chain to `find_run_id_for_directive()`:
1. Primary (current): scan `run_state.json` files
2. Fallback 1: check `directive_state.json` → `run_ids` array
3. Fallback 2: read `run_id` from Master Filter
4. Add `current_state` validation -- only return COMPLETE runs

---

## Friction Point 2: Composite Portfolio (PF_*) Promotion is Blocked

### The Problem

PF_ composites achieve CORE status in the Master Portfolio Sheet but **cannot be promoted**. The promote tool has three hard gates that all fail for composites:

| Gate | Location | Why It Fails for PF_ |
|------|----------|---------------------|
| `strategy.py` exists | `promote_to_burnin.py:266-269` | PF_ composites have no strategy.py -- they're aggregations |
| `find_run_id_for_directive(strategy_id)` | `promote_to_burnin.py:447-452` | PF_ composites don't have a single directive/run |
| `BACKTESTS_DIR.glob(f"{strategy_id}_*")` | `promote_to_burnin.py:103-113` | No backtest folders named `PF_XXXX_*` |

### No Defined Workaround

The workflow document (`promote.md`) does not address composites. The implicit workaround requires:

1. Read `constituent_run_ids` from MPS (comma-separated string)
2. Trace each run_id to its source strategy ID via `run_metadata.json`
3. Verify each constituent independently reached PORTFOLIO_COMPLETE
4. Promote each constituent individually via `promote_to_burnin.py`
5. Hope all constituents are independently viable (they may not be)

### The Composite Quality Masking Problem

Documented incident (promote.md:53-57): `PF_0C0C974A75F7` showed PF 1.73 with zero negative rolling windows, but two of three components had 96% and 51% top-5 concentration respectively. The composite looked strong only because one strategy carried all weight.

### Recommendation

Two options:
- **Option A (simple)**: Document the "promote individual constituents" workflow explicitly. Add a `decompose_portfolio` utility that traces PF_ → constituent strategy IDs.
- **Option B (better)**: Add `--composite` flag to promote tool that auto-decomposes and promotes constituents, with per-constituent quality gates.

---

## Friction Point 3: Quality Gate Inconsistency Across Entity Types

### Three Classification Systems

The pipeline has three independent classification systems with different criteria:

| System | Entity Type | Where | Key Gates |
|--------|-------------|-------|-----------|
| `filter_strategies.py` | Per-symbol rows from Master Filter | `Filtered_Strategies_Passed.xlsx` | SQN >= 2.5 CORE, PF >= 1.25, trade_density >= 50, max_dd <= 30% |
| `portfolio_evaluator.py` (Portfolios tab) | Multi-symbol composites | `Master_Portfolio_Sheet.xlsx` | edge_quality >= 0.12 CORE, >= 0.08 WATCH |
| `portfolio_evaluator.py` (Single-Asset tab) | Single-symbol composites | `Master_Portfolio_Sheet.xlsx` | SQN >= 2.5 CORE, >= 2.0 WATCH |
| `promote.md` (manual) | Individual trades | Agent/operator pre-check | edge_ratio (MFE/MAE), top-5 concentration, flat %, PF-5% |

### The `edge_quality` vs `edge_ratio` Confusion

These are **different metrics** with confusingly similar names:

| Metric | Formula | Used Where |
|--------|---------|-----------|
| `edge_quality` | `mean(R) / stdev(R)` (normalized edge, SQN without sqrt(N)) | Portfolio evaluator -- Portfolios tab quality gate |
| `edge_ratio` | `avg_MFE / avg_MAE` (Van Tharp trade-level metric) | Manual promote quality gate in `promote.md` only |

Neither is automatically enforced at promote time. The promote tool only checks expectancy (per asset class).

### The WATCH Classification Bug (Single-Asset)

In `_compute_portfolio_status()` (`portfolio_evaluator.py:1283-1291`):

```python
# WATCH gate
if eq is not None:               # line 1285 -- edge_quality
    return "WATCH" if eq >= 0.08 else "FAIL"
elif sq is not None:             # line 1288 -- SQN (DEAD CODE)
    return "WATCH" if sq >= 2.0 else "FAIL"
```

Both `edge_quality` and `sqn` are always computed (defaulting to 0.0), so both are always non-None. The `eq is not None` check at line 1285 **always fires first**, even for Single-Asset entries where `sqn` should be the governing metric (per the tab's column schema).

**Impact:** A single-asset strategy with `sqn=3.0` but `edge_quality=0.05` would be classified FAIL instead of WATCH. The SQN WATCH branch is effectively dead code when both metrics are populated.

**Note:** The CORE gate (`portfolio_evaluator.py:1270-1281`) uses `if/if` (not `if/elif`) so both paths are checked and either can independently trigger CORE. The WATCH gate uses `if/elif` which creates the dead code issue.

### Recommendation

1. Fix WATCH gate: route Single-Asset entries through SQN check, Portfolios entries through edge_quality check -- mirror the CORE gate logic
2. Add the entity type (tab identity) as a parameter to `_compute_portfolio_status()` so it knows which metric to apply
3. Consider automating the manual quality gate (edge_ratio, top-5, flat %, PF-5%) in the promote tool

---

## Friction Point 4: Post-Pipeline Artifacts Are Non-Blocking

### The Problem

The directive reaches PORTFOLIO_COMPLETE **before** capital profiles are generated:

```
Stage 7 (PORTFOLIO stage):
  portfolio_evaluator.py      → ledger write          → BLOCKING
  ↓
  directive FSM → PORTFOLIO_COMPLETE                   ← THIS TRANSITION (line 182, stage_portfolio.py)
  ↓
  capital_wrapper.py (Step 8)  → deployable/ artifacts → NON-BLOCKING (warn only)
  profile_selector.py (Step 8.5) → profile enrichment  → NON-BLOCKING (warn only)
  deployable_verification.py (Step 9) → validation     → NON-BLOCKING (warn only)
```

If Step 8 or 8.5 fails, the directive is still PORTFOLIO_COMPLETE but:
- `strategies/{ID}/deployable/` may be missing or incomplete
- The promote tool doesn't gate on deployable artifacts
- But TS_Execution needs them

### Additional Gap

`filter_strategies.py` (which creates `Filtered_Strategies_Passed.xlsx`) only runs in **batch mode** (`run_pipeline.py --all`). Single-directive mode (`run_pipeline.py <ID>`) does not call it. A strategy can be PORTFOLIO_COMPLETE but not yet appear in the candidate ledger.

### Recommendation

Either make Step 8/8.5 blocking (abort pipeline if they fail), or add explicit deployable artifact check to `promote_to_burnin.py`.

---

## Friction Point 5: strategy.py Authority Copy Lost During Iterative Research

### The strategy.py Lifecycle

```
1. PROVISION (strategy_provisioner.py:389-409)
   Directive parsed → Trade_Scan/strategies/{name}/strategy.py CREATED
   Human reviews & approves (strategy.py.approved marker)
                ↓
2. SNAPSHOT (stage_symbol_execution.py:101-109)
   Copies authority → TradeScan_State/runs/{run_id}/strategy.py (WRITE-ONCE)
                ↓
3. VERIFY (stage_symbol_execution.py:481-509)
   After backtest, verifies snapshot == source (hash match)
                ↓
4. ITERATIVE RESEARCH
   Agent creates next pass → OVERWRITES or DELETES old authority folder
   Old run snapshot SURVIVES (write-once, never touched)
                ↓
5. PROMOTE TIME
   promote_to_burnin.py:266 checks ONLY Trade_Scan/strategies/{id}/strategy.py
   → ABORT: "strategy.py not found" (even though snapshot exists in runs/)
```

### The Problem

The promote tool (`promote_to_burnin.py:266-269`) has a **single lookup path**:
```python
base_spy = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
if not base_spy.exists():
    print(f"[ABORT] strategy.py not found: {base_spy}")
    sys.exit(1)
```

It never falls back to the write-once snapshot at `TradeScan_State/runs/{run_id}/strategy.py`, even though:
- The snapshot was created by the pipeline itself (Stage 1)
- It was hash-verified against the source at Stage 3
- It is immutable (never modified after creation)
- 431 of 435 runs have this snapshot

### Scale of the Problem

- **41 unique directives** have strategy.py in run snapshots but NO authority copy in `Trade_Scan/strategies/`
- **75 rows** in the Master Filter have no strategy.py at base or per-symbol level
- **4 of 12 CORE** candidates in `Filtered_Strategies_Passed.xlsx` have no strategy.py

Root cause: during sweep iteration (multiple passes of the same family), agents create new passes and the old authority folders get deleted or superseded. The run snapshots survive but the promote tool can't find them.

### Recommendation

1. **Add snapshot fallback to `_validate_strategy_files()`**: if authority copy missing, locate via `find_run_id_for_directive()` → `runs/{run_id}/strategy.py`, and auto-recover to authority location
2. **Prevent authority deletion during sweeps**: flag strategies that have PORTFOLIO_COMPLETE or IN_PORTFOLIO status as protected from deletion
3. **Add recovery command**: `python tools/recover_strategy.py {ID}` that finds the snapshot and restores the authority copy

---

## Friction Point 5b: Multi-Symbol Strategy.py Sync is Manual

### The Problem

The promote tool requires per-symbol `strategy.py` files:

```
strategies/22_CONT_FX_1H_RSIAVG_TRENDFILT_S09_V1_P00/strategy.py          ← base (exists)
strategies/22_CONT_FX_1H_RSIAVG_TRENDFILT_S09_V1_P00_EURUSD/strategy.py   ← per-symbol (must create)
strategies/22_CONT_FX_1H_RSIAVG_TRENDFILT_S09_V1_P00_GBPUSD/strategy.py   ← per-symbol (must create)
...
```

Current process:
1. Manually create each per-symbol folder: `mkdir -p strategies/{ID}_{SYMBOL}/`
2. Run `python tools/sync_multisymbol_strategy.py {ID} SYM1 SYM2 ...`
3. `sync_multisymbol_strategy.py` refuses to create folders (line 81-83) -- will only copy into existing ones
4. Operator must know the symbol list (from Master Filter or backtest folders)

### Why This Exists

The Multi-Symbol Deployment Contract (memory: `feedback_multisymbol_deployment.md`) requires per-symbol `strategy.py` with `name` field matching `{ID}_{SYMBOL}`. This is architecturally correct for TS_Execution (each slot loads its own strategy.py).

### Recommendation

- Make `sync_multisymbol_strategy.py` auto-create folders (remove the hard gate)
- Or: integrate sync into `promote_to_burnin.py` as an automatic pre-step when multi-symbol is detected
- Auto-detect symbols from backtest folders or Master Filter (already available via `_detect_symbols()`)

---

## Friction Point 6: Single-Asset Strategies Skip Portfolio Evaluation

### The Problem

In `stage_portfolio.py` (lines 91-95), the `is_multi_asset` gate skips `portfolio_evaluator.py` entirely for single-symbol strategies. This means:

- `strategies/{ID}/portfolio_evaluation/` may not exist
- The MPS may not have a row for this strategy
- But the promote workflow lists `portfolio_evaluation/` as a pre-condition

Single-symbol strategies still get capital profiles (Step 8) and filter classification, but the MPS quality gate path is only exercised for multi-symbol portfolios.

### Impact

A single-symbol XAUUSD strategy can reach PORTFOLIO_COMPLETE, get CORE status in `Filtered_Strategies_Passed.xlsx`, but have no `portfolio_evaluation/` folder. The promote tool checks for this folder and aborts.

### Recommendation

Either:
- Remove the `portfolio_evaluation/` pre-check from promote for single-symbol strategies
- Or ensure `portfolio_evaluator.py` always runs (even for single-symbol), creating the folder

---

## Friction Point 7: No Automated Quality Gate at Promote Time

### The Problem

The 6-metric manual quality gate from `promote.md` is entirely manual:

| Metric | Automated? | Where Checked |
|--------|-----------|---------------|
| Top-5 trade concentration | NO | Manual Python snippet |
| PF without top 5% wins | NO | Manual |
| Flat period % | NO | Manual |
| Edge ratio (MFE/MAE) | NO | Manual |
| Trade count | NO | Manual (though promote tool checks expectancy) |
| PF minus top 5% all trades | NO | Manual |

The promote tool enforces only:
- Expectancy >= asset-class floor
- Per-symbol expectancy gate (multi-symbol)
- `run_state.json` exists
- `strategy.py` exists
- Not already in `portfolio.yaml`

### Impact

A strategy can be promoted even if it would HARD FAIL the quality gate. The gate relies entirely on the operator remembering to run the manual check first.

### Recommendation

Integrate the 6-metric quality gate into `promote_to_burnin.py` as an automated `--quality-gate` check (or make it the default with `--skip-quality-gate` override for operator discretion).

---

## Cross-Reference with Existing Audit Documents

### DEPLOYMENT_UNIFICATION_PLAN.md (2026-04-03)

- Phase 1 (vault extension): DONE -- vault now has full snapshots
- Phase 2 (runtime safety / guard wiring): NOT DONE -- accepted deferred risk
- Phase 3 (promotion flow): PARTIALLY DONE -- vault is mandatory but quality gate is manual
- Phase 4 (dead code removal): NOT DONE -- `generate_golive_package.py` still exists
- Phase 5 (verification tests): NOT DONE -- `validate_safety_layers.py` still broken

**Key gap from unification plan still open:** Guard integration (signal verification, kill-switch) not wired into TS_Execution. This was noted as accepted risk during burn-in observation phase.

### LIFECYCLE_PLAN.md (2026-04-10)

- Phase 1-5: IMPLEMENTED
- Phase 3.3 (`burnin_monitor --json`): DEFERRED
- Phase 6 (consistency guarantees): OPERATIONAL

**Traceability chain is solid:** `strategy_ref.json` → `Trade_Scan/strategies/{ID}/strategy.py` → vault snapshot. The gap is in getting TO the promote step, not in what happens after.

### GOLIVE_PACKAGE_COMPATIBILITY_AUDIT.md (2026-04-10)

- Option B (merge go-live into vault) was PARTIALLY IMPLEMENTED
- Broker specs, selected_profile.json, signal hashes: DONE
- Guard wiring: NOT DONE
- Current deployment path: `portfolio.yaml` direct, no runtime guard

---

## Full Issue Registry

### Pipeline Friction (from audit)

| ID | Issue | Severity | Effort |
|----|-------|----------|--------|
| F1 | `find_run_id_for_directive` has no fallback -- old runs can't promote | HIGH | 2-3h |
| F2 | PF_ composites have no promotion path | HIGH | 4-6h |
| F3 | WATCH classification bug (edge_quality vs SQN routing in `_compute_portfolio_status`) | MEDIUM | 1h |
| F4 | Post-pipeline artifacts (Step 8/8.5) non-blocking -- deployable/ may be incomplete | LOW-MEDIUM | 1h |
| F5 | strategy.py authority lost during sweeps -- 41 directives, 4 CORE candidates affected | HIGH | 2-3h |
| F5b | Multi-symbol strategy.py sync is manual (folder creation + symbol list) | MEDIUM | 1-2h |
| F6 | Single-asset strategies skip portfolio_evaluation/ folder creation | LOW | 1h |
| F7 | No automated quality gate at promote time (6-metric gate is manual only) | MEDIUM | 3-4h |

### Resilience Gaps (newly identified)

| ID | Issue | Severity | Effort |
|----|-------|----------|--------|
| R1 | PORTFOLIO_COMPLETE strategies not explicitly protected by lineage_pruner -- protection is implicit via spreadsheet presence only. Strategy can lose run folders while waiting for promotion. | HIGH | 2h |
| R2 | Promote has no rollback -- vault created but portfolio.yaml write fails = orphaned vault, no recovery log | MEDIUM | 2h |
| R3 | Regime cache has zero invalidation -- no mtime check, no TTL. Stale results on historical corrections. OHLC cache is mtime-valid but never evicted. | MEDIUM | 2h |
| R4 | Promote audit trail is best-effort and TS_Execution-dependent. Failed promotes leave zero record. | LOW | 1h |
| R5 | No pre-promote readiness check -- no single command to verify all preconditions before attempting promotion | LOW-MEDIUM | 2h |

### Data Flow Boundary Violations (from appendix)

| ID | Issue | Severity | Effort |
|----|-------|----------|--------|
| V1 | Trade_Scan writes OHLC cache to Anti_Gravity_DATA_ROOT (read-only contract violation) | MEDIUM | 1h |
| V2 | Trade_Scan writes regime cache to Anti_Gravity_DATA_ROOT (same) | MEDIUM | 1h |
| V3 | Trade_Scan orchestration writes logs/PID into TS_Execution (wider than documented) | LOW | 1h |
| V6 | TS_Execution burnin_monitor writes backward into TradeScan_State | MEDIUM | 1h |
| V7 | TS_Execution shadow_logger writes to DRY_RUN_VAULT | LOW | 0.5h |

---

## Implementation Sequence

### Design Principles for Sequencing

1. **Dependencies first** -- later fixes depend on earlier ones working
2. **Unblock before harden** -- get promotion working, then make it safe
3. **Quick wins bundled** -- small independent fixes grouped into one session
4. **No partial correctness** -- classification bug fix before quality gate automation (so automated gates use correct classifications)
5. **Boundary fixes with related work** -- cache relocation paired with cache invalidation

---

### Wave 1: Unblock Promotion (Foundation)

**Goal:** Make `promote_to_burnin.py` succeed for strategies that currently fail due to missing artifacts.
**Dependency:** Everything in Waves 2-5 depends on promotion actually working.
**Effort:** 6-8h

| Order | ID | Task | Why This Order |
|-------|----|------|----------------|
| 1.1 | F5 | **Add strategy.py snapshot fallback + auto-recovery.** If authority copy missing in `Trade_Scan/strategies/`, locate via `find_run_id_for_directive()` → `runs/{run_id}/strategy.py`, copy back to authority location. | Highest impact: unblocks 41 directives and 4 CORE candidates immediately |
| 1.2 | F1 | **Add fallback chain to `find_run_id_for_directive()`.** Priority: (1) scan `run_state.json`, (2) `directive_state.json` → `run_ids[]`, (3) Master Filter `run_id` column. Add `current_state == COMPLETE` validation. | F5 depends on this — snapshot fallback needs run_id to locate the snapshot |
| 1.3 | F5b | **Integrate multi-symbol sync into promote tool.** Auto-detect symbols from backtest folders, auto-create per-symbol folders, auto-sync strategy.py. Remove the manual mkdir + symbol-list requirement. | With F5 and F1 fixed, this is the last barrier to multi-symbol promotion |
| 1.4 | R1 | **Add explicit PORTFOLIO_COMPLETE protection to lineage_pruner.** Scan `directive_state.json` for PORTFOLIO_COMPLETE state; add those run_ids to `keep_runs` set. Prevents losing artifacts while waiting for promotion. | Without this, fixes F5/F1 may be undermined — pruner can delete the very artifacts we just learned to find |

**Exit criteria:** `promote_to_burnin.py --dry-run` succeeds for all 11 MPS CORE strategies (including those with missing run_state.json and strategy.py).

---

### Wave 2: Fix Correctness (Classification & Boundaries)

**Goal:** Ensure strategies are classified correctly before we automate quality gates.
**Dependency:** Wave 1 (promotion must work). Wave 3 quality gate automation needs correct classifications.
**Effort:** 4-5h

| Order | ID | Task | Why This Order |
|-------|----|------|----------------|
| 2.1 | F3 | **Fix WATCH classification bug.** Add `is_single_asset` parameter to `_compute_portfolio_status()`. Single-Asset uses SQN path, Portfolios uses edge_quality path. Fix the `if/elif` → `if/if` or explicit routing. | Must fix before Wave 3 — automated gates should use correct status |
| 2.2 | F6 | **Fix single-asset portfolio_evaluation skip.** Either: run portfolio_evaluator for single-symbol (creates the folder), or remove the `portfolio_evaluation/` pre-check from promote for single-symbol. | Removes a promote blocker for single-symbol strategies |
| 2.3 | V1+V2 | **Relocate caches out of Anti_Gravity_DATA_ROOT.** Move `ohlc_cache/` and `regime_cache/` to `TradeScan_State/cache/` (or Trade_Scan local `.cache/`). Update 2 path definitions. | Bundled with R3 (cache invalidation) — touch the cache code once |
| 2.4 | R3 | **Add regime cache invalidation.** Add source-file mtime to regime cache key (mirror OHLC cache approach). Add optional cache eviction for files older than 7 days. | While touching cache paths (V1/V2), fix the invalidation gap too |

**Exit criteria:** Re-run portfolio_evaluator on MPS — verify WATCH/FAIL classifications change where expected. Caches write to new location. Old cache dirs can be deleted.

---

### Wave 3: Harden Promotion (Quality & Safety)

**Goal:** Make promotion safe — prevent promoting bad strategies, ensure audit trail, enable recovery.
**Dependency:** Wave 2 (correct classifications). Quality gate automation needs correct underlying data.
**Effort:** 7-9h

| Order | ID | Task | Why This Order |
|-------|----|------|----------------|
| 3.1 | F7 | **Automate quality gate in promote tool.** Add `--quality-gate` flag (default ON) to `promote_to_burnin.py`. Compute 6 metrics from `results_tradelevel.csv`. FAIL blocks promotion. WARN requires `--override-warn`. `--skip-quality-gate` for operator override. | Core safety improvement — prevents promoting tail-dependent strategies |
| 3.2 | R5 | **Add `--preflight` mode to promote tool.** Single command that checks ALL preconditions: strategy.py, run_state.json, deployable/, quality gate, portfolio_evaluation/, not in portfolio.yaml, PORTFOLIO_COMPLETE state. Prints checklist with PASS/FAIL per item. | Natural extension of F7 — preflight is the "check everything" version of quality gate |
| 3.3 | R2 | **Add promote transaction log + idempotent recovery.** Write `promote_transaction.json` to vault before portfolio.yaml write. On re-run, detect orphaned vault and resume from portfolio.yaml write step. | Prevents orphaned vaults from mid-failure promotes |
| 3.4 | R4 | **Add Trade_Scan-side promote audit log.** Write to `TradeScan_State/logs/promote_audit.jsonl` on every promote attempt (success, failure, dry-run). Include strategy_id, profile, timestamp, outcome, failure_reason. | Removes dependency on TS_Execution for audit trail |
| 3.5 | F4 | **Make post-pipeline Steps 8/8.5 blocking (or add deployable check to promote).** Either: move PORTFOLIO_COMPLETE transition after Step 9, or add `deployable/` artifact check to promote preflight. | Lower priority — promotes now have preflight check (3.2) that catches this |

**Exit criteria:** `promote_to_burnin.py --preflight <ID>` reports full readiness. Quality gate blocks tail-dependent strategies. Promote audit log captures all attempts.

---

### Wave 4: Composite Support (Structural)

**Goal:** Enable promotion of composite portfolios and unify the classification systems.
**Dependency:** Waves 1-3 (individual promotion must be robust first).
**Effort:** 5-7h

| Order | ID | Task | Why This Order |
|-------|----|------|----------------|
| 4.1 | F2a | **Build `decompose_portfolio` utility.** Takes PF_ ID → reads `constituent_run_ids` from MPS → traces each to source strategy_id via `run_metadata.json` → returns list of {strategy_id, symbol, run_id, status}. | Foundation for composite promotion — must trace constituents first |
| 4.2 | F2b | **Add `--composite` flag to promote tool.** Auto-decomposes PF_ portfolio, runs per-constituent quality gate, promotes each passing constituent individually. Reports which constituents pass/fail/skip (already in burn-in). | Builds on 4.1 + Wave 3 quality gate |
| 4.3 | -- | **Unify classification terminology and document.** Create a single reference table: what CORE/WATCH/FAIL means in each system (filter_strategies vs portfolio_evaluator vs promote quality gate), what metric governs each, what entity type each applies to. Write to `outputs/system_reports/`. | Documentation — prevents future confusion about edge_quality vs edge_ratio vs SQN |

**Exit criteria:** `promote_to_burnin.py --composite PF_04C5F80CB1E3 --profile CONSERVATIVE_V1 --dry-run` succeeds, listing constituent promotions.

---

### Wave 5: Boundary Fixes & Architecture (Long-term)

**Goal:** Clean up data flow violations and reduce cross-repo coupling.
**Dependency:** None (independent of Waves 1-4, but lower priority).
**Effort:** 3-5h (excluding engine packaging)

| Order | ID | Task | Why This Order |
|-------|----|------|----------------|
| 5.1 | V6 | **Move burnin_monitor output to TS_Execution.** Write to `TS_Execution/outputs/burnin/` instead of `TradeScan_State/strategies/`. | Only true backward write — clean violation |
| 5.2 | V3 | **Document expanded TS_Execution write surface.** Update `DEPLOYMENT_UNIFICATION_PLAN.md` to reflect that orchestration tools (watchdog, startup_launcher) write logs/PIDs into TS_Execution. This is by design, not a bug. | Documentation only — codifies existing behavior |
| 5.3 | -- | **Long-term: package engine as installable module.** Replace `chdir` + `sys.path` hack with proper `pip install -e` of engine package. Decouples TS_Execution from Trade_Scan file tree. | Largest effort, biggest architectural payoff. Deferred. |

**Exit criteria:** Zero backward writes from TS_Execution to TradeScan_State. Boundary documentation updated.

---

## Additional Robustness Recommendations (Beyond Audit Findings)

These are systemic improvements not tied to specific friction points but identified during the audit as missing resilience layers.

### R6: Promotion Readiness Dashboard

**What:** A single command (`python tools/promote_readiness.py`) that scans all CORE + WATCH strategies across MPS and FSP, and reports promotion readiness for each:

```
Strategy                                    Status    strategy.py  run_state  deployable  quality_gate  portfolio.yaml
22_CONT_FX_1H_RSIAVG_TRENDFILT_S09_V1_P00  CORE      MISSING(*)   MISSING    OK          PASS          not present
22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P03  CORE      OK(run)      OK         OK          PASS          not present
23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12        CORE      OK           OK         OK          WARN          not present
PF_04C5F80CB1E3                             CORE      COMPOSITE    N/A        N/A         N/A           not present
   └─ constituent: SPKFADE_S03 (XAUUSD)              OK           OK         OK          PASS          BURN_IN ✓
   └─ constituent: BOS_S01 (XAUUSD)                  OK           OK         OK          FAIL          not present
(*) = recoverable from run snapshot
```

**Why:** Eliminates the ad-hoc "check this, then check that" discovery process that caused the friction in the first place. Agents and operators see the full picture before attempting any promotion.
**Effort:** 3-4h
**When:** After Wave 3 (uses preflight + quality gate + decompose_portfolio)

### R7: Strategy Authority Protection Flag

**What:** Add a `protected: true` field to `directive_state.json` for any strategy at PORTFOLIO_COMPLETE or IN_PORTFOLIO. Lineage pruner and cleanup tools check this flag before touching any associated run folders.

**Why:** R1 (Wave 1) adds PORTFOLIO_COMPLETE to the pruner's keep-set, but this is an implicit protection based on scanning. An explicit flag is more robust — survives spreadsheet reconciliation, works even if FSM state is consulted before spreadsheets are regenerated.
**Effort:** 1-2h
**When:** Wave 1 (alongside R1), or Wave 3

### R8: Pipeline Completion Verification Gate

**What:** After PORTFOLIO_COMPLETE, before the directive is archived, run a final verification:
- All run_ids referenced in directive_state.json still exist on disk
- All backtest folders have expected artifacts
- strategy.py authority copy still matches run snapshot
- deployable/ folder exists and has all 7 profiles

**Why:** Catches artifact loss between pipeline completion and promotion. Currently, the gap between PORTFOLIO_COMPLETE and promotion is unmonitored — run folders can be deleted, strategy.py can be overwritten, and nobody notices until promotion fails.
**Effort:** 2-3h
**When:** Wave 3 (after promote preflight exists — shares verification logic)

### R9: Sweep-Safe Strategy Lifecycle

**What:** During sweep iteration (creating new passes of the same family), the agent should:
1. Check if any existing pass is at PORTFOLIO_COMPLETE or IN_PORTFOLIO
2. If yes, NEVER delete its `Trade_Scan/strategies/{id}/` folder
3. Create the new pass in its own folder (which already happens)

This requires adding a pre-delete check to whatever process currently removes old strategy folders during sweeps.

**Why:** Root cause of F5 (strategy.py lost during sweeps). The snapshot fallback (F5) is a recovery mechanism — this prevents the problem from occurring in the first place.
**Effort:** 1-2h
**When:** Wave 1 (prevention alongside F5 recovery)

### R10: Promote Batch Mode

**What:** `python tools/promote_to_burnin.py --batch` that reads all CORE strategies from FSP/MPS, runs preflight + quality gate on each, and promotes all passing strategies in one session. Outputs a summary table.

**Why:** Current process requires running promote individually for each strategy, manually checking quality gates, manually resolving symbols. Batch mode with automated gates eliminates the per-strategy friction that makes promotion a multi-hour process.
**Effort:** 2-3h
**When:** After Wave 3 (requires preflight, quality gate, and audit log)

---

## Consolidated Timeline

| Wave | Theme | Total Effort | Key Deliverable |
|------|-------|-------------|-----------------|
| **Wave 1** | Unblock Promotion | 6-8h | `promote --dry-run` succeeds for all CORE strategies |
| **Wave 2** | Fix Correctness | 4-5h | Classifications are correct, caches are clean |
| **Wave 3** | Harden Promotion | 7-9h | Automated quality gate, preflight check, audit trail |
| **Wave 4** | Composite Support | 5-7h | PF_ composites promotable via `--composite` |
| **Wave 5** | Boundary Cleanup | 3-5h | Zero backward writes, documented boundaries |
| **R6-R10** | Robustness Extras | 10-14h | Dashboard, protection flags, batch promote |
| **Total** | | **35-48h** | |

### Recommended Pace

- **Tomorrow (Wave 1):** Unblock promotion. This is the immediate need — CORE strategies are waiting.
- **Next 2 sessions (Wave 2+3):** Fix correctness and harden. These make promotion reliable.
- **Following week (Wave 4+5):** Composite support and boundary cleanup. Lower urgency but important for completeness.
- **R6-R10:** Implement opportunistically as the system matures through burn-in observation.

---

---

## Appendix: Cross-Repo Data Flow Boundary Audit

### Intended Architecture

```
DATA_INGRESS ──writes──► Anti_Gravity_DATA_ROOT ──reads──► Trade_Scan ──writes──► TradeScan_State ──reads──► TS_Execution
                          (master data store)                                     (results store)
```

Each stage reads from the previous stage's output and writes only to its own output location. No backward writes.

### Audit Results

| Boundary | Expected | Actual | Violations |
|----------|----------|--------|------------|
| DATA_INGRESS → Anti_Gravity_DATA_ROOT | Write only | Write only | **CLEAN** |
| DATA_INGRESS → Trade_Scan/TradeScan_State | Never | Never | **CLEAN** |
| Trade_Scan reads Anti_Gravity_DATA_ROOT | Read only | **Read + Cache Write** | 2 violations |
| Trade_Scan writes TradeScan_State | Write only | Write only | **CLEAN** |
| Trade_Scan writes TS_Execution | portfolio.yaml only | portfolio.yaml + logs + PID + audit | Wider than documented |
| TS_Execution reads TradeScan_State | Read only | **Read + 1 Write** | 1 violation |
| TS_Execution reads Trade_Scan | Read only (strategy.py, engine) | Read only + code execution (chdir) | Borderline |
| TS_Execution → Anti_Gravity_DATA_ROOT | Never | Never | **CLEAN** |
| TS_Execution → DRY_RUN_VAULT | Not documented | Shadow trade backup writes | 1 violation |

### Violations Detail

#### V1-V2: Trade_Scan writes cache files into Anti_Gravity_DATA_ROOT (MEDIUM)

- `data_access/readers/research_data_reader.py:34-35` — writes `.parquet` OHLC cache to `data_root/ohlc_cache/`
- `engines/regime_state_machine.py:35,334,337` — writes `.parquet` regime cache to `data_root/regime_cache/`

These are performance caches (content-addressed filenames), not source data corruption. But they violate the read-only contract with Anti_Gravity_DATA_ROOT. DATA_INGRESS could overwrite or conflict.

**Fix:** Relocate cache directories to `TradeScan_State/cache/ohlc/` and `TradeScan_State/cache/regime/`, or to a local `.cache/` directory within Trade_Scan.

#### V3-V5: Trade_Scan writes more than portfolio.yaml into TS_Execution (LOW)

- `tools/orchestration/watchdog_daemon.py` — writes `watchdog.pid`, `watchdog_guard.json`, logs to `TS_Execution/outputs/logs/`
- `tools/orchestration/startup_launcher.py` — writes startup logs, archives to `TS_Execution/outputs/logs/`
- `tools/promote_to_burnin.py:610-626` — calls `TS_Execution/tools/audit_log.py` to write audit entry

These are supervisory/operational writes. Architecturally defensible (watchdog needs to co-locate state with the process it monitors), but wider than the documented "portfolio.yaml only" contract.

**Fix (optional):** Move orchestration logs to `Trade_Scan/outputs/logs/orchestration/` and have TS_Execution read them if needed. Or document the expanded write surface.

#### V6: TS_Execution writes backward to TradeScan_State (MEDIUM)

- `TS_Execution/tools/burnin_monitor.py:592` — writes directly to `TradeScan_State/strategies/.../BURNIN_*.md`

This is a direct backward write from a consumer repo to a producer repo's output store.

**Fix:** Move burn-in monitoring output to `TS_Execution/outputs/burnin/` and have Trade_Scan read it from there if needed.

#### V7: TS_Execution writes to DRY_RUN_VAULT (LOW)

- `TS_Execution/src/shadow_logger.py:396-399` — copies `shadow_trades.xlsx` to `DRY_RUN_VAULT/shadow_backups/`

DRY_RUN_VAULT is a shared backup sink. This is append-only (timestamped filenames) and may be intentional.

**Fix (optional):** If DRY_RUN_VAULT should be Trade_Scan-only, move shadow backups to `TS_Execution/outputs/backups/`.

#### Borderline: TS_Execution executes Trade_Scan code

- `src/main.py:50-51` — `os.chdir(research_root)` + `sys.path.insert(0, research_root)` then imports engine modules from Trade_Scan. This makes TS_Execution dependent on Trade_Scan being present and importable at runtime.
- `tools/disable_burnin.py:243-248` — subprocess-calls `Trade_Scan/tools/sync_portfolio_flags.py` which writes to TradeScan_State.
- `src/shadow_logger.py:491-503` — subprocess-calls `Trade_Scan/tools/format_excel_artifact.py` on TS_Execution's own file.

These are code-execution boundary crossings, not data-write violations. But they create tight coupling: TS_Execution cannot run without Trade_Scan's code tree present.

### Suggestions

1. **Move caches out of Anti_Gravity_DATA_ROOT** (V1-V2) — highest priority, cleanest fix. Relocate to `TradeScan_State/cache/` or Trade_Scan local `.cache/`.

2. **Document the expanded TS_Execution write surface** (V3-V5) — the orchestration tools are supervisory by design. Either document the wider contract or relocate logs.

3. **Move burnin_monitor output to TS_Execution** (V6) — this is the only true backward write from consumer to producer. Should live in TS_Execution's own output directory.

4. **Long-term: package Trade_Scan engine as importable module** — TS_Execution's `chdir` + `sys.path` hack creates fragile coupling. A proper package install (pip install -e or wheel) would make the engine importable without path manipulation. This is a larger architectural change.

---

*Generated: 2026-04-12 | Auditor: Claude | Scope: Trade_Scan pipeline stages 0-7, promote_to_burnin.py, filter_strategies.py, portfolio_evaluator.py, promote.md workflow, cross-repo data flow boundaries across DATA_INGRESS, Anti_Gravity_DATA_ROOT, Trade_Scan, TradeScan_State, TS_Execution, DRY_RUN_VAULT*
