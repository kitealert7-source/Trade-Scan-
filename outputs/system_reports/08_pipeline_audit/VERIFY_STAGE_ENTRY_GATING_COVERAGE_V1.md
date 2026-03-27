# VERIFY_STAGE_ENTRY_GATING_COVERAGE_V1
**Date:** 2026-03-20
**Scope:** Stage entry gating audit — Stages 0–4, orchestration layer, state machines
**Status:** COMPLETE — No code changes made

---

## 1. Existing Guards Enumeration

### PREFLIGHT (Stage 0)

| Guard | Type | Location |
|---|---|---|
| Directive must exist in INBOX or active_backup (path resolution) | State-based | `run_pipeline.py` |
| Manifest timestamp guard (`verify_tools_timestamp_guard`) | Artifact-based | `run_pipeline.py:588` |
| Skip set: `{PREFLIGHT_COMPLETE, PREFLIGHT_COMPLETE_SEMANTICALLY_VALID, SYMBOL_RUNS_COMPLETE, PORTFOLIO_COMPLETE}` | State-based | `stage_preflight.py:37-42` |
| Semantic validation runs ONLY when state == `PREFLIGHT_COMPLETE` | State-based | `stage_preflight.py:67` |
| Dryrun runs ONLY when state == `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID` | State-based | `stage_preflight.py:128` |
| `strategy.py.approved` marker presence (Option B gate) | Artifact-based | `preflight.py` CHECK 6.5 |
| No pre-entry artifact check on directive `.txt` file itself | — | **NONE** |

---

### SYMBOL_EXECUTION (Stage 1)

| Guard | Type | Location |
|---|---|---|
| Skip if run in `{STAGE_1_COMPLETE, STAGE_2_COMPLETE, STAGE_3_COMPLETE, STAGE_3A_COMPLETE, COMPLETE}` | State-based | `stage_symbol_execution.py:112-118` |
| Abort if run in `FAILED` state | State-based | `stage_symbol_execution.py:140-148` |
| Post-execution: `raw/results_tradelevel.csv` existence → NO_TRADES marker | Artifact-based (post) | `stage_symbol_execution.py:155-172` |
| No pre-entry check that OHLCV data file exists | — | **NONE** |
| No pre-entry check that `strategy.py` is importable at execution time | — | **NONE** (dryrun in PREFLIGHT is the only gate) |

---

### REPORTING (Stage 2)

| Guard | Type | Location |
|---|---|---|
| Runs only after SymbolExecutionStage (StageRunner fail-fast) | State-based (implicit) | `runner.py:52-58` |
| Per-run: checks run is in `STAGE_1_COMPLETE` before transition | State-based | `stage_symbol_execution.py:243` |
| Engine module existence (`ImportError` guard) | Artifact-based | `stage_symbol_execution.py:228-233` |
| Post-execution: AK_Trade_Report presence per run | Artifact-based (post) | `stage_symbol_execution.py:245-259` |
| **AK_Trade_Report missing → marks run FAILED, NO exception raised** | — | **GAP — see Section 5** |
| No pre-entry check that `raw/results_tradelevel.csv` exists before invoking stage2_compiler | — | **NONE** |

---

### SCHEMA_VALIDATION (Stage 2 gate)

| Guard | Type | Location |
|---|---|---|
| Runs only after ReportingStage (StageRunner fail-fast) | State-based (implicit) | `runner.py:52-58` |
| AK_Trade_Report_*.xlsx must exist per run | Artifact-based | `stage_schema_validation.py:100-108` |
| 32 required metrics present and non-null in Performance Summary sheet | Artifact-based | `stage_schema_validation.py:44-72` |
| Collects all per-run failures before raising | Fail-collect | `stage_schema_validation.py:129-135` |
| **No pre-entry check: any run in FAILED state** | — | **GAP — see Section 5** |
| **No state-based guard: runs even when Stage 2 silently failed runs** | — | **GAP — see Section 5** |

---

### AGGREGATION (Stage 3)

