# AGENT.md — Failure Classification & Rectification Playbook v1

**Authority:** Governance-First Pipeline Architecture  
**Status:** DIAGNOSTIC ONLY — No mutation authority  
**Scope:** All failures encountered in `run_pipeline.py` orchestrated execution

> [!CAUTION]
> This playbook is NOT an autonomous repair system.  
> It MUST NEVER authorize automatic mutation of strategy code, directives, artifacts, `run_state.json`, or Master Ledgers.  
> It is a diagnostic and remediation guide only.

---

## SYSTEM INVARIANTS

These are non-negotiable. The agent must never violate any of these.

1. **Ledger Supremacy** — `Master_Portfolio_Sheet.xlsx` and `Strategy_Master_Filter.xlsx` are append-only. No deletion. No overwrite.
2. **Fail-Fast** — Any failure at any stage aborts the entire pipeline. No partial progression. No continuation after error.
3. **Artifact Authority** — All gating decisions derive from physical artifact existence and content, not memory or cache.
4. **Snapshot Immutability** — `runs/<RUN_ID>/strategy.py` and `STRATEGY_SNAPSHOT.manifest.json` are write-once. No mutation after creation.
5. **State Machine Integrity** — `run_state.json` transitions are strictly forward. FAILED is terminal. Re-provisioning is the only recovery.
6. **Directive Integrity** — Directives in `backtest_directives/active/` are not modified by the pipeline. Only moved to `completed/` on success.
7. **Deterministic Execution** — Same directive + same data = same output. No randomness. No inference. No implicit defaults.
8. **Single Authority** — Only `run_pipeline.py` may mutate `run_state.json`. No other tool, script, or agent may modify state files.
9. **Append-Only Audit** — `directive_audit.log` and run audit logs are append-only. No truncation. No retroactive edits.
10. **Human Gating** — No new `strategy.py` may enter execution without explicit human approval (Admission Gate — SOP_TESTING §4A).

---

## LIFECYCLE OVERVIEW

```
Directive (YAML in active/)
    │
    ▼
Stage-0: Preflight
    ├── Strategy Provisioning (create/update strategy.py shell)
    ├── Dependency Validation (indicators, engine, broker specs)
    └── Governance Compliance Check
    │
    ▼
Stage-0.5: Semantic Validation
    ├── Identity Verification (name, timeframe)
    ├── Signature Schema Enforcement (version, deep equality)
    ├── Indicator Set Verification (exact import matching)
    ├── Behavioral Guard (FilterStack enforcement, no hardcoded regime access)
    └── Admission Gate (hollow strategy detection → PROVISION_REQUIRED)
    │
    ▼
Stage-0.75: Dry-Run Validation
    ├── Strategy Instantiation Test
    ├── prepare_indicators() Crash Detection
    └── check_entry() Crash Detection
    │
    ▼
Stage-1: Execution (per symbol, atomic)
    ├── Data Load (RESEARCH only)
    ├── Engine Execution Loop
    ├── Artifact Emission (results_tradelevel.csv, results_standard.csv)
    └── Artifact Gate (physical file existence check)
    │
    ▼
Stage-2: Compilation (per symbol)
    ├── Stage-1 Artifact Ingestion
    ├── Metric Computation (SOP_OUTPUT compliant)
    └── AK_Trade_Report Excel Generation
    │
    ▼
Stage-3: Aggregation
    ├── Strategy_Master_Filter.xlsx Update
    ├── Cardinality Gate (row count == symbol count)
    ├── Strategy Snapshot Copy + Hash Verification
    └── STRATEGY_SNAPSHOT.manifest.json Binding
    │
    ▼
Pre-Stage-4: Manifest Integrity Verification
    ├── Manifest Existence Check (all runs)
    ├── Manifest Key Set Verification
    └── Artifact Hash Re-Computation + Comparison
    │
    ▼
Stage-4: Portfolio Evaluation
    ├── Portfolio Metrics Computation
    ├── Chart Generation
    ├── Master_Portfolio_Sheet.xlsx Append
    ├── Ledger Row Count Verification
    └── Constituent Run ID Cardinality Gate
    │
    ▼
PORTFOLIO_COMPLETE → Directive moved to completed/
```

