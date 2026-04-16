# Capital Sizing System Audit

**Last updated: 2026-04-16 (v3.0 Retail Amateur Model)**
**Valuation layer: MT5-verified static (frozen tick_value / tick_size)**
**Engine version: v1.5.4 (frozen)**

> **2026-04-16 Model Change -- Retail Retirement of Institutional Profiles.**
> The six institutional profiles (`DYNAMIC_V1`, `CONSERVATIVE_V1`, institutional
> `FIXED_USD_V1` $10k/$50, `MIN_LOT_FALLBACK_V1`, `MIN_LOT_FALLBACK_UNCAPPED_V1`,
> `BOUNDED_MIN_LOT_V1`) have been retired. They modelled desk-style portfolio
> heat / leverage caps that do not apply to a single retail OctaFx account.
> The active profile set is **three retail profiles at $1,000 seed**:
> `RAW_MIN_LOT_V1`, `FIXED_USD_V1` (retail variant), `REAL_MODEL_V1`.
> Sections 3-4 below describe the active set. Sections 9-11 preserve the
> legacy institutional calibration for historical reference -- they no longer
> govern live deployment.

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

## 3. Profile Inventory (3 Active Profiles -- v3.0 Retail Amateur Model)

### 3.1 RAW_MIN_LOT_V1 -- Diagnostic Baseline

| Parameter | Value |
|-----------|-------|
| Starting capital | $1,000 |
| Risk budget | None |
| Lot sizing | Always 0.01 (min lot) |
| Gates | None -- `raw_lot_mode: True` bypasses all checks |
| min_lot / lot_step | 0.01 / 0.01 |

**Purpose:** "Is the directional edge real?" probe. Every signal fires at 0.01 lot unconditionally, independent of sizing/risk/heat/leverage. No rejections, ever. Isolates signal quality from capital constraints so a profitable RAW run proves the signal has edge, and a loss-making RAW run proves retail deployment is not worth attempting at any sizing.

**Sizing formula:** `lot = 0.01` (constant)

---

### 3.2 FIXED_USD_V1 -- Retail Conservative

| Parameter | Value |
|-----------|-------|
| Starting capital | $1,000 |
| Risk per trade | 0.02 (2% of equity) |
| Fixed risk USD floor | $20 (effective risk = max(2% * equity, $20)) |
| Heat cap | 9999 (disabled) |
| Leverage cap | 9999 (disabled) |
| min_lot / lot_step | 0.01 / 0.01 |
| Min lot fallback | No -- sub-min_lot trades SKIP honestly |

**Purpose:** Retail conservative profile. Applies a fixed-percentage-of-equity risk with a dollar floor. The floor matters early -- at $1k seed, 2% = $20, which is the floor; as equity grows beyond $1k, risk tracks 2% of equity.

**Sizing formula:**
```
risk_capital = max(equity * 0.02, $20)
lot = floor(risk_capital / (risk_distance * usd_per_pu), 0.01)
IF lot < 0.01: REJECT (LOT_TOO_SMALL)   -- honest skip, no fallback
```

**Behavioral notes:**
- Trades that would require sub-0.01 lot (wide stops relative to $20+ risk budget) SKIP. This keeps actual risk honest -- the profile never "cheats" by taking a 0.01 lot at much higher effective risk.
- Heat and leverage caps are disabled because a single retail OctaFx account does not need desk-style portfolio heat management.
- Expected to reject many XAUUSD trades at $1k seed (wide stops * $100/pu outruns the $20 floor).

---

### 3.3 REAL_MODEL_V1 -- Retail Aggressive (Tier-Ramp)

| Parameter | Value |
|-----------|-------|
| Starting capital | $1,000 |
| Risk per trade (base) | 0.02 |
| tier_ramp | True |
| tier_base_pct / tier_step_pct / tier_cap_pct | 0.02 / 0.01 / 0.05 |
| tier_multiplier | 2.0 (doubling equity triggers step) |
| Heat cap | 9999 (disabled) |
| Leverage cap | 9999 (disabled) |
| retail_max_lot | 10.0 (hard cap) |
| min_lot / lot_step | 0.01 / 0.01 |

