# ⚠️ TL;DR – Strict Constraints (AGENT MUST READ)

**DO NOT:**
*   **Edit RAW, CLEAN, or RESEARCH data files manually.**
*   **Alter execution models** (OctaFX/Delta) defined in this SOP.
*   **Add missing ingest functions** unless strictly matching the SOP source.
*   **Change BCSL parameters** (Contract Value, Lot Steps) in bindings.
*   **Relax or bypass hash checks** in the Validator.
*   **Resample or shift timeframes** outside of the defined Pipeline.
*   **Add strategy logic** into RESEARCH datasets.

---
# ANTI_GRAVITY_SOP_v17.2.md (REVISED)
# (Complete File)

## STATUS
**FINAL LOCKED – Immutable**  
**FORMAT:** Markdown (.md)  
**PURPOSE:** Canonical rules for Anti-Gravity system (data, execution, bindings, outputs, reproducibility)

---

# 0. PURPOSE
This SOP defines authoritative, permanent, non-negotiable rules for:

- Data lifecycle (RAW → CLEAN → RESEARCH)  
- Execution-model embedding  
- Broker Contract Specification Layer (BCSL)  
- Position model governance  
- Binding generation  
- Backtest reproducibility  
- Results architecture  
- Logging & audit  
- Error-classification  
- Dataset & strategy versioning  
- Unified Markdown reporting  
- Timezone normalization  
- Template-based binding auto-generation  

No retroactive edits allowed. Future changes must produce v18+.

---

# 1. MASTER DATA & STRATEGY STATE ARCHITECTURE

This section defines the authoritative data layer and the non-runtime strategy
state layer for Anti-Gravity v17. It enforces strict separation between market
data, strategy governance state, and execution behavior.

**Terminology Clarification**

In Anti-Gravity v17, the terms **DATA** and **MASTER_DATA** refer to the same
logical layer.

- `MASTER_DATA/` is the physical directory name used on disk.
- Any reference to `DATA` in legacy SOPs, scripts, or documentation
  SHALL be interpreted as `MASTER_DATA`.

No separate `DATA/` directory is permitted.

## 1.1 MASTER DATA ARCHITECTURE

MASTER_DATA/
    <ASSET>_<FEED>_MASTER/
        RAW/
        CLEAN/
        RESEARCH/

Approved masters:
- XAUUSD_OCTAFX_MASTER
- EURUSD_OCTAFX_MASTER
- GBPUSD_OCTAFX_MASTER
- USDJPY_OCTAFX_MASTER
- AUDUSD_OCTAFX_MASTER
- USDCAD_OCTAFX_MASTER
- USDCHF_OCTAFX_MASTER
- NZDUSD_OCTAFX_MASTER
- EURAUD_OCTAFX_MASTER
- GBPAUD_OCTAFX_MASTER
- AUDNZD_OCTAFX_MASTER
- GBPNZD_OCTAFX_MASTER
- NAS100_OCTAFX_MASTER
- SPX500_OCTAFX_MASTER
- GER40_OCTAFX_MASTER
- AUS200_OCTAFX_MASTER
- UK100_OCTAFX_MASTER
- FRA40_OCTAFX_MASTER
- ESP35_OCTAFX_MASTER
- EUSTX50_OCTAFX_MASTER
- US30_OCTAFX_MASTER
- JPN225_OCTAFX_MASTER
- BTC_DELTA_MASTER
- BTC_OCTAFX_MASTER
- ETH_DELTA_MASTER
- ETH_OCTAFX_MASTER
- US10Y_YAHOO_MASTER

Rules:
1. Only RAW, CLEAN, and RESEARCH directories are permitted.
2. Append-only; no overwriting or in-place mutation.
3. Every dataset file must include immutable metadata:
   - asset
   - feed
   - timeframe
   - source
   - source_api_version
   - dataset_version
   - SHA256
   - generation timestamp
4. All timestamps must be normalized to UTC.
5. MASTER_DATA must contain market data only.
   Strategy logic, indicators, features, parameters,
   execution artifacts, or results are strictly forbidden.

MASTER_DATA defines market reality and is the sole source of truth for price data.

## 1.2 STRATEGY STATE ARCHITECTURE (NON-RUNTIME) [DEPRECATED]

**Status:** Deprecated. Do not use for new development. Strategies should be stateless or fully parametrized via runner arguments.


Allowed contents:
- Approved parameter snapshots
- Strategy semantic version
- Interface checksum or hash
- Governance annotations
- Approval timestamps

Forbidden contents:
- Runtime state
- Adaptive variables
- Counters
- Equity or PnL values
- Trade history
- Any value read during execution, tuning, or backtesting

