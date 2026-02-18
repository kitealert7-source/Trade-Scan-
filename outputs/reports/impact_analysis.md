# Governance & Engine Impact Analysis: Directive-Declared Indicators

## 1. Governance Review

### **Responsibility & Contracts**

* **Contractual Responsibility**: The **Strategy** is contractually responsible for "indicator invocation and selection" (`STRATEGY_PLUGIN_CONTRACT`). The **Engine** is explicitly forbidden from computing or choosing indicators ("The engine MUST NOT: compute indicators").
* **Validation Responsibility**: `SOP_INDICATOR` (Section 10) mandates that "Dependency validation MUST occur BEFORE: Strategy import, Engine execution...".
* **Current Gap**: While `SOP_INDICATOR` mandates pre-execution validation, currently `run_stage1.py` performs this check *inside* the execution process (`load_strategy`), effectively during Stage-1, not the distinct "Preflight" phase (`exec_preflight.py` / `governance/preflight.py`).
* **Directive Declaration**: Currently, `SOP_TESTING` does not explicitly forbid directive-level declaration. It states execution is "directive-driven". Declaring dependencies in the directive is consistent with this philosophy ("Trade_Scan exists only while executing explicit instructions"). It does *not* violate existing SOPs to add this, provided the *Strategy* code still performs the actual import/invocation.

### **Permissibility**

* **Preflight Validation**: Permitted and encouraged. `SOP_TESTING` lists "Preflight validation" as step 1. Moving dependency checks here aligns better with `SOP_INDICATOR`'s "BEFORE Engine execution" rule.
* **Dynamic Logic**: Prohibited. `SOP_INDICATOR` explicitly bans "Inline indicator implementations" and "Dynamic logic injection". Directive-declaration must remain *declarative* (pointers to files), not logic injection.

## 2. Engine & Pipeline Review

### **Current Architecture**

* **Parsing**: `tools/run_stage1.py` > `parse_directive` handles `Key: Value` and Lists. It is robust enough to handle a new `Indicators:` list section without breaking (it stores unknown keys in the dict).
* **Preflight**: `governance/preflight.py` parses the directive *separately* using regex/line-splitting to extract scope (Broker/Symbol/Timeframe/Date). It does **not** currently use the robust `parse_directive` from `run_stage1.py` for everything, nor does it check indicators.
* **Dependency Tracking**: Currently **Implicit**. `run_stage1.py` > `load_strategy` statically analyzes `strategy.py` source code to find `from indicators.x import y` statements and verifies file existence.
* **Strategy Loading**: Dynamic via `importlib`.

### **Technical Impact**

* **Directive Schema**: extending the directive with an `Indicators:` block will **not break** `run_stage1.py` (it just ignores extra keys). It will **not break** `execution_emitter_stage1.py`.
* **Preflight**: This is the logical place for modification.

## 3. Stage-1 & Emission Analysis

* **Preservation**: `atr_entry` is preserved in `RawTradeRecord`.
* **Regime**: Volatility regime is computed in `execution_emitter_stage1.py` using `atr_entry` (if available) or `trade_high - trade_low` (fallback). It is calculated based on the *distribution of ATRs in the current run* (percentiles). It is **outcome-based** (requires all trades to define percentiles), though the per-trade value is entry-based.
* **Reconstruction**: The emitter *cannot* currently reconstruct the full time-series regime without the strategy, because it only sees trades. It does not output a timeseries of "Regime" for every bar, only for trade entry points.

## 4. Failure Mode Enumeration

| Mode | Scenario | Severity | Affected Layer | Detectable in Preflight? |
| :--- | :--- | :--- | :--- | :--- |
| **Missing File** | Directive declares `indicators/vol/atr.py`, file missing. | **High** | Preflight | **YES** |
| **Usage Mismatch** | Directive declares `ATR`, Strategy imports `RSI` (undeclared). | **Medium** | Governance | **YES** (if Preflight scans strategy) / **NO** (if Preflight only checks directive) |
| **Superfluous Decl.** | Directive declares `ATR`, Strategy uses nothing. | **Low** | Governance | **YES** |
| **Version Drift** | Strategy expects `ATR(df, n)`, Repo has `ATR(series, n)`. | **High** | Execution | **NO** (Requires static type analysis or runtime) |
| **Parsing Failure** | Directive `Indicators:` block malformed. | **Medium** | Preflight | **YES** |

## 5. Minimal Safe Modification Path

### **Layer Responsibility Map** (Proposed)

| Layer | Responsibility | New/Modified Behavior |
| :--- | :--- | :--- |
| **Directive** | **Declaration** | Added `Indicators:` section listing required repository paths. |
| **Preflight** | **Validation** | **(MODIFY)** Parse `Indicators:` list. Verify file existence in `indicators/` repo. |
| **Stage-1** | **Enforcement** | **(INVARIANT)** Continue to enforce `STRATEGY_PLUGIN_CONTRACT`. Continue to verify imports exist (redundant but safe). |
| **Strategy** | **Invocation** | **(INVARIANT)** Must import what is declared. |

### **Identified Architectural Gaps**

1. **Duplicate Parsing Logic**: `governance/preflight.py` and `tools/run_stage1.py` both have directive parsing logic. Preflight's logic is ad-hoc (regex).
2. **Scope of Preflight**: Preflight currently checks *governance documents* and *directive basic scope*. It does validates *strategy existence* but not *strategy content* vs directive.

### **Minimal Change Path (Ordered)**

1. **Refactor Preflight Parser**: Update `governance/preflight.py` to use `tools.run_stage1.parse_directive` (or a shared utility) to reliably parse the `Indicators` list.
    * *Why*: Current regex parsing in Preflight is brittle for lists.
2. **Implement Indicator Check in Preflight**: Add logic to `governance/preflight.py`:
    * Extract `Indicators` list.
    * For each item, verify `Trade_Scan/indicators/<path>.py` exists.
    * Return `BLOCK_EXECUTION` if missing.
3. **No Engine Changes**: Do not modify `engine/` or `execution_loop.py`.
4. **No Stage-1 Changes**: `run_stage1.py` can remain as is (it will still fail if imports are missing, providing a second safety net).

### **Risk Assessment**

* **Low Risk**. Moving the "Does file exist?" check to Preflight is purely additive governance.
* **Regime Risk**: No impact. Indicator existence does not change how regime is calculated.
* **Strictness Risk**: If we implement "Strict" checking (Strategy MUST use declared), we risk successful runs failing due to paperwork. **Recommendation**: Start with "Availability Check" (If declared, MUST exist). Leave "Usage Enforcement" (Strategy MUST NOT use undeclared) for a later iteration or handle in `run_stage1` validation.

### **Recommendation**

Modify `governance/preflight.py` to:

1. Import `parse_directive` from `tools.run_stage1`.
2. Read `Indicators` key from directive.
3. Validate existence of referenced files in `indicators/` directory.
4. Fail Preflight if files are missing.

This places the responsibility on **Governance (Preflight)** where it belongs (`SOP_TESTING` §10 "Dependency validation MUST occur BEFORE..."), without touching the Engine or Strategy logic.
