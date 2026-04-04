# 05_capital_and_risk_models

Read before changing capital formulas, lot sizing, profile selection, or risk model controls.

## Active Documents

| Document | Contents |
|----------|----------|
| `CAPITAL_SIZING_AUDIT.md` | **Primary reference.** Valuation layer (MT5 static), all 7 profiles with formulas, comparison matrix, rejection conditions, leverage calibration, capital sensitivity, XAUUSD vs FX capital floor analysis |
| `CAPITAL_AND_SELECTION_CURRENT_2026-03-29.md` | Profile selection logic, portfolio evaluation, candidate scoring |
| `CAPITAL_WRAPPER_SAFETY_AUDIT.md` | Safety invariants, gate ordering, heat/leverage breach guards, MT5 migration details |
| `DYNAMIC_PIP_VALUE_FEASIBILITY.md` | Feasibility study for dynamic FX conversion (rejected -- static MT5 chosen) |

## See Also

- `11_deployment_and_burnin/` -- Go-live package audit, deployment pipeline topology, dry-run vault, strategy guard integration

## Key Decisions (2026-04-03)

- **Valuation:** MT5-verified static `tick_value/tick_size` for all 31 symbols. No dynamic FX conversion. Frozen rate drift accepted.
- **Deployment profile:** FIXED_USD_V1, $50 risk, leverage_cap = 11x (calibrated from p99 = 10.67x)
- **Capital floor:** $10K minimum for XAUUSD (broker lot floor binds at lower capital). FX scales cleanly to $5K.
- **Acceptance rate:** 98.4% at $10K on XAUUSD portfolio; 99.4% on FX at both $5K and $10K.

## Archived Documents
See `archive/2026-03-29/` for historical reports.