| Guard | Type | Location |
|---|---|---|
| Runs only after SchemaValidationStage (StageRunner fail-fast) | State-based (implicit) | `runner.py:52-58` |
| Post-execution: Master Filter file existence | Artifact-based (post) | `stage_symbol_execution.py:283-289` |
| Cardinality gate: actual rows == expected rows (accounting for NO_TRADES) | Artifact-based (post) | `stage_symbol_execution.py:306-326` |
| NO_TRADES exclusion via `status_no_trades.json` marker | Artifact-based | `stage_symbol_execution.py:312-315` |
| **No pre-entry check: all runs in STAGE_2_COMPLETE** | — | **GAP — see Section 5** |
| **No idempotency: re-runs on resume → appends duplicate rows to Master Filter** | — | **GAP — see Section 5** |

---

### MANIFEST_BINDING (Stage 3a)

| Guard | Type | Location |
|---|---|---|
| Runs only after AggregationStage (StageRunner fail-fast) | State-based (implicit) | `runner.py:52-58` |
| Strategy snapshot integrity: hash(snapshot) == hash(source strategy.py) | Artifact-based | `stage_symbol_execution.py:375` |
| Required artifacts: `results_tradelevel.csv`, `results_standard.csv`, `equity_curve.csv` | Artifact-based | `stage_symbol_execution.py:420-424` |
| Manifest freeze guard: if manifest exists AND state == COMPLETE → verify immutability | Hybrid | `stage_symbol_execution.py:449-455` |
| equity_curve.csv auto-generated if missing | Artifact-based (auto-repair) | `stage_symbol_execution.py:398-418` |
| **No directive-state check: does NOT skip if directive already == SYMBOL_RUNS_COMPLETE** | — | **GAP — see Section 5** |

---

### PORTFOLIO (Stage 4)

| Guard | Type | Location |
|---|---|---|
| Runs only after ManifestBindingStage (StageRunner fail-fast) | State-based (implicit) | `runner.py:52-58` |
| Dependency guard: each run_id present in registry and on filesystem | Hybrid | `stage_portfolio.py:33-46` |
| Artifact integrity guard: manifest.json existence + hash verification per run | Artifact-based | `stage_portfolio.py:47-87` |
| Batch summary CSV must exist | Artifact-based | `stage_portfolio.py:64-67` |
| Ledger write eligibility: multi-run / multi-asset check | State-based | `stage_portfolio.py:102-106` |
| Ledger validation: exactly 1 row, correct constituent count | Artifact-based | `stage_portfolio.py:115-145` |
| Post-steps (report gen, capital wrapper, profile selector) logged but NOT fatal | Intentional | `stage_portfolio.py:157-197` |

---

## 2. Artifact Dependency Mapping

| Stage | Required Artifacts | Pre-entry Check? | Classification |
|---|---|---|---|
| PREFLIGHT | Directive `.txt` file | YES (path resolution) | Explicit |
| SYMBOL_EXECUTION | `strategy.py` (loaded in `run_stage1.py`) | NO — dryrun only at PREFLIGHT | **Implicit** |
| SYMBOL_EXECUTION | OHLCV data file | NO | **Implicit** |
| REPORTING | `raw/results_tradelevel.csv` (Stage 1 output) | NO | **Implicit** |
| SCHEMA_VALIDATION | `AK_Trade_Report_*.xlsx` | YES — post-run probe, not pre-entry | Artifact (post) |
| AGGREGATION | All runs in `STAGE_2_COMPLETE` | NO | **Implicit** |
| AGGREGATION | `Strategy_Master_Filter.xlsx` exists after write | YES — post-write only | Artifact (post) |
| MANIFEST_BINDING | `results_tradelevel.csv`, `results_standard.csv`, `equity_curve.csv` | YES | Explicit |
| MANIFEST_BINDING | Directive NOT already in `SYMBOL_RUNS_COMPLETE` | NO | **Implicit** |
| PORTFOLIO | All run manifests + hash integrity | YES | Explicit |
| PORTFOLIO | `Master_Portfolio_Sheet.xlsx` | YES — post-write only | Artifact (post) |

