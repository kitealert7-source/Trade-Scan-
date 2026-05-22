# H2 Regime Feature Probe — V2_P00 Window

Window: 2024-09-02 -> 2026-05-09
Daily observations: 445 (after shift(1) + window filter)

**Purpose:** decide whether the planned 4-way single-feature gate sweep is worth running.
Probe answers: are the 4 regime feature axes (compression, autocorr, stretch, vol) redundant or orthogonal?
If redundant -> sweep is wasteful; declare 'single-axis filtering is insufficient' and skip to composite gate or trend-exit design.
If orthogonal -> sweep is essential; each axis may carry distinct edge information.

## 1. Per-feature distribution stats

| Feature | mean | std | min | P25 | P50 | P75 | P95 | max |
|---|---|---|---|---|---|---|---|---|
| `compression_5d` | 14.238 | 86.025 | 1.000 | 1.445 | 2.324 | 5.086 | 26.273 | 1417.660 |
| `compression_20d` | 14.670 | 50.572 | 1.359 | 3.115 | 4.519 | 8.961 | 48.863 | 754.616 |
| `autocorr_5d` | -0.226 | 0.455 | -0.991 | -0.575 | -0.301 | 0.082 | 0.640 | 0.945 |
| `autocorr_20d` | -0.040 | 0.238 | -0.669 | -0.204 | -0.034 | 0.128 | 0.355 | 0.628 |
| `stretch_z20` | -0.008 | 0.980 | -3.551 | -0.612 | 0.025 | 0.663 | 1.402 | 3.172 |
| `vol_5d` | 0.058 | 0.029 | 0.009 | 0.039 | 0.051 | 0.071 | 0.109 | 0.201 |
| `vol_20d` | 0.062 | 0.019 | 0.032 | 0.052 | 0.059 | 0.069 | 0.093 | 0.128 |
| `abs_stretch_z20` | 0.766 | 0.610 | 0.000 | 0.325 | 0.626 | 1.065 | 1.939 | 3.551 |

## 2. Cross-correlation matrix

Pearson (linear) correlation across the 4 primary axes + 20d variants.

**Pearson:**

| | `compression_5d` | `compression_20d` | `autocorr_5d` | `autocorr_20d` | `abs_stretch_z20` | `vol_5d` | `vol_20d` |
|---|---|---|---|---|---|---|---|
| `compression_5d` | +1.00 | +0.05 | +0.01 | -0.03 | +0.05 | +0.07 | +0.07 |
| `compression_20d` | +0.05 | +1.00 | -0.02 | -0.01 | +0.01 | +0.01 | -0.02 |
| `autocorr_5d` | +0.01 | -0.02 | +1.00 | +0.31 | +0.11 | -0.03 | -0.08 |
| `autocorr_20d` | -0.03 | -0.01 | +0.31 | +1.00 | -0.01 | -0.23 | -0.18 |
| `abs_stretch_z20` | +0.05 | +0.01 | +0.11 | -0.01 | +1.00 | +0.29 | -0.03 |
| `vol_5d` | +0.07 | +0.01 | -0.03 | -0.23 | +0.29 | +1.00 | +0.60 |
| `vol_20d` | +0.07 | -0.02 | -0.08 | -0.18 | -0.03 | +0.60 | +1.00 |

**Spearman (rank-based, robust to non-linearity):**

| | `compression_5d` | `compression_20d` | `autocorr_5d` | `autocorr_20d` | `abs_stretch_z20` | `vol_5d` | `vol_20d` |
|---|---|---|---|---|---|---|---|
| `compression_5d` | +1.00 | +0.09 | +0.02 | -0.22 | +0.12 | +0.36 | +0.19 |
| `compression_20d` | +0.09 | +1.00 | -0.05 | -0.06 | +0.02 | +0.06 | +0.07 |
| `autocorr_5d` | +0.02 | -0.05 | +1.00 | +0.32 | +0.10 | -0.03 | -0.07 |
| `autocorr_20d` | -0.22 | -0.06 | +0.32 | +1.00 | -0.03 | -0.22 | -0.24 |
| `abs_stretch_z20` | +0.12 | +0.02 | +0.10 | -0.03 | +1.00 | +0.24 | -0.03 |
| `vol_5d` | +0.36 | +0.06 | -0.03 | -0.22 | +0.24 | +1.00 | +0.60 |
| `vol_20d` | +0.19 | +0.07 | -0.07 | -0.24 | -0.03 | +0.60 | +1.00 |

