# Indicator Capabilities Reference

> **Registry Version:** 3 | **Generated:** 2026-03-09 | **Total Indicators:** 33
>
> Machine-readable source: [`INDICATOR_REGISTRY.yaml`](./INDICATOR_REGISTRY.yaml)

---

## Summary

| Category | Count | Indicators |
|---|---|---|
| **Momentum** | 5 | rsi, roc, stochastic_k, ultimate_c_percent, stochastic_momentum_index |
| **Trend** | 4 | adx, ema_slope, hull_moving_average, linear_regression_channel |
| **Volatility** | 5 | atr, atr_percentile, bollinger_band_width, keltner_channel, volatility_regime |
| **Regime** | 7 | efficiency_ratio_regime, ema_regime, kalman_regime, linreg_regime, linreg_regime_htf, sha_regime, trend_persistence |
| **Structure** | 6 | daily_pivot_points, donchian_channel, highest_high, lowest_low, session_range_structure, previous_bar_breakout |
| **Price** | 3 | candle_state, previous_bar_breakout, usd_stress_index |
| **Composite** | 2 | usd_stress_index, market_state |
| **Statistical** | 3 | rolling_max, rolling_percentile, rolling_zscore |

---

## Full Capabilities Table

| Indicator | Module Path | Function | Output Type | Output Columns | Lookahead Safe | Vectorized | HTF Compatible | Daily | Intraday | Cost | Overfit Risk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **candle_state** | `indicators.price.candle_state` | `apply` | DataFrame | is_green, is_red, green_streak, red_streak | ✅ | ⚠️ loop | ✅ | ✅ | ✅ | Low | Low |
| **previous_bar_breakout** | `indicators.price.previous_bar_breakout` | `apply` | DataFrame | prev_high, prev_low, breakout_up_close, breakout_down_close | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **usd_stress_index** | `indicators.price.usd_stress_index` | `apply` | DataFrame | usd_stress, usd_stress_percentile | ✅ | ✅ | ⚠️ | ✅ | ✅ | Medium | Low |
| **roc** | `indicators.momentum.roc` | `roc` | Series | roc (%) | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **rsi** | `indicators.momentum.rsi` | `rsi` | Series | rsi (0–100) | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Medium |
| **stochastic_k** | `indicators.momentum.stochastic` | `stochastic_k` | Series | stochastic_k (0–100) | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Medium |
| **stochastic_momentum_index** | `indicators.momentum.stochastic_momentum_index` | `stochastic_momentum_index` | DataFrame | smi, smi_signal, smi_hist | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Medium |
| **ultimate_c_percent** | `indicators.momentum.ultimate_c_percent` | `ultimate_c_percent` | DataFrame | ultimate_c, ultimate_signal | ✅ | ✅ | ✅ | ✅ | ✅ | Medium | Medium |
| **rolling_max** | `indicators.stats.rolling_max` | `rolling_max` | Series | rolling_max | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **rolling_percentile** | `indicators.stats.rolling_percentile` | `rolling_percentile` | Series | percentile (0–100) | ✅ | ✅ | ✅ | ✅ | ✅ | Medium | Low |
| **rolling_zscore** | `indicators.stats.rolling_zscore` | `rolling_zscore` | Series | zscore | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **adx** | `indicators.structure.adx` | `adx` | Series | adx (0–100) | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **daily_pivot_points** | `indicators.structure.daily_pivot_points` | `daily_pivot_points` | DataFrame | pivot, r1, s1, r2, s2 | ✅ | ✅ | ⚠️ | ✅ | ✅ | Low | Low |
| **donchian_channel** | `indicators.structure.donchian_channel` | `donchian_channel` | Tuple | dc_mid, dc_width | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **ema_slope** | `indicators.structure.ema_slope` | `ema_slope` | Series | ema_slope | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **highest_high** | `indicators.structure.highest_high` | `highest_high` | Series | highest_high | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **hull_moving_average** | `indicators.structure.hull_moving_average` | `hull_moving_average` | Series | hma | ✅ | ⚠️ loop | ✅ | ✅ | ✅ | Medium | Low |
| **linear_regression_channel** | `indicators.structure.linear_regression_channel` | `linear_regression_channel` | Tuple | lr_mid, lr_upper, lr_lower | ✅ | ✅ | ✅ | ✅ | ✅ | Medium | Medium |
| **lowest_low** | `indicators.structure.lowest_low` | `lowest_low` | Series | lowest_low | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **session_range_structure** | `indicators.structure.range_breakout_session` | `session_range_structure` | DataFrame | session_high, session_low, range_points, range_percent, break_direction, has_broken | ✅ | ✅ | ❌ | ❌ | ✅ | Medium | Low |
| **efficiency_ratio_regime** | `indicators.trend.efficiency_ratio_regime` | `efficiency_ratio_regime` | DataFrame | er, regime | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **ema_regime** | `indicators.trend.ema_regime` | `ema_regime` | DataFrame | trend, regime | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **kalman_regime** | `indicators.trend.kalman_regime` | `kalman_regime` | DataFrame | trend, regime | ✅ | ⚠️ loop | ✅ | ✅ | ✅ | Medium | Low |
| **linreg_regime** | `indicators.trend.linreg_regime` | `linreg_regime` | DataFrame | trend, slope, regime | ✅ | ✅ | ✅ | ✅ | ✅ | Medium | Low |
| **linreg_regime_htf** | `indicators.trend.linreg_regime_htf` | `linreg_regime_htf` | DataFrame | trend, slope, regime | ✅ | ✅ | ✅ | ❌ | ✅ | Medium | Low |
| **sha_regime** | `indicators.trend.sha_regime` | `sha_regime` | DataFrame | trend, regime | ✅ | ⚠️ loop | ✅ | ✅ | ✅ | Medium | Low |
| **trend_persistence** | `indicators.trend.trend_persistence` | `trend_persistence` | DataFrame | persistence, regime | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **atr** | `indicators.volatility.atr` | `atr` | Series | atr | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **atr_percentile** | `indicators.volatility.atr_percentile` | `atr_percentile` | Series | atr_percentile (0–1) | ✅ | ✅ | ✅ | ✅ | ✅ | Medium | Low |
| **bollinger_band_width** | `indicators.volatility.bollinger_band_width` | `bollinger_band_width` | Series | bb_width | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **keltner_channel** | `indicators.volatility.keltner_channel` | `keltner_channel` | Tuple | kc_mid, kc_upper, kc_lower | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Low |
| **market_state** | `indicators.volatility.market_state` | `market_state` | DataFrame | state (0–4) | ✅ | ✅ | ✅ | ✅ | ✅ | Low | Medium |
| **volatility_regime** | `indicators.volatility.volatility_regime` | `volatility_regime` | DataFrame | atr, percentile, regime | ✅ | ✅ | ✅ | ✅ | ✅ | Medium | Low |

