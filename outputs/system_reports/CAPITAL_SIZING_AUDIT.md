# Capital Sizing System Audit

## 1. Capital Model Inventory

**Capital Wrapper (`tools/capital_wrapper.py`)**

* **Responsibility:** Primary authority for translating raw strategy signals into sized portfolio positions. Applies user-defined rules, dynamic USD conversion, and capital constraints.
* **Key Functions / Classes:**
  * `PortfolioState.compute_lot_size()`: Calculates theoretical sizing based on fixed fractional, fixed USD, or dynamic heat-aware modes.
  * `PortfolioState.process_entry()`: Checks minimum lot constraints, heat caps, leverage caps, and concurrency caps. Rejects trades that violate constraints.
  * `PortfolioState._floor_to_step()`: Rounds theoretical lots down to the nearest lot step.
  * `get_usd_per_price_unit_dynamic()`: Handles dynamic conversion of contract sizes into base USD for accurate sizing calculation.

**Friction Module (`tools/utils/research/friction.py` & `tools/robustness/friction.py`)**

* **Responsibility:** Applies conservative typical spreads and slippage friction drag directly to the final USD PnL. It does **not** alter lot size or trade admission directly.
* **Key Functions / Classes:**
  * `_cost_per_trade()`: Estimates friction cost in USD based on slippage pips, spread add pips, and pip size.
  * `apply_friction()`: Subtracts the calculated friction drag from the trade's PnL.

**Execution Engine (`engine_dev/universal_research_engine/v1_4_0/execution_loop.py`)**

* **Responsibility:** Generates size-agnostic trade signals consisting of entry/exit times, prices, stop distances, and directions based on intrinsic market state and strategy conditions. It delegates explicit capital sizing to the Capital Wrapper.
* **Key Functions / Classes:**
  * `run_execution_loop()`: Executes pure un-sized signals. Evaluates entry gating through `strategy.filter_stack.allow_direction()`.

---

## 2. Position Size Formula

**`CONSERVATIVE_V1`**

* **Method:** Fixed Fractional (Lower Risk)
* **Formula:** `lot_size = Floor( (equity * risk_per_trade) / (risk_distance * usd_per_pu_per_lot) , lot_step )`
* **Parameters:** `risk_per_trade = 0.0025` (0.25%), `lot_step = 0.01`

**`DYNAMIC_V1`**

* **Method:** Dynamic Heat-Aware Scaling
* **Formula:**
    1. `base_risk_capital = equity * risk_per_trade`
    2. `remaining_heat_usd = max((heat_cap * equity) - total_open_risk, 0.0)`
    3. `risk_capital = min(base_risk_capital, remaining_heat_usd)`
    4. *(Skip trade if `risk_capital < base_risk_capital * min_position_pct`)*
    5. `lot_size = Floor( risk_capital / (risk_distance * usd_per_pu_per_lot) , lot_step )`
* **Parameters:** `risk_per_trade = 0.005` (0.5%), `heat_cap = 0.03` (3.0%), `lot_step = 0.01`, `min_position_pct = 0.40`

**`FIXED_USD_V1`**

* **Method:** Fixed USD Risk
* **Formula:** `lot_size = Floor( fixed_risk_usd / (risk_distance * usd_per_pu_per_lot) , lot_step )`
* **Parameters:** `fixed_risk_usd = 50.0`, `lot_step = 0.01`

---

## 3. Trade Rejection Conditions

Trades are explicitly rejected (logged but not executed) in `PortfolioState.process_entry()` under the following conditions:

1. **Concurrency Cap:** (`CONCURRENCY_CAP`)
    * Evaluated if the profile has a `concurrency_cap` configured. Rejects if current `open_trades >= concurrency_cap`.
2. **Minimum Lot Restraint:** (`LOT_TOO_SMALL`)
    * Rejects if the computed `lot_size` falls strictly below the profile's `min_lot` parameter (0.01 for all three profiles). Also activated in `DYNAMIC_V1` if the scaled risk is less than 40% of the base risk, resulting in a pre-emptive size of 0.0.
3. **Heat Constraint Breach:** (`HEAT_CAP` / `HEAT_CAP_EDGE`)
    * Rejects if adding the new trade's `trade_risk_usd` pushes the total portfolio heat percentage (`total_open_risk / equity`) above the profile's `heat_cap` (3.0% for DYNAMIC, 4.0% for others).