**Purpose:** Retail aggressive profile. Starts at 2% risk, ramps +1% each time equity doubles from the $1k start, capped at 5%. Symmetric on retracement: if equity falls below a tier threshold, risk tier steps back down. `retail_max_lot=10.0` is the real ceiling -- OctaFx `vol_max=500` is admin/marketing and not a practical retail execution limit.

**Sizing formula:**
```
tier = min(tier_cap_pct,
           tier_base_pct + floor(log(equity / starting_capital) / log(tier_multiplier))
                         * tier_step_pct)
risk_capital = equity * tier
lot = floor(risk_capital / (risk_distance * usd_per_pu), 0.01)
IF lot > retail_max_lot (10.0): REJECT (RETAIL_LOT_CAP)
IF lot < 0.01: REJECT (LOT_TOO_SMALL)   -- no fallback
```

**Tier ladder (starting at $1k):**
- $1,000 -> 2%
- $2,000 -> 3%
- $4,000 -> 4%
- $8,000 -> 5% (capped)
- any retracement below threshold steps risk back down

**Behavioral notes:**
- Tier changes compound -- doubling equity pushes the percentage risk up, so ramp is super-linear in the winning regime.
- `retail_max_lot=10` SKIPs super-large trades that would otherwise be flagged by OctaFx monitoring or hit per-order size limits on a retail account.

---

## 4. Profile Comparison Matrix

| Dimension | RAW_MIN_LOT_V1 | FIXED_USD_V1 | REAL_MODEL_V1 |
|-----------|----------------|--------------|---------------|
| Starting capital | $1,000 | $1,000 | $1,000 |
| Role | Diagnostic baseline | Retail conservative | Retail aggressive |
| Risk budget source | None (fixed 0.01 lot) | max(2% equity, $20) | tier-ramp % equity |
| Risk %, base / cap | N/A | 2% (or $20 floor) | 2% base / 5% cap |
| Scales with equity | No | Yes (above $1k) | Yes (super-linear via tier-ramp) |
| Heat cap | N/A | Disabled (9999) | Disabled (9999) |
| Leverage cap | N/A | Disabled (9999) | Disabled (9999) |
| Retail lot cap | N/A | N/A | 10.0 lot |
| Min lot fallback | N/A | No (honest skip) | No (honest skip) |
| Can reject? | Never | LOT_TOO_SMALL | LOT_TOO_SMALL, RETAIL_LOT_CAP |

---

### Retired Profiles (for historical lookup)

These profiles are no longer in the `PROFILES` dict in `tools/capital_wrapper.py` (retired 2026-04-16):

| Retired profile | Last spec | Reason retired |
|-----------------|-----------|---------------|
| `DYNAMIC_V1` | 0.5% equity risk, 3% heat, 15x leverage, 40% min-position, $10k seed | Portfolio heat / leverage caps do not apply to single retail account |
| `CONSERVATIVE_V1` | 0.25% equity risk, 4% heat, 5x leverage, $10k seed | Same -- desk-style model |
| `FIXED_USD_V1` (institutional) | $50 flat risk, 4% heat, 11x leverage, $10k seed | Superseded by retail variant ($1k seed, 2%/$20 floor, caps disabled) |
| `MIN_LOT_FALLBACK_V1` | $50 + 3x fallback, 4% heat, 5x leverage | Retail should SKIP honestly, not fall back to 0.01 at 3x target risk |
| `MIN_LOT_FALLBACK_UNCAPPED_V1` | $50 + unlimited fallback | Research-only; no live deployment use |
| `BOUNDED_MIN_LOT_V1` | $65 + 1.5x fallback, 4% heat, 5x leverage | Same fallback objection as MLF variants |

Prior calibration analysis for these profiles is preserved below (sections 9-11) for historical reference only.

---

## 5. Trade Rejection Conditions

Trades are rejected (logged, not executed) in `PortfolioState.process_entry()` under these conditions, evaluated in order:

