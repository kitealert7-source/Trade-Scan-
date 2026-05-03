# NEWSBRK 15M Comparative — S03 (A1) vs S05 (A2)

**Date:** 2026-05-03
**Symbol:** NAS100
**Calendar:** ForexFactory RESEARCH-layer, USD High-impact only
**Directives in scope:** 6 (S03 P00/P01/P02 + S05 P00/P01/P02), all PORTFOLIO_COMPLETE under `FRAMEWORK_BASELINE_2026_05_03`
**Backtest period:** 2024-01-01 → 2026-03-20

---

## TL;DR — Verdict

| Architecture | Verdict | Reason |
|---|---|---|
| **S03 (A1 pre-event compression breakout)** | **KILL** | Intended pre-event edge has 1–4 trades per directive (statistically null). The strategy is *de facto* a post-event continuation that uses a compression-box filter; trim-PF < 1.0 across all patches. |
| **S05 (A2 post-event continuation)** | **KILL** | Same post-event window as S03's de-facto behavior, one losing patch (PF 0.88), worse tail concentration (315–321 % top-5 share vs S03's 226–258 %). |

Both fail the project's promote quality gate (`feedback_promote_quality_gate.md`): tail-dependent edge — top-5 % of trades carry > 100 % of total PnL, the remainder collectively loses money.

The NEWSBRK family on NAS100 INDEX **should not be promoted to burn-in.**

---

## Headline metrics (per directive)

| Directive | N | PF | PnL$ | trim PF | top-5 % share | news-only PF | news-only N |
|---|--:|--:|--:|--:|--:|--:|--:|
| S03_V1_P00 | 159 | 1.20 | +55.2 | **0.68** | **258 %** | 1.20 | 157 |
| S03_V1_P01 | 114 | 1.21 | +38.7 | **0.74** | **226 %** | 1.21 | 112 |
| S03_V1_P02 | 93 | 1.36 | +56.2 | **0.86** | **139 %** | 1.36 | 91 |
| S05_V1_P00 | 74 | **0.88** | **-9.7** | 0.49 | 317 % | 0.88 | 74 |
| S05_V1_P01 | 99 | 1.13 | +14.4 | 0.71 | 321 % | 1.13 | 97 |
| S05_V1_P02 | 141 | 1.15 | +33.9 | 0.67 | 315 % | 1.16 | 137 |

`top-5 % share` = top-5 % of trades' PnL ÷ total PnL. Values > 100 % mean the bottom 95 % collectively lose money — the gross profit lives entirely in the tail.

`trim PF` removes those top-5 % winners and recomputes PF on the remainder. Across all 6 directives the trim PF is < 1.0 — i.e., **the underlying distribution is unprofitable; only the rare extreme winner makes it look like an edge.**

---

## News-proximity decomposition

Tags by entry timestamp vs nearest USD High-impact event:
- **pre** = entry in [event – 30 m, event)
- **post** = entry in [event, event + 90 m]
- **outside** = no high-impact event within ±90 m

| Directive | pre N / PnL / PF | post N / PnL / PF | outside N / PnL / PF |
|---|---|---|---|
| S03_V1_P00 | 4 / +7.6 / 35.4 | 153 / +46.8 / 1.17 | 2 / +0.8 / 1.31 |
| S03_V1_P01 | 2 / +3.1 / 15.1 | 110 / +34.8 / 1.19 | 2 / +0.8 / 1.31 |
| S03_V1_P02 | 1 / +3.3 / inf | 90 / +52.1 / 1.34 | 2 / +0.8 / 1.31 |
| S05_V1_P00 | 1 / +0.7 / inf | 73 / **-10.4 / 0.87** | 0 / — |
| S05_V1_P01 | 1 / +0.7 / inf | 96 / +12.9 / 1.12 | 2 / +0.8 / 1.31 |
| S05_V1_P02 | 5 / +14.0 / 1.59 | 132 / +19.7 / 1.10 | 4 / +0.2 / 1.04 |

**Key finding:** S03's pre-event bucket (the architecture's *intended* edge) has only **1–5 trades per directive** across 27 months. The architecture's hypothesis is **statistically null** — the compression-box filter at 15 M almost never fires inside the pre-event window. What's left is essentially a post-event strategy with a different filter, indistinguishable from S05's A2 design at the entry-timing level.

**Outside-news** trades collapse to ≤ 4 per directive in both architectures — by design of the news-window entry filter, but it also means there's effectively no non-news baseline to compare against.

---

## Yearwise PF stability