---

## Important Notes & Gotchas

| Issue | Indicators Affected |
|---|---|
| **Capital column names** (Open/High/Low/Close) | `kalman_regime`, `sha_regime` — incompatible with engine default lowercase |
| **Python loop (not vectorized)** | `candle_state`, `kalman_regime`, `sha_regime`, `hull_moving_average` — slower on large datasets |
| **Requires DatetimeIndex** | `linreg_regime_htf`, `session_range_structure` |
| **Intraday only** | `session_range_structure` — meaningless on daily bars |
| **External file dependency** | `usd_stress_index` — requires `data_root/SYSTEM_FACTORS/USD_SYNTH/usd_synth_return_d1.csv` |
| **Output scale: 0–1 (not 0–100)** | `atr_percentile` — multiply by 100 for percentage comparison |
| **Output scale: 0–100** | `rolling_percentile`, `rsi`, `stochastic_k`, `ultimate_c_percent`, `adx` |
| **Output scale: –100 to +100** | `stochastic_momentum_index` — smi, smi_signal, smi_hist all on this scale |
| **Composite dependencies** | `market_state` requires `trend_slope` + `volatility_percentile` as pre-computed inputs |
| **Regime encoding** | `volatility_regime`: -1=low, 0=medium, 1=high. Engine maps to "low"/"normal"/"high" strings. |
| **Taxonomy change (v3)** | `roc`, `rsi`, `stochastic`, `ultimate_c_percent` moved from `indicators/price/` to `indicators/momentum/` |

---

## Regime Output Reference

| Indicator | regime=1 | regime=0 | regime=-1 |
|---|---|---|---|
| `ema_regime` | EMA rising | first bar | EMA falling |
| `kalman_regime` | trend rising | first bar | trend falling |
| `linreg_regime` | positive slope | warmup | negative slope |
| `linreg_regime_htf` | uptrend | warmup | downtrend |
| `sha_regime` | HA trend rising | first bar | HA trend falling |
| `trend_persistence` | persistent up | mixed | persistent down |
| `efficiency_ratio_regime` | trending | — | ranging/choppy |
| `volatility_regime` | high vol | medium vol | low vol |
| `market_state` | trending up | undefined/NaN | — (uses 2=down, 3=range-low, 4=range-high) |

---

*Validation: All 33 `.py` files in `indicators/` (excluding `__init__.py` and `__pycache__`) are represented. Registry v3. Status: **PASS**.*
