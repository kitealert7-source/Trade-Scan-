# Capital Sizing System Audit

**Last updated: 2026-04-03**
**Valuation layer: MT5-verified static (frozen tick_value / tick_size)**
**Engine version: v1.5.4 (frozen)**

---

## 1. Valuation Layer

All PnL and risk computation flows through a single formula:

```
usd_per_pu_per_lot = mt5_tick_value / mt5_tick_size
pnl = (exit_price - entry_price) * direction * usd_per_pu_per_lot * lot_size
trade_risk_usd = risk_distance * usd_per_pu_per_lot * lot_size
```

**Source of truth:** Each broker spec YAML (`data_access/broker_specs/OctaFx/*.yaml`) stores `calibration.usd_pnl_per_price_unit_0p01`, derived from MT5 `symbol_info()` extraction on 2026-04-02. The simulation reads this and multiplies by 100 to get `usd_per_pu_per_lot`.

**Verification:** `tools/verify_broker_specs.py --mt5-json` confirms all 31 symbols at ratio 1.0000 against MT5 ground truth.

**Key values (representative):**

| Symbol | tick_value | tick_size | usd_per_pu_per_lot | currency_profit |
|--------|-----------|-----------|-------------------|-----------------|
| XAUUSD | 1.0 | 0.01 | 100.0 | USD |
| EURUSD | 1.0 | 0.00001 | 100,000.0 | USD |
| USDJPY | 0.627 | 0.001 | 627.0 | JPY |
| NAS100 | 1.0 | 0.1 | 10.0 | USD |
| SPX500 | 0.1 | 0.1 | 1.0 | USD |
| JPN225 | 0.627 | 1.0 | 0.627 | JPY |
| GER40 | 1.153 | 0.1 | 11.53 | EUR |
| EURGBP | 1.321 | 0.00001 | 132,131.0 | GBP |

**Design decision:** Static valuation is used for ALL 31 symbols. For the 21 non-USD profit-currency symbols, the frozen tick_value embeds the FX rate at extraction time. This introduces bounded drift (up to ~12% for JPY over 2 years) which is accepted as within research tolerance for risk sizing. No dynamic conversion is used.

---

## 2. Capital Model Inventory

**Capital Wrapper (`tools/capital_wrapper.py`)**

* **Responsibility:** Translates raw strategy signals into sized portfolio positions across multiple risk profiles. Applies user-defined rules and capital constraints.
* **Key code paths:**
  * `PortfolioState.compute_lot_size()` — calculates lot from risk budget and risk_distance
  * `PortfolioState.process_entry()` — applies gate sequence (concurrency, lot floor, heat, leverage)
  * `PortfolioState.process_exit()` — computes realized PnL using stored `usd_per_price_unit_per_lot`
  * `get_usd_per_price_unit_static()` — reads YAML calibration, returns `usd_pnl_per_price_unit_0p01 * 100`

**Friction Module (`tools/robustness/friction.py`)**

* Applies conservative spread and slippage drag to final USD PnL. Does not alter lot size or trade admission.

**Execution Engine (`engine_dev/universal_research_engine/v1_5_4/execution_loop.py`)**

* Generates size-agnostic trade signals: entry/exit times, prices, stop distances, directions. Delegates all capital sizing to the Capital Wrapper.

---

## 3. Profile Inventory (7 Profiles)

### 3.1 RAW_MIN_LOT_V1 -- Baseline Signal Quality

| Parameter | Value |
|-----------|-------|
| Risk budget | None |
| Lot sizing | Always 0.01 (min lot) |
| Gates | None -- `raw_lot_mode: True` bypasses all checks |
| Starting capital | $10,000 |

**Purpose:** Pure signal measurement. Every signal is executed at minimum lot unconditionally. No rejections ever. Provides the unfiltered directional edge of the strategy. All other profiles are compared against this.

**Sizing formula:** `lot = 0.01` (constant)

---

### 3.2 DYNAMIC_V1 -- Heat-Aware Fractional

| Parameter | Value |
|-----------|-------|
| Risk budget | 0.5% of equity (dynamic) |
| Heat cap | 3.0% |
| Leverage cap | 15x |
| Dynamic scaling | Yes |
| Min position % | 40% |
| Starting capital | $10,000 |

**Purpose:** Aggressive equity-growth profile. Scales position size with equity. Actively shrinks risk allocation when approaching heat cap. Skips trade entirely if remaining heat budget would produce a position < 40% of base risk (avoids taking negligible positions).

