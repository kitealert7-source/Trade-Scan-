# FAILURE_PLAYBOOK.md — Pipeline Failure Classification & Rectification

**Authority:** `AGENT.md` — read invariants and lifecycle there first
**Status:** DIAGNOSTIC ONLY — No mutation authority
**Scope:** All pipeline failures in run_pipeline.py orchestrated execution

> [!IMPORTANT]
> Read AGENT.md before using this playbook.
> Every recovery path assumes you have already stopped execution (Fail-Fast).
> Do not attempt ad-hoc fixes. Follow the deterministic recovery path exactly.

---

## Stable API Contract

The `### SECTION_NAME` headings below are **stable identifiers** — not documentation labels.
They appear verbatim in pipeline code (`semantic_validator.py`, `pipeline_utils.py`,
`stage_preflight.py`) and in audit logs.

Rules:
- **NEVER rename** an existing class — it will silently break code and log parsing
- **NEVER change casing** — these identifiers are case-sensitive and must match exactly across code, logs, and tests
- To deprecate: add a new class, mark the old entry `[DEPRECATED — superseded by NEW_NAME]`, keep the old entry in place
- Any rename requires a simultaneous change in code + tests in the same commit

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
3. Re-execute pipeline: `python tools/run_pipeline.py <DIRECTIVE>`
   (If state is FAILED, human must first run `python tools/reset_directive.py <ID> --reason "strategy authored"`)

**Escalation Required:** YES — Human must author strategy logic

------------------------------------------------------------

### SCHEMA_VIOLATION

------------------------------------------------------------

**Trigger Location:**  
`tools/semantic_validator.py` → Stage-0.5

**Detection Mechanism:**  
Any of:

- `signature_version` in strategy does not match `SIGNATURE_SCHEMA_VERSION` (currently `2`, defined in `tools/directive_schema.py`)
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
2. If directive changed: re-provision strategy (human resets via `tools/reset_directive.py`)
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
3. After root cause is addressed: reset via `python tools/reset_directive.py <ID> --reason "<fix description>"` then re-run pipeline

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

1. If directive is FAILED: reset via `python tools/reset_directive.py <ID> --reason "<justification>"`
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
3. Reset via `python tools/reset_directive.py <ID> --reason "<fix description>"` then re-run pipeline

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
2. If some runs FAILED: fix root cause, reset via `reset_directive.py --reason`, then re-run
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

> Subtype of **PROVISION_REQUIRED** above. Same rules, actions, and recovery path apply.

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
3. Reset via `python tools/reset_directive.py <ID> --reason "<fix description>"` then re-run pipeline.

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

------------------------------------------------------------

### MISSING_BROKER_SPECIFICATION

------------------------------------------------------------

**Trigger Location:**  
`tools/run_stage1.py` → Stage-1 (`load_broker_spec`)

**Detection Mechanism:**  

- `FileNotFoundError: Broker spec not found: broker_specs/OctaFX/<SYMBOL>.yaml`
- `ValueError: Broker spec missing mandatory field: min_lot` (or other schema fields)

**Structural Meaning:**  
Having historical CSV data in the `data_root` is not enough to execute a new symbol. The engine requires a strictly formatted YAML specification for the broker to understand contract sizes, tick values, and cost models.

**Allowed Actions:**  

- Identify which symbol/broker combination is missing the `.yaml` file.
- Identify which schema fields are missing if the file exists.

**Forbidden Actions:**  

- Do NOT proceed with Stage-1 execution if the broker spec is missing or malformed.
- Do NOT use a hardcoded default configuration in place of the YAML definition.

**Deterministic Recovery Path:**  

1. Create the missing `<SYMBOL>.yaml` file in `data_access/broker_specs/<BROKER>/`
2. Ensure ALL mandatory schema fields are populated: `min_lot`, `lot_step`, `max_lot`, `cost_model`, `precision`, `tick_size`, `pip_size`, `margin_currency`, `profit_currency`, and the `calibration` block.
3. Reset via `python tools/reset_directive.py <ID> --reason "broker spec added"` then re-run pipeline.

**Escalation Required:** NO — Broker specs are defined statically.

------------------------------------------------------------

### ORPHANED_MASTER_LEDGER_ENTRIES

------------------------------------------------------------

**Trigger Location:**  
`tools/run_pipeline.py` → Stage-3 Gate (Cardinality Mismatch)

**Detection Mechanism:**  
Stage-3 throws `[FATAL] Stage-3 cardinality mismatch: expected X, found Y for <STRATEGY_ID>` where Y > X.

**Structural Meaning:**  
A previous execution attempt created rows in `Strategy_Master_Filter.xlsx` that were not automatically wiped when local `runs/` or `backtests/` directories were deleted. Because the ledger is persistent, the orphaned rows caused the aggregator to miscount the active artifacts.

**Allowed Actions:**  

- Read the master ledger `Strategy_Master_Filter.xlsx` to identify the corrupted/stale rows for the active `STRATEGY_ID`.
- Purge the specific rows belonging to the active `STRATEGY_ID` prefix.

**Forbidden Actions:**  

- Do NOT delete the entire `Strategy_Master_Filter.xlsx` file.
- Do NOT delete rows belonging to other strategies.
- Do NOT bypass the Stage-3 cardinality check.

**Deterministic Recovery Path:**  

1. Deleting local `runs/` and `backtest/` folders is insufficient for a full reset.
2. Programmatically drop all rows matching `strategy.startswith(<STRATEGY_ID>)` from `backtests/Strategy_Master_Filter.xlsx`.
3. Re-run the pipeline.