| Directive | 2024 (PF / N) | 2025 (PF / N) | 2026 (PF / N) |
|---|---|---|---|
| S03_V1_P00 | 1.49 / 58 | 1.02 / 89 | 1.91 / 12 |
| S03_V1_P01 | 1.62 / 41 | 0.89 / 62 | 1.75 / 11 |
| S03_V1_P02 | 1.50 / 35 | 1.21 / 49 | 1.66 / 9 |
| S05_V1_P00 | **0.55 / 28** | 1.06 / 37 | 2.06 / 9 |
| S05_V1_P01 | **0.80 / 36** | 1.26 / 54 | 2.49 / 9 |
| S05_V1_P02 | 1.23 / 52 | 1.08 / 76 | 1.36 / 13 |

- S03 is more stable across years (all 9 cells PF > 0.89). S05 has two losing years in 2024.
- 2026 PF is highest for everything but the sample is small (9–13 trades, < 3 months elapsed) — recency bias caveat.
- Across years the median PF hovers near 1.0–1.5 — exactly the regime where tail concentration determines outcome, which is the same diagnosis the headline trim-PF gives.

---

## Architecture-level aggregation

| Metric | **S03 (A1)** | **S05 (A2)** |
|---|--:|--:|
| n directives | 3 | 3 |
| Total trades | 366 | 314 |
| Total PnL ($) | +150.1 | +38.6 |
| Median PF | 1.21 | 1.13 |
| Median trim-PF | 0.74 | 0.67 |
| Median top-5 % share | 226 % | 317 % |
| Median news-only PF | 1.21 | 1.13 |
| Frac PF > 1 | **3/3 (100 %)** | 2/3 (67 %) |
| Frac trim-PF > 1 | **0/3** | **0/3** |

S03 looks marginally better on every headline metric. **Both fail the trim-PF gate unanimously.**

---

## Mechanism diagnosis

The "edge" both architectures show is a **post-event drift continuation** carried by a small number of large winners — exactly the pathology already documented for `ZREV`, `ZPULL`, and `SYMSEQ` in `RESEARCH_MEMORY.md`. Same disease, different family.

S03's nominal pre-event design did not falsify or validate the pre-event hypothesis — it simply never produced enough samples to test it. The compression-box filter at 15 M is too restrictive given the 30-minute pre-event window. **The pre-event hypothesis is undecided, not refuted, but it cannot be tested at this configuration.**

S05's A2 design is a direct test of the post-event continuation hypothesis. Result: PF ≈ 1.1 with crushing tail dependence — same diagnosis as every other tail-carried edge we've seen.

---

## Recommendations

1. **NEWSBRK family on NAS100 INDEX 15M: do not promote.** Both architectures fail the standard quality gate. Park them.
2. **Append a `RESEARCH_MEMORY.md` entry** classifying this as "NEWSBRK INDEX 15M tail-carried, same disease as ZREV/SYMSEQ" so future agents don't reattempt the same hypothesis blindly.
3. **If we want to test the pre-event hypothesis honestly**, the right configuration is *not* a longer S03 — it's a different timeframe (5 M) where the pre-event window contains enough bars for the compression-box filter to fire more than once per six months. That requires the 5 M data extension you offered (see deferred note below).
4. **Cross-asset re-test optional but low-priority.** Same pattern killed ZREV across XAU + EUR. NEWSBRK on indexes is structurally similar; expecting a different result from running it on more symbols at the same TF would be confirmation bias.

---

## Deferred (per your offer to extend back-test period)

You wrote: *"we can reduce backtest period if coverage is less."* The 5 M directives (S02 + S04) failed at admission with `DATA_RANGE_INSUFFICIENT` — NAS100 5 M data starts 2024-08-06 vs requested 2024-01-01.

**If you want to bring the 5 M variants in scope** (which is the only way to test the pre-event hypothesis with adequate sample), the mechanical change is to bump `start_date: 2024-08-06` in S02 and S04 directive YAMLs and re-run. ~4 directives × ~5 min = ~20 min of pipeline time, no framework risk.

I have **not** made that change yet — flagging the option, awaiting your call.

---

## Artifacts

- Trade-level CSVs: `TradeScan_State/backtests/64_BRK_IDX_15M_NEWSBRK_S0[35]_V1_P0[012]_NAS100/raw/results_tradelevel.csv`
- Per-directive REPORTs: `…/REPORT_64_BRK_IDX_15M_NEWSBRK_*.md`
- Analysis script: `tmp/newsbrk_15m_compare.py` (one-off, not committed)
- Anchor: `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
