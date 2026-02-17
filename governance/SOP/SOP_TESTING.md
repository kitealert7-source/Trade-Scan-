# SOP_TESTING — Backtest Execution & Stage-1 Artifact Authority

**Stage:** BACKTESTING  
**Applies to:** Trade_Scan  
**Status:** AUTHORITATIVE | ACTIVE  
**Companion SOP:** SOP_OUTPUT — VERSION 4.1 (POST_BACKTEST)

---

## 1. Purpose

This SOP governs **execution‑time behavior only**.

Trade_Scan:

- reads human‑written directives
- executes back tests
- computes execution metrics
- emits Stage‑1 artifacts
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
8. Portfolio evaluation (if applicable).
9. Stop.

There is:

- no autonomous continuation
- no implicit rerun
- no partial execution
- no pipeline skipping

Vault is not accessed during normal execution and must not influence pipeline behavior.

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

A run is `RUN_COMPLETE` only if **all declared executions finish atomically**.

Failed or partial runs:

- produce no retained artifacts
- produce no retained artifacts
- must be deleted
- must not update any indices

---

## 6. Stage‑1 Artifact Authority (EXECUTION LAW)

Stage‑1 artifacts:

- define execution truth
- define execution schema
- are immutable after RUN_COMPLETE
- must be sufficient for exact reproduction

Stage‑2 and Stage‑3:

- MUST NOT recompute execution metrics already present in Stage-1 artifacts.
- MUST NOT recompute execution metrics already present in Stage-1 artifacts.
- MAY aggregate only as allowed by SOP_OUTPUT — VERSION 4.1

---

## 7. Stage‑1 Trade‑Level Schema (AUTHORITATIVE)

This is the **complete and authoritative Stage‑1 trade schema**.
Field names and presence MUST match SOP_OUTPUT

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

**Rules**

- All fields MUST be computed during execution
- All fields MUST be emitted in Stage‑1 artifacts
- Fields MUST NOT be inferred, reconstructed, or recomputed later
- Fields MUST remain immutable after RUN_COMPLETE

Any change to this schema or its computation constitutes **engine evolution** and requires a new engine identity per SOP_AGENT_ENGINE_GOVERNANCE.

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

A run is considered RUN_COMPLETE only after all declared execution phases are completed successfully.

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

------------------------------------------------------------------------

---

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
- post‑hoc filtering
- data snooping
- undeclared reruns
- metric inference
- execution schema drift

---

## 12. Handoff to SOP_OUTPUT

Upon RUN_COMPLETE:

- Stage‑2 and Stage‑3 are executed per SOP_OUTPUT — VERSION 4.1
- Stage‑2 and Stage‑3 are executed per SOP_OUTPUT — VERSION 4.1
- This SOP relinquishes authority beyond Stage‑1 artifacts

---

**End of SOP_TESTING — VERSION 2.1**