## 3. Calibrated thresholds — admit ~25% of days each

For fair single-axis comparison, each feature's threshold is chosen to admit ~25% of days.
This isolates 'given equal selectivity, what does each axis select?'.

| Feature | Polarity | Threshold | Actual admit % |
|---|---|---|---|
| `compression_5d` | `high` | 5.086 | 25.2% |
| `compression_20d` | `high` | 8.961 | 25.2% |
| `autocorr_5d` | `low` | -0.575 | 25.2% |
| `autocorr_20d` | `low` | -0.204 | 25.2% |
| `stretch_z20` | `near_zero` | 0.325 | 25.2% |
| `vol_5d` | `mid` | [0.046, 0.059] | 24.9% |
| `vol_20d` | `mid` | [0.056, 0.064] | 24.9% |

## 4. Pairwise joint-admit % — at calibrated thresholds

If two features are statistically independent and each admits 25% of days, joint admission is ~6%. 
If 100% correlated, joint admission stays at 25%. The diagonal shows each feature alone.

| | `compression_5d` | `compression_20d` | `autocorr_5d` | `autocorr_20d` | `stretch_z20` | `vol_20d` |
|---|---|---|---|---|---|---|
| `compression_5d` | 25.2% | 8.5% | 7.2% | 8.8% | 5.4% | 6.7% |
| `compression_20d` | 8.5% | 25.2% | 6.7% | 8.3% | 4.9% | 6.7% |
| `autocorr_5d` | 7.2% | 6.7% | 25.2% | 11.5% | 5.2% | 4.7% |
| `autocorr_20d` | 8.8% | 8.3% | 11.5% | 25.2% | 5.8% | 5.6% |
| `stretch_z20` | 5.4% | 4.9% | 5.2% | 5.8% | 25.2% | 6.3% |
| `vol_20d` | 6.7% | 6.7% | 4.7% | 5.6% | 6.3% | 24.9% |

## 5. Bar-class conditional distributions (V2_P00 diagnostic)

Per-bar telemetry from V2_P00 (Gate=10) re-simulation, joined to that day's daily features.
Median feature value per bar class — looks for which feature most discriminates 'recycle_fired'
(favorable) from 'dd_freeze' (stressed) bars.

| Class | n_bars | `compression_5d` | `compression_20d` | `autocorr_5d` | `autocorr_20d` | `stretch_z20` | `vol_5d` | `vol_20d` |
|---|---|---|---|---|---|---|---|---|
| all_bars | 81,153 | 2.610 | 4.928 | -0.334 | -0.090 | 0.026 | 0.054 | 0.061 |
| recycle_fired | 31 | 13.416 | 10.999 | -0.407 | -0.300 | -0.199 | 0.069 | 0.058 |
| dd_freeze | 38,723 | 3.092 | 4.859 | -0.283 | -0.102 | 0.026 | 0.066 | 0.066 |
| regime_freeze | 36,579 | 2.099 | 4.707 | -0.346 | -0.047 | 0.015 | 0.049 | 0.059 |
| healthy | 5,851 | 20.284 | 9.023 | -0.407 | -0.114 | 0.057 | 0.070 | 0.060 |

**How to read:** if `recycle_fired` row shows materially higher compression_5d and lower autocorr_5d than the `dd_freeze` row, those features discriminate favorable from stressed. If the rows are similar, the feature carries no signal for state.

## 6. Decision criteria for next step

Read the matrices above with these thresholds in mind:

- **|correlation| > 0.85 across all pairs**  -> features are redundant. Single-axis filtering is the bottleneck regardless of axis. Skip 4-way sweep; jump to composite gate or trend-exit mechanic.
- **|correlation| in 0.4-0.85**  -> partial overlap. Sweep is useful for identifying best single-axis, but composite gate is the likely winner.
- **|correlation| < 0.4**  -> features are largely orthogonal. Sweep is essential to find which axis carries the edge.

- **bar-class table shows clear feature separation between recycle_fired and dd_freeze**  -> that feature is the candidate for next experiment.
- **all features show similar medians across bar classes**  -> the strategy's bar-state is not driven by daily-resolution regime; something else (intraday dynamics, prior-cycle state) dominates.

---
*Auto-generated by `tmp/h2_regime_feature_probe.py`.*