# Cross-Family News-Edge Discovery — Discovery Triage Report

`CLASSIFICATION_THRESHOLDS_FROZEN_2026_05_03`

**Date:** 2026-05-03
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
**Scope:** Full backtest archive (`TradeScan_State/backtests/`) — 1,084 completed runs across 81 (idea_id × asset_class × timeframe) groups.
**Method:** First-principles re-classification of every selected backtest's `results_tradelevel.csv` against the production news calendar. Historical report sections are not consulted.
**Discovery question:** Of all existing strategy families, which naturally express edge during scheduled macro events?

---

## FROZEN parameters (for audit integrity — do not adjust post-hoc)

```
MIN_TRADES                        = 150
RATIO_THRESHOLD                   = 1.20    (news_pf > outside_pf × 1.20 ⇒ AMPLIFIED)
LOW_NEWS_SAMPLE_FLAG              = 30      (advisory sub-flag, not a bucket)
PRE_WINDOW_MINUTES                = 30
POST_WINDOW_MINUTES               = 90
NEUTRAL_BAND_MINUTES              = 90      (events > ±90 m of entry = "outside")
IMPACT_FILTER                     = "High"
CURRENCY_MAPPING                  = derive_currencies(symbol)  [production, 2026-05-03]
SELECTION_PRIMARY_KEY             = expectancy × √N (descending)
SELECTION_TIEBREAK                = net_pnl_usd (descending)
GROUP_KEY                         = (idea_id, asset_class, timeframe)
RECOMPUTE_FROM_FIRST_PRINCIPLES   = True
```

These were locked before the run.

---

## Bucket distribution

| Bucket | Count | Meaning |
|---|--:|---|
| `NEWS_AMPLIFIED` | 9 | News PF > outside × 1.20, **and** trim-PF ≥ 1.0 (distributed news edge) |
| `EVENT_CONCENTRATED` | 10 | News PF > outside × 1.20, **but** trim-PF < 1.0 (tail-carried news edge) |
| `NEWS_SUPPRESSED` | 22 | Outside PF > news × 1.20 (news windows hurt — filter candidates) |
| `NEWS_INDIFFERENT` | 14 | Within ±20% (skip) |
| `INSUFFICIENT_SAMPLE` | 26 | Top pick had < 150 trades |
| `NO_VALID_RUN` | 0 | — |
| **Total groups evaluated** | **81** | |

---

## Phase 1 disclaimer

This is a **discovery triage**, not a validated edge. A `NEWS_AMPLIFIED` family could be coincidence (the strategy fires at a time-of-day that overlaps with US releases). To convert discovery → action requires **Phase 2: re-run the top candidates with a news-only or news-blocked filter and verify the lift survives in a clean backtest.**

The report names candidates for Phase 2 validation. It does not justify any deployment, promotion, or directive change on its own.

---

## NEWS_AMPLIFIED (rank 1) — distributed news edge, robust to top-5% removal

**The most actionable bucket.** These families show > 20% news-PF lift, and the lift survives top-5% trimming.

| Rank | idea | model | asset | TF | symbol | N | news_N | news_share | news_PF | outside_PF | ratio | trim_PF | sample |
|--:|--:|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | 22 | RSIAVG | FX | 30M | GBPJPY | 336 | 5 | 1.5 % | 21.84 | 1.81 | **12.06×** | 13.21 | low |
| 2 | 7 | SMI | XAU | 15M | XAUUSD | 284 | 13 | 4.6 % | 5.77 | 1.62 | **3.57×** | 1.97 | low |
| 3 | 60 | SYMSEQ | BTC | 1H | BTCUSD | 361 | 16 | 4.4 % | 1.96 | 0.97 | **2.03×** | 1.35 | low |
| 4 | 22 | RSIAVG | FX | 15M | EURUSD | 1322 | 54 | 4.1 % | 2.78 | 1.40 | **1.99×** | 1.76 | OK |
| 5 | 34 | FAKEBREAK | FX | 30M | USDJPY | 870 | 23 | 2.6 % | 1.79 | 0.96 | **1.88×** | 1.40 | low |
| 6 | 36 | IMPULSE | BTC | 15M | ETHUSD | 499 | 16 | 3.2 % | 2.05 | 1.35 | **1.52×** | 1.32 | low |
| 7 | 5 | PORT | XAU | 5M | XAUUSD | 1333 | 43 | 3.2 % | 2.16 | 1.47 | **1.47×** | 1.23 | OK |
| 8 | 54 | MACDX | XAU | 5M | XAUUSD | 1333 | 43 | 3.2 % | 2.16 | 1.47 | **1.47×** | 1.23 | OK |
| 9 | 55 | ZREV | XAU | 15M | XAUUSD | 1344 | 41 | 3.1 % | 1.75 | 1.39 | **1.26×** | 1.33 | OK |