Rules:
1. Write-once, append-by-version only.
2. Strategy execution, tuning, and analysis must never read from STRATEGY_STATE.
3. STRATEGY_STATE exists solely for audit and governance.
4. Strategy behavior must be fully determined by:
   - RESEARCH datasets
   - bindings
   - parameters
   - execution models
5. Any runtime dependency on STRATEGY_STATE is a CRITICAL SOP violation.

## 1.3 DATA ↔ STRATEGY ISOLATION GUARANTEE

Anti-Gravity enforces strict isolation between layers:

- MASTER_DATA defines market reality
- STRATEGY_STATE defines human-approved strategy snapshots
- RESULTS define observed performance

No circular dependency is permitted.

This isolation guarantees:
- deterministic backtesting
- reproducibility
- auditability
- prevention of hidden state leakage
- long-term system integrity

---

**End of Section 1**


# 2. EXECUTION MODELS

## 2.1 OctaFX (MT5 CFD) [DESCRIPTIVE / CERTIFICATION ONLY]
```
commission_cash = 0.40 USD per 0.01 lot per side
spread = 0
slippage = 0
execution_model_version = "octafx_exec_v1.1" # Semantic: Pre-Applied Costs
```

**CRITICAL RULE:**
Commission, spread, and slippage are **pre-applied** in RESEARCH datasets.
Runtime/Runners MUST NOT re-apply costs. Double-taxation is a CRITICAL violation.

## 2.2 Delta Exchange
```
fee_pct = 0.036% per leg
spread = 0
slippage = 0
execution_model_version = "delta_exec_v1.0"
```

## Rules
- **Hard Rule:** If costs are declared as embedded (OctaFX), bindings and runners MUST NOT apply execution costs again.
- Binding cannot modify execution model.
- Versions mandatory for reproducibility.

---

# 3. RAW STAGE RULES
- API downloads only  
- No resampling, no timezone shifting, no indicators  
- Immutable  
- Naming:
```
<ASSET>_<TIMEFRAME>_<YEAR>_<SOURCE>_RAW.csv
```

---

# 4. CLEAN STAGE RULES
Allowed:
- Duplicate removal  
- Remove zero-OHLC  
- Enforce monotonic timestamps  
- Missing-bar detection  

Forbidden:
- Indicators, smoothing, strategy logic  

Naming:
```
<ASSET>_<TIMEFRAME>_<YEAR>_<SOURCE>_CLEAN.csv
```

Must include:
- dataset_version  
- SHA256 hash  

---

# 5. RESEARCH STAGE RULES
Allowed:
- Execution model embedding  
- Session tagging  
- Fee/spread/slippage modeling
  (For OctaFX feeds, cost modeling is upstream; RESEARCH contains final prices.)
- Bar metadata  

Forbidden:
- Strategy logic  
- Indicators  
- Feature engineering  

Naming:
```
<ASSET>_<TIMEFRAME>_<YEAR>_<SOURCE>_RESEARCH.csv
```

Must include:
- dataset_version  
- execution_model_version  
- feed_version  
- source_api_version  
- SHA256 hash  

---

# 6. SESSION FILTER RULE (v16)
Bad Session Window:
**23:00 → 03:00 exchange-time (stored as UTC).**

Rules:
- Entry creation **blocked**  
- Exits always allowed  
- State updates allowed  
- Count removed bars in binding_debug.log  

---

# 7. TIMEFRAME EXPANSION PROTOCOL (TEP)
Steps:
1. Download RAW fresh  
2. Generate CLEAN  
3. Generate RESEARCH  
4. Update audit logs  
5. Increment dataset_version  

Never resample.

---

# 8. RUN_BINDING RULES
Bindings must:
- Declare single asset/feed/strategy/timeframe  
- Validate dataset hashes + dataset_version + exec model version  
- Hard-fail on mismatch  
- Include BCSL parameters (v17)  
- Enforce position model (v17)  

Output folder:
```
strategies/<STRATEGY>/RUN_<TIMESTAMP>_<UUID>/
```

## 8.1 Canonical Backtest Window

### 1. DEFAULT BACKTEST WINDOW
The default BACKTEST temporal window SHALL be the most recent 365 calendar days of available RESEARCH data.
This default applies when no explicit backtest range is declared in the binding.

### 2. EXPLICIT RANGE OVERRIDE
BACKTEST bindings MAY explicitly declare a custom backtest range (start/end dates).
Explicit ranges ALWAYS override the default window.

### 3. FULL-HISTORY BACKTESTS
Full-history backtests are permitted but MUST be explicitly declared (e.g. FULL_HISTORY or explicit start/end).
Full-history runs MUST NOT be the implicit default.

### 4. REPORTING REQUIREMENT
The effective backtest period (start date, end date, duration) MUST be reported in AK_Trade_Report_<STRATEGY_ID>.xlsx for all BACKTEST runs, regardless of default or explicit range.