**Sizing formula:**
```
base_risk = equity * 0.005
remaining_heat = max((0.03 * equity) - total_open_risk, 0)
risk_capital = min(base_risk, remaining_heat)
IF risk_capital < base_risk * 0.40: REJECT (LOT_TOO_SMALL)
lot = floor(risk_capital / (risk_distance * usd_per_pu), 0.01)
```

**Behavioral notes:**
- At $10K equity, base risk = $50. Max 3% heat = $300 open risk.
- With 6 concurrent positions at $50 risk each = $300, fully saturated.
- The 40% min_position_pct means it won't take a trade at < $20 risk budget.

---

### 3.3 CONSERVATIVE_V1 -- Lower Fixed Fractional

| Parameter | Value |
|-----------|-------|
| Risk budget | 0.25% of equity |
| Heat cap | 4.0% |
| Leverage cap | 5x |
| Starting capital | $10,000 |

**Purpose:** Conservative equity-scaling profile. Half the per-trade risk of DYNAMIC. Tighter leverage cap but wider heat cap. No dynamic scaling -- allocates full 0.25% on every accepted trade.

**Sizing formula:**
```
risk_capital = equity * 0.0025
lot = floor(risk_capital / (risk_distance * usd_per_pu), 0.01)
```

**Behavioral notes:**
- At $10K equity, risk = $25/trade. Rejects more via LOT_TOO_SMALL because $25 often can't buy 0.01 lot on wider-stop instruments.
- The 5x leverage cap is the binding constraint for FX (EURUSD notional at 0.01 lot = $1,080 = 10.8% of equity per position).

---

### 3.4 FIXED_USD_V1 -- Fixed Dollar Risk (Deployment Profile)

| Parameter | Value |
|-----------|-------|
| Risk budget | $50 flat |
| Heat cap | 4.0% |
| Leverage cap | 11x (calibrated 2026-04-03) |
| Starting capital | $10,000 |

**Purpose:** Constant dollar risk regardless of equity level. No compounding -- risk stays at $50/trade whether equity is $8K or $15K. Simplest model for comparing strategy quality across time. **Selected as the deployment profile.**

**Sizing formula:**
```
lot = floor($50 / (risk_distance * usd_per_pu), 0.01)
IF lot < 0.01: REJECT (LOT_TOO_SMALL)
```

**Behavioral notes:**
- Instruments with large risk_distance * usd_per_pu may not be sizable at 0.01 lot within $50 budget. Example: US30 with 1000pt stop = $100 risk at min lot > $50 budget = rejected.
- No fallback mechanism. Trade is simply not taken.

**Leverage cap calibration (2026-04-03):**
- p99 required leverage across 22,282 shadow trades: **10.67x**
- Cap set to 11x (ceiling of p99) to achieve >98% acceptance
- Validated: 98.4% acceptance on full portfolio (PF_E1FCD12A8EC3, 906 trades)

---

### 3.5 MIN_LOT_FALLBACK_V1 -- Fixed Dollar with Override

| Parameter | Value |
|-----------|-------|
| Risk budget | $50 flat |
| Heat cap | 4.0% |
| Leverage cap | 5x |
| Min lot fallback | Yes |
| Max risk multiple | 3.0x |
| Track risk override | Yes |
| Starting capital | $10,000 |

**Purpose:** Same as FIXED_USD_V1 but when computed lot < 0.01, falls back to 0.01 lot instead of rejecting. Accepts trades where actual risk is up to 3x the $50 target (up to $150 actual risk).

**Sizing formula:**
```
lot = floor($50 / (risk_distance * usd_per_pu), 0.01)
IF lot < 0.01:
    lot = 0.01  (fallback)
    actual_risk = risk_distance * usd_per_pu * 0.01
    IF actual_risk > $50 * 3.0: REJECT (RISK_MULT_EXCEEDED)
```

**Behavioral notes:**
- Captures trades that FIXED_USD_V1 misses due to wide stops.
- The 3x cap ($150) prevents taking trades where min lot risk is absurdly large.
- `track_risk_override: True` logs every fallback for audit.

---

### 3.6 MIN_LOT_FALLBACK_UNCAPPED_V1 -- Research Only

| Parameter | Value |
|-----------|-------|
| Risk budget | $50 flat |
| Heat cap | 4.0% |
| Leverage cap | 5x |
| Min lot fallback | Yes |
| Max risk multiple | None (uncapped) |
| Track risk override | Yes |
| Starting capital | $10,000 |