---

## FAILURE CLASSIFICATION

------------------------------------------------------------

### PROVISION_REQUIRED

------------------------------------------------------------

**Trigger Location:**  
`tools/semantic_validator.py` → Stage-0.5 (HollowDetector)

**Detection Mechanism:**  
`check_entry()` function body contains only: optional docstring + optional `self.filter_stack.allow_trade()` guard + `return None`. No other statements present.

**Structural Meaning:**  
Strategy was auto-provisioned by `strategy_provisioner.py` but no execution logic was authored. The strategy will produce zero trades if executed.

**Allowed Actions:**  

- Report the failure with strategy path  
- Advise human that strategy logic must be implemented  
- Offer to assist with strategy authoring (with human approval)

**Forbidden Actions:**  

- Do NOT auto-generate strategy logic  
- Do NOT modify `strategy.py` without explicit human approval  
- Do NOT bypass by removing the HollowDetector check  
- Do NOT retry execution without addressing the root cause

**Deterministic Recovery Path:**  

1. Human authors `check_entry()`, `check_exit()`, and `prepare_indicators()` logic
2. Human approves the strategy (Admission Gate)
3. Re-execute pipeline with `--force`

**Escalation Required:** YES — Human must author strategy logic

------------------------------------------------------------

### SCHEMA_VIOLATION

------------------------------------------------------------

**Trigger Location:**  
`tools/semantic_validator.py` → Stage-0.5

**Detection Mechanism:**  
Any of:

- `signature_version` in strategy does not match `SIGNATURE_SCHEMA_VERSION` (currently `1`)
- Deep canonical comparison of `STRATEGY_SIGNATURE` in code vs directive-derived expected signature fails
- Strategy `name` attribute does not match directive's declared strategy name
- Strategy `timeframe` attribute does not match directive's declared timeframe

**Structural Meaning:**  
The strategy implementation does not match its governing directive. The signature, identity, or structural contract has diverged.

**Allowed Actions:**  

- Report exact mismatch details (expected vs actual)  
- Diagnose whether directive or strategy changed

**Forbidden Actions:**  

- Do NOT patch the signature  
- Do NOT downgrade schema version  
- Do NOT modify the directive to match the strategy  
- Do NOT perform schema migration

**Deterministic Recovery Path:**  

1. Determine which is authoritative: directive or strategy
2. If directive changed: re-provision strategy (`--force`)
3. If strategy was manually edited: restore signature from directive
4. Re-run pipeline

**Escalation Required:** YES — Human must determine authority source

------------------------------------------------------------

### ARTIFACT_MISSING

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Multiple stages:

- Stage-1 Artifact Gate (line ~347): `results_tradelevel.csv` missing after execution
- Stage-2 Artifact Gate (line ~378): `AK_Trade_Report_*.xlsx` missing
- Stage-3 Artifact Gate (line ~386): `Strategy_Master_Filter.xlsx` missing
- Stage-3A Artifact Binding (line ~478): Required artifacts for manifest missing
- Pre-Stage-4 Manifest Verification (line ~544): Artifact file missing during hash check
- Stage-4 Artifact Gate (line ~561): `Master_Portfolio_Sheet.xlsx` missing

**Detection Mechanism:**  
Physical file existence check via `Path.exists()` returns `False`.

**Structural Meaning:**  
A required output from a prior stage was not produced. This can indicate:

- Strategy produced zero trades (Stage-1)
- Stage-2 compiler failed silently
- Stage-3 aggregator failed
- Artifact was deleted between stages

**Allowed Actions:**  

- Report which artifact is missing and which stage gate detected it  
- Check process exit codes for the producing stage  
- Check for zero-trade conditions (NO_TRADES)

**Forbidden Actions:**  

