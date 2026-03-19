# Updated Profile Deployment Report

## 1. Profile Distribution
- **MIN_LOT_FALLBACK_V1**: 11 directives
- **BOUNDED_MIN_LOT_V1**: 10 directives
- **FIXED_USD_V1**: 6 directives
- **DYNAMIC_V1**: 5 directives
- **MIN_LOT_FALLBACK_UNCAPPED_V1**: 1 directives

## 2. Migration Summary
- **To BOUNDED profiles:** 10
- **To FIXED/DYNAMIC profiles:** 1
- **Remained Unchanged:** 22

## 3. Aggregate Metrics (by profile)
### DYNAMIC_V1
- Avg Realized PnL: $3051.80
- Avg Max Drawdown: $335.27
- Avg MAR Ratio: 0.3934
- Avg Heat Utilization: 0.00%
### BOUNDED_MIN_LOT_V1
- Avg Realized PnL: $843.10
- Avg Max Drawdown: $1482.91
- Avg MAR Ratio: 0.4234
- Avg Heat Utilization: 42.93%
### FIXED_USD_V1
- Avg Realized PnL: $921.37
- Avg Max Drawdown: $121.65
- Avg MAR Ratio: inf
- Avg Heat Utilization: 10.70%
### MIN_LOT_FALLBACK_V1
- Avg Realized PnL: $23.94
- Avg Max Drawdown: $18.37
- Avg MAR Ratio: 0.0057
- Avg Heat Utilization: 0.00%
### MIN_LOT_FALLBACK_UNCAPPED_V1
- Avg Realized PnL: $5856.93
- Avg Max Drawdown: $2436.18
- Avg MAR Ratio: 0.9716
- Avg Heat Utilization: 125.87%

## 4. Risk Validation
- **Status:** Confirmed. NO selected profile has avg_risk_multiple > 1.5.

## 5. Failure Flags
- **07_MR_XAUUSD_15M_SMI_SMIFILT_S01_V1_P00**: Max DD Real > 12% (33.53%)
- **07_MR_XAUUSD_15M_SMI_SMIFILT_S01_V1_P01**: Max DD Real > 12% (33.53%)
- **07_MR_XAUUSD_15M_SMI_SMIFILT_S02_V1_P02**: Max DD Real > 12% (33.53%)
- **07_MR_XAUUSD_15M_SMI_SMIFILT_S02_V1_P03**: Max DD Real > 12% (33.53%)
- **07_MR_XAUUSD_15M_SMI_SMIFILT_S02_V1_P04**: Max DD Real > 12% (33.53%)
- **02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S05_V1_P00**: Max DD Real > 12% (20.21%)
- **02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P03**: Max DD Real > 12% (24.36%)
- **07_MR_XAUUSD_5M_SMI_SMIFILT_S03_V1_P00**: Max DD Real > 12% (41.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02**: Max DD Real > 12% (31.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S07_V1_P03**: Max DD Real > 12% (31.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00**: Max DD Real > 12% (31.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S09_V1_P00**: Max DD Real > 12% (31.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S10_V1_P00**: Max DD Real > 12% (31.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S11_V1_P00**: Max DD Real > 12% (31.53%)
- **01_MR_FX_1H_ULTC_REGFILT_S12_V1_P00**: Max DD Real > 12% (31.53%)