**`sample = OK`** when news-trade count ≥ 30. Rows flagged `low` have small news samples and require Phase-2 confirmation before they can be trusted.

Strongest unambiguous signals (high N + high ratio + trim ≥ 1.0):
- **22 RSIAVG FX 15M EURUSD** — 1322 trades, 54 news trades, 1.99× ratio, trim-PF 1.76. Most credible candidate by sample size.
- **5 PORT XAU 5M XAUUSD** + **54 MACDX XAU 5M XAUUSD** — 1333 trades each, identical numbers (likely the same underlying strategy duplicated under two model tokens; flag for investigation).
- **55 ZREV XAU 15M XAUUSD** — 1344 trades, trim 1.33. Notable given ZREV is on the project KILL list for non-news performance — but the news-window subset shows distinct edge.

---

## EVENT_CONCENTRATED (rank 2) — tail-carried news edge, fewer-large-events pattern

These families show news lift > 1.20× **but** trim-PF < 1.0 — a small number of news events drive most of the news PnL. Less robust than NEWS_AMPLIFIED, but worth flagging — they suggest specific event types matter (FOMC, NFP, CPI) rather than news in general.

| Rank | idea | model | asset | TF | symbol | N | news_N | news_share | news_PF | outside_PF | ratio | trim_PF |
|--:|--:|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 17 | FAKEBREAK | XAU | 1H | XAUUSD | 245 | 4 | 1.6 % | 6.56 | 1.54 | **4.27×** | 0.30 |
| 2 | 23 | MICROREV | XAU | 1H | XAUUSD | 232 | 6 | 2.6 % | 7.44 | 1.78 | **4.18×** | 0.47 |
| 3 | 9 | LORB | FX | 1H | GBPUSD | 551 | 3 | 0.5 % | 1.82 | 1.03 | **1.78×** | 0.64 |
| 4 | 36 | IMPULSE | BTC | 30M | ETHUSD | 573 | 11 | 1.9 % | 1.72 | 1.09 | **1.57×** | 0.98 |
| 5 | 28 | ENGULF | XAU | 1H | XAUUSD | 166 | 4 | 2.4 % | 1.54 | 1.02 | **1.51×** | 0.36 |
| 6 | 36 | IMPULSE | BTC | 1H | ETHUSD | 228 | 2 | 0.9 % | 1.63 | 1.11 | **1.47×** | 0.00 |
| 7 | 20 | ZREV | XAU | 1H | XAUUSD | 1191 | 44 | 3.7 % | 1.27 | 0.87 | **1.46×** | 0.65 |
| 8 | 30 | SMI | XAU | 1H | XAUUSD | 244 | 11 | 4.5 % | 0.90 | 0.68 | **1.33×** | 0.48 |
| 9 | 49 | CHOCH | XAU | 1H | XAUUSD | 326 | 10 | 3.1 % | 1.34 | 1.01 | **1.32×** | 0.76 |
| 10 | 1 | ULTC | FX | 1H | USDJPY | 438 | 22 | 5.0 % | 1.43 | 1.11 | **1.28×** | 0.93 |

XAU 1H dominates this bucket — multiple unrelated families (FAKEBREAK, MICROREV, ENGULF, ZREV, SMI, CHOCH) all show concentrated event response on XAUUSD 1H. Suggests XAU 1H is structurally event-reactive across architectures, with the edge concentrated in a small set of releases.

---

## NEWS_SUPPRESSED (rank 3) — pure filter-overlay candidates

**These are the easiest wins.** Each row is a strategy where news-window trades hurt the strategy. Adding a news-window block as a filter would lift PF and reduce drawdown without inventing any new edge.

Sorted by inverse ratio (outside_PF / news_PF, descending):