- Do NOT create placeholder artifacts  
- Do NOT skip the gate  
- Do NOT mark the stage as complete without the artifact

**Deterministic Recovery Path:**  

1. If Stage-1 NO_TRADES:
   - Verify HollowDetector did NOT trigger at Stage-0.5
   - If HollowDetector passed → legitimate zero-trade scenario (strategy parameters too restrictive for this symbol/period)
   - If HollowDetector failed → PROVISION_REQUIRED
2. If Stage-2/3/4 process failed: check stderr for root cause
3. Re-run pipeline with `--force` after root cause is addressed

**Escalation Required:** YES if hollow strategy. YES if persistent NO_TRADES across all symbols (may indicate strategy logic review needed). NO if process crash (environmental).

------------------------------------------------------------

### STATE_TRANSITION_INVALID

------------------------------------------------------------

**Trigger Location:**  
`tools/pipeline_state.py` → Any stage transition

**Detection Mechanism:**  
`PipelineStateManager.transition_to()` or `DirectiveStateManager.transition_to()` receives a state that is not a valid forward transition from the current state.

**Structural Meaning:**  
The pipeline attempted an illegal state transition, indicating:

- A stage was skipped
- A completed stage was re-entered
- A FAILED run was not reset before retry

**Allowed Actions:**  

- Report current state and attempted transition  
- Check if `--force` was used for a FAILED directive

**Forbidden Actions:**  

- Do NOT manually edit `run_state.json`  
- Do NOT manually edit `directive_state.json`  
- Do NOT delete state files to "reset"

**Deterministic Recovery Path:**  

1. If directive is FAILED: use `--force` to reset to INITIALIZED
2. If individual run has bad state: investigate what caused the premature transition
3. If state file is corrupted: a full re-provision is required

**Escalation Required:** YES — State corruption requires human judgment

------------------------------------------------------------

### EXECUTION_ERROR

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Stage-0.75 (dry-run), Stage-1, Stage-2, Stage-3, Stage-4

**Detection Mechanism:**  

- Subprocess returns non-zero exit code
- Python exception raised during execution
- Strategy `prepare_indicators()` or `check_entry()` crashes (Stage-0.75)
- Engine execution loop raises (Stage-1)

**Structural Meaning:**  
A runtime error occurred during execution. This is distinct from governance violations — the code ran but encountered an unexpected condition.

**Allowed Actions:**  

- Report the full exception and traceback  
- Identify which symbol/stage/bar caused the crash  
- Check for data issues (missing columns, NaN values)

**Forbidden Actions:**  

- Do NOT retry blindly  
- Do NOT suppress the exception  
- Do NOT modify the execution engine

**Deterministic Recovery Path:**  

1. Read the exception message and traceback
2. Fix the root cause (strategy bug, data issue, indicator error)
3. Re-run with `--force`

**Escalation Required:** Depends on root cause classification

------------------------------------------------------------

### STAGE_3_CARDINALITY_MISMATCH

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Stage-3 Gate (line ~418)

**Detection Mechanism:**  
Row count in `Strategy_Master_Filter.xlsx` for the current `clean_id` does not equal the number of declared symbols.

**Structural Meaning:**  
Stage-3 aggregation produced an incorrect number of rows. Either:

- Some symbols were not aggregated
- Duplicate rows were inserted
- A prior run's rows were not cleaned

**Allowed Actions:**  

- Report expected vs actual count  
- Check Stage-3 compiler output for errors  
- Check if any symbol runs are in FAILED state

**Forbidden Actions:**  

- Do NOT manually add/remove rows from `Strategy_Master_Filter.xlsx`  
- Do NOT delete the Master Filter file  
- Do NOT modify the cardinality check threshold

**Deterministic Recovery Path:**  

1. Verify all symbol runs reached STAGE_2_COMPLETE
2. If some runs FAILED: fix root cause, re-run with `--force`
3. If aggregator logic is incorrect: fix `stage3_compiler.py`

**Escalation Required:** YES — Ledger integrity investigation required