**Purpose:** Research-only profile. Same as MIN_LOT_FALLBACK_V1 but with no risk multiple cap. Will take any trade at 0.01 lot regardless of how much the actual risk exceeds $50. Useful for measuring what the fallback population looks like without artificial truncation.

**Sizing formula:**
```
lot = floor($50 / (risk_distance * usd_per_pu), 0.01)
IF lot < 0.01: lot = 0.01  (always, no rejection)
```

**Behavioral notes:**
- Never rejects on RISK_MULT_EXCEEDED.
- Still subject to heat cap and leverage cap.
- Should NOT be used for live deployment. Exists to bound the "what if we took everything" scenario.

---

### 3.7 BOUNDED_MIN_LOT_V1 -- Tight Fallback

| Parameter | Value |
|-----------|-------|
| Risk budget | $65 flat |
| Heat cap | 4.0% |
| Leverage cap | 5x |
| Min lot fallback | Yes |
| Max risk multiple | 1.5x |
| Starting capital | $10,000 |

**Purpose:** Tighter version of MIN_LOT_FALLBACK. Higher base risk ($65 vs $50) but much stricter risk multiple cap (1.5x vs 3.0x). This means actual risk on fallback trades is capped at $97.50. Rejects aggressively on wider stops.

**Sizing formula:**
```
lot = floor($65 / (risk_distance * usd_per_pu), 0.01)
IF lot < 0.01:
    lot = 0.01
    actual_risk = risk_distance * usd_per_pu * 0.01
    IF actual_risk > $65 * 1.5: REJECT (RISK_MULTIPLE_EXCEEDED)
```

**Behavioral notes:**
- The $65 base means it can size slightly larger lots than $50 profiles.
- The 1.5x cap is very tight -- a US30 trade with 1000pt stop ($100 risk) would fail: $100 / $65 = 1.54x > 1.5x.
- This is the burn-in profile for the 10-index daily strategy (02_VOL_IDX).

---

## 4. Profile Comparison Matrix

| Dimension | RAW | DYNAMIC | CONSERVATIVE | FIXED_USD | MLF | MLF_UNCAP | BOUNDED |
|-----------|-----|---------|-------------|-----------|-----|-----------|---------|
| Risk budget source | None | % equity | % equity | $ flat | $ flat | $ flat | $ flat |
| Risk amount | N/A | 0.5% | 0.25% | $50 | $50 | $50 | $65 |
| Scales with equity | No | Yes | Yes | No | No | No | No |
| Heat cap | N/A | 3% | 4% | 4% | 4% | 4% | 4% |
| Leverage cap | N/A | 15x | 5x | **11x** | 5x | 5x | 5x |
| Min lot fallback | N/A | No | No | No | Yes | Yes | Yes |
| Risk multiple cap | N/A | N/A | N/A | N/A | 3.0x | None | 1.5x |
| Dynamic scaling | N/A | Yes | No | No | No | No | No |
| Min position % | N/A | 40% | 0% | 0% | 0% | 0% | 0% |
| Can reject? | Never | Yes | Yes | Yes | Yes | Rarely | Yes |

---

## 5. Trade Rejection Conditions

Trades are rejected (logged, not executed) in `PortfolioState.process_entry()` under these conditions, evaluated in order:

1. **CONCURRENCY_CAP** -- if `len(open_trades) >= concurrency_cap`. Currently no profile sets this.
2. **LOT_TOO_SMALL** -- if `computed_lot < min_lot (0.01)` and `min_lot_fallback` is False.
3. **RISK_MULT_EXCEEDED / RISK_MULTIPLE_EXCEEDED** -- if fallback is active and `actual_risk / target_risk > max_risk_multiple`.
4. **HEAT_CAP / HEAT_CAP_EDGE** -- if `(total_open_risk + trade_risk) / equity > heat_cap`.
5. **LEVERAGE_CAP** -- if `(total_notional + trade_notional) / equity > leverage_cap`.

**Observed rejection patterns (burn-in run 2026-04-03):**

