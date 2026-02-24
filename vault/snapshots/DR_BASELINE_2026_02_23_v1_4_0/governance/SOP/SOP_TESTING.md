# SOP_TESTING — Backtest Execution & Stage-1 Artifact Authority

**Stage:** BACKTESTING  
**Applies to:** Trade_Scan  
**Status:** AUTHORITATIVE | ACTIVE  
**Companion SOP:** SOP_OUTPUT — VERSION 4.2 (POST_BACKTEST)

---

## 1. Purpose

This SOP governs **execution‑time behavior only**.

Trade_Scan:

- reads human-written directives
- executes back tests
- computes execution metrics
- emits Stage-1 artifacts
- participates in pipeline finalization through Stage-3A snapshot enforcement
- stops

All post‑execution presentation, aggregation, and reporting are governed by **SOP_OUTPUT — VERSION 4.1**.

---

## 2. Authority Model

All decisions are made by **humans**.

Trade_Scan has **no authority** to:

- decide what to back test
- expand scope
- judge outcomes
- promote results
- continue autonomously

Trade_Scan exists only while executing explicit instructions.

---

## 3. Directive Lifecycle

### 3.1 Directive Source

Executable directives MUST reside in:

```
backtest_directives/active/
```

Execution may be:

- Single-directive mode (explicit ID)
- Sequential batch mode (`--all`)

---

### 3.2  Authoritative Execution Entry Point

Execution is directive-explicit and does not rely on folder isolation.

All executions MUST be initiated via:

```
python tools/run_pipeline.py <DIRECTIVE_ID>
```

or

```
python tools/run_pipeline.py --all
```

Direct invocation of individual stage scripts (run_stage1.py, stage2_compiler.py, stage3_compiler.py, apply_portfolio_constraints.py, portfolio_evaluator.py) is prohibited for full multi-asset runs.

The pipeline orchestrator is the sole authorized execution entry point.

---

### 3.3 Directive Completion & State Transition

Upon atomic completion of all declared execution phases:
Execution phases include Stage-3A Strategy Snapshot Finalization.

Directive state transition to `completed_run/` MUST occur only after snapshot creation succeeds.

The processed directive MUST be moved to:

```
backtest_directives/completed_run/
```

If execution fails or is interrupted:

- The directive MUST remain in `active/`
- No partial completion is permitted
- No artifacts may be considered authoritative

Overwrite of previously completed directives is permitted in research mode, as execution is deterministic and reproducible.

---

## 4. Execution Model

> **Authoritative Market Data Rule:** All Stage-1 executions MUST use **RESEARCH** market data. CLEAN or derived datasets are non-authoritative and MUST NOT be used for execution or metric computation.

Execution flow is deterministic and pipeline-driven:

1. Preflight validation (governance + safety).
2. Directive validation.
3. Enforcement of STRATEGY_PLUGIN_CONTRACT.md.
4. Enforcement of SOP_INDICATOR.md (repository-only indicators; no inline logic).
5. Stage-1 execution (including declared deterministic constraints).
6. Stage-2 compilation.
7. Stage-3 aggregation.
8. Stage-3A Strategy Snapshot Finalization (including indicator dependency fingerprinting).
9. Portfolio evaluation (if applicable).
10. Stop.

There is:

- no autonomous continuation
- no implicit rerun
- no partial execution
- no pipeline skipping

Vault is not accessed during normal execution and must not influence pipeline behavior.

---

## 4A. Stage-0.5 — Strategy Semantic Validation (MANDATORY)

Stage-0.5 executes after Preflight and before Stage-1.

Stage-1 MUST NOT execute unless Stage-0.5 passes.

This is  Directive-Driven Model

- Strategy folders are engine-managed artifacts.
- Preflight may create or modify strategy code to align with directive.
- Stage-0.5 validates final strategy state against directive.
- Stage-0.5 does NOT generate or modify code.

---

### Provisioning Model (Stage-0 Responsibility

During Preflight:

1. If `strategies/<StrategyName>/` does NOT exist:
   - Create folder.
   - Generate `strategy.py` from canonical template.
   - Embed structured `STRATEGY_SIGNATURE` block.
   - Log provisioning event.

2. If strategy exists:
   - Engine MAY modify strategy deterministically to align with directive.
   - Modifications must be idempotent.
   - No manual edits are preserved if conflicting with directive.

Preflight MUST complete before Stage-0.5 executes.

---

### Strategy Execution Admission Rule (MANDATORY)

Pipeline execution is **prohibited** when:

- A new directory is created under `strategies/`, OR
- Any `strategy.py` inside `strategies/` is modified with a **logic-affecting change**

AND explicit human approval has **not** been granted.

**Logic-affecting modification** includes any change that can alter:

- Entry or exit conditions
- Indicator calculations or wiring
- Filter stack composition
- Parameter default values
- Regime classification logic
- Position sizing or risk logic

