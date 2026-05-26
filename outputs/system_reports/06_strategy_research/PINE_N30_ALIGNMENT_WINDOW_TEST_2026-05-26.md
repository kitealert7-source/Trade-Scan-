# Pine N=30 (Alignment-Window) Methodology Test — Falsification

**Date:** 2026-05-26
**Strategy:** `pine_ratio_zrev_v1` at N=30, 15m, entry_mode=absolute
**Cohort:** 18 pairs, each tested on its specific BOTH-window cointegrated alignment period from the screener's History tab (≥30 days continuous)
**Cohort excluded:** 4 pairs (BTCUSD/NZDJPY, UK100/XAUUSD, ESP35/XAUUSD, EUSTX50/XAUUSD) — H2RecycleRuleV3 currency-reference table doesn't define BTC or XAU; pre-execution rejection

## Headline

**Methodology falsified by absence of evidence.** 0 of 18 pairs produced a CORE or WATCH verdict. The thesis "the strategy has tradeable edge at N=30/15m/absolute on cointegrated periods" is not supported.

## Class-aggregated results

| Class | N | Mean Net% | Mean DD% | Mean Ret/DD | Median Ret/DD | % positive Ret/DD | % CORE/WATCH |
|---|---|---|---|---|---|---|---|
| **CROSS** (FX-IDX, IDX-CMD, FX-CMD) | 10 | **−115.3** | **140.3** | **−0.65** | −0.87 | **10%** | 0% |
| **IDX-IDX** | 4 | +16.3 | 22.3 | +0.89 | +0.82 | **75%** | 0% |
| **FX-FX** | 4 | +16.8 | 26.2 | +0.94 | +0.51 | **75%** | 0% |

## Per-pair results (sorted by Ret/DD)

| Pair | Class | Align days | Net % | DD % | Ret/DD | Trades | Verdict |
|---|---|---|---|---|---|---|---|
| EURGBP/GBPNZD | FX | 50 | +43.2 | 14.5 | **+2.98** | 140 | FAIL |
| EUSTX50/FRA40 | IDX | 75 | +36.9 | 16.0 | **+2.31** | 168 | FAIL |
| ESP35/UK100 | IDX | 45 | +19.2 | 23.1 | +0.83 | 40 | FAIL |
| ESP35/FRA40 | IDX | 81 | +19.4 | 23.8 | +0.81 | 78 | FAIL |
| GBPAUD/NZDJPY | FX | 36 | +23.2 | 31.7 | +0.73 | 94 | FAIL |
| GBPNZD/GER40 | CROSS | 44 | +14.1 | 37.0 | +0.38 | 84 | FAIL |
| AUDUSD/NZDJPY | FX | 30 | +8.4 | 29.2 | +0.29 | 76 | FAIL |
| EURGBP/NAS100 | CROSS | 35 | −4.4 | 52.5 | −0.08 | 86 | FAIL |
| EURGBP/EURUSD | FX | 40 | −7.8 | 29.6 | −0.26 | 102 | FAIL |
| ESP35/EUSTX50 | IDX | 46 | −10.3 | 26.2 | −0.39 | 44 | FAIL |
| CHFJPY/UK100 | CROSS | 89 | −49.8 | 92.6 | −0.54 | 230 | FAIL |
| CADJPY/FRA40 | CROSS | 30 | −85.6 | 109.8 | −0.78 | 70 | FAIL |
| EURUSD/FRA40 | CROSS | 76 | −118.4 | 136.5 | −0.87 | 178 | FAIL |
| CHFJPY/EUSTX50 | CROSS | 38 | −89.0 | 102.3 | −0.87 | 86 | FAIL |
| EURJPY/FRA40 | CROSS | 91 | −233.5 | 253.0 | −0.92 | 208 | FAIL |
| AUDNZD/FRA40 | CROSS | 64 | −139.8 | 148.5 | −0.94 | 138 | FAIL |
| EURGBP/FRA40 | CROSS | 82 | −170.2 | 180.5 | −0.94 | 188 | FAIL |
| CHFJPY/FRA40 | CROSS | 91 | −276.5 | 289.7 | −0.95 | 212 | FAIL |

## Structural insights (the test DID prove these, even if it falsified the headline)

### 1. CROSS class is structurally hostile at this parameter regime
9 of 10 CROSS pairs (FX-vs-index or commodity) are catastrophic FAILs with mean DD 140% and 90% having negative Ret/DD. Hypothesis: synthesized 24-hour CFD index bars at OctaFX retain session-open jumps that the rolling-spread treats as signal but aren't real microstructure mean-reversion events. The single near-flat exception (GBPNZD/GER40, +0.38) doesn't break the pattern.

