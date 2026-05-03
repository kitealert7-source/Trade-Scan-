# Phase 2 Path A — Generality Test (ZREV + PORT)

**Date:** 2026-05-03
**Method:** Side-channel — direct call to engine v1.5.8a `run_execution_loop` against historical bars + the base strategy's own logic, with news-window gating monkey-patched onto `prepare_indicators` and `check_entry`. No file mutation, no directives, no admission.
**Period:** 2024-01-02 → 2026-03-20
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`

PORT vs MACDX duplication verified: trade-level CSVs and trade lists are byte-identical at the `pnl_usd` / `entry_timestamp` / `exit_price` level. Tested PORT only.

---

## Result table

| Candidate | Variant | N | PF | trim_PF | expectancy | 95% PF CI | Verdict |
|---|---|--:|--:|--:|--:|---|---|
| RSIAVG FX 15M EURUSD | Baseline | 1322 | 1.43 | 1.05 | $0.153 | [1.24,1.68] | — |
| RSIAVG FX 15M EURUSD | **Full-window** | 69 | **0.76** | **0.56** | -$0.000 | [0.41,1.52] | **FAIL** |
| RSIAVG FX 15M EURUSD | Pre-only | 37 | 1.14 | 0.81 | +$0.000 | [0.50,3.04] | FAIL |
| ZREV XAU 15M | Baseline | 1373 | 1.22 | 0.78 | +$1.38 | [1.03,1.45] | — |
| ZREV XAU 15M | **Full-window** | 126 | 1.63 | **0.83** | +$3.72 | [0.87,2.97] | **FAIL (trim)** |
| ZREV XAU 15M | Pre-only | 91 | 1.39 | 0.97 | +$2.16 | [0.78,2.58] | FAIL |
| PORT XAU 5M | Baseline | 1339 | 1.32 | 0.71 | +$1.35 | [1.12,1.57] | — |
| **PORT XAU 5M** | **Full-window** | **55** | **3.21** | **1.66** | **+$6.41** | **[1.37,6.82]** | **PASS** |
| PORT XAU 5M | Pre-only | 12 | 10.48 | 4.54 | +$14.41 | [1.56,52.70] | FAIL (N) |

---

## Verdicts

- **RSIAVG FX 15M EURUSD: KILL** (already documented)
- **ZREV XAU 15M: KILL.** Full-window trim_PF=0.83, Pre-only trim_PF=0.97. Same selection-bias pattern as RSIAVG: post-hoc lift collapses under isolation. Different archetype, market, and holding behavior — but same disease.
- **PORT XAU 5M: SURVIVES.** Full-window PASSES all four exploratory gates. N=55, PF 3.21 vs baseline 1.32 (2.43× lift), trim 1.66, expectancy +$6.41/trade, bootstrap 95% CI [1.37, 6.82] excludes 1.0. **First confirmed news-isolation candidate in the project.**

The discovery's NEWS_AMPLIFIED bucket is not a universally-misleading category — but most of it likely is. **2 of 3 cleanest candidates collapsed under isolation.**

---

## Why PORT XAU 5M survives where RSIAVG and ZREV don't

Hypothesis (not yet validated): PORT's flat-state interaction with news bars is much weaker than RSIAVG's or ZREV's. RSIAVG max_bars=12 (3h hold) and ZREV's mean-reversion typical holds overlap many news windows; their unrestricted-version positions are *frequently* held during news fires, biasing the post-hoc news subset. PORT XAU 5M's hold profile or position-management pattern apparently leaves the strategy flat at news moments more often, so post-hoc news subset ≈ restricted-trading set.

Confirmation would require comparing flat-share-at-news between the three strategies. Not run here — open for follow-up.

PORT/MACDX shared-trade-list (confirmed duplication) means there are two model tokens for the same underlying signal. Either the discovery double-counted, or one is a copy/alias. Worth resolving before any further work on this candidate.

---

## What this changes about the discovery report

The NEWS_AMPLIFIED bucket is **not** a universally-misleading category, but a **mixed** category:

- A subset (~⅓ of the cleanest candidates so far) survives Path A isolation and represents a real, exploitable news-window edge.
- The majority (~⅔) collapse — their apparent lift is selection bias.

Phase-2 Path A side-channel is the only way to tell which is which. Each candidate takes ~2 minutes of compute. The full NEWS_AMPLIFIED bucket (9 candidates) could be re-validated in ~20 minutes if you want a complete picture.

EVENT_CONCENTRATED is still suspect because tail-carriedness is the diagnosis BEFORE selection bias. Path A on these would mostly confirm what the discovery already flagged.

---

## What survives the chain of doubt for PORT XAU 5M

1. ✅ Discovery flagged it as NEWS_AMPLIFIED (1333 N, 43 news trades, 1.47× ratio in original CSV)
2. ✅ Path A side-channel preserves the lift under causal isolation (55 N, 2.43× ratio, trim 1.66)
3. ✅ Bootstrap 95% CI excludes 1.0 (statistically distinguishable from random)
4. ✅ Expectancy +$6.41/trade is materially above baseline +$1.35

Still **does not** clear:
- Phase 3 execution-realism stress (spread doubling at news, slippage)
- PORT/MACDX duplication root-cause investigation
- Out-of-sample / forward holdout
- Independence verification (cross-correlation with the same strategy's burn-in BURN_IN brethren)

The candidate is **promote-eligible to Phase 3**, not promote-eligible to live deployment.

---

## Decision logic resolution per your rule

> *"If both also collapse: KILL the entire NEWS_AMPLIFIED exploitation thesis. And then: Move fully to NEWS_SUPPRESSED overlays."*

Both did NOT collapse. **One survived (PORT).** Two paths forward:

### Path 1 — Continue NEWS_AMPLIFIED validation (selectively)

Run Path A against the remaining 6 NEWS_AMPLIFIED candidates not yet tested:
- 22 RSIAVG FX 30M GBPJPY (low news sample N=5; will likely INSUFFICIENT)
- 7 SMI XAU 15M XAUUSD (low N=13)
- 60 SYMSEQ BTC 1H BTCUSD (N=16)
- 34 FAKEBREAK FX 30M USDJPY (N=23)
- 36 IMPULSE BTC 15M ETHUSD (N=16)
- 55 ZREV XAU 15M XAUUSD ✅ **already tested → KILL**

Most have low news samples in the original; even if isolated they may not clear N≥40.

### Path 2 — Move forward on PORT XAU 5M alone + NEWS_SUPPRESSED in parallel

- **PORT XAU 5M:** Resolve PORT/MACDX duplication. Run Phase-3 stressed execution. If Phase-3 holds, PORT becomes the first confirmed news-active candidate.
- **NEWS_SUPPRESSED bucket:** Begin operational filter overlay for PINBAR XAU 1H (in BURN_IN, large sample, clean news-suppression signal). This is the higher-confidence operational lift independent of the NEWS_AMPLIFIED thesis.

### Path 3 — Pure NEWS_SUPPRESSED pivot

Stop NEWS_AMPLIFIED hunting entirely. PORT might be a real edge, but the bucket's hit rate (1/3 = 33%) is too low to justify systematic re-validation; the survivors are anomalies, not a thesis. Focus operational work on the cleaner NEWS_SUPPRESSED overlays.

---

## My recommendation

**Path 2.** Two parallel tracks:

1. **PORT XAU 5M Phase-3 stressed-execution test** — small scoped follow-up. Either PORT survives (first real news-active candidate, justifies more validation work) or fails (KILL, revert to Path 3).
2. **PINBAR XAU 1H news-block overlay design** — independent of the NEWS_AMPLIFIED outcome, this is operational Sharpe lift on an existing BURN_IN strategy.

The two tracks don't compete. PORT either confirms or kills the NEWS_AMPLIFIED thesis cleanly; the suppression overlay starts paying dividends regardless.

---

## Caveats (same as prior Path A report)

- PnL proxy = `(exit - entry) × direction`, not OctaFx capital-wrapped pnl_usd. PF/trim/expectancy ratios sound; absolute $ figures not directly comparable to the original backtest's pnl_usd.
- No spread/slippage stress applied. Path A is the optimistic case. Real-news execution typically erodes 30-60% of theoretical edge.
- HTF regime fields computed on 5M/15M data directly rather than merged from a higher TF. Pattern of trade selection may differ marginally from production pipeline output.
- PORT/MACDX duplication unresolved — strategies produce identical trade lists despite different code. Worth investigating.

---

## Artifacts

- Side-channel script: `tmp/news_isolation_sidechannel.py`
- Discovery report: [outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md](outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md)
- Path B (RSIAVG): [outputs/PHASE2_PATHB_RSIAVG_EURUSD_2026_05_03.md](outputs/PHASE2_PATHB_RSIAVG_EURUSD_2026_05_03.md)
- Path A (RSIAVG): [outputs/PHASE2_PATHA_RSIAVG_EURUSD_2026_05_03.md](outputs/PHASE2_PATHA_RSIAVG_EURUSD_2026_05_03.md)
- This report: [outputs/PHASE2_PATHA_GENERALITY_TEST_2026_05_03.md](outputs/PHASE2_PATHA_GENERALITY_TEST_2026_05_03.md)
- Anchor: `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