**Explicitly excluded** (no approval required):

- Formatting and whitespace changes
- Comments and docstrings
- Non-executable metadata
- `STRATEGY_SIGNATURE` block updates that are deterministically derived from directive

The agent MUST stop and request human approval before proceeding with pipeline execution when a logic-affecting change is detected. This gate is pre-FSM and purely procedural.

---

### Stage-0.5 Validation Scope

Stage-0.5 SHALL validate:

1. Strategy Identity
   - `Strategy.name` matches directive.
   - `Strategy.timeframe` matches directive.

2. STRATEGY_SIGNATURE Integrity
   - Extract `STRATEGY_SIGNATURE` object from strategy.
   - Compare strictly against directive spec:
       - Indicators
       - Parameters
       - Timeframe
       - Trade limits
       - Filters

3. Indicator Module Identity
   - Imported indicator modules must exactly match declared modules.
   - Exact set equality required.

Mismatch → HARD FAIL.

No auto-correction.
No mutation.
No warnings.

Stage-0.5 is validation only.

---

### Failure Rule

On failure:

- Transition to FAILED
- Abort run
- Emit no artifacts
- Directive remains in `active/`

---

### Boundary

Stage-0.5:

- Does NOT execute strategy logic
- Does NOT recompute indicators
- Does NOT evaluate trade results
- Does NOT modify strategy code
- Does NOT enforce runtime constraints

It is a pre-execution structural identity check only.

---

## 5. Strategy Folder & Artifact Authority (LOCKED)

For each run, Trade_Scan MUST:

- Create one run output folder named exactly as the human-defined Strategy Name
- Place it under:

```
backtests/<strategy_name>/
```

This folder is the **sole authoritative container** for the run.

### RUN_COMPLETE Rule

A run is `RUN_COMPLETE` only if:

- Stage-1 execution completes successfully
- Stage-2 compilation completes successfully
- Stage-3 aggregation completes successfully
- Stage-3A Strategy Snapshot Finalization completes successfully

If snapshot creation fails:

- RUN_COMPLETE MUST NOT be emitted
- No artifacts are authoritative
- No directive state transition may occur
- No index update may occur

RUN_COMPLETE is atomic across all declared pipeline stages.

---

## 6. Stage‑1 Artifact Authority (EXECUTION LAW)

Stage‑1 artifacts:

- define execution truth
- define execution schema
- are immutable after RUN_COMPLETE
- must be sufficient for exact reproduction

Stage‑2 and Stage‑3:

- MUST NOT recompute execution metrics already present in Stage-1 artifacts.
- MAY aggregate only as allowed by SOP_OUTPUT — VERSION 4.1

---

## 7. Stage‑1 Trade‑Level Schema (AUTHORITATIVE — VERSION 2.0)

This defines the complete and authoritative Stage-1 trade schema.

Field names and presence MUST match SOP_OUTPUT.

Any change to this schema or its computation constitutes **engine evolution** and requires a new engine identity per SOP_AGENT_ENGINE_GOVERNANCE.

- Engine version increment
- Snapshot fingerprint update
- Governance compliance under SOP_AGENT_ENGINE_GOVERNANCE

### Core Identity & Timing

- strategy_name
- parent_trade_id
- sequence_index
- entry_timestamp
- exit_timestamp

### Trade Semantics

- direction
- entry_price
- exit_price
- pnl_usd
- bars_held (nullable)

### Risk, Sizing & Exposure

- atr_entry (nullable)
- position_units (nullable)
- notional_usd (nullable)

### Excursion Metrics

- trade_high (nullable)
- trade_low (nullable)
- mfe_price (nullable)
- mae_price (nullable)
- mfe_r (nullable)
- mae_r (nullable)
- r_multiple (nullable)

### Market State Dimensions (MANDATORY)

Market state dimensions are intrinsic execution-time context.

They:

- Are independent of YAML filter activation
- Are computed before execution
- Are captured at entry
- Must not be recomputed post-trade
- Are immutable after RUN_COMPLETE

#### Volatility

- volatility_regime (string: "low" | "normal" | "high")

#### Trend

- trend_score (integer: −5 … +5)
- trend_regime (integer: −2, −1, 0, +1, +2)
- trend_label (string)

Trend classification:

| Condition | trend_regime | trend_label |
|------------|--------------|-------------|
| score ≥ +3 | +2 | strong_up |
| score = +1 or +2 | +1 | weak_up |
| score = 0 | 0 | neutral |
| score = −1 or −2 | −1 | weak_down |
| score ≤ −3 | −2 | strong_down |

### Invariants