---

## 3. Failure Path Analysis

### 3a. Stage 1 failure → SCHEMA_VALIDATION execution

```
Stage 1 ENGINE_CRASH (e.g. AUDNZD)
  → run state: FAILED
  → exception raised → StageRunner halts
  → directive: stays at PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
  ↓
Manual reset + rerun:
  Stage 1 re-attempts AUDNZD (FAILED not in skip_states)
  Stage 1 succeeds → STAGE_1_COMPLETE
  ↓
ReportingStage:
  stage2_compiler --scan invoked
  If AK_Trade_Report not produced for AUDNZD:
    → run marked FAILED internally
    → NO exception raised → StageRunner continues
  ↓
SchemaValidationStage:
  → AK_Trade_Report not found for AUDNZD
  → PipelineExecutionError raised
  → Error message: "AK_Trade_Report not found" (misleading — real cause: Stage 2 failed)
```

**Confirmed in log**: `01_MR_FX_1H_ULTC_REGFILT_S07_V1_P01`:
- `12:52:37Z` — SYMBOL_EXECUTION ENGINE_CRASH (AUDNZD)
- `13:00:14Z` — SCHEMA_VALIDATION AK_Trade_Report not found (AUDNZD)

**Root cause**: Reporting marks runs FAILED silently. Schema Validation is the first loud failure. The error message attributes the fault to a missing artifact rather than the real upstream Stage 2 failure.

---

### 3b. REPORTING failure — re-entry gating

```
ReportingStage fails a run (per-run, no exception to StageRunner)
  → directive stays at PREFLIGHT_COMPLETE_SEMANTICALLY_VALID
  → run stays at STAGE_1_COMPLETE (failed state transition attempted)
  ↓
Manual reset + rerun:
  ReportingStage re-invoked (completed_stages cleared on reset)
  stage2_compiler --scan runs again for same run
  If root cause not fixed → same failure
  → Repeats indefinitely (no pipeline-enforced retry limit)
```

**Confirmed in log**: `02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S05_V1_P00`:
- REPORTING failed at `13:31`, `13:36`, `13:37`, `13:46`, `13:49`, `14:16` — 6 identical failures.
- Directive never transitioned to FAILED; user could reset and retry without limit.

---

## 4. Idempotency Check

| Stage | Re-runs on resume? | Behavior | Safety |
|---|---|---|---|
| PREFLIGHT | NO — skip set enforced | Skips if already complete | Safe |
| SYMBOL_EXECUTION | Partial — skips STAGE_1_COMPLETE+ runs, re-runs FAILED | Correct by design | Safe |
| REPORTING | YES — re-invokes stage2_compiler for all runs | Idempotent if Stage 1 artifacts stable | Acceptable |
| SCHEMA_VALIDATION | YES — re-validates every run | No state skip | Acceptable |
| AGGREGATION | **YES — re-appends to Master Filter** | **Duplicate rows → cardinality mismatch** | **UNSAFE** |
| MANIFEST_BINDING | Partial — manifest freeze guard for COMPLETE runs | Safe per-run; **unsafe at directive level** | Partial |
| PORTFOLIO | Partial — ledger identical-row guard | Safe for ledger append | Safe |

**Confirmed in log**: `07_MR_XAUUSD_15M_SMI_SMIFILT_S01_V1_P00` — Stage-3 cardinality progressed 2→3→4 across retries (`06:44`, `06:50`, `07:52` on 2026-03-16). Aggregation re-appended rows each run.

---

## 5. Gap Identification