4. **Leverage Constraint Breach:** (`LEVERAGE_CAP`)
    * Rejects if the new total notional exposure (`total_notional / equity`) exceeds the profile's `leverage_cap` (15x for DYNAMIC, 5x for CONSERVATIVE/FIXED).

---

## 4. Execution Adjustments

Modifications made to theoretical sizing before recording the finalized open trade:

1. **Rounding:** The continuous fractional `raw_lots` calculated via the risk distance formula is explicitly rounded **down** (floored) to the nearest `lot_step` (typically 0.01) using `PortfolioState._floor_to_step()`.
2. **Minimum Lot Enforcement:** Implemented strictly as a rejection gate rather than an adjustment. If the floored lot size is `< min_lot` (0.01), it is not rounded up to the minimum lot; the trade is entirely rejected.
3. **Leverage Constraints:** Handled passively via rejection. The pipeline does not currently scale down trade sizes to fit leverage limits; it outright rejects the entire trade if `leverage_cap` is breached.
4. **Heat Scaling:** Unique to `DYNAMIC_V1`, theoretical fixed-fractional size is actively scaled down before execution to fit exactly within the `remaining_heat_usd` budget, provided the clamped size does not fall below the 40% `min_position_pct` threshold.

---

## 5. Overlap Detection

1. **Trade Admission Control Overlaps:**
    * **Engine vs. Capital Wrapper:** The execution engine checks directional admittance (`strategy.filter_stack.allow_direction()`) and stop-distance violations conceptually before the signal reaches the Capital Wrapper. The Capital Wrapper then re-evaluates admission linearly through heat, concurrency, and leverage barriers.
2. **Risk Parameter Redundancy:**
    * Alternative sizing exploration exists disconnected from execution inside `tools/analyze_capital_models.py` (e.g., maximum concurrent risk per symbol based on MAE).
3. **Sizing Constraints Overlap:**
    * `DYNAMIC_V1` applies dynamic heat-scaling (which artificially shrinks lot size) but immediately follows it up with a hard `heat_cap` rejection check, creating a potential redundancy since the scaled risk logic fundamentally aims to prevent crossing the heat cap border.

---

## 6. Capital Flow Diagram

1. **Signal Generation:** Execution Engine evaluates `check_entry()`, computes distance to stop (`risk_distance`), asserts rules via `allow_direction()`, and generates size-agnostic `TradeEvent`s.
2. **Conversion Loading:** `Capital Wrapper` computes `usd_per_price_unit_per_lot` using dynamic historical conversion lookups (`ConversionLookup`) mapping the base/quote currency to USD for the specific entry date.
3. **Base Capital Scaling:** `PortfolioState` translates risk distance into theoretical continuous `raw_lots` utilizing either structural percent-equity or fixed-usd rules.
4. **Dynamic Clamping:** If `DYNAMIC_V1`, clamps risk capital to `remaining_heat_usd` bounds.
5. **Discrete Floor:** Floored `lot_size` is calculated down to strictly adhere to broker `lot_step`.
6. **Constraint Gates:** The proposed `lot_size` sequentially runs the gauntlet against:
    * `min_lot` threshold.
    * `heat_cap` max open threshold.
    * `leverage_cap` notional tracking limit.
7. **Final Execution:** Trade is officially recorded in the running `PortfolioState`, consuming simulated equity margins and establishing exact PnL parameters ready for `friction.py` adjustments.

---

## 7. Current System Summary

The pipeline strictly isolates market-driven signal generation from portfolio constraints. Theoretical entry and exit signals are formulated by the `universal_research_engine` without any knowledge of capital size or constraints. These signals undergo transformation exclusively within the Phase 2-6 `capital_wrapper.py`.

The wrapper projects discrete profiles (`CONSERVATIVE_V1`, `DYNAMIC_V1`, `FIXED_USD_V1`) onto the signals sequentially. Rather than dynamically attempting to repair large or risky trades (excluding `DYNAMIC_V1`'s heat scaling), the system employs binary acceptance logic. Trades violating minimum size (after down-rounding), maximum notional leverage, or total risk heat are flatly rejected and sequestered in logs. Final system deliverables are fully simulated portfolios embodying pure equity-curve results mathematically exposed to later-stage theoretical spread and slippage friction stress-tests.
