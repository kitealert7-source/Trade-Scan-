# DIRECTIVE RESEARCH SHEET (Template)

**Standardized Hypothesis-Driven Experimentation for Trade_Scan**

## 1. RESEARCH METADATA

| Field | Value |
| :--- | :--- |
| **Researcher** | [Name] |
| **Date** | YYYY-MM-DD |
| **Directive ID** | `[Strategy_Name]_[Variant]_[Version]` (e.g. `Range_Breakout_VolFilter_v1`) |
| **Base Strategy** | [Name of existing strategy being modified] |
| **Engine Version** | [vX.Y.Z] |

---

## 2. HYPOTHESIS DEFINITION

*Describe the causal link you are testing. Avoid "optimization" language. Use "mechanism" language.*

* **Observation/Problem**: [What behavior in the baseline is suboptimal?]
* **Proposed Mechanism**: [What specific logic change are you introducing?]
* **prediction**: IF [Mechanism is applied] THEN [Specific Metric] will improve BECAUSE [Reasoning].

---

## 3. EXPERIMENT CONFIGURATION

*Must map 1:1 to the Directive File (`.txt`)*

| Parameter | Value | Notes |
| :--- | :--- | :--- |
| **Broker** | `OctaFx` | |
| **Timeframe** | `[e.g. 5m]` | |
| **Test Window** | `[Start Date]` to `[End Date]` | *Must include stress periods* |
| **Universe** | `[List Symbols]` | *Subset or Full Portfolio?* |

---

## 4. STRATEGY VARIANT (Parameters)

*List ONLY parameters that differ from the Baseline. "Ceteris Paribus" principle applies.*

| Parameter Name | Baseline Value | Test Value | Rationale |
| :--- | :--- | :--- | :--- |
| `[Param A]` | `[Value]` | `[Value]` | |
| `[Param B]` | `[Value]` | `[Value]` | |

---

## 5. SUCCESS CRITERIA (governance/SOP_OUTPUT)

*Quantify success before running. align with Stage-4 metrics.*

| Metric | Baseline (Current) | Target (Success) | Failure Threshold (Abort) |
| :--- | :--- | :--- | :--- |
| **Sharpe Ratio** | | `> X.X` | `< X.X` |
| **Max Drawdown %** | | `< X%` | `> Y%` |
| **Return/DD** | | `> X.X` | |
| **Win Rate** | | | |
| **Avg Concurrent** | | | `> [Capacity]` |

---

## 6. POST-RUN RESULTS (Stage-4 Output)

*Fill this section AFTER execution using `portfolio_evaluator.py` outputs.*

### 6.1 Performance Metrics

| Metric | Result | Delta vs Baseline | Pass/Fail |
| :--- | :--- | :--- | :--- |
| **Net PmL** | | | |
| **Sharpe** | | | |
| **Max DD %** | | | |
| **CAGR** | | | |

### 6.2 Risk & Behavior

* **Concurrency Peak**: [Max concurrent positions]
* **Correlation**: [Avg Pairwise Correlation]
* **Drawdown Duration**: [Days]

---

## 7. CONCLUSION & DECISION

* **Outcome**: [Hypothesis Confirmed / Rejected / Inconclusive]
* **Decision**:
  * [ ] **PROMOTE**: Move to Candidate Portfolio (Update Master Sheet)
  * [ ] **REFINE**: Adjust methodology/parameters and re-test (New Directive ID)
  * [ ] **REJECT**: Archive as failed experiment (Do not use logic)
* **Next Steps**: [Action items]

---
---

# SYSTEM GUIDE & PROTOCOL

## A. Purpose of Sections

1. **Metadata**: Establishes lineage and ownership. Vital for audit trails.
2. **Hypothesis**: Enforces "Scientific Method". Prevents random curve-fitting. You must explain *why* it should work.
3. **Config**: Maps directly to the Directive file. Ensures reproducibility.
4. **Variant**: Isolates variables. If you change 5 things, you learn nothing. Change 1-2 correlated things max.
5. **Criteria**: Prevents "moving the goalposts" after seeing results.
6. **Results**: The truth as reported by the Engine (Stage 4).
7. **Conclusion**: The actionable business decision.

## B. Iteration Protocol

### 1. Small Batch Testing (Sanity Check)

* **Scope**: 1-3 Symbols (e.g. `AUDNZD`, `EURUSD`), Short Timeframe (1-2 years).
* **Goal**: Verify the mechanism works mechanically. Check logs.
* **Exit**: If it crashes or produces 0 trades, **REJECT** immediately.

### 2. Expansion Logic (Full Backtest)

* **Scope**: Full Universe (10+ symbols), Full History (5+ years).
* **Goal**: Statistical significance. Stress test across volatility regimes.
* **Exit**: Compare against `Failure Thresholds`.

### 3. Kill-Switch Conditions

* **Drawdown** > 30% (Hard Stop).
* **Sharpe** < 0.5 (Unprofitable risk).
* **Concurrency** > 20 (Operational impossibility).

### 4. Promotion

* If **Target** met AND **Failure Threshold** avoided:
  * Save this sheet as `[Directive_ID]_REPORT.md`.
  * Update `strategies/[Name]/STRATEGY_DESCRIPTION.md`.
  * Mark `IN_PORTFOLIO = True` in `Strategy_Master_Filter.xlsx`.

---
---

# EXAMPLE: "Volatility Filter Implementation"

## 1. METADATA

* **ID**: `Range_Breakout_Filter_v2`
* **Date**: 2024-05-15

## 2. HYPOTHESIS

* **Problem**: Strategy enters false breakouts during low-volatility "chop".
* **Mechanism**: Add `ATR_Filter`. Only trade if `ATR(14) > ATR(14).SMA(50)`.
* **Prediction**: Win Rate will increase (~5%) because we avoid chop, but Total Trades will decrease (~20%). Sharpe should rise.

## 3. CONFIG

* **Timeframe**: `1h`
* **Universe**: `[EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD]`

## 4. VARIANT

| Parameter | Baseline | Test |
| :--- | :--- | :--- |
| `UseATRFilter` | `False` | `True` |
| `ATR_Period` | `N/A` | `14` |

## 5. CRITERIA

| Metric | Baseline | Target | Failure |
| :--- | :--- | :--- | :--- |
| **Sharpe** | 1.2 | > 1.4 | < 1.0 |
| **Win Rate** | 45% | > 48% | < 45% |
| **Trades** | 500 | > 350 | < 200 |

## 6. RESULTS (Sample)

| Metric | Result | Delta | Pass/Fail |
| :--- | :--- | :--- | :--- |
| **Sharpe** | **1.55** | +0.35 | **PASS** |
| **Win Rate** | **52%** | +7% | **PASS** |
| **Trades** | **380** | -120 | **PASS** |

## 7. CONCLUSION

**PROMOTE**. ATR Filter successfully filters chop without killing opportunity count.
