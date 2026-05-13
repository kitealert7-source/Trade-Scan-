# USD_SYNTH - SYSTEM_FACTOR

## Status
**Governance**: Anti_Gravity_DATA_ROOT
**Type**: SYSTEM_FACTOR
**Version**: USD_SYNTH_D1_v2.0 (2026-05-13: added USDCHF + regime feature outputs)
**Build Frequency**: Daily
**Dependency**: RAW → CLEAN → RESEARCH → VALIDATION PASS

## Location
Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/USD_SYNTH/

## Files

### Core (existing since v1)
- `usd_synth_close_d1.csv` - Synthetic USD index (close prices, base 100.0)
- `usd_synth_return_d1.csv` - Synthetic USD index (daily log returns)
- `metadata.json` - Factor metadata, version, source hashes, validation stats

### Regime feature outputs (v2.0)
Universal market-state dimensions, computed from `usd_synth_return_d1.csv` via
`engines/core/regime_features.py`. Available to any consumer (strategies,
indicators, research scripts).

| File | Columns | Interpretation |
|---|---|---|
| `usd_synth_volatility_d1.csv` | `vol_5d`, `vol_20d`, `vol_60d` | Annualized rolling realized volatility. Higher = more turbulent regime. |
| `usd_synth_persistence_d1.csv` | `autocorr_5d`, `autocorr_20d`, `autocorr_60d` | Rolling lag-1 autocorrelation of returns. >0 = trending, <0 = mean-reverting, 0 = random walk. |
| `usd_synth_compression_d1.csv` | `compression_5d`, `compression_20d` | Path-length / net-displacement ratio. =1 = clean trend; >5 = significant chop; very high = pure range. |
| `usd_synth_stretch_d1.csv` | `stretch_z20`, `stretch_z60` | Rolling Z-score of returns. \|Z\| > 2 = extreme move vs recent distribution. |

## Access Control
- **Write**: DATA_INGRESS only (`engines/ops/build_usd_synth.py`)
- **Read**: any consumer (read-only)

## Lookahead safety

All regime features computed via rolling **trailing** windows. The published
files are **not** pre-shifted. Consumers should apply `.shift(1)` when reading
features for same-day decisions, to use the previous completed day's value.
This matches the convention in `Trade_Scan/indicators/macro/usd_synth_zscore.py`
and `Trade_Scan/tools/research/regime_gate.py`.

## Calculation (v2.0)

- **Basket**: EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD, **USDCHF** (v2.0 addition)
- **Direction**: Invert EUR/GBP/AUD, Keep JPY/CAD/CHF
- **Aggregation**: Equal-weight mean of log returns
- **Return Type**: Log returns
- **Base Value**: 100.0
- **Calendar Rule**: intersection_only (drops dates where any pair didn't trade; <5% drop gate)
- **Validation Gates**: NaN check, vol-reduction (synth vol < median component vol), max-return sanity, no-component-correlation > 0.98

## Daily Update Rule

USD_SYNTH will only update if base data pipeline completes successfully:
1. RAW incremental update (PASS)
2. Validation (PASS)
3. CLEAN rebuild (PASS)
4. RESEARCH rebuild (PASS)

If any stage fails, USD_SYNTH update is skipped.

## Use cases (any strategy may consume)

The factor is intentionally generic. Different consumers use different feature
combinations. Examples:

| Strategy class | Useful features | Typical interpretation |
|---|---|---|
| Mean-reversion fade | `stretch_z20`, `stretch_z60` | Fade when \|Z\| > 2 |
| Trend-following | `autocorr_20d`, `compression_5d` | Enter when autocorr > 0.3 AND compression < 3 |
| Vol-targeting | `vol_5d`, `vol_20d` | Scale position size inversely |
| Recycle basket gate | `compression_5d` | Block recycle when < threshold (sustained-trend regime) |
| Macro direction filter | `usd_synth_close_d1`, `stretch_z20` | Long-only USD-pairs above MA + Z extreme |

## Migration History

- **2026-01-11**: Migrated from AG/DERIVED/FACTORS/USD_SYNTH to DATA_ROOT/SYSTEM_FACTORS/USD_SYNTH; promoted to first-class SYSTEM_FACTOR under DATA_ROOT governance.
- **2026-05-13** (**v2.0**): Added USDCHF to basket (5→6 pairs); added 4 regime feature output CSVs (volatility, persistence, compression, stretch). Backwards-compatible for `usd_synth_close_d1.csv` and `usd_synth_return_d1.csv` consumers (values change slightly due to USDCHF addition; existing consumer `indicators/macro/usd_synth_zscore.py` re-validated and unaffected in directional behavior).