### 5. GOVERNANCE CLARIFICATION
Backtest window selection is:
- An execution-scope decision
- Not a tuning parameter
- Not a promotion or gating criterion

Absence of an explicit range SHALL NOT invalidate historical runs.

---

# 9. AUDIT & INTEGRITY
- RAW immutable  
- CLEAN re-generated when RAW changes  
- RESEARCH only patched for exec-model updates  
- Full lineage tracked  
- All runs reproducible  
- BCSL parameters must match feed specification (v17)  

---

# 10. HASHING & METADATA
Each dataset and strategy file stores:
- SHA256  
- generator version  
- dataset_version  
- feed_version  
- source_api_version  
- execution_model_version  

Bindings must verify hash/set before running.

---

# 11. LOGGING
binding_debug.log must include:
- Dataset path + SHA256  
- Missing/duplicate bars  
- Bars removed by session filter  
- Execution model version  
- Strategy version  
- Binding parameters (resolved)  
- BCSL parameters applied (v17)  
- Position sizing calculations (v17)  
- Errors with severity  

---

# 12. BROKER CONTRACT SPECIFICATION LAYER (BCSL)

## 12.1 OctaFX (MT5 CFD)
XAUUSD:
- contract_value = 100
- minimum_tradable_unit = 0.01
- lot_step = 0.01

BTCUSD:
- contract_value = 1
- minimum_tradable_unit = 0.01
- lot_step = 0.01

ETHUSD:
- contract_value = 10
- minimum_tradable_unit = 0.01
- lot_step = 0.01

## 12.2 Delta Exchange (PERP)
BTC-PERP:
- contract_value = 0.001
- minimum_tradable_unit = 1
- lot_step = 1

ETH-PERP:
- contract_value = 0.01
- minimum_tradable_unit = 1
- lot_step = 1

## 12.3 BCSL Rules
1. All bindings **must** declare BCSL parameters  
2. Position sizing **must** use minimum_tradable_unit  
3. Lot sizes **must** be multiples of lot_step  
4. contract_value used for P&L and exposure calculations  
5. BCSL parameters **must** match feed specification exactly  
6. Mismatch = CRITICAL error (abort immediately)  
7. BCSL never applies transaction costs  

---

# 13. POSITION MODEL SPECIFICATION

## 13.1 Default Model
```
position_size = minimum_tradable_unit
pyramiding = 0
max_positions = 1
```

## 13.2 Position Sizing Formula
For risk-based sizing (when account_size specified):

### OctaFX Formula
```
lot_size = FLOOR(
    (account_size × risk_pct) / (stop_loss_usd × contract_value)
    / lot_step
) × lot_step

lot_size = MAX(lot_size, minimum_tradable_unit)
```

### Delta Exchange Formula
```
lot_size = FLOOR(
    (account_size × risk_pct) / (stop_loss_usd × contract_value)
    / lot_step
) × lot_step

lot_size = MAX(lot_size, minimum_tradable_unit)
```

## 13.3 Position Model Rules
1. Default model uses **exactly** minimum_tradable_unit  
2. No pyramiding (pyramiding = 0)  
3. Maximum 1 position at a time (max_positions = 1)  
4. Risk-based sizing optional but must respect BCSL constraints  
5. All position sizes **must** be >= minimum_tradable_unit  
6. All position sizes **must** be multiples of lot_step  

---

# 14. BINDING TEMPLATE REQUIREMENTS

## 14.1 Mandatory BCSL Fields
```python
contract_value = <value>
minimum_tradable_unit = <value>
lot_step = <value>
lot_size = minimum_tradable_unit
pyramiding = 0
max_positions = 1
sop_version = "v17"
```

## 14.2 Optional Position Sizing Fields
```python
account_size = <value>
risk_per_trade_pct = <value>
stop_loss_usd = <value>
```

## 14.3 Validation Requirements
Binding must validate:
1. BCSL parameters match feed specification  
2. lot_size >= minimum_tradable_unit  
3. lot_size is multiple of lot_step  
4. pyramiding = 0  
5. max_positions = 1  
6. If account_size specified, validate calculated position size  

---

# 15. TIMEZONE NORMALIZATION
All timestamps normalized to UTC.
Session windows converted to UTC before enforcement.

---

# 16. ERROR CLASSIFICATION
```
CRITICAL – abort immediately  
MAJOR – run completes but flagged  
MINOR – informational
```

Examples:

CRITICAL:
- Hash mismatch  
- Dataset missing  
- Non-monotonic timestamps  
- Duplicate bars after CLEAN  
- BCSL parameter mismatch (v17)  
- Position size < minimum_tradable_unit (v17)  
- Position size not multiple of lot_step (v17)  