### 2. FX-FX and IDX-IDX both show marginal positive signal but neither clears governance
75% of pairs in each class have positive Ret/DD. Median Ret/DD is +0.51 to +0.82. Best individual pairs reach Ret/DD 2.31–2.98. **But absolute returns (typical +20% to +40%) are too low for CORE/WATCH governance bars.** Cost burden of always-in-market 2σ-reversal eats most of the edge.

### 3. Prior "winners" don't survive the methodologically-clean window
Comparison vs the earlier 2024-2026 run (pre-alignment-window methodology):

| Pair | Prior 2024-2026 (unfiltered) | Alignment-window 2026 | Direction |
|---|---|---|---|
| CHFJPY/UK100 | Net **+129** / DD 54 / FAIL | Net **−50** / DD 93 / FAIL | **Flipped negative** |
| AUDUSD/NZDJPY | Net **+153** / DD 42 / **WATCH** | Net **+8** / DD 29 / FAIL | Lost WATCH grade |
| CHFJPY/FRA40 | Net −436 / DD 248 / FAIL | Net −277 / DD 290 / FAIL | Same direction |
| EURJPY/FRA40 | Net −481 / DD 280 / FAIL | Net −234 / DD 253 / FAIL | Same direction |

The TradingView-favored CHFJPY/UK100 produced its prior "+129%" entirely from the pre-cointegration trending period. **On the actual cointegrated window, the result is negative.** The AUDUSD/NZDJPY WATCH was similarly artifact-driven — collapses to FAIL on the clean window.

### 4. The pair-selection criterion (daily cointegration) is uncorrelated with strategy edge
EURGBP/GBPNZD and EUSTX50/FRA40 produced the best Ret/DD in the cohort (2.98, 2.31). EURGBP/GBPNZD wasn't even in our top stable list — it qualified at only 50 days continuous alignment. The "stronger" alignment pairs (CHFJPY/FRA40 91d, EURJPY/FRA40 91d) had the worst results.

## Decision

Per the operator-locked methodology (prove-by-broad-cohort; falsify-by-absence):

- **0 / 18 pairs CORE or WATCH** → strategy at this parameter regime has no demonstrable edge
- **No structural class produces consistent positive verdicts** → operating regime not found
- **Headline thesis falsified.** The pine_ratio_zrev_v1 at N=30/15m/absolute does NOT survive the methodologically-clean test.

## What remains as possible next moves (not blocked, just demoted)

If the operator wants to continue exploring this strategy class:

1. **Try Centered entry_mode.** The CROSS-class catastrophe pattern is consistent with structural z_r drift on indices. Centered mode subtracts the rolling mean of z_r, which would absorb session-gap drift. Would re-test if drift is the failure mode.
2. **Raise z_entry threshold.** The current z=2.0 fires ~2.76 trades/day. Higher z (e.g., 3.0) reduces trade frequency by maybe half — could let modest FX-FX/IDX-IDX edge break through governance.
3. **Restrict cohort to FX-FX + IDX-IDX surfaces.** 75% positive Ret/DD on these classes suggests something real. But marginal — would need a parameter change to clear governance.
4. **Accept falsification.** The strategy as-is doesn't work. Move on to other research arcs.

My read: **(4) is the right call given current evidence.** Options (1)–(3) are speculative perturbations; the headline thesis (this strategy at this param regime) is clean falsified. If a future operator wants to revisit, the data is preserved.

## Operational notes

- BTC and XAU currency tokens are unsupported by `H2RecycleRuleV3` currency-reference table. Pairs containing them trigger fail-fast at basket setup. The error message mentions H2RecycleRuleV3 even when the actual strategy is `pine_ratio_zrev_v1` — basket setup code path runs the currency-reference check regardless of recycle rule. **Worth a separate tech-debt fix later** (extend the reference table to include BTC/ETH/XAU, or move the check to the rule that actually uses it).
- MPS xlsx export failed twice during this session (Permission denied — file was open). Ledger DB has the canonical data; `python tools/ledger_db.py --export-mps` re-syncs once the file is closed.

## Provenance

- Pipeline runs: 18 directives across 3 sub-batches (batches 1+2 partially halted by fail-fast on BTC/XAU currency rejections; batch 3 completed all 9 cleanly).
- Run IDs in `analyze_alignment_window_results.py` for traceability.
- Ledger DB query: `SELECT FROM basket_sheet WHERE directive_id LIKE '%15M_COINTREV_V3_L30%'`.
- Alignment windows sourced from screener's History tab via `tmp/generate_pine_alignment_directives.py`.