| Rank | idea | model | asset | TF | symbol | N | news_N | news_share | news_PF | outside_PF | inv_ratio | trim_PF |
|--:|--:|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 24 | SFP | XAU | 1H | XAUUSD | 158 | 2 | 1.3 % | 0.00 | 1.73 | **∞** | — |
| 2 | 18 | LIQSWEEP | XAU | 1H | XAUUSD | 243 | 1 | 0.4 % | 0.00 | 1.36 | **∞** | — |
| 3 | 42 | LIQSWEEP | FX | 15M | EURJPY | 317 | 5 | 1.6 % | 0.12 | 1.49 | **12.41×** | 0.00 |
| 4 | 55 | ZREV | FX | 15M | EURUSD | 226 | 8 | 3.5 % | 0.20 | 0.98 | **5.03×** | 0.05 |
| 5 | 7 | SMI | XAU | 5M | XAUUSD | 245 | 9 | 3.7 % | 0.31 | 1.48 | **4.74×** | 0.02 |
| 6 | 25 | LIQGRAB | XAU | 15M | XAUUSD | 218 | 2 | 0.9 % | 0.36 | 1.20 | **3.36×** | 0.00 |
| 7 | 32 | EMAXO | XAU | 30M | XAUUSD | 434 | 14 | 3.2 % | 0.27 | 0.87 | **3.29×** | 0.15 |
| 8 | 34 | FAKEBREAK | FX | 15M | EURUSD | 1664 | 43 | 2.6 % | 0.33 | 0.96 | **2.93×** | 0.24 |
| 9 | 3 | IMPULSE | XAU | 1H | XAUUSD | 465 | 6 | 1.3 % | 0.62 | 1.63 | **2.63×** | 0.14 |
| 10 | 61 | GMAFLIP | INDEX | 5M | NAS100 | 853 | 31 | 3.6 % | 0.55 | 1.28 | **2.32×** | 0.19 |
| 11 | 27 | PINBAR | XAU | 1H | XAUUSD | 620 | 19 | 3.1 % | 0.59 | 1.31 | **2.22×** | 0.40 |
| 12 | 59 | RUNFAIL | XAU | 15M | XAUUSD | 196 | 12 | 6.1 % | 0.67 | 1.33 | **1.98×** | 0.45 |
| 13 | 56 | ZPULL | XAU | 15M | XAUUSD | 530 | 27 | 5.1 % | 0.62 | 1.21 | **1.96×** | 0.53 |
| 14 | 63 | ATRBRK | INDEX | 30M | NAS100 | 303 | 11 | 3.6 % | 0.81 | 1.58 | **1.95×** | 0.59 |
| 15 | 28 | ENGULF | XAU | 30M | XAUUSD | 310 | 12 | 3.9 % | 0.55 | 1.02 | **1.88×** | 0.38 |
| 16 | 15 | ASRANGE | XAU | 1H | XAUUSD | 277 | 16 | 5.8 % | 0.33 | 0.62 | **1.87×** | 0.23 |
| 17 | 33 | IMPULSE | BTC | 15M | BTCUSD | 1094 | 26 | 2.4 % | 0.66 | 1.08 | **1.63×** | 0.43 |
| 18 | 32 | EMAXO | XAU | 15M | XAUUSD | 541 | 34 | 6.3 % | 0.74 | 1.13 | **1.53×** | 0.40 |
| 19 | 40 | RSIPULL | FX | 15M | GBPUSD | 289 | 2 | 0.7 % | 0.95 | 1.25 | **1.32×** | 0.00 |
| 20 | 33 | IMPULSE | BTC | 1H | BTCUSD | 179 | 6 | 3.4 % | 1.37 | 1.79 | **1.30×** | 0.55 |
| 21 | 21 | CMR | XAU | 1H | XAUUSD | 156 | 3 | 1.9 % | 0.62 | 0.81 | **1.30×** | 0.00 |
| 22 | 53 | CMR | FX | 4H | GBPUSD | 170 | 12 | 7.1 % | 0.98 | 1.18 | **1.21×** | 0.55 |

Highest-confidence filter candidates (large N, large delta):
- **34 FAKEBREAK FX 15M EURUSD** — 1664 trades, news-PF 0.33 vs outside 0.96. Blocking news windows could turn a marginal-loser into a credible strategy.
- **33 IMPULSE BTC 15M BTCUSD** — 1094 trades, 2.63× lift outside news.
- **27 PINBAR XAU 1H XAUUSD** — 620 trades, news collapses PF to 0.59 vs outside 1.31. PINBAR is a current BURN_IN strategy; this is a high-priority filter candidate.
- **63 ATRBRK INDEX 30M NAS100** — 303 trades, 1.95× outside lift.

PINBAR XAU 1H specifically is in the active portfolio (per memory) — applying a news-window block here is the single most actionable item in this report.

---

## NEWS_INDIFFERENT (rank 4) — skip