| Stage | Required Precondition | Guard Exists? | Guard Type | Gap Description | Severity |
|---|---|---|---|---|---|
| SCHEMA_VALIDATION | All runs not in FAILED state | **NO** | — | Runs even when Reporting silently failed runs; error is attributed to missing artifact, not upstream Stage 2 failure | **HIGH** |
| MANIFEST_BINDING | Directive != `SYMBOL_RUNS_COMPLETE` | **NO** | — | Does not skip when directive already transitioned; Portfolio-fail retry crashes with `Illegal Directive Transition: SYMBOL_RUNS_COMPLETE → SYMBOL_RUNS_COMPLETE` | **HIGH** |
| AGGREGATION | Rows not already present in Master Filter | **NO** | — | No idempotency; re-appends rows on every resume → cardinality corruption on retry | **HIGH** |
| REPORTING | `raw/results_tradelevel.csv` exists pre-invocation | **NO** | — | No pre-entry artifact check; stage2_compiler called even if Stage 1 artifacts absent | **MEDIUM** |
| REPORTING | Any run failure propagates to StageRunner | Partial | Post-execution, per-run | Silent per-run failure allows StageRunner to continue; blind retry enabled | **MEDIUM** |
| SYMBOL_EXECUTION | `strategy.py` importable at execution time | NO (dryrun only) | — | Dryrun at PREFLIGHT is the only gate; data-dependent crashes at execution time have no second gate | **LOW** |

---

## 6. Overlap / Conflict Detection

| Proposed New Guard | Conflicts / Overlaps | Safe to Add? |
|---|---|---|
| Pre-entry FAILED-run check in SchemaValidationStage | Reporting already marks runs FAILED; Schema Validation artifact probe catches the same condition — this is a **duplicate that fires earlier and with a clearer message** | YES — earlier classification, no conflict |
| `SYMBOL_RUNS_COMPLETE` skip in ManifestBindingStage | ManifestBindingStage has per-run manifest freeze guard; directive-level skip adds a separate layer. **Conflict**: `--to-stage4` reset explicitly sets `SYMBOL_RUNS_COMPLETE` to re-enter Portfolio — the skip guard would block this path | YES — but must be conditioned on NOT being a `--to-stage4` resume. Use `context.completed_stages` or a bootstrap context flag |
| Idempotency check in AggregationStage (skip write if rows already match) | The existing cardinality gate (post-write) can still run as a verification step after the skip. No conflict with downstream stages | YES — safe; skip write, keep cardinality verification |
| Pre-entry `results_tradelevel.csv` check in ReportingStage | No existing check at this point; no conflicts | YES — safe addition |
| Making Reporting raise on per-run failure | Changes StageRunner fail-fast behavior; currently allows multi-symbol directives to continue even if one symbol's Stage 2 fails. Changing to raise stops ALL remaining symbols | **CAUTION** — changes the multi-symbol failure model; Gap 1 fix (Schema Validation state check) is sufficient without this change |

---

## 7. Recommendations

> No code changes made. Safe insertion points only.

---

### REC-01 — HIGH: SCHEMA_VALIDATION pre-entry state check

**File**: `tools/orchestration/stage_schema_validation.py`
**Function**: `run()` method, before per-run artifact probe loop
**Type**: Pre-stage check / hard fail

**Logic**: Collect run IDs where `PipelineStateManager(rid).get_state() == "FAILED"`.
If any found → raise `PipelineExecutionError("Stage 2 failed for: [list of run_ids]. Fix Stage 2 before schema validation.")` without proceeding to artifact probes.

**Effect**: Replaces the misleading "AK_Trade_Report not found" error with a clear upstream failure message. Eliminates the confusing double-failure sequence.

---

### REC-02 — HIGH: MANIFEST_BINDING directive-state skip guard

**File**: `tools/orchestration/manifest_binding_stage.py`
**Function**: `run()` method, before per-run iteration
**Type**: Pre-stage check / skip (not hard fail)

**Logic**: Check `context.dir_state_mgr.get_state() == "SYMBOL_RUNS_COMPLETE"`.
If true AND this is NOT a `--to-stage4` resume → log `"[MANIFEST_BINDING] Already SYMBOL_RUNS_COMPLETE — skipping."` and return.

**Conflict resolution**: The `--to-stage4` reset path deliberately sets `SYMBOL_RUNS_COMPLETE` before re-entry. Distinguish by checking whether a context flag (e.g., `context.resume_from_stage4`) is set by the bootstrap. Alternatively, check if `"MANIFEST_BINDING"` is already in `context.completed_stages` — but this set is not persisted across sessions.