1. **CONCURRENCY_CAP** -- if `len(open_trades) >= concurrency_cap`. Currently no profile sets this.
2. **LOT_TOO_SMALL** -- if `computed_lot < min_lot (0.01)` and `min_lot_fallback` is False. **Primary gate in the v3.0 retail model** for `FIXED_USD_V1` and `REAL_MODEL_V1`.
3. **RETAIL_LOT_CAP** -- if `computed_lot > retail_max_lot` (REAL_MODEL_V1 only; cap = 10.0).
4. **RISK_MULT_EXCEEDED / RISK_MULTIPLE_EXCEEDED** -- fallback-path reject. Only retired profiles used `min_lot_fallback`; no active profile triggers this.
5. **HEAT_CAP / HEAT_CAP_EDGE** -- `(total_open_risk + trade_risk) / equity > heat_cap`. **Disabled in all active profiles** (`heat_cap=9999`); retained in code for legacy institutional profiles.
6. **LEVERAGE_CAP** -- `(total_notional + trade_notional) / equity > leverage_cap`. **Disabled in all active profiles** (`leverage_cap=9999`); same note.

**Observed rejection patterns (burn-in run 2026-04-03, historical -- institutional profiles):**

| Profile | Index 10-sym (416 signals) | FX 9-pair (1650 signals) | Primary cause |
|---------|---------------------------|--------------------------|---------------|
| RAW_MIN_LOT_V1 | 0 | 0 | N/A |
| DYNAMIC_V1 (retired) | 92 LOT_TOO_SMALL | 39 LEV_CAP, 1 LOT | LOT (idx), LEV (FX) |
| CONSERVATIVE_V1 (retired) | 162 LOT_TOO_SMALL | 142 LEV_CAP | LOT (idx), LEV (FX) |
| FIXED_USD_V1 (institutional, retired) | 94 LOT_TOO_SMALL | 379 LEV_CAP | LOT (idx), LEV (FX) |
| MIN_LOT_FALLBACK_V1 (retired) | 9 HEAT_CAP | 379 LEV_CAP | HEAT (idx), LEV (FX) |
| MIN_LOT_FALLBACK_UNCAPPED_V1 (retired) | 9 HEAT_CAP | 379 LEV_CAP | Same as MLF |
| BOUNDED_MIN_LOT_V1 (retired) | 16 HEAT + 17 RISK_MULT | 574 LEV_CAP | Both (idx), LEV (FX) |

> **v3.0 Retail Model note:** Rejection profile for the active retail profiles
> (`FIXED_USD_V1` at $1k/2%/$20 floor and `REAL_MODEL_V1` tier-ramp) will be
> dominated by `LOT_TOO_SMALL` on instruments with wide stops relative to the
> reduced risk budget (XAUUSD especially at $1k seed). `RAW_MIN_LOT_V1` never
> rejects.

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

4. **$1K starting capital (v3.0 retail):** All three active profiles use `starting_capital: 1000.0`. This reflects the actual retail OctaFx account context. The $1k floor + $20 risk floor on `FIXED_USD_V1` means XAUUSD trades with >$2000/unit * stop distance will SKIP rather than undersize. `REAL_MODEL_V1` tier-ramp thresholds (`$1k -> 2%`, `$2k -> 3%`, etc.) also tie to this $1k seed.

5. **Lot step uniformity:** All profiles use `lot_step: 0.01`. The YAML broker specs now carry MT5-verified `min_lot` and `lot_step` per symbol, but the profile-level value overrides.

---

## 9. FIXED_USD_V1 Leverage Calibration (Historical -- Institutional Model, Retired)

> Preserved for historical traceability. Refers to the retired institutional
> `FIXED_USD_V1` profile ($10k seed, $50 risk). The v3.0 retail `FIXED_USD_V1`
> disables the leverage cap entirely (`leverage_cap=9999`).

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

## 10. Capital Sensitivity Analysis (Historical -- Institutional Model, Retired)

> Preserved for historical traceability. Refers to the retired institutional
> `FIXED_USD_V1` profile. Directly relevant takeaway that still applies to the
> retail model: **LOT_TOO_SMALL is capital-independent** and instrument-specific,
> depending only on `risk_distance * usd_per_pu` relative to the risk budget.
> At $1k retail seed with $20 risk floor, XAUUSD rejection will be much more
> aggressive than it was at $10k / $50.

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

## 11. Capital Floor: XAUUSD vs FX (Historical -- Institutional Model, Retired)

> Preserved for historical traceability. The instrument-class asymmetry (XAUUSD
> lot floor binds; FX does not) still applies to the retail model and is the
> primary reason `FIXED_USD_V1` at $1k seed will SKIP many XAUUSD trades.
> For retail XAUUSD edge measurement, use `RAW_MIN_LOT_V1` (0.01 lot
> unconditional) as the honest probe.

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
