# Capital And Selection Current State
**Date:** 2026-03-29 | **Updated:** 2026-04-03 | **Retail model migration:** 2026-04-16
**Scope:** Capital metrics, sizing behavior, and deployed profile selection behavior.
**Status:** Canonical current-state reference.

> **2026-04-16 Update -- v3.0 Retail Amateur Model.** The institutional profile
> set described below (7 profiles at $10k seed with heat/leverage caps) has been
> retired. Active profile set is **three retail profiles at $1,000 seed**:
> `RAW_MIN_LOT_V1` (diagnostic, 0.01 lot unconditional), `FIXED_USD_V1`
> (retail conservative, max(2% equity, $20 floor), heat/leverage caps disabled),
> `REAL_MODEL_V1` (retail aggressive tier-ramp 2%->5% at equity doublings,
> `retail_max_lot=10`). Selection logic (Section 3+) is unchanged; only the
> profile set that feeds it has been narrowed.

## 1. Current Architecture
- Simulation and profile execution use fixed `starting_capital = 1000` (v3.0 retail). Historical runs used $10k institutional seed.
- Lot sizing is driven by profile risk logic and broker constraints, not by `capital_per_asset`.
- Profiles diverge primarily through execution behavior (accept/reject paths, risk-ramp behavior, and resulting realized PnL / drawdown outcomes).
- **Valuation layer (2026-04-03):** MT5-verified static `tick_value / tick_size` for all 31 symbols. Dynamic FX conversion removed. See `CAPITAL_SIZING_AUDIT.md` Section 1.

## 2. Key Findings
- The system operates frequently in a min-lot and constraint-sensitive regime for parts of the portfolio universe. This is more pronounced at the $1k retail seed than at the institutional $10k seed.
- `capital_per_asset` changes do not currently activate sizing differences in simulation outcomes.
- Deployed profile selection is effectively driven by risk-adjusted economic output plus execution quality penalties. Under v3.0, selection compares the three active retail profiles only (legacy deployment to institutional FIXED_USD_V1 is retired).
- **FIXED_USD_V1 is retained (as retail variant) but no longer with leverage_cap=11** -- the retail profile disables the leverage cap entirely. Historical calibration (p99=10.67x across 22,282 trades) applies to the retired institutional profile.
- **Capital floor is instrument-specific (2026-04-03, still true under retail):** XAUUSD lot-floor saturation is higher at the retail $1k seed than it was at $10k. `RAW_MIN_LOT_V1` is the honest retail XAUUSD edge probe. FX pairs still scale cleanly (0% fallback at retail sizes). Root cause: `usd_per_pu_per_lot` ratio -- XAUUSD = 100 (low, many trades hit 0.01 floor), EURUSD = 100,000 (high, lot floor never binds).

## 3. Selection System (Final Logic)
- Hard validity filter:
  - `realized_pnl > 0`
  - `capital_validity_flag == true`
- Reliability gate:
  - `total_accepted >= 50`
  - `simulation_years >= 1.0`
- Execution penalty on base score (`realized_pnl / max(max_drawdown_usd, 1)`):
  - `DEGRADED` (`rejection_rate_pct > 60`) -> `x0.4`
  - `WARNING` (`30 < rejection_rate_pct <= 60`) -> `x0.7`
  - `HEALTHY` (`<= 30`) -> `x1.0`
- Tie stabilization window (`<15%` relative score gap):
  - lower rejection rate
  - higher accepted trades
  - lexical profile name fallback
- Persistence rule:
  - keep previous deployed profile if still eligible and score >= 85% of current best
- Reliability override:
  - if reliability gate empties candidates, fallback to hard-valid set and mark `reliability_override=true`
- No-valid behavior:
  - if no hard-valid profiles remain, `deployed_profile = None`

## 4. Current Behavior
- Persistence is dominant in stable portfolios.
- Profile switching occurs mainly when score gaps are strong enough to beat persistence.
- Some portfolios are explicitly marked undeployable when no hard-valid profile exists.

## 5. Known Limitations
- Capital allocation inputs are not in the active lot-sizing control loop.
- Capital scaling sensitivity remains inactive under current architecture.
- Some strategies sit near min-lot thresholds and can be highly constraint-sensitive.
- **Static valuation drift (2026-04-03):** 21 non-USD profit-currency symbols use frozen MT5 tick_value. Maximum drift: ~12% (JPY over 2 years). Accepted as within research tolerance. See `CAPITAL_SIZING_AUDIT.md` Section 8 and `DYNAMIC_PIP_VALUE_FEASIBILITY.md` for the rejected dynamic alternative.

## 6. Future Work
- Integrate capital basis into live sizing control path.
- Activate and validate risk scaling response to capital changes.
- Tune persistence thresholds if stability/reactivity balance needs adjustment.
- Evaluate periodic MT5 tick_value refresh cadence to bound static drift on non-USD symbols.