| Profile | Index 10-sym (416 signals) | FX 9-pair (1650 signals) | Primary cause |
|---------|---------------------------|--------------------------|---------------|
| RAW | 0 | 0 | N/A |
| DYNAMIC | 92 LOT_TOO_SMALL | 39 LEV_CAP, 1 LOT | LOT (idx), LEV (FX) |
| CONSERVATIVE | 162 LOT_TOO_SMALL | 142 LEV_CAP | LOT (idx), LEV (FX) |
| FIXED_USD | 94 LOT_TOO_SMALL | 379 LEV_CAP | LOT (idx), LEV (FX) |
| MLF | 9 HEAT_CAP | 379 LEV_CAP | HEAT (idx), LEV (FX) |
| MLF_UNCAP | 9 HEAT_CAP | 379 LEV_CAP | Same as MLF |
| BOUNDED | 16 HEAT + 17 RISK_MULT | 574 LEV_CAP | Both (idx), LEV (FX) |

**Interpretation:**
- **Indices** are low-notional (e.g., SPX500 at 0.01 lot = $55 notional). Leverage cap never binds. The binding constraint is LOT_TOO_SMALL (risk budget too small for min lot at wide stops) or HEAT_CAP (for fallback profiles).
- **FX** is high-notional (EURUSD at 0.01 lot = $1,080). Leverage cap is the dominant constraint. At 5x cap on $10K equity, only ~4-5 concurrent FX positions fit.

---

## 6. Execution Adjustments

1. **Floor rounding:** `raw_lots` is floored to nearest `lot_step` (0.01). Never rounded up.
2. **Minimum lot enforcement:** Binary rejection, not adjustment (except with `min_lot_fallback`).
3. **Leverage constraint:** Binary rejection. Lot size is never scaled down to fit -- trade is rejected entirely.
4. **Heat scaling (DYNAMIC only):** Risk capital is actively clamped to `remaining_heat_usd` before lot computation. The subsequent heat_cap rejection is a safety net for rounding.

---

## 7. Capital Flow Diagram

```
Signal Generation (Engine v1.5.4)
  |
  v
TradeEvent (entry_price, exit_price, risk_distance, direction)
  |
  v
Broker Spec Lookup -> usd_per_pu_per_lot = usd_pnl_per_price_unit_0p01 * 100
  |                    (MT5-verified, static, frozen at extraction date)
  v
compute_lot_size(risk_distance, usd_per_pu_per_lot)
  |  risk_budget = fixed_risk_usd OR equity * risk_per_trade
  |  lot = floor(risk_budget / (risk_distance * usd_per_pu), lot_step)
  v
Gate Sequence:
  1. Concurrency check
  2. Min lot check (reject or fallback)
  3. Risk multiple check (if fallback)
  4. Heat cap check
  5. Leverage cap check
  |
  v
Accept -> OpenTrade stored with usd_per_pu, lot, risk_usd
  |
  v
process_exit -> pnl = (exit - entry) * direction * usd_per_pu * lot
```

---

## 8. Known Constraints and Design Decisions

1. **Static valuation drift:** Non-USD profit-currency symbols (21 of 31) use a frozen tick_value from MT5 extraction date. Maximum observed drift: ~12% (JPY pairs over 2-year backtest). Accepted as within research tolerance.

2. **No position scaling to fit leverage:** If a trade would breach the leverage cap, it is rejected outright. No mechanism exists to scale the lot down to fit under the cap. This is by design -- partial fills would complicate the PnL attribution.

3. **Heat cap redundancy in DYNAMIC_V1:** The dynamic scaling logic already clamps risk to remaining heat budget, making the hard heat_cap rejection check largely redundant. It exists as a safety net for floating-point rounding edge cases.

4. **$10K starting capital is hardcoded:** All profiles use `starting_capital: 10000.0`. This is a simulation parameter, not a live account balance. Changing it affects lot sizing for fractional profiles (DYNAMIC, CONSERVATIVE) but not fixed-dollar profiles.

5. **Lot step uniformity:** All profiles use `lot_step: 0.01`. The YAML broker specs now carry MT5-verified `min_lot` and `lot_step` per symbol, but the profile-level value overrides.

---

## 9. FIXED_USD_V1 Leverage Calibration

**Date:** 2026-04-03
**Method:** Computed required leverage for every trade in the shadow portfolio (22,282 trades across all strategies and symbols), then selected the ceiling of p99.

| Percentile | Required Leverage |
|------------|------------------|
| p50 | 1.82x |
| p75 | 3.91x |
| p90 | 6.73x |
| p95 | 8.23x |
| **p99** | **10.67x** |
| max | 21.62x |

**Calibrated value:** `leverage_cap = 11` (ceiling of p99).

**Validation run (PF_E1FCD12A8EC3, 6-engine XAUUSD portfolio, 906 trades):**