- Market state MUST be captured at entry.
- Market state MUST NOT be recomputed in Stage-2 or Stage-3.
- Missing volatility_regime → HARD FAIL.
- Missing trend_regime → HARD FAIL.
- Default fallback values are prohibited.
- Schema changes require engine version increment
- All fields MUST be computed during execution
- All fields MUST be emitted in Stage‑1 artifacts
- Fields MUST NOT be inferred, reconstructed, or recomputed later
- Fields MUST remain immutable after RUN_COMPLETE

### Reproducibility

Given identical directive, engine version, and data:

- volatility_regime
- trend_score
- trend_regime
- trend_label

MUST reproduce identically.

Deviation constitutes engine drift.

------------------------------------------------------------------------

## 7A. Stage-1 Constraint Enforcement (When Declared)

If a directive explicitly declares deterministic execution constraints, including but not limited to:

- Maximum concurrent positions
- Capital exposure limits
- Trade admission rules
- Deterministic filtering conditions

Then constraint enforcement SHALL be considered part of Stage-1 execution.

Stage-1 execution MAY include:

• Raw execution phase  
• Deterministic constraint enforcement phase (if declared)

A run is considered RUN_COMPLETE only after:

- All declared Stage-1 execution phases complete successfully, AND
- Stage-3A Strategy Snapshot Finalization completes successfully.

Stage-1 artifacts become immutable only after all declared execution phases are complete.

------------------------------------------------------------------------

### 7A.1 Artifact Authority

If constraint enforcement is applied:

- The post-constraint results_tradelevel.csv becomes the authoritative Stage-1 artifact.
- The pre-constraint raw execution output MUST be preserved as:

results_tradelevel_raw_snapshot.csv

The raw snapshot is archival only and MUST NOT be used for metric computation.

------------------------------------------------------------------------

### 7A.2 Compliance Clarification

Deterministic constraint enforcement under Stage-1 does NOT constitute:

- Post-hoc filtering
- Data snooping
- Retroactive execution modification

Because it is part of declared execution semantics.

------------------------------------------------------------------------

### 7A.3 Determinism Requirement

Constraint logic MUST:

- Be deterministic
- Use only declared directive parameters
- Be reproducible from raw execution output
- Not introduce probabilistic trade selection

Any change to constraint logic constitutes engine evolution.

## 7B. Stage-1 Stop Contract (MANDATORY)

Stop resolution is part of Stage-1 execution semantics.

At trade entry, engine MUST resolve `initial_stop_price`
using deterministic precedence.

### Stop Resolution Order

1. Strategy Stop (Primary)
   If `check_entry()` returns `stop_price`,
   engine SHALL use it without modification.

2. ATR Fallback (Secondary)
   If strategy does not provide `stop_price`,
   engine MUST compute stop using:
     • ATR value at entry bar
     • Fixed engine ATR multiplier
     • Direction-aware calculation

No additional fallback mechanisms are permitted.

### Determinism

Stop resolution MUST:

- Use entry-bar data only
- Use fixed engine parameters
- Produce identical output given identical directive, engine version, and data

### Hard Fail Conditions

At entry:

- Long → stop_price < entry_price
- Short → stop_price > entry_price
- risk_distance > 0

If ATR fallback is invoked:

- ATR MUST exist
- ATR MUST be > 0

If neither strategy stop nor valid ATR exists → HARD FAIL.

## 8. Capital, Risk & Broker Constraints (LOCKED)

### 8.1 Reference Capital

| Parameter | Requirement |
|---------|-------------|
| reference_capital_usd | Mandatory, explicit |
| Capital role | Measurement only |
| Capital injection/reset | Forbidden |

Drawdown % MUST be computed using `reference_capital_usd`.

---

### 8.2 Broker & Execution Geometry

Broker constraints MUST be loaded from:

```
Trade_Scan/data_access/broker_specs/<BROKER>/<SYMBOL>.yaml
```

Mandatory fields:

- min_lot
- lot_step
- max_lot
- contract_size

No defaults or inference permitted.

---

## 9. Iteration Execution

Iteration is permitted **only if explicitly declared**.

Each iteration:

- is a full folder copy
- is isolated
- is non‑adaptive
- must independently satisfy RUN_COMPLETE

---

## 10. Reproducibility & Data Authority

- Market data is read‑only from the authoritative data root
- Derived data is written only to the strategy folder
- Any violation invalidates the run

---

## 11. Prohibitions (HARD)

Forbidden:

- post‑hoc filtering
- data snooping
- undeclared reruns
- metric inference
- execution schema drift

---

## 12. Handoff to SOP_OUTPUT

Upon RUN_COMPLETE:

- Stage‑2 and Stage‑3 are executed per SOP_OUTPUT — VERSION 4.2
- This SOP governs execution truth through Stage-1 and participates in RUN_COMPLETE validation through Stage-3A snapshot finalization.

All presentation, aggregation, and portfolio synthesis remain governed by SOP_OUTPUT and SOP_PORTFOLIO_ANALYSIS.

---

**End of SOP_TESTING — VERSION 2.1**