| idea | model | asset | TF | symbol | N | news_PF | outside_PF | ratio |
|--:|---|---|---|---|--:|--:|--:|--:|
| 35 | DAYOC | INDEX | 30M | JPN225 | 509 | n/a | 1.16 | n/a |
| 35 | DAYOC | INDEX | 1H | JPN225 | 500 | n/a | 1.06 | n/a |
| 46 | CHOCH | XAU | 1H | XAUUSD | 356 | 1.22 | 1.33 | 0.92 |
| 35 | DAYOC | INDEX | 15M | JPN225 | 505 | n/a | 1.02 | n/a |
| 63 | ATRBRK | INDEX | 15M | NAS100 | 2391 | 1.06 | 1.15 | 0.93 |
| 62 | KALFLIP | INDEX | 5M | NAS100 | 1075 | 1.33 | 1.27 | 1.05 |
| 41 | FAKEBREAK | FX | 1H | EURUSD | 691 | 1.16 | 1.22 | 0.96 |
| 41 | FAKEBREAK | FX | 15M | USDJPY | 586 | 1.32 | 1.26 | 1.05 |
| 63 | ATRBRK | INDEX | 5M | NAS100 | 4781 | 1.01 | 1.02 | 0.99 |
| 15 | ASRANGE | FX | 15M | AUDNZD | 461 | n/a | 1.56 | n/a |
| 15 | ASRANGE | FX | 1H | AUDUSD | 377 | 1.45 | 1.26 | 1.15 |
| 34 | FAKEBREAK | FX | 1H | USDJPY | 441 | 1.13 | 1.03 | 1.09 |
| 56 | ZPULL | FX | 15M | EURUSD | 669 | 0.93 | 0.79 | 1.17 |
| 57 | ZTRANS | XAU | 15M | XAUUSD | 729 | 0.75 | 0.83 | 0.90 |

JPN225 strategies show `n/a` news PF — JPY High-impact news appears to land outside the daily session window for these strategies. Edge case; not actionable.

---

## INSUFFICIENT_SAMPLE (rank 5) — < 150 trades, no decision

26 groups had top picks below the 150-trade floor. Most are XAU 1H families with sparse coverage. The new NEWSBRK family is here too (S03/S05 15M ranged 93–159 N — at or below floor, hence the bucket).

Notable: NEWSBRK 5M S02 P00 had 229 trades and was eligible but its top pick was P02 (107 trades, the strongest by score across the 3-patch group), so it landed in INSUFFICIENT_SAMPLE rather than appearing in NEWS_SUPPRESSED. This is a side-effect of "one pick per group" — full NEWSBRK accounting is in the prior reports.

---

## Suggested Phase-2 priorities

The discovery is now done. Recommended order for Phase 2 validation work, when you choose to schedule it:

1. **PINBAR XAU 1H — apply news-window block.** Active BURN_IN strategy, large N, clean signal. Highest expected lift relative to effort.
2. **FAKEBREAK FX 15M EURUSD — apply news-window block.** Largest sample suppression candidate (1664 trades). Could turn a sub-1 PF into a viable strategy.
3. **RSIAVG FX 15M EURUSD — apply news-only filter.** Largest amplification candidate by sample (1322 trades, 54 news trades, trim 1.76). Test whether trading only-during-news preserves the lift.
4. **PORT vs MACDX XAU 5M — investigate the duplication.** Identical numbers across two model tokens; likely a registry/labeling issue worth resolving before any further analysis on either.

Each Phase 2 validation is one or two directives, not a sweep — small follow-ups, not new families.

---

## Appendix A — selection traceability

Per group, the strongest backtest selected was the one ranking highest by `expectancy × √N` (descending), with `net_pnl_usd` then `n` as tiebreaks. The full decision table (1,084 candidates → 81 group picks) is in:

- `tmp/news_edge_discovery_results.csv` — all picks with full metrics
- `tmp/news_edge_discovery.py` — the analysis script (frozen-threshold constants in module header)

To audit any selection: filter the discovery CSV by `(idea_id, asset_class, timeframe)` and confirm `score = expectancy × √n` is the maximum.

---

## Notes on integrity

- All 81 groups were classified under the same news logic (production calendar + production `derive_currencies` + frozen thresholds).
- No historical report sections were consulted — every metric was recomputed from raw `results_tradelevel.csv`.
- Threshold values are immutable for this report. Any future re-classification with adjusted thresholds requires a new report under a new `CLASSIFICATION_THRESHOLDS_FROZEN_<date>` tag, not a revision of this one.
- This report does not mutate ledgers, vault, FSM state, or any production artifact. It is a pure analysis of existing results.