| Metric | Value |
|--------|-------|
| Acceptance rate | 98.4% |
| Rejections | 15 (all LEVERAGE_CAP) |
| Invariant breaches | 0 |

---

## 10. Capital Sensitivity Analysis

**Date:** 2026-04-03
**Profile:** FIXED_USD_V1 with leverage_cap=11, risk=$50

Tested at three capital levels ($5K, $10K, $20K) against the same 22,282 trade events:

| Capital | Accepted | Rejected | Acceptance % | Binding Constraint |
|---------|----------|----------|-------------|-------------------|
| $5,000 | 19,154 | 3,095 | 86.1% | LOT_TOO_SMALL (62%), LEVERAGE (23%), HEAT (15%) |
| $10,000 | 21,428 | 821 | 96.3% | LEVERAGE (primary) |
| $20,000 | 22,078 | 171 | 99.2% | LEVERAGE (only) |

**LOT_TOO_SMALL is capital-independent** -- it depends only on risk_distance * usd_per_pu vs the $50 budget. The 3.8% baseline rejection at all capital levels comes from this.

---

## 11. Capital Floor: XAUUSD vs FX

**Date:** 2026-04-03
**Question:** Does the $10K capital floor observed on XAUUSD apply to FX?

Tested with FIXED_USD_V1 + min_lot_fallback (matched absolute risk cap $150) on two instrument classes:

### 11.1 XAUUSD (PF_E1FCD12A8EC3, 6 engines, 902 accepted trades)

| Metric | $10K / $50 | $5K / $25 |
|--------|-----------|----------|
| Accepted | 902 | 902 |
| Rejected | 4 | 4 |
| Acceptance % | 99.56% | 99.56% |
| Fallback trades (0.01 lot) | 162 (18.0%) | **409 (45.3%)** |
| Total PnL | $8,731 | $4,968 |
| PnL ratio | -- | **1.76** (expected 2.0) |
| Max DD % | 3.25% | 3.38% |

**Conclusion:** At $5K on XAUUSD, 45% of trades hit the broker lot floor. These produce identical PnL at both capital levels (both use 0.01 lot), dragging the blended ratio from 2.0 to 1.76. Risk on fallback trades is uncontrolled (actual risk > target). **$10K is the minimum operating capital for XAUUSD under FIXED_USD.**

### 11.2 FX (01_MR_FX_1H_ULTC_REGFILT_S07_V1_P01, 5 pairs, 1944 accepted trades)

| Metric | $10K / $50 | $5K / $25 |
|--------|-----------|----------|
| Accepted | 1,942 | 1,944 |
| Rejected | 13 | 11 |
| Acceptance % | 99.34% | 99.44% |
| Fallback trades (0.01 lot) | **0 (0.0%)** | **0 (0.0%)** |
| Total PnL | -$1,219 | -$547 |
| PnL ratio | -- | **2.23** |
| Max DD % | 30.60% | 29.36% |

Per-symbol breakdown:

| Symbol | $10K fb% | $5K fb% | PnL ratio |
|--------|----------|---------|-----------|
| AUDUSD | 0.0% | 0.0% | 2.30 |
| EURUSD | 0.0% | 0.0% | 2.00 |
| GBPNZD | 0.0% | 0.0% | 2.15 |
| GBPUSD | 0.0% | 0.0% | 3.58 |
| USDJPY | 0.0% | 0.0% | 2.06 |

**Conclusion:** FX has **zero fallback trades at any capital level**. The lot floor never binds because FX pairs have high `usd_per_pu_per_lot` values (e.g., EURUSD = 100,000), producing large lot numbers even at $25 risk. FX scales cleanly to $5K. Only binding constraint: LEVERAGE_CAP (minor, <1%).

### 11.3 Why the Difference

The lot floor formula: `lot = risk / (risk_distance * usd_per_pu_per_lot)`.

For XAUUSD (`usd_per_pu = 100`): lot = 25 / (risk_distance * 100). Falls below 0.01 when risk_distance > 2.5 price units ($250 move). Many XAUUSD trades have wider stops.

For EURUSD (`usd_per_pu = 100,000`): lot = 25 / (risk_distance * 100,000). Falls below 0.01 when risk_distance > 0.0025 (25 pips). Nearly zero FX trades have stops this wide in pip terms relative to the unit scale.

**The capital floor is instrument-specific, not universal.** It depends on the ratio of risk_distance to usd_per_pu_per_lot.