**Recommended approach**: Bootstrap sets `context.skip_manifest_binding = True` when directive is already `SYMBOL_RUNS_COMPLETE` and `--to-stage4` was NOT invoked.

---

### REC-03 — HIGH: AGGREGATION idempotency pre-check

**File**: `tools/orchestration/stage_symbol_execution.py`
**Function**: `run_stage3_aggregation()`, before `run_command([..., "tools/stage3_compiler.py", ...])`
**Type**: Pre-stage check / skip

**Logic**: Load Master Filter; count rows matching `clean_id` in `strategy` column.
Compute expected count = `len(symbols) - NO_TRADES_count`.
If `actual_count == expected_count` → skip stage3_compiler call, log `"[AGGREGATION] Rows already present — skipping write."`.
Existing post-write cardinality gate runs as-is as a verification step.

**Effect**: Eliminates duplicate row appends on resume. Cardinality gate still validates the skip result.

---

### REC-04 — MEDIUM: REPORTING pre-entry artifact check

**File**: `tools/orchestration/stage_symbol_execution.py`
**Function**: Per-run loop in reporting stage, before `run_command([..., "stage2_compiler", ...])`
**Type**: Pre-run check / hard fail per run

**Logic**: Check `BACKTESTS_DIR / f"{clean_id}_{symbol}" / "raw" / "results_tradelevel.csv"` exists.
If missing → mark run FAILED immediately with `"Stage-1 artifact missing before Stage-2 invocation"`. Do not invoke stage2_compiler.

**Effect**: Stage 2 is not called against a run with no Stage 1 output. Error is attributed to the correct stage.

---

### REC-05 — MEDIUM: REPORTING per-run silent failure (no change recommended)

Do NOT change Reporting to raise on per-run failure.
**Rationale**: The current model allows multi-symbol directives to process all symbols even if one fails Stage 2, which is operationally useful.
**Instead**: REC-01 (Schema Validation state pre-check) is the correct intercept — it provides the loud failure with clear attribution without changing the multi-symbol failure model.

---

## State Machine Reference

### DirectiveStateManager — ALLOWED_TRANSITIONS (`pipeline_utils.py:517-524`)

```
INITIALIZED                          → [PREFLIGHT_COMPLETE, FAILED]
PREFLIGHT_COMPLETE                   → [PREFLIGHT_COMPLETE_SEMANTICALLY_VALID, FAILED]
PREFLIGHT_COMPLETE_SEMANTICALLY_VALID → [SYMBOL_RUNS_COMPLETE, FAILED]
SYMBOL_RUNS_COMPLETE                 → [PORTFOLIO_COMPLETE, FAILED]
PORTFOLIO_COMPLETE                   → [FAILED]
FAILED                               → [INITIALIZED, SYMBOL_RUNS_COMPLETE]
```

### PipelineStateManager (per-run) — ALLOWED_TRANSITIONS (`pipeline_utils.py:294-304`)

```
IDLE                                  → [PREFLIGHT_COMPLETE, FAILED]
PREFLIGHT_COMPLETE                    → [PREFLIGHT_COMPLETE_SEMANTICALLY_VALID, FAILED]
PREFLIGHT_COMPLETE_SEMANTICALLY_VALID → [STAGE_1_COMPLETE, FAILED]
STAGE_1_COMPLETE                      → [STAGE_2_COMPLETE, FAILED]
STAGE_2_COMPLETE                      → [STAGE_3_COMPLETE, FAILED]
STAGE_3_COMPLETE                      → [STAGE_3A_COMPLETE, FAILED]
STAGE_3A_COMPLETE                     → [COMPLETE, FAILED]
COMPLETE                              → []
FAILED                                → []
```

### Illegal Transition Behavior (`pipeline_utils.py:417-424`)
Raises `RuntimeError("[FATAL] Illegal State Transition: {old} → {new}. Allowed: {list}")`.
Appends `ILLEGAL_TRANSITION_ATTEMPT` to audit log before raising. No recovery at state machine level.
