# SOP_TESTING
**Stage:** BACKTESTING  
**Applies to:** Trade_Scan  
**Status:** ACTIVE 

---

## 1. Purpose

This SOP governs execution of back tests.

Trade_Scan:
- reads human-written directives
- executes back tests
- emits deterministic artifacts
- stops

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

Trade_Scan operates only on **the directive explicitly selected by the human operator** from:

```
backtest_directives/active/
```

Trade_Scan MUST ignore all other directive files.

### 3.2 Directive Requirements

A directive MUST declare intent across:
- Entry Conditions
- Exit logic
- Risk and cost assumptions
- Iteration allowance and scope (if any)

### 3.3 Directive Completion

Upon **atomic completion** of all declared runs, Trade_Scan MUST move **that directive file only** to:

```
backtest_directives/completed_run/
```

Trade_Scan MUST NOT move the directive if execution is partial, interrupted, or failed.

---

## 4. Execution Model

When invoked by a human:

1. Read the selected directive.
2. Validate presence of executable conditions.
3. Constrain execution strictly to the directive.
4. Execute analyses required to produce back test artifacts.
5. Apply economic calculations per Section 6–12, enforcing decimal (0.0–1.0) storage for all percentage metrics in execution artifacts;
   scaling to 0–100 is permitted only in post-backtest presentation stages.
6. Write outputs per SOP_OUTPUT.
7. Stop.

There is:
- no loop
- no persistence
- no self-expansion

---
## 5. Strategy Folder & Stage-1 Artifact Authority (LOCKED)

For each back test run, Trade_Scan MUST:

- Create one strategy folder named exactly as the human-defined Strategy Name
- Place it under:
---------------
backtests/
---------------
- Treat this folder as the **sole authoritative container** for the run

### Stage-1 Authority Rules

All Stage-1 execution artifacts in the strategy folder:

- define execution truth
- define the execution schema
- are immutable after RUN_COMPLETE

After RUN_COMPLETE:

- Strategy logic MUST NOT change
- Execution semantics MUST NOT change
- Emitted Stage-1 fields MUST NOT change
- Artifacts MUST remain sufficient for exact reproduction

No Stage-2 or Stage-3 process may infer, recompute, approximate, or create
execution metrics.

### Stage-1 Schema (EXECUTION ONLY)

### Stage-1 Trade-Level Schema (AUTHORITATIVE)

Stage-1 trade-level execution artifacts MUST emit the following fields.
This list defines the complete and authoritative Stage-1 trade schema.

Core identity & timing:
- strategy_name
- parent_trade_id
- sequence_index
- entry_timestamp
- exit_timestamp

Trade semantics:
- direction
- entry_price
- exit_price
- net_pnl
- bars_held (nullable)

Risk, sizing & exposure:
- atr_entry (nullable)
- position_units (nullable)
- notional_usd (nullable)

Excursion metrics:
- mfe_price (nullable)
- mae_price (nullable)
- mfe_r (nullable)
- mae_r (nullable)

All fields above:
- MUST be computed during Stage-1 execution
- MUST be emitted directly into Stage-1 artifacts
- MUST NOT be inferred, reconstructed, or recomputed in later stages
- MUST remain immutable after RUN_COMPLETE


Rules:
- MUST be computed during execution
- MUST be emitted in Stage-1 artifacts
- MUST NOT be reconstructed later

### Engine Evolution Trigger

Any change to:
- execution logic
- metric computation
- or the set or meaning of Stage-1 fields

⇒ constitutes engine evolution and requires a new engine identity per SOP_AGENT_ENGINE_GOVERNANCE.


### Reproducibility & Data Authority

- All artifacts MUST reproduce the run exactly
- Market data MUST come only from the authoritative data root located at:
  Trade_Scan/data_root/ (read-only)
- Derived data and outputs MUST be written only to the strategy folder
- Any violation invalidates the run

---

## 6. Iteration Execution

### 6.1 Iteration Allowance

Iteration is permitted **only if explicitly allowed in the directive**.

Humans define:
- Base Strategy Name / ID
- Iteration type (filters, parameter sweeps, or both)
- Bounds and full enumerability of iterations

### 6.2 Iteration Folders

If iterations are declared:
- The first strategy folder is treated as the **parent**
- For each iteration, Trade_Scan MUST:
  - create a full copy of the parent strategy folder
  - increase the strategy numbering sequentially
  - execute within the copied folder

Each iteration folder MUST be:
- complete and self-contained
- isolated from all other iterations
- non-adaptive and non-interactive

---

## 7. Atomic Execution Rule

Trade_Scan execution is **atomic**.

- Either all declared runs complete, or
- No back test artifacts are retained

If execution fails or is interrupted:
- all generated folders and artifacts are deleted
- the directive remains in `backtest_directives/active/`
- no metadata or outputs persist

A run is **RUN_COMPLETE** if all declared executions finish atomically.

---

## 8. Back Test Parameters

### 8.1 Capital & Trade Size Declaration (LOCKED)

| Parameter                   | Requirement                       |
| --------------------------- | --------------------------------- |
| Reference Capital           | USD 5,000                         |
| Capital Role                | Measurement reference only        |
| Capital Injection / Reset   | Forbidden                         |
| Broker Spec                 | Mandatory, explicit (no defaults) |
| Sizing Mode                 | Mandatory, explicitly declared    |
| Base Lot Size               | Mandatory                         |
| Manual Override             | Forbidden                         |
| Inference of Missing Fields | Forbidden                         |