------------------------------------------------------------

### STAGE_4_LEDGER_MISMATCH

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Stage-4 Gate (lines ~595–623)

**Detection Mechanism:**  
Any of:

- `Master_Portfolio_Sheet.xlsx` is empty (0 data rows)
- Portfolio ID (`clean_id`) not found or found more than once
- Constituent run ID count does not match symbol count

**Structural Meaning:**  
Stage-4 portfolio evaluator either failed to append to the Master Ledger, or appended duplicate/malformed data.

**Allowed Actions:**  

- Report exact validation failure  
- Check Stage-4 process output for errors  
- Verify portfolio evaluator input data

**Forbidden Actions:**  

- Do NOT manually edit `Master_Portfolio_Sheet.xlsx`  
- Do NOT delete ledger entries  
- Do NOT re-run portfolio evaluator without understanding the duplicate/missing condition

**Deterministic Recovery Path:**  

1. If missing: check portfolio_evaluator.py stderr for crash
2. If duplicate: ledger integrity is compromised — human investigation required
3. After root cause fix: full re-provision with `--force`

**Escalation Required:** YES — Ledger is append-only and authoritative

------------------------------------------------------------

### SNAPSHOT_INTEGRITY_MISMATCH

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Stage-3A (line ~456)

**Detection Mechanism:**  
SHA-256 hash of `runs/<RUN_ID>/strategy.py` does not match SHA-256 hash of `strategies/<STRATEGY_ID>/strategy.py`.

**Structural Meaning:**  
The strategy snapshot taken at run time does not match the current source strategy. This means either:

- Source strategy was modified after snapshot was taken
- Snapshot file was corrupted or tampered with

**Allowed Actions:**  

- Report both hash values  
- Compare file contents to identify the diff  
- Determine which version was used during execution

**Forbidden Actions:**  

- Do NOT overwrite the snapshot  
- Do NOT modify the source to match the snapshot  
- Do NOT skip the hash check

**Deterministic Recovery Path:**  

1. Determine if source strategy was modified after Stage-1 execution
2. If source changed: the run is invalid — full re-provision with `--force` required
3. If snapshot corrupted: the run is invalid — full re-provision with `--force` required

This is NOT recoverable by partial rerun. Full re-provision is the only valid path.  
All stages from Stage-0 onward must re-execute.

**Escalation Required:** YES — This is a potential integrity violation

------------------------------------------------------------

### MANIFEST_TAMPER_DETECTED

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Pre-Stage-4 Verification (lines ~538–552)

**Detection Mechanism:**  
Any of:

- Manifest key set does not match expected artifact set (`results_tradelevel.csv`, `results_standard.csv`, `batch_summary.csv`)
- Re-computed SHA-256 hash of an artifact does not match the hash stored in `STRATEGY_SNAPSHOT.manifest.json`

**Structural Meaning:**  
Artifacts were modified or replaced after the manifest was bound. This is a critical integrity violation.

**Allowed Actions:**  

- Report which artifact(s) have hash mismatches  
- Report the expected vs current hash values  
- Identify when the file was last modified (filesystem timestamp)

**Forbidden Actions:**  

- Do NOT re-bind the manifest with new hashes  
- Do NOT delete the manifest  
- Do NOT proceed to Stage-4  
- Do NOT modify the artifact to restore the original hash

**Deterministic Recovery Path:**  

1. Full re-provision with `--force` is the only valid path
2. All artifacts from Stage-1 onward will be regenerated
3. Manifests will be rebound with fresh hashes

**Escalation Required:** YES — Tamper detection is a critical security event

------------------------------------------------------------

### FILTERSTACK_ARCHITECTURAL_VIOLATION

------------------------------------------------------------

**Trigger Location:**  
`tools/semantic_validator.py` → Stage-0.5 (BehavioralGuard)

**Detection Mechanism:**  
Any of:

