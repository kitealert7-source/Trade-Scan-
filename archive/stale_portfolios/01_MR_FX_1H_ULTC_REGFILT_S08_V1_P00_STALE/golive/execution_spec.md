# Execution Spec

- Strategy: `01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00`
- Profile: `FIXED_USD_V1`
- Generated UTC: `2026-03-11T13:32:05Z`

## Universe

- Symbols (6): AUDNZD, AUDUSD, EURUSD, GBPNZD, GBPUSD, USDJPY

## Entry Execution

- Order type: `market`
- Execution timing: `next_bar_open`
- Session reset: `utc_day` (default)

## Exit / Risk Rules

- Stop loss config: `{"multiple": 1.35, "type": "atr_multiple"}`
- Take profit config: `{"enabled": false}`
- Trailing stop config: `{"enabled": false}`
- Trade management: `{"direction_restriction": "none", "reentry": {"allowed": true}}`

## Live Enforcement (Selected Profile)

- Enforcement: `{"max_leverage": 5, "max_open_trades": null, "max_portfolio_risk_pct": 0.04}`
- Sizing: `{"dynamic_scaling": false, "fixed_risk_usd": 50.0, "lot_step": 0.01, "max_risk_multiple": null, "min_lot": 0.01, "min_lot_fallback": false, "min_position_pct": null, "risk_per_trade": 0.005, "starting_capital": 10000.0}`

## Explicit Assumptions

- Non-FX symbols are treated as USD-quoted for conversion in the capital wrapper.
- USD-quote FX pairs require no conversion pair snapshot.