**Escalation Required:** NO — Routine artifact cleanup.

------------------------------------------------------------

### IDEMPOTENT_OVERWRITE_LOCK

------------------------------------------------------------

**Trigger Location:**  
`tools/portfolio_evaluator.py` → Stage-4 (`update_master_portfolio_ledger`)

**Detection Mechanism:**  
`ValueError: [FATAL] Attempted modification of existing portfolio entry '<STRATEGY_ID>'. Explicit human authorization required. No automatic overwrite allowed.`

**Structural Meaning:**  
Stage-4 detected that `Master_Portfolio_Sheet.xlsx` already contains a historical record for this exact `portfolio_id`. Output from a previous test block. The engine strictly forbids auto-overwrites.

**Allowed Actions:**  

- Read the master portfolio ledger to confirm the presence of the colliding `portfolio_id`.
- Programmatically drop the single legacy historical record with the exact `STRATEGY_ID` to allow the new result batch to write.

**Forbidden Actions:**  

- Do NOT modify the `update_master_portfolio_ledger` function to bypass the overwrite restriction.
- Do NOT delete the entire `Master_Portfolio_Sheet.xlsx` file.

**Deterministic Recovery Path:**  

1. Evaluate if the previous portfolio record was a failed test run or temporary cache.
2. Manually or programmatically purge the existing row from `strategies/Master_Portfolio_Sheet.xlsx`.
3. Re-run `tools/portfolio_evaluator.py <STRATEGY_ID>` or re-execute the final pipeline pass.

**Escalation Required:** NO — Handled via standard reset protocols.

## FAILURE ESCALATION MATRIX

| Category | Failure Classes | Recovery Authority |
|:---|:---|:---|
| **Strategy Authoring Error** | PROVISION_REQUIRED, HOLLOW_STRATEGY_DETECTED, DRYRUN_CRASH, FILTERSTACK_ARCHITECTURAL_VIOLATION, TRADE_PAYLOAD_SCHEMA_VIOLATION, INDICATOR_SERIES_OVERWRITE | Human — strategy logic must be authored/corrected |
| **Data Issue** | DATA_LOAD_FAILURE, ARTIFACT_MISSING (NO_TRADES from bad data) | Data pipeline — re-ingest via SOP_17 |
| **Governance Violation** | SCHEMA_VIOLATION, INDICATOR_IMPORT_MISMATCH, FILTERSTACK_ARCHITECTURAL_VIOLATION | Human — must align strategy with directive |
| **Artifact Corruption** | MANIFEST_TAMPER_DETECTED, ARTIFACT_MISSING (post-creation) | Full re-provision |
| **State Corruption** | STATE_TRANSITION_INVALID | Human investigation + `reset_directive.py` |
| **Environmental Failure** | PREFLIGHT_FAILURE, DATA_LOAD_FAILURE | Fix environment, then re-run |
| **Requires Triage** | EXECUTION_ERROR | Subclassify after traceback inspection: may be Strategy Authoring Error, Data Issue, or Environmental Failure |
| **Ledger Integrity** | STAGE_3_CARDINALITY_MISMATCH, STAGE_4_LEDGER_MISMATCH, SNAPSHOT_INTEGRITY_MISMATCH | Human investigation — ledger is authoritative |
| **Post-Pipeline (Non-Fatal)** | REPORT_GENERATION_FAILURE, CAPITAL_WRAPPER_FAILURE, DEPLOYABLE_INTEGRITY_FAILURE, ROBUSTNESS_EVALUATION_FAILURE | Do NOT invalidate directive. Report error. Do NOT downgrade PORTFOLIO_COMPLETE. |

---

## OPERATIONAL NOTES (Session Discoveries)

### 5M Data Path — 2026-04-20

**Discovery:** XAUUSD 5M RESEARCH data exists at the correct path but was missed by
filename grep (`grep 5m` matches `15m`). Always search with exact token `_5m_`.

**Correct path:** `Anti_Gravity_DATA_ROOT/MASTER_DATA/XAUUSD_OCTAFX_MASTER/RESEARCH/XAUUSD_OCTAFX_5m_YYYY_RESEARCH.csv`

**Available years:** 2024, 2025, 2026

**Root cause:** `ls | grep 5m` matches `15m` first; `grep _5m_` or `ls | grep "_5m_"` returns correct files only.

**Rule:** When loading sub-hourly XAUUSD data, always use `_5m_` as the exact search token, not `5m`.

---

### Missing Indicator Source Files — 2026-04-20

**Discovery:** `indicators/trend/ema_cross.py` and `indicators/momentum/macd.py` source files
are absent. Only `.pyc` bytecode remains in `__pycache__/`. Strategy `54_STR_XAUUSD_5M_MACDX_S21_V1_P00`
imports both and fails at load time.

**Symptom:** `ModuleNotFoundError: No module named 'indicators.trend.ema_cross'` (and `.momentum.macd`)

**Impact:** Any strategy using `ema_cross` or `macd` will fail at Stage-0.5 or at runtime
`prepare_indicators()`. Pipeline aborts with EXECUTION_ERROR.

**Recovery:** Restore `ema_cross.py` and `macd.py` from git history or re-implement from `.pyc`.
Do NOT use `.pyc` as source substitute.

**Classification:** EXECUTION_ERROR -> Environmental Failure (missing indicator modules)

---