- `from engines.filter_stack import FilterStack` missing
- `self.filter_stack = FilterStack(...)` not in `__init__`
- `self.filter_stack.allow_trade(...)` not called in `check_entry`
- Hardcoded regime comparison detected (direct `row["regime"] == X` patterns)

**Structural Meaning:**  
The strategy bypasses the FilterStack abstraction layer and directly accesses regime data. This violates the architectural separation enforced by STRATEGY_PLUGIN_CONTRACT.md.

**Allowed Actions:**  

- Report the specific violation  
- Identify the violating line(s) in strategy code

**Forbidden Actions:**  

- Do NOT add FilterStack calls automatically  
- Do NOT remove the BehavioralGuard check  
- Do NOT allow execution to proceed

**Deterministic Recovery Path:**  

1. Modify strategy to use FilterStack for all regime-dependent gating
2. Remove hardcoded regime comparisons
3. Human approves updated strategy (Admission Gate)
4. Re-run pipeline

**Escalation Required:** YES — Strategy must be corrected by human

------------------------------------------------------------

### HOLLOW_STRATEGY_DETECTED

------------------------------------------------------------

> **Subtype of PROVISION_REQUIRED.** This is the specific detection mechanism name.
> All rules, allowed actions, forbidden actions, and recovery path are identical to PROVISION_REQUIRED above.
> Canonical classification: **PROVISION_REQUIRED**.

------------------------------------------------------------

### DRYRUN_CRASH

------------------------------------------------------------

**Trigger Location:**  
`tools/strategy_dryrun_validator.py` → Stage-0.75

**Detection Mechanism:**  
Any of:

- Strategy class fails to import or instantiate
- `prepare_indicators(df)` raises an exception
- `check_entry(ctx)` raises an exception on any bar

**Structural Meaning:**  
The strategy code has a runtime bug that will crash Stage-1. This is caught early with a 1000-bar sample before committing to full execution.

**Allowed Actions:**  

- Report the full exception  
- Report which method crashed and on which bar (for check_entry)

**Forbidden Actions:**  

- Do NOT fix the strategy code automatically  
- Do NOT bypass the dry-run  
- Do NOT proceed to Stage-1

**Deterministic Recovery Path:**  

1. Read the exception and fix the strategy bug
2. Human approves the fix (Admission Gate)
3. Re-run pipeline

**Escalation Required:** YES — Strategy bug requires human fix

------------------------------------------------------------

### INDICATOR_IMPORT_MISMATCH

------------------------------------------------------------

**Trigger Location:**  
`tools/semantic_validator.py` → Stage-0.5

**Detection Mechanism:**  

- Declared indicators (from directive) that are not imported in strategy code → `Missing Indicator Import(s)`
- Imported indicators (in strategy code) that are not declared in directive → `Undeclared Indicator Import(s)`

**Structural Meaning:**  
The strategy's imports do not match the directive's declared indicator set. Exact set equality is required.

**Allowed Actions:**  

- Report missing or undeclared imports  
- Compare directive indicator list vs strategy import statements

**Forbidden Actions:**  

- Do NOT add imports automatically  
- Do NOT remove undeclared imports  
- Do NOT modify the directive's indicator list

**Deterministic Recovery Path:**  

1. Align strategy imports with directive indicators
2. If directive is wrong: fix directive (requires re-provision)
3. If strategy imports are wrong: fix strategy imports

**Escalation Required:** YES — Requires human judgment on which is correct

------------------------------------------------------------

### PREFLIGHT_FAILURE

------------------------------------------------------------

**Trigger Location:**  
`tools/exec_preflight.py` → Stage-0 (via `governance/preflight.py`)

**Detection Mechanism:**  
`run_preflight()` returns decision != `ALLOW_EXECUTION`. Process exits with code 1.

**Structural Meaning:**  
One or more preflight checks failed:

- Strategy file missing or unimportable
- Indicator modules missing
- Engine version mismatch
- Broker spec missing
- Directive malformed

**Allowed Actions:**  

- Report the preflight decision and explanation  
- Check strategy provisioner output

