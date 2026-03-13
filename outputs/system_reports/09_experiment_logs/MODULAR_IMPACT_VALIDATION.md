# AGENT DIRECTIVE — MODULAR IMPACT VALIDATION (REPORTING VS CORE ENGINE)

## SECTION 1 — CORE ENGINE ISOLATION CHECK

| Module | Status | Justification |
| :--- | :--- | :--- |
| `execution_loop.py` | SAFE | The loop generates raw signal interactions, extrema (MFE/MAE), and physical constraints (SL) per asset. The wrapper processes these emissions *post-engine*, meaning the core generation logic requires zero mutation to support portfolio-level constraints. |
| Strategy logic modules | SAFE | Output is pure directional alpha signals. Independent of capital geometry. |
| Indicator computation modules | SAFE | Mathematical transformations of price; entirely blind to portfolio size. |
| Signal generation logic | SAFE | Driven entirely by technical states (`check_entry`/`check_exit`). |
| Stop/Target computation logic | SAFE | ATR distance/price levels are captured perfectly at runtime before capital is even considered. |
| Volatility regime tagging | SAFE | Intrinsic market state classification relies solely on price geometry. |
| Trade lifecycle management | SAFE | `entry_timestamp` to `exit_timestamp` sequence remains universally valid for both atomic backtests and overlapping portfolio queues. |

---

## SECTION 2 — EMITTER LAYER IMPACT

**Target Files**: `execution_emitter_stage1.py`, `run_stage1.py`

| Component | Status | Justification |
| :--- | :--- | :--- |
| **Schema Extension** | ONLY EXTENSION REQUIRED | Modifying `RawTradeRecord` to include `symbol`, `initial_stop_price`, and `risk_distance` extends the schema without mutating existing outputs. |
| **Logic Change** | NO | No logic is changed. The emitter simply passes variables that `execution_loop.py` already computes but was previously dropping. |
| **Risk to Research Alpha** | NONE | Emitting 3 additional columns to a CSV has zero impact on how signals are generated or how technical states behave. |

---

## SECTION 3 — REPORTING & AGGREGATION IMPACT

| Module | Impact Status | Resolution Path |
| :--- | :--- | :--- |
| `portfolio_evaluator.py` | REPLACEMENT (For Deployable) | The current explicit summation (`portfolio_equity = daily_pnl.cumsum() + N * 5000`) is mathematically incompatible with dynamic compounding, rejected trades, and partial sizing. Must be replaced (or severely branched) to handle true sequence of return. |
| `stage2_compiler.py` | MODIFICATION / DUAL-MODE | Re-calibrating metrics like Max DD% and Sharpe logic to consume the Wrapper's dynamic equity curve instead of static reference capital. |
| Report Generators | DUAL-MODE | Required. One template for "Alpha Research" (unconstrained) and one for "Deployable Simulation" (constrained). |
| CSV Artifact Schema | MODIFICATION | The Wrapper will need to emit a *new* Stage-3 artifact (`results_deployable.csv`) containing portfolio-level events (rejections, margin calls, heat capacity). |
| Metrics Calculations | MODIFICATION | Risk/Return calculations must transition from nominal USD sums against a static baseline to true Geometric geometric percentage changes against real-time float. |

---

## SECTION 4 — CLEAN MODULAR SPLIT FEASIBILITY

Can a clean split be achieved without refactoring `execution_loop` or signal generation?

**Answer:**
YES (clean modular split feasible)

**Explanation:**
Because `execution_loop.py` correctly calculates and stores all physics locally (`entry_price`, `exit_price`, timestamps, and stops), it acts as a perfect **Alpha Generator**.

The wrapper (a new module, e.g., `Deployable_Engine_V1`) simply acts as a middle-tier **Consumer**. It ingests the raw Stage 1 CSV artifacts, sorts them into a master chronological queue across all symbols, and simulates the capital flows, rejections, and margin requirements tick-by-tick. The Research Engine remains untouched, preserving thousands of hours of legacy backtests.

---

## SECTION 5 — FINAL STRUCTURAL MAP

```mermaid
graph TD
    subgraph Layer 1: Research Engine (Untouched)
        A[Strategies & Indicators] --> B[execution_loop.py]
        B -->|Computes Raw Alpha| C[run_stage1.py]
        C --> D[execution_emitter_stage1.py]
        D -->|Emits Ext. CSV Schema| E[(RAW CSV Storage)]
    end

    subgraph Layer 2: Wrapper (New)
        E -->|Ingests all pairs| F[Deployable_Capital_Wrapper]
        F -->|Sorts Chronologically| G[Event-Driven Queue]
        G -->|Simulates Margin/Heat| H[Trade Accept/Reject Logic]
        H -->|Emits Realistic Equity| I[(DEPLOYABLE CSV Storage)]
    end

    subgraph Layer 3: Reporting (Dual-Mode)
        E -->|Unconstrained Mode| J[Legacy portfolio_evaluator]
        I -->|Constrained Mode| K[New portfolio_evaluator_v2]
        J --> L((Alpha Lab Reports))
        K --> M((Deployable Reports))
    end
```

**File Migrations & Assignments:**

- `execution_loop.py`, `run_stage1.py`, `execution_emitter_stage1.py` stay permanently in **Layer 1**.
- `portfolio_evaluator.py` splits: Legacy remains for **Layer 1**, bounded iteration built for **Layer 3**.
- **Layer 2** is completely new code (e.g., `tools/capital_wrapper.py`), protecting existing dependencies.