Simulated capital is used to measure outcomes, not to constrain execution.
However, all trade-level notionals MUST be explicitly derivable from the declared broker specification and sizing parameters.
If any trade size, notional value, or capital usage is:
inferred,
defaulted,
manually overridden, or
not reconcilable with declared settings,
the run is INVALID and MUST be discarded

---

### 8.2 Calibration Admissibility (LOCKED)

Symbols may be tested under one of two calibration states:

**PASS**  
Empirically calibrated using real executed trades.  
These symbols may be used for validation, comparison, and execution analysis.

**DERIVED_BACKTEST_ONLY**  
Calibration derived from FX economic relationships or quote data.  
These symbols may be used for preliminary backtesting only and are excluded from execution or promotion.

Empirical calibration always supersedes derived calibration.

---

### 8.3 Execution Unit & Scaling Model (DISCRETE)

| Parameter | Rule |
|---------|------|
| Base Execution Unit | Broker minimum (`min_lot`) |
| Fractional Lots | Forbidden |
| Lot Quantization | Integer multiples of `min_lot` only |

**Rules:**
- All entries, adds, and exits MUST be in integer multiples of `min_lot`
- No execution may assume finer granularity than broker allows
- Execution logic must remain valid at `1 × min_lot`
- Economic PnL scaling is governed by broker symbol calibration and is independent of execution discretization

---

### 8.4 Scaling & Pyramiding (PERMITTED)

The following are **explicitly allowed** during backtesting:

- Scaling into positions
- Scaling out / partial exits
- Pyramiding (multiple adds in the same direction)
- Multi-leg trade structures

**Constraints:**
- Each add or reduction is a discrete execution
- Each leg uses valid broker lot increments
- No implicit averaging via fractional sizing

Scaling logic is treated as **strategy behavior**, not risk control.

---

## 9. Broker Constraints & Execution Geometry (Source: Broker Specs)

### 9.1 Authoritative Source

Broker constraints and geometry MUST be loaded from the instrument-specific **Broker Specs File**.

Location:
```
Trade_Scan/data_access/broker_specs/<BROKER>/<SYMBOL>.yaml
```

**Fields (Mandatory):**
- `min_lot`
- `lot_step`
- `max_lot`
- `contract_size`

No broker or instrument defaults may be inferred if a field is missing.

### 9.2 Application Rules (Invariant)

1. Compute ideal position size using the risk formula.
2. Apply broker quantization using **floor rounding only**:
   `quantized_size = floor(ideal_size / lot_step) * lot_step`
3. **Min Lot Check:** If `quantized_size < min_lot` → skip the trade (status: `skipped_min_lot`).
4. **Max Lot Check:** If `quantized_size > max_lot` → cap at `max_lot` (status: `capped_max_lot`) OR skip (status: `skipped_max_lot`) as declared.

### 9.3 Hard Constraint

**Manual overriding of spec values is FORBIDDEN.**  
If the spec file is missing or invalid, the run MUST fail validation.

---

## 10. Instrument Handling

### 10.1 Forex Instruments

Forex instruments receive **no special handling**:
- No pip-based calculations
- No base/quote currency logic
- No implicit leverage or margin assumptions

Forex pairs are treated as **contract-based instruments**, identical to metals, indices, and crypto.

### 10.2 Broker Cost Handling

Cost responsibility is defined by the **execution model**.

**Embedded-Cost Models (e.g., OctaFX):**
- Prices are net-of-cost
- Trade_Scan MUST NOT re-apply spread, commission, or slippage

**Non-Embedded Cost Models (e.g., Delta Exchange):**
- Directive MUST declare all cost components
- Trade_Scan applies costs exactly once

Double application of costs is forbidden.  
Ambiguous cost semantics → validation failure.

---

## 11. Back Test Scope & Declarations

### 11.1 Test Scope Defaults

| Requirement | Default |
|-------------|---------|
| Test Period | Maximum available historical range |
| Calendar Coverage | Full available period (no cherry-picking) |

### 11.2 Mandatory Declarations (per run)

- Instrument(s)
- Timeframe
- Start date
- End date
- Data source
- Timezone
- Bar construction rules
- Fill model (e.g., close, next open)

### 11.3 Execution Constraints

Forbidden:
- Partial fills
- Broker-level fractional executions

All PnL, risk, and drawdown are expressed in USD.

### 11.4 Partial Windows

Selective or shortened windows:
- MUST be explicitly declared
- Are NOT directly comparable to full-history runs

---

## 12. Run Index Maintenance

Upon successful completion, a run index record is appended to CSV index at:

```
Trade_Scan/outputs/run_index/run_index.csv
```

**Fixed Header:**
```csv
run_id,strategy_name,parent_strategy_name,iteration_id,directive_name,directive_hash,engine_hash,data_fingerprint,execution_timestamp_utc,run_status,strategy_folder_path
```

**Rules:**
- Append exactly one row per atomically completed run
- `run_status` MUST be `RUN_COMPLETE`
- Failed or partial runs MUST NOT appear in the index
- Update only after directive relocation to `completed_run/`
- Index is descriptive only and MUST NOT influence execution

---

## 13. Prohibitions (HARD)

The following are forbidden:

- Post-hoc filtering
- Regime cherry-picking
- Data snooping
- Undeclared counterfactual reruns
- Broker-specific optimization

---