**Forbidden Actions:**  

- Do NOT skip preflight  
- Do NOT force-pass preflight

**Deterministic Recovery Path:**  

1. Read the explanation from preflight output
2. Address the specific missing dependency
3. Re-run pipeline

**Escalation Required:** Depends on failure type

------------------------------------------------------------

### DATA_LOAD_FAILURE

------------------------------------------------------------

**Trigger Location:**  
`tools/run_stage1.py` → Stage-1 (`load_market_data`)

**Detection Mechanism:**  

- No RESEARCH CSV files found for symbol/broker/timeframe combination
- CSV parsing failure
- Conversion data missing for cross-pair PnL normalization

**Structural Meaning:**  
Market data for the requested symbol is not available in the MASTER_DATA repository, or the data pipeline has not provisioned it.

**Allowed Actions:**  

- Report the missing data path  
- Check if data exists for other timeframes/brokers

**Forbidden Actions:**  

- Do NOT fabricate data  
- Do NOT use CLEAN data as fallback (RESEARCH only)  
- Do NOT download data during execution

**Deterministic Recovery Path:**  

1. Run `raw_update_sop17.py` to backfill the missing data
2. Run data cleaning and research pipeline
3. Re-run strategy pipeline

**Escalation Required:** NO — Data provisioning is a separate workflow

------------------------------------------------------------

### TRADE_PAYLOAD_SCHEMA_VIOLATION

------------------------------------------------------------

**Trigger Location:**  
`tools/run_stage1.py` → Stage-1 (`execution_loop.py`) or `tools/strategy_dryrun_validator.py` → Stage-0.75

**Detection Mechanism:**  
Engine crashes with errors like `CRITICAL: Trade X missing 'volatility_regime'` or `KeyError` on expected market state fields.

**Structural Meaning:**  
The strategy correctly fired trades, but the resulting trade payload or context lacks mandatory keys required by the engine or downstream ledgers. Often caused by failing to include required metadata indicators (e.g., `volatility_regime`, `trend_regime`) in the directive or failing to attach them to the dataframe in `prepare_indicators()`.

**Allowed Actions:**  

- Report the missing keys or payload properties.
- Check the strategy's `prepare_indicators` logic against the directive's indicator list.

**Forbidden Actions:**  

- Do NOT auto-inject indicators into the directive.
- Do NOT inject defaults to bypass schema requirements.

**Deterministic Recovery Path:**  

1. Human updates the directive to include required state indicators (if missing).
2. Human updates `strategy.py`'s `prepare_indicators` to correctly calculate and attach the indicator outputs to `df`.
3. Re-run pipeline (`--force`).

**Escalation Required:** YES — Strategy code or directive must be fixed by human.

------------------------------------------------------------

### INDICATOR_SERIES_OVERWRITE

------------------------------------------------------------

**Trigger Location:**  
`tools/strategy_dryrun_validator.py` → Stage-0.75 or `tools/run_stage1.py` → Stage-1

**Detection Mechanism:**  
`KeyError: 'close'` or similar missing core OHLCV column errors during `prepare_indicators` or subsequent indicator calls.

**Structural Meaning:**  
A classic human authoring mistake where an indicator returning a `pd.Series` (like `atr`) is assigned over the entire dataframe (`df = atr(df)` instead of `df['atr'] = atr(df)`). This destroys the OHLCV structure required by subsequent logic.

**Allowed Actions:**  

- Report the exact line in `prepare_indicators` where the dataframe structure is lost.

**Forbidden Actions:**  

- Do NOT auto-patch the strategy without approval (unless explicitly authorized for surgical fixes).

**Deterministic Recovery Path:**  

1. Human reviews and fixes the variable assignment in `prepare_indicators`.
2. Human approves the strategy (Admission Gate).
3. Re-run pipeline.

**Escalation Required:** YES — Strategy bug requires human fix.

---

## ENGINE ARCHITECTURE STANDARDS (MANDATORY)

Purpose: Prevent structural drift, shadow routing, and split execution authority.

