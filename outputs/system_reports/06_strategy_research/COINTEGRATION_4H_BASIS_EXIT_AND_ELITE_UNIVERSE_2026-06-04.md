# Cointegration Research — 4H Basis, Exit Variant, and the FX-FX Elite Universe

**Date:** 2026-06-04
**Scope:** COINTREV_V3 (`pine_ratio_zrev_v1`), granular_parity sizing, 15m execution.
**Status:** Decision-grade — pipeline-produced, run_id-stamped (AGENT.md Invariant #10). Mechanical-trading context; **not** investment-portfolio construction.

## Questions
1. Is a **4H** cointegration basis a better selector than **1D** for the 15m mean-reversion engine?
2. Does the **Z=0 (zcross)** exit help vs the baseline (reverse@±2)?
3. Is there a **look-ahead-safe orthogonal filter** (volatility, regime)?
4. Is there a **stable reduced ("elite") universe**?

## Findings

### 1. 4H basis is NOT a replacement for 1D
- Matched-cohort (GP / default-p / N=5 / baseline exit; maturity-matched ~1.6 runs/pair), FX-FX **pair-grain median Ret/DD: 4H +0.27 vs 1D +0.24 — a wash** (ΔM +0.034).
- The apparent 4H advantage is **concentrated**: of pairs where 4H+zcross beats 1D+zcross, **top-5 ≈ 60–81%** of the profit, **top-10 ≈ 81–98%**; two pairs (`CHFJPY/EURJPY`, `EURGBP/GBPNZD`) ≈ 40%. So it's ~5–10 thin pairs, not a broad basis edge.
- **Mechanism (real but not actionable):** the 4H regime persists longer on some pairs → captures the full MR arc (e.g. `EURGBP/GBPNZD`: 4H one 95-day window +90%, vs 1D fragmented into 3 short windows ~+27% total). But *which* pairs get long windows is **hindsight** — not selectable at entry.
- **Verdict: keep 1D as the basis; do not adopt 4H.** The 4H corpus is retained as a research artifact (`lookback_days=1500`).

### 2. Exit (Z=0 / zcross vs baseline) is a fixed, look-ahead-safe choice
- 2×2 (basis × exit), FX-FX pair-grain median Ret/DD: **best cell = 4H+zcross (+0.34)**; zcross unmasks the (small, concentrated) 4H edge (4H−1D = **+0.13** under zcross vs +0.03 under baseline).
- But long-window pairs prefer **baseline** (`EURGBP/GBPNZD` +90% baseline vs +53% zcross — riding to ±2 harvests more across a months-long regime).
- Both exits fire on the current z-score (look-ahead-safe). **The choice is fixed, not conditional** (window length = hindsight): **zcross = better median + reliability** (~63% positive); **baseline = fatter, unpredictable tail**. zcross-as-default adoption remains a pending operator decision.

### 3. No usable orthogonal filter
- **volatility_regime:** weak but consistent — low-vol slightly higher median_R than high-vol in *both* bases (4H 0.46 vs 0.38; 1D 0.69 vs 0.34) — but win% is flat and mean_R muddy. Marginal.
- **market_regime:** **NOT robust** — `RANGE` > `TREND` on 4H-zcross but **reverses** (`TREND` > `RANGE`) on 1D-baseline → cohort artifact. Do not use.
- **window length:** hindsight; not realizable as a filter.

### 4. A defensible FX-FX elite universe — the buildable finding
Pooling **all** runs per pair (every 1D + 4H cohort, deduped → *thick* evidence) reveals a stable quality tier. The per-cohort persistence scan looked like "rotation / no elite" only because per-cohort data is ~1.6 runs/pair (noisy ranks); pooled-thick data surfaces the tier.

**FX-FX elite — n ≥ 10 runs, median Ret/DD ≥ 0.75, robust across sizing / p-threshold / N / exit / basis variants:**

| Pair | runs | median Ret/DD | % positive |
|---|---|---|---|
| GBPAUD/NZDUSD | 17 | +2.23 | 94% |
| CHFJPY/EURJPY | 44 | +1.68 | 93% |
| AUDJPY/GBPNZD | 12 | +1.41 | 83% |
| GBPUSD/USDCHF | 25 | +1.39 | 84% |
| CADJPY/USDCHF | 23 | +1.21 | 87% |
| GBPJPY/NZDJPY | 16 | +1.03 | 100% |
| EURGBP/NZDJPY | 11 | +0.91 | 82% |
| EURJPY/GBPJPY | 22 | +0.90 | 91% |
| CHFJPY/NZDJPY | 27 | +0.89 | 85% |
| AUDJPY/CADJPY | 54 | +0.84 | 85% |
| EURAUD/GBPAUD | 13 | +0.77 | 92% |
| AUDNZD/USDCHF | 39 | +0.77 | 85% |
| CADJPY/GBPNZD | 10 | +0.76 | 100% |

Tier sizes at other bars (thick pairs): median Ret/DD ≥ 1.0 → 21 pairs (6 FX-FX); ≥ 0.5 → 63 pairs (20 FX-FX). The tier is dominated by the **USDCHF-hedge / JPY-cross / GBP-cross family** (shared legs → likely correlated; relevant only if ever traded jointly).

## Caveats
- Pooled median mixes configs — but high %positive + thick n means **robust-across-configs**, not single-config flukes.
- **1D-dominated** (most runs are 1D; 4H adds minor corroboration).
- CRY/MET pairs in the broader tier (e.g. `ETHUSD/GBPAUD`) are fat-tail-suspect — excluded; FX-FX is the clean deployable class.

## Methodology lessons
- Decide on the **deployable subset**, not the whole-universe run-level average (junk-diluted, run-weighted).
- **Pooled-thick > per-cohort-thin** for pair quality — per-cohort ranks (~1.6 runs/pair) are noise.
- **Cross-check generality** (1D vs 4H): it killed the `market_regime` filter (reversed) — single-cohort relations can be artifacts.
- `runs≥5` is a candidate-tab gate, **not** an A/B comparison gate; **match the cohort** (sizing/p/N/exit/basis) for basis A/Bs.
- **Look-ahead discipline:** window length is hindsight — not a filter.

## Provenance
Cohorts in `cointegration_sheet` (`TradeScan_State/ledger.db`): 1D `lookback_days=252` (GP / notional / P01–03 / N0 / zcross / zopp), 4H `lookback_days=1500` (GP baseline + GP zcross, generated 2026-06-04). Generator: `tools/generate_cointrev_v3_directives.py` (`lookback_days` propagation + `--exit-variant` flag + `_TF4H` basis tag, all added 2026-06-04). Infra follow-up filed: **COINT-NAMING-TF-TAG** (1D/4H name-disjoint by construction).
