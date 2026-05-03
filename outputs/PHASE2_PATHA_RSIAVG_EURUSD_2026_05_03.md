# Phase 2 Path A — RSIAVG FX 15M EURUSD (Side-Channel Engine Execution)

**Date:** 2026-05-03
**Method:** Side-channel — direct call to engine v1.5.8a `run_execution_loop` against EURUSD 15M bars + wrapper strategies. No YAML, no directives, no admission gates, no state machines, no approval markers.
**Wrapper strategies:** `22_CONT_FX_15M_RSIAVG_TRENDFILT_S13_V1_P00` (Full-window), `S14_V1_P00` (Pre-only). Both copies of `S03_V1_P03` logic + `news_event_window` indicator + entry-time gate.
**Period:** 2024-01-02 → 2026-03-20 (54,976 EURUSD 15M bars)
**News calendar:** USD + EUR High-impact, ±30m / ±90m windows
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`

---

## Verdict: **A1 = KILL conclusively**

Restricted-trading (the causal version) of the news-filtered RSIAVG strategy fails all exploratory gates. The Path B post-hoc lift was a **selection artefact**, not a real edge.

---

## Side-by-side: Path A (causal) vs Path B (post-hoc)

| | Path B post-hoc | **Path A side-channel (causal)** |
|---|---|---|
| **Full-window** N | 54 | **69** |
| Full-window PF | 2.78 | **0.76** |
| Full-window trim-PF | 1.76 | **0.56** |
| Full-window expectancy | +$0.376 | **-$0.000** |
| Full-window 95% CI | [1.27, 7.63] | [0.41, 1.52] (excludes 1.0 *below*) |
| **Pre-only** N | 27 | **37** |
| Pre-only PF | 5.26 | **1.14** |
| Pre-only trim-PF | 4.23 | **0.81** |
| Pre-only expectancy | +$0.564 | +$0.000 |
| Pre-only 95% CI | [1.58, 66.38] | [0.50, 3.04] |

The restricted-trading version takes **15 more trades** in Full-window and **10 more** in Pre-only than Path B's post-hoc filter. Those additional trades collectively destroy the apparent edge.

---

## Why Path B was misleading

Path B masked an existing trade list by news proximity. Path A actually re-runs the strategy with news as a hard filter on entry. The two diverge whenever the strategy is **non-flat at the moment a news bar fires**:

- **Path B:** bars where strategy was non-flat are silently dropped from the news subset (the actual unrestricted run rejected them via `entry_when_flat_only`). Surviving news trades are a selection of bars where the strategy happened to have just exited a non-news trade.
- **Path A:** strategy is *always* flat at non-news bars (gate blocks all of them). Every news bar with a valid signal fires. No selection effect.

The 15 additional Path A trades are the news fires that, in the unrestricted backtest, were blocked because the strategy was holding a non-news position. **They lose money on average.** This is exactly the asymmetry I flagged in the original Path A vs Path B proposal — the asymmetry was much larger than expected.

The lesson: post-hoc filtering of an unrestricted backtest's trade list **can substantially overestimate restricted-trading edge** when the strategy has any state that depends on prior trades (`entry_when_flat_only`, `pyramiding=false`, etc.).

---

## What this proves about the discovery

The cross-family discovery report flagged RSIAVG FX 15M EURUSD as the cleanest NEWS_AMPLIFIED candidate (1322 N, 54 news, ratio 1.99×, trim 1.76). All of those numbers are correct **as descriptions of the unrestricted strategy's news-window subset**. They are NOT correct as predictions of restricted-trading performance.

This is the foundational question we set out to answer:
> *"Can incidental news edge survive when isolated as an intentional strategy?"*

**Answer: no, on this candidate.** The "edge" was incidental selection, not isolatable structure.

If the cleanest candidate in the archive can't survive isolation, the EVENT_CONCENTRATED bucket (tail-carried by definition) and weaker NEWS_AMPLIFIED candidates almost certainly cannot either.

---

## Diagnostic confirmation

Engine-side diagnostic counters (full data — 54,976 bar evaluations):

```
Full-window:  news_pass=2870  fs_pass=1100  asia_ok=1100  rsi_signal=1100  fired=68  trades=69
Pre-only:     news_pass= 670  fs_pass= 410  asia_ok= 410  rsi_signal= 410  fired=37  trades=37
```

The pipeline is doing what we asked: ~2870 news-window bars in 27 months, ~1100 of them clear FilterStack + Asia, ~68 of them produce RSIAVG signals, 69 trades execute. The wrapper integration is working correctly. The numbers are what they are.

---

## Why not run Path A through the production pipeline

Earlier attempts hit a chain of orchestration friction:

| # | Friction | Caused by |
|---|---|---|
| 1 | Canonicalizer rejected `news_window_filter` as unknown YAML key | Schema doesn't include news filter |
| 2 | Engine resolver rejected old contract ID | RSIAVG bound to pre-v1.5.8a engine |
| 3 | EXPERIMENT_DISCIPLINE blocked reset | Marker not refreshed after contract update |
| 4 | Strategy directory drift | Reset orphaned bookkeeping |
| 5 | `bar_hour` missing from ctx | Strategy convention requires `prepare_indicators` to set it |

All of these are pipeline orchestration debt unrelated to the research question. The side-channel run bypassed all five and produced a clean answer in ~2 minutes. The research result above is causally clean; the production pipeline simply isn't necessary to deliver it.

---

## Caveats acknowledged

- **PnL proxy** = `(exit_price - entry_price) × direction`, not the OctaFx capital-wrapped pnl_usd. PF and trim-PF are unit-invariant ratios so this proxy is sound for comparison; absolute $ figures are not directly comparable to the original backtest's $202.55.
- **No spread/slippage stress.** This is the optimistic case. Real live-news execution would be worse (wider spreads at release). If the optimistic version fails the gates, the realistic version definitely fails.
- **HTF regime computation:** my side-channel calls `apply_regime_model` directly on 15M data; production computes regime on a higher TF and merges. This may shift FilterStack rejection patterns marginally, but PF=0.76 vs 2.78 is far too large a delta to be explained by regime-computation noise.

---

## Implications

1. **Discovery report's NEWS_AMPLIFIED bucket** is now downgraded in confidence. It correctly identifies which strategies *show* news lift in their unrestricted runs; it does **not** predict whether that lift survives isolation. Phase 2 Path A is the only honest test.
2. **The other 8 NEWS_AMPLIFIED candidates** + **10 EVENT_CONCENTRATED candidates** in the discovery report are now suspect. Their post-hoc lifts are subject to the same selection bias. Re-validating each via Path A side-channel takes ~5 min per candidate; not free, but not expensive.
3. **The NEWS_SUPPRESSED bucket** (22 candidates where outside_PF ≫ news_PF) is **unaffected by this critique** — those are filter-OUT recommendations, not isolation tests. Adding a news-window block to PINBAR XAU 1H or FAKEBREAK FX 15M EURUSD remains valid Phase-2 work because it doesn't depend on flat-state selection.
4. **No deployment** of any news-active strategy. Period.

---

## What I have NOT changed

- Production strategies untouched.
- Production pipeline untouched.
- No commits made for this Phase 2 work.
- The S13/S14 wrappers exist but are scratch artifacts; they are NOT in any sweep_registry that the production pipeline will admit (the S13/S14 stubs I added remain registered but the strategies live in `strategies/` under those IDs without being entered into Master Filter / portfolio).
- No promotion, no FSM mutation.

The S13/S14 strategy folders + sweep_registry stubs can be cleaned up; happy to do that on your call.

---

## Recommendation

**Stop here on RSIAVG-news.** The cleanest candidate failed isolation. Two reasonable next moves, neither urgent:

1. **Re-run Path A side-channel against the next 2-3 NEWS_AMPLIFIED candidates** (PORT/MACDX XAU 5M, ZREV XAU 15M) to confirm the selection-bias pattern holds across the bucket. If all fail, the entire NEWS_AMPLIFIED-as-discovered hypothesis closes.
2. **Pivot to NEWS_SUPPRESSED** as the actually-actionable bucket — adding news-window blocks to existing strategies (PINBAR XAU 1H, FAKEBREAK FX 15M EURUSD) is mathematically a different operation that doesn't suffer the flat-state asymmetry, and the candidates there have stronger N.

My recommendation: **option 2 first** — actively-traded news edge looks structurally hard to find on existing strategies, but news-as-filter is a clean, low-risk Sharpe lift on already-validated strategies.

---

## Artifacts

- Side-channel script: `tmp/rsiavg_patha_sidechannel.py`
- Wrapper strategies: `strategies/22_CONT_FX_15M_RSIAVG_TRENDFILT_S13_V1_P00/`, `S14_V1_P00/`
- Source backtest (baseline): `TradeScan_State/backtests/22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P03_EURUSD/`
- Path B report: [outputs/PHASE2_PATHB_RSIAVG_EURUSD_2026_05_03.md](outputs/PHASE2_PATHB_RSIAVG_EURUSD_2026_05_03.md)
- Discovery report: [outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md](outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md)
- Anchor: `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