These rules are non-negotiable.

------------------------------------------------------------

### 1. Version Namespace Validity

Engine version folders inside:

engine_dev/universal_research_engine/

MUST follow this exact pattern:

v<major>_<minor>_<patch>

Example:

- v1_4_0  ✅
- 1.4.0   ❌
- 1_4_0   ❌
- version1_4_0 ❌

If a version folder cannot be imported via native Python syntax,
the architecture is invalid.

------------------------------------------------------------

### 2. No Engine Core Import Bypass

The following is strictly forbidden for engine core modules:

importlib.util.spec_from_file_location

Dynamic filesystem injection is permitted ONLY for strategy plugins.

All engine execution components MUST be imported using standard syntax:

from engine_dev.universal_research_engine.vX_Y_Z.<module> import ...

If dynamic loading is detected for engine core → HARD FAIL.

------------------------------------------------------------

### 3. Single Execution Authority

At runtime, the following modules MUST resolve inside the active version folder:

- execution_loop
- execution_emitter_stage1
- stage2_compiler

If any resolve outside the active version directory → HARD FAIL.

Split execution authority is prohibited.

------------------------------------------------------------

### 4. Engine Self-Containment Doctrine

An engine version folder MUST be fully self-contained for:

- Stage-1 execution loop
- Stage-1 artifact emission
- Stage-2 compilation

No execution lifecycle component may depend on unversioned global modules.

------------------------------------------------------------

### 5. Shadow Core Prohibition

Core execution files MUST NOT exist in multiple active locations
in a way that allows silent fallback.

If duplicate filenames exist across:

- engine_dev/
- tools/

Runtime must explicitly bind to the version folder.

Implicit fallback to global modules is prohibited.

------------------------------------------------------------

### 6. Manifest Localization & Strict Integrity

engine_manifest.json MUST reside inside the active version folder.

verify_engine_integrity.py MUST:

- Hash only files inside the active version directory
- Fail strictly if manifest is missing
- Fail strictly on any SHA-256 mismatch
- Never downgrade to WARN

------------------------------------------------------------

### 7. Vault Non-Authority Doctrine

Vault snapshots are non-authoritative for execution.
They are recovery artifacts only.

---

## FAILURE ESCALATION MATRIX

| Category | Failure Classes | Recovery Authority |
|:---|:---|:---|
| **Strategy Authoring Error** | PROVISION_REQUIRED, HOLLOW_STRATEGY_DETECTED, DRYRUN_CRASH, FILTERSTACK_ARCHITECTURAL_VIOLATION, TRADE_PAYLOAD_SCHEMA_VIOLATION, INDICATOR_SERIES_OVERWRITE | Human — strategy logic must be authored/corrected |
| **Data Issue** | DATA_LOAD_FAILURE, ARTIFACT_MISSING (NO_TRADES from bad data) | Data pipeline — re-ingest via SOP_17 |
| **Governance Violation** | SCHEMA_VIOLATION, INDICATOR_IMPORT_MISMATCH, FILTERSTACK_ARCHITECTURAL_VIOLATION | Human — must align strategy with directive |
| **Artifact Corruption** | MANIFEST_TAMPER_DETECTED, ARTIFACT_MISSING (post-creation) | Full re-provision (`--force`) |
| **State Corruption** | STATE_TRANSITION_INVALID | Human investigation + `--force` reset |
| **Environmental Failure** | PREFLIGHT_FAILURE, DATA_LOAD_FAILURE | Fix environment, then re-run |
| **Requires Triage** | EXECUTION_ERROR | Subclassify after traceback inspection: may be Strategy Authoring Error, Data Issue, or Environmental Failure |
| **Ledger Integrity** | STAGE_3_CARDINALITY_MISMATCH, STAGE_4_LEDGER_MISMATCH, SNAPSHOT_INTEGRITY_MISMATCH | Human investigation — ledger is authoritative |

---

**End of AGENT.md — Failure Classification & Rectification Playbook v1**