MAJOR:
- Missing bars >1%  
- Equity spikes >5%  
- Win-rate >95% or <5%  

MINOR:
- Optional metadata missing  

---

# 17. DATASET VERSION TAGGING
Example:
```
dataset_version: "RESEARCH_v4_EXECv2_SESSIONv3"
```
Increment when any structural behavior changes.

---

# 18. STRATEGY VERSION SNAPSHOT [DEPRECATED]
Status: Deprecated. Strategy versioning is handled via RUN metadata and git commit hashes.

---

# 19. BINDING COMPATIBILITY CONTRACT
Each template declares:

```
required_parameters
optional_parameters
incompatible_versions
```

AG must validate before generating a runnable binding.

---

# 20. PERFORMANCE HEURISTICS (NON-AUTHORITATIVE)
The following are heuristic checks for sanity only. They do not invalidate a run but may trigger warnings.

Flags:
- Win-rate >95% or <5%  
- <10 trades/year equivalent  
- Equity jumps >5%/bar  
- Abnormal drawdown shape  
- Abnormal trade duration

Heuristics MAY be surfaced in AK Trade Report; no independent reporting required.

---

# 21. EXECUTION MODEL VERSIONING
RESEARCH stores:
```
execution_model_version
```
(For descriptive models (OctaFX), version certifies dataset semantics, not runtime behavior.)
Binding must verify before running.

---

# 22. FOLDER ARCHITECTURE (v2.5 STANDARD)

## 22.1 Strategy Root
```
strategies/<STRATEGY_ID>/
├── AK_Trade_Report_<STRATEGY_ID>.xlsx  (Standardized Human Report)
└── RUN_<TIMESTAMP>_<UUID>/             (Canonical Execution Data)
```

## 22.2 Canonical RUN Folder Contents (Immutable)
The RUN folder MUST contain ONLY the following 6 authoritative artifacts:
```
results_standard.csv
results_risk.csv
results_yearwise.csv
results_tradelevel.csv
metrics_glossary.csv
run_metadata.json
```

## 22.3 Report Location Rule
All human-readable Excel reports (`AK_Trade_Report_*.xlsx`) MUST reside in the **Strategy Root**, never inside a specific RUN folder.

---

# 23. VERSIONING RULE

ANTI_GRAVITY_SOP_v17 defines the execution, tuning, binding,
and promotion contract for the Anti-Gravity system.

These execution rules are final and locked.

Editorial, documentation, or reporting-only modifications
may be introduced with:
1. Explicit human approval
2. A versioned changelog entry
3. A written declaration of execution impact (NONE / YES)

Any modification that alters execution, tuning, binding,
or promotion logic requires a new major SOP version (v18+).

---

# 24. PERMANENT LOCK STATEMENT
This SOP, dataset architecture, execution model behavior, BCSL specifications, position model governance, binding protocol, and results architecture are permanently frozen. Reproducibility is guaranteed only when following this SOP exactly.

---


---

---

## Governance Clarification

This SOP remains authoritative and binding.

Any modification, including editorial or reporting-only changes,
requires:
1. Explicit human approval
2. A versioned changelog entry
3. Written declaration of execution impact (NONE / YES)

No modification may alter execution, tuning, binding, or promotion
logic without a major version increment.
---

# 25. CHANGELOG
- **v17.3 (2026-01-30):**
    - **Renumbering:** Renumbered sections sequentially to remove gaps. Execution impact: NONE.
    - **Architecture:** Rewrote §25 (now §22) to enforce decentralized Strategy Root structure (`strategies/<ID>/RUN...`) and retired `results_human_snapshot.xlsx`. Mandated `AK_Trade_Report` in Strategy Root.
    - **Cleanup:** Purged legacy sections: §9 (Results), §22 (Param Governance), §24 (Binding Gen).
    - **Deprecation:** §1.2 Strategy State marked DEPRECATED.
    - **Execution Models:** §2.1 OctaFX updated to `octafx_exec_v1.1` (Certification Only). Added Prohibition on Runtime Double-Taxation.
    - **Downgrade:** §21 (now §20) downgraded to "Performance Heuristics".
- **v17.2.1 (2025-12-20):** Editorial clarification - Renamed Section 21 from "PERFORMANCE VALIDATION (SANITY)" to "PERFORMANCE VALIDATION" to avoid confusion with formal S0 SANITY verification phase. No execution impact.
- **v17.2 (2025-12-16):** Defined canonical default BACKTEST window (365 days) with explicit override support.
- **v17.1 (2025-12-16):** Extended reporting with contextual, non-computational sections in Section 9. Governance clarification added. Execution impact explicitly declared as NONE.

END OF FILE