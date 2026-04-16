# 05_capital_and_risk_models

Read before changing capital formulas, lot sizing, profile selection, or risk model controls.

## Active Documents

| Document | Contents |
|----------|----------|
| `CAPITAL_SIZING_AUDIT.md` | **Primary reference.** Valuation layer (MT5 static), all 3 active profiles (`RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1`) with formulas, comparison matrix, rejection conditions, retail lot cap (`retail_max_lot=10`), capital sensitivity at $1k seed, XAUUSD vs FX viability notes |
| `CAPITAL_AND_SELECTION_CURRENT_2026-03-29.md` | Profile selection logic, portfolio evaluation, candidate scoring (see retail-model update note at top) |
| `CAPITAL_WRAPPER_SAFETY_AUDIT.md` | Safety invariants, gate ordering, breach guards -- heat_cap / leverage_cap are disabled (9999) in v3.0 retail profiles, only lot-floor / retail_max_lot gates remain active |
| `DYNAMIC_PIP_VALUE_FEASIBILITY.md` | Feasibility study for dynamic FX conversion (rejected -- static MT5 chosen) |

## See Also

- `11_deployment_and_burnin/` -- Go-live package audit, deployment pipeline topology, dry-run vault, strategy guard integration

## Key Decisions (2026-04-16) -- v3.0 Retail Amateur Model

- **Profile set:** Reduced from six institutional profiles to three retail profiles. Legacy `DYNAMIC_V1`, `CONSERVATIVE_V1`, `MIN_LOT_FALLBACK_V1`, `MIN_LOT_FALLBACK_UNCAPPED_V1`, `BOUNDED_MIN_LOT_V1` and the institutional $50/$10k variant of `FIXED_USD_V1` are retired. Portfolio-heat / leverage caps modelled desk-style allocation and do not apply to a single retail OctaFx account.
- **Active profiles (seed = $1,000):**
  - `RAW_MIN_LOT_V1` -- diagnostic baseline, 0.01 lot unconditionally, `raw_lot_mode=True`, no risk/heat/leverage gates. Probes directional edge independent of sizing.
  - `FIXED_USD_V1` -- retail conservative, `risk_per_trade = max(2% of equity, $20 floor)`, `heat_cap=9999`, `leverage_cap=9999` (both disabled). Sub-min_lot trades SKIP honestly -- no fallback.
  - `REAL_MODEL_V1` -- retail aggressive, tier-ramp risk (2% base, +1% per equity doubling, capped 5%, symmetric on retracement), `retail_max_lot=10.0` hard cap. OctaFx `vol_max=500` is admin/marketing, not a real retail ceiling.
- **Valuation:** MT5-verified static `tick_value/tick_size` for all 31 symbols. No dynamic FX conversion. Frozen rate drift accepted.
- **Deployment profile:** Selected per strategy by `profile_selector.py` using Return/DD ratio on the three active profiles (see SOP_PORTFOLIO_ANALYSIS §4.6).
- **Parallel reference model:** `tools/real_model_evaluator.py` writes `TradeScan_State/strategies/Real_Model_Evaluation.xlsx` as an always-on pooled-equity cross-check for every MPS row with `portfolio_status='CORE'`. NOT part of `deployed_profile` selection.
- **Capital floor:** XAUUSD remains broker-lot-bound at $1k seed -- `FIXED_USD_V1` will SKIP many trades on XAUUSD at this seed. `RAW_MIN_LOT_V1` is the honest probe for XAUUSD edge at retail capital.

## Archived Documents
See `archive/2026-03-29/` for historical reports.
