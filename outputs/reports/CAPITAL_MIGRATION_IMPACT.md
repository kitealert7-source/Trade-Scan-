# AGENT DIRECTIVE — CAPITAL ENGINE MIGRATION IMPACT ASSESSMENT

## SECTION 1 — CURRENT ARCHITECTURE SNAPSHOT

| Component | Current Location | Implementation Detail |
| :--- | :--- | :--- |
| **Position Sizing Computation** | `tools/run_stage1.py` | Sizing is fixed per trade (`min_lot` * `multiplier` optional). Applied post-logic execution, decoupled from running equity. |
| **Equity Curve Construction** | `tools/stage2_compiler.py`, `tools/portfolio_evaluator.py` | Built via linear additive summation of nominal `pnl_usd` per independent trade sequence. |
| **Portfolio Aggregation** | `tools/portfolio_evaluator.py` | Post-facto alignment of CSV logs by timestamp. No runtime interactivity. |
| **Risk Calculation** | `engine_dev/universal_research_engine/.../execution_loop.py` | Raw distance logic (Entry - Stop Price) captured at signal generation time. |
| **Margin Modeling** | **DATA NOT AVAILABLE** | Unmodeled. Assumes infinite portfolio leverage. |
| **Trade Rejection Logic** | **DATA NOT AVAILABLE** | Non-existent. Signals map to fills 100% of the time regardless of capital constraints. |

**Data Flow Summary:**

1. Pipeline calls `run_stage1.py` per symbol independently.
2. `execution_loop.py` generates signals (Entry → Exit) entirely ignorant of capital.
3. `run_stage1.py` linearly maps price distance to fixed-lot `pnl_usd` (ignoring margin/leverage).
4. Emits `pnl_usd` to CSV.
5. Post-processors (`stage2_compiler`, `portfolio_evaluator`) linearly sum CSV `pnl_usd` columns sequentially against a fake, static \$10,000 baseline.

---

## SECTION 2 — REQUIRED STRUCTURAL CHANGES

| Upgrade Component | Files/Modules Affected | Scope | Complexity | Breaking Risk |
| :--- | :--- | :--- | :--- | :--- |
| **Shared Capital Pool** | `run_stage1.py`, `pipeline_utils.py` | Cross-Engine | HIGH | Very High |
| **Real-Time Equity Tracking** | `execution_loop.py`, `run_stage1.py` | Cross-Engine | HIGH | High |
| **Fixed Fractional Sizing** | `execution_loop.py` | Localized | MEDIUM | Medium |
| **Portfolio Heat Tracking** | `execution_loop.py` (needs cross-asset context) | Cross-Engine | HIGH | High |
| **Leverage/Notional Caps** | `execution_loop.py` | Localized | MEDIUM | Medium |
| **Trade Rejection Logic** | `execution_loop.py` | Localized | LOW | Medium |
| **Additive Builder Replacement** | `portfolio_evaluator.py` | Localized | HIGH | High |
| **Compounding Integration** | `execution_loop.py`, emitted CSVs | Cross-Engine | HIGH | High |
| **Backward Compatibility** | `pipeline_utils.py`, `stage2_compiler.py` | Cross-Engine | MEDIUM | High |

---

## SECTION 3 — CHANGE FOOTPRINT ANALYSIS

| Area | Impact Assessment |
| :--- | :--- |
| **Lines of Code Affected** | 1,500 - 3,000 LOC |
| **Core Files to Modify** | `execution_loop.py`, `run_stage1.py`, `portfolio_evaluator.py`, `stage2_compiler.py`, `execution_emitter_stage1.py` |
| **`portfolio_evaluator` Rewrite?** | YES. The current evaluator assumes static sum lines. It must be rewritten to handle variable fractional sizes and shared DD scaling. |
| **`execution_loop` Change?** | YES. Loop currently processes 1 asset at a time unconditionally. Must be refactored to process *ticks/bars* across *all assets simultaneously* (Event-Driven or Multi-Asset Vectorized) to track shared capital logic. |
| **CSV Artifacts Format Change?** | YES. Must include properties like `capital_utilized`, `available_margin`, `rejected_flag`, `portfolio_equity_at_entry`. |

---

## SECTION 4 — COMPLEXITY CLASSIFICATION

**Classification:** MAJOR ARCHITECTURAL REFACTOR

**Justification:**
Moving from an isolated, post-facto summation model to a real-time, shared-capital, cross-correlating margin engine is not a patch. It requires replacing the fundamental execution loop from navigating one row at a time for a single symbol to managing a consolidated, chronologically synchronized data frame containing all symbols, and updating a central state object (The Portfolio Margin Account) at every tick.

---

## SECTION 5 — IMPLEMENTATION RISK

| Risk Type | Assessment |
| :--- | :--- |
| **Highest Risk Module** | The `execution_loop.py` vectorization to chronological multi-asset event processing. |
| **Data Inconsistencies** | Aligning disjointed bar timestamps across 15+ symbols without Lookahead Bias. |
| **Performance Impact** | Transitioning from 1D single-asset arrays to an N-Asset chronological state machine will severely hit execution speed (estimated 10x - 50x slowdown without heavy optimization). |
| **Historical Comparability** | Complete breakage. Compounding and heat rejection will radically alter 19-year drawdowns and CAGRs. Previous static-lot backtests will instantly become non-comparable to V1 output. |

---

## SECTION 6 — MIGRATION STRATEGY RECOMMENDATION

**RANKED PROPOSALS:**

1. **(A) Modular Capital Layer Wrapper**
   *Create a brand new Engine (e.g., `Deployable_Engine_V1`) alongside the current `Universal_Research_Engine`. Leave the Research layer untouched for initial alpha discovery. Pass Research signals into the new Wrapper to handle rejection, compounding, and realistic DD mapping. Lowest risk to current integrity.*
2. **(B) Run Dual Mode (Alpha Lab + Deployable Engine)**
   *Similar to A, but forks the codebase entirely to prevent cross-contamination of metric schema.*
3. **(C) Replace Current Engine Entirely**
   *Not recommended. Will break all legacy validations and heavily slow down atomic strategy testing due to portfolio overhead required for a single symbol.*
