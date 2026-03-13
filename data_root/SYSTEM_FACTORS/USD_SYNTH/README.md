# USD_SYNTH - SYSTEM_FACTOR

## Status
**Governance**: Anti_Gravity_DATA_ROOT  
**Type**: SYSTEM_FACTOR  
**Build Frequency**: Daily  
**Dependency**: RAW → CLEAN → RESEARCH → VALIDATION PASS

## Location
Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/USD_SYNTH/

## Files
- usd_synth_close_d1.csv - Synthetic USD index (close prices)
- usd_synth_return_d1.csv - Synthetic USD index (log returns)
- metadata.json - Factor metadata and governance

## Access Control
- **Write**: DATA_INGRESS only
- **Read**: AG (read-only)

## Migration History
- **2026-01-11**: Migrated from AG/DERIVED/FACTORS/USD_SYNTH to DATA_ROOT/SYSTEM_FACTORS/USD_SYNTH
- **Reason**: Promote to first-class SYSTEM_FACTOR under DATA_ROOT governance
- **Data Integrity**: Preserved (531 rows, 2024-01-03 to 2026-01-08)

## Daily Update Rule
USD_SYNTH will only update if base data pipeline completes successfully:
1. RAW incremental update (PASS)
2. Validation (PASS)
3. CLEAN rebuild (PASS)
4. RESEARCH rebuild (PASS)

If any stage fails, USD_SYNTH update is skipped.

## Calculation (Unchanged)
- **Basket**: EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD
- **Direction**: Invert EUR/GBP/AUD, Keep JPY/CAD
- **Aggregation**: Equal-weight mean
- **Return Type**: Log returns
- **Base Value**: 100.0
