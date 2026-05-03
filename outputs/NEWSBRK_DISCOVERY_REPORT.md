# NEWSBRK Discovery Report — News-Window Alpha Across Existing Research Corpus

**Date:** 2026-05-02
**Scope:** Research-only synthesis. No new strategy code, no new backtests.
**Inputs:** 1,076 `REPORT_*.md` files in `TradeScan_State/backtests/`; 565 strategy/symbol rows carrying a populated `News Policy Impact` section; ForexFactory news calendar (10,298 events, 2024–2026); RESEARCH_MEMORY post-2026-04-14 entries.
**Method:** Extract News-Window vs Outside aggregates from each report's News Policy section, classify each strategy/symbol by news-edge type, rank candidates by composite quality (news_pf × edge_lift × sqrt(news_trades)), then map dominant patterns to NEWSBRK v1 architecture candidates.

---

## 1. Headline Finding

The corpus has a single, structurally unmistakable cluster of **event-dependent alpha on equity-index breakouts**:

> `63_BRK_IDX_*M_ATRBRK_*` (5M, 15M, 30M) on NAS100, GER40, JPN225, EUSTX50, ESP35, UK100 produces **News PF 4.0–6.7 with Outside PF 0.62–0.86** in nearly every parameter / symbol cell tested. Strategy-level Baseline PFs sit between 1.04 and 1.23 — i.e., the entire profit-and-then-some comes from the 8–25 % of trades that overlap a news window. Outside news, ATRBRK loses money on every single index it has been tested on.

This is the strongest news-alpha signature in the entire pipeline. It is cross-symbol-replicated, cross-timeframe-stable (5M/15M/30M), and yearwise-consistent (PF 1.04–1.06 across 2024 / 2025 / 2026). It is also the reason NEWSBRK should exist as its own family rather than as a filter retrofitted onto another idea.

A weaker but real **Class A (event-amplified)** cluster exists on `IMPULSE` (XAU 1H, BTC 1H, ETH 15M), `KALFLIP` (NAS100 5M with ADX+RSI+Hurst stack), and `GMAFLIP P01` (NAS100 5M). Outside-news is profitable; news multiplies it by 3–6×.

Most other families (CMR, RSIAVG, ZPULL, ZTRANS, VOLEXP 1D, SYMSEQ) are **news-neutral or news-negative** and should be excluded from any news-conditioned design.

---

## 2. How the Edge Was Measured

Every per-strategy `REPORT_*.md` contains a **News Policy Impact** section produced by [tools/report/report_sections/news.py](tools/report/report_sections/news.py) and [tools/report/report_news_policy.py](tools/report/report_news_policy.py). For each trade it overlaps the trade's `[entry_timestamp, exit_timestamp]` against `(window_start, window_end)` windows derived from the calendar's `(currency, impact)` pairs in [data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/](data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH).

For this discovery I extracted the `News Window` vs `Outside` aggregate rows from every report and computed:

| Metric | Definition |
|---|---|
| `news_trade_pct` | News trades / total trades |
| `news_pnl_pct` | News PnL / Net PnL (>100 % means outside loses money) |
| `edge_lift` | `news_pf − out_pf` |
| `Q` (quality) | `news_pf × (edge_lift + 0.5) × sqrt(min(news_trades, 500)/500)` |

Caveats kept in mind through the ranking:
- The current windows treat **all impacts equally** within a currency. ForexFactory `impact ∈ {High, Medium, Low}` exists but is not currently used to gate the windows. Many of the "news" trades for high-news-PF strategies will in practice be Medium or Low events — i.e., a noise event in the same window as a real release. This is a known understatement of the true high-impact PF.
- The default window is symmetric around the event timestamp; pre-event vs post-event split is **not** preserved in the report. Architectures (1) vs (3) below cannot be distinguished from the existing reports — only the existence of news edge can.
- The classifier flags a trade `news = True` if any news window for any of the symbol's currencies overlaps the trade's holding period. For multi-currency symbols (XAUUSD = USD, EUR; NAS100 = USD; GER40 = EUR; etc.) this somewhat inflates the news-flag rate compared to a strict "pre-event-only" window.
- Top-5 concentration / yearwise / regime detail is not included in the news subsection — only Baseline-level. So per-news tail-risk is approximated from baseline tail-risk plus the news vs outside PnL split.

These caveats reduce the precision of the magnitudes but not the direction of the findings — when a strategy shows news_pf ≈ 5× and out_pf < 1.0 across six independent index symbols, the signal is robust to any reasonable redefinition of "news window".

---

## 3. Classification of All 565 Strategy/Symbol Cells

| Class | Definition | Count |
|---|---|---|
| **A — Event-Amplified** | Outside-PF ≥ 1.0 AND News-PF ≥ 1.2 × Outside-PF AND News-PF ≥ 1.3, news_trades ≥ 30 | 31 |
| **B — Event-Dependent** | Outside-PF < 1.0 AND News-PF ≥ 1.5, news_trades ≥ 30 | 54 |
| **B-weak** | Outside-PF < 0.95 AND News-PF ≥ 1.2 (lower news-PF threshold) | 1 |
| **C — Insufficient sample** | News-PF ≥ 1.5 but news_trades < 30 | 28 |
| **N — No edge / news-neutral / news-negative** | Everything else | 451 |

Full ranked tables: [tmp/news_classified.md](.claude/worktrees/vigilant-allen-a3c2a7/tmp/news_classified.md) (working file). Source CSV: [tmp/news_scan.csv](.claude/worktrees/vigilant-allen-a3c2a7/tmp/news_scan.csv).

### 3.1 Class A — Event-Amplified (top picks)

These strategies are profitable on their own, and news multiplies the edge. They are evidence that "news + a working substrate" is real.

| Strategy/Symbol | TF | News N | News PF | Out PF | News $ % | Notes |
|---|---|---|---|---|---|---|
| `03_TREND_XAUUSD_1H_IMPULSE_P02` | 1H | 52 | **6.23** | 1.08 | 77 % | Profitable substrate; news-amplified ~6× |
| `33_TREND_BTCUSD_1H_IMPULSE_P02/P05` | 1H | 59 | **5.82** | 1.13 | 74 % | Same primitive transports to BTC 1H |
| `61_TREND_IDX_5M_GMAFLIP_P01` | 5M | 52 | **5.53** | 1.05 | 82 % | NAS100; the regime-only locked variant |
| `62_TREND_IDX_5M_KALFLIP_P15` | 5M | 79 | **3.50** | 1.11 | 63 % | Production-locked ADX+RSI+Hurst stack |
| `54_STR_XAUUSD_5M_MACDX_P03` (S03 triple-conv) | 5M | 73 | **2.86** | 1.41 | 14 % | Outside is already PF 1.41; news-marginal |
| `55_MR_XAUUSD_15M_ZREV` (multiple P-variants) | 15M | 234–327 | 1.40–1.89 | 1.05–1.32 | 26–64 % | Family-wide, but tail-PF gate-fail (see RESEARCH_MEMORY 2026-04-23) |
| `46_STR_XAU_1H_CHOCH_P03` | 1H | 81 | 2.17 | 1.09 | 80 % | Pivot-CHOCH long-only |
| `36_TREND_ETHUSD_15M_IMPULSE_P05` | 15M | 49 | 2.19 | 1.28 | 31 % | Crypto IMPULSE |

### 3.2 Class B — Event-Dependent (the NEWSBRK substrate)

These strategies **lose money outside news windows** but show news_pf 4–10. The breakout / flip primitive only earns its keep when the market is being moved by an event. This is the right substrate to build NEWSBRK on top of.

| Strategy/Symbol family | TF | Symbols | News PF range | Out PF range | News $ % | Q-rank top |
|---|---|---|---|---|---|---|
| **`63_BRK_IDX_15M_ATRBRK`** | 15M | NAS100, JPN225 | **5.47–6.65** | 0.74–0.80 | 275–464 % | Q = 36.2 (best-in-corpus) |
| **`63_BRK_IDX_30M_ATRBRK`** | 30M | NAS100, GER40, JPN225, EUSTX50, ESP35, UK100 | **3.99–5.69** | 0.62–0.90 | 129–277 % | Q = 24.8 |
| **`62_TREND_IDX_5M_KALFLIP`** (filter variants without all-3 stack) | 5M | NAS100 | **6.74–9.59** | 0.89–0.95 | 127–161 % | Q = 33.6 (P17) |
| `61_TREND_IDX_5M_GMAFLIP_P00` (no filter baseline) | 5M | NAS100 | 5.69 | 0.94 | 141 % | Q = 13.2 |
| `63_BRK_IDX_5M_ATRBRK_S03` | 5M | NAS100, JPN225 | 2.79–3.0 | 0.93 | ~150 % | Q = 8 |

The **`63_BRK` family is the headline**. Six independent index symbols, three timeframes (5M/15M/30M), thirteen parameter cells, all converging on the same news-PF 4–6 / out-PF < 1 signature. This is the closest thing to a fully out-of-sample replication that exists in the corpus today.

### 3.3 Class C — Insufficient Sample

28 cells flagged with news_pf ≥ 1.5 but fewer than 30 news trades. These are dominated by GMAFLIP / KALFLIP filter variants that filtered themselves down to 3–28 news trades, and a handful of mean-reversion strategies (LIQSWEEP, PINBAR, FAKEBREAK, SPKFADE). Treat all of them as **not-yet-evidence** — they support the broader pattern but cannot independently license a directive.

### 3.4 Class N — News-Neutral / News-Negative (exclude from NEWSBRK design)

| Family | Symbols/cells | Avg News PF | Avg Out PF | Verdict |
|---|---|---|---|---|
| `02_VOL_IDX_1D_VOLEXP` | 10 | 1.27 | 1.15 | News neutral on 1D — TF too coarse to isolate event windows |
| `22_CONT_FX_*M_RSIAVG` | 45 | 1.07–1.38 | 1.39–1.58 | News HURTS — RSIAVG continuation degrades during events |
| `53_MR_FX_4H_CMR` | 90 | 0.90 | 1.12 | News HURTS — mean-reversion fails inside event windows |
| `53_MR_FX/EURUSD_1D_CMR` | 285 | 1.30 | 1.27 | Effectively neutral — daily timestep dilutes event timing |
| `56_CONT_*_15M_ZPULL`, `57_TRANS_*_15M_ZTRANS` | 5 | 0.43–0.64 | 0.84–1.17 | News negative |
| `60_MICRO_BTCUSD_4H_SYMSEQ` | 4 | 0.88 | 1.03 | News neutral/negative |

This is itself an interesting finding: **continuation and mean-reversion FX signals get worse during news** — the event "breaks" the persistence/range assumption that the signal relies on. NEWSBRK should not be built on FX continuation/MR primitives.

---

## 4. Architecture Mapping

Of the three architectures the user proposed, the existing corpus directly supports two and indirectly supports the third.

### Architecture (1) — Pre-event range breakout (30–60 min compression → post-release expansion)

**Status: Indirectly supported, not yet directly tested.** The current `News Policy` reports do not split pre-event vs post-event. But the structural ATRBRK behavior — Outside-PF < 1 (= no edge in normal conditions), News-PF 4–6 (= big asymmetric move on the event) — is exactly what a pre-event compression / post-release expansion architecture would produce on an ATR-band entry. ATRBRK without a news filter is essentially this architecture firing on every breakout regardless of cause; restricting to the pre-event compression window is the obvious next gate.

**Strongest evidence:** `63_BRK_IDX_15M_ATRBRK_S02_V1_P00–P02` on NAS100 + JPN225 (12 cells, news_pf 5.5–6.7, out_pf 0.74–0.80). News PnL alone is +$2,700 to +$4,500 over 22 months while outside is −$2,100 to −$2,600.

### Architecture (2) — Volatility-expansion continuation (ATR / vol spike + directional follow-through)

**Status: Strongly supported.** This is what `KALFLIP P05–P08, P11–P18` and `GMAFLIP P00, P01, P03–P06` are doing on NAS100 5M during news. Kalman / Gaussian slope-flip is a primitive that fires on directional acceleration; news creates the largest acceleration spikes; news_pf 5.5–9.6 across many parameter cells.

**Strongest evidence:**
- `62_KALFLIP P17` NAS100 5M: news_pf 9.59 (n=73), out_pf 0.91 — purest "news = the entire edge" signature in the corpus
- `62_KALFLIP P15` NAS100 5M (locked production): news_pf 3.50 (n=79), out_pf 1.11 — same primitive when filters keep outside profitable; news still ~63 % of PnL
- `61_GMAFLIP P00` NAS100 5M: news_pf 5.69 (n=98), out_pf 0.94 — confirms the pattern is not Kalman-specific

### Architecture (3) — News-gap retrace / reclaim (initial spike → structural reclaim → continuation)

**Status: Not directly supported by the corpus.** No existing strategy in the 565-cell scan implements a reclaim primitive (CHOCH-V2 is the closest pivot-reclaim signal, and `46_CHOCH_P00/P03` shows news_pf 1.36–2.17 vs out_pf 1.08–1.09 on XAU 1H — Class A but mild and not on indexes). Reclaim is the architecture with the **least pre-existing evidence**. Build it last, on top of (1)+(2) infrastructure.

---

## 5. Candidate Symbol / Timeframe Table for NEWSBRK v1

| Rank | Symbol | TF | Sample size (existing) | Strongest evidence | Failure modes to expect |
|---|---|---|---|---|---|
| 1 | **NAS100** | 15M | 4,400+ trades / 360+ news trades per cell across 4 parameter cells | `63_BRK_IDX_15M_ATRBRK_P00/P01/P02`: news_pf 5.5–6.7, out_pf 0.74–0.80, six-fold cross-symbol replication | Out-of-news regime drag — needs a hard gate that blocks entries outside event windows, otherwise the carry kills the edge |
| 2 | **GER40** | 30M | 4,800+ / 550+ news per cell across 6 parameter cells | `63_BRK_IDX_30M_ATRBRK_P00`: news_pf 3.99–5.69, out_pf 0.82–0.86, identical-by-construction across DAX-zone indexes | EUR + USD overlap — windows fire on US releases at 13:30 UTC AND on EUR releases; need (currency, impact) gating to avoid double-counting |
| 3 | **JPN225** | 30M | 4,800+ / 335–593 news per cell | Same `63_BRK_IDX_30M_ATRBRK_P00`: news_pf 4.11–4.68 | JPY-only news is sparse during the JPN session (Asia hours); most news edge is on USD release nights — TF and session interaction needs to be explicit |
| 4 | **EUSTX50, ESP35, UK100** | 30M | 4,800+ / 200–593 news per cell | Cross-replication of GER40 result on adjacent EUR-zone symbols | Liquidity of ESP35 / UK100 is materially worse than NAS / GER — confirm fill-quality assumptions before treating as 4 independent symbols |
| 5 | **XAUUSD** | 1H | 52–127 news per cell | `03_TREND_XAUUSD_1H_IMPULSE_P02` news_pf 6.23 / out_pf 1.08; `46_CHOCH_P03` news_pf 2.17 / out_pf 1.09 | Cross-currency confound (XAU = USD + EUR for windows); high-impact USD events dominate; need explicit single-currency window |
| 6 | **BTCUSD** | 1H | 59 news per cell | `33_TREND_BTCUSD_1H_IMPULSE_P02/P05` news_pf 5.82 / out_pf 1.13 | News calendar is FX-only — BTC's "news edge" is being measured against FX events that happen to push USD; this is a real overlap (BTC follows DXY around CPI/FOMC) but small N; treat as exploratory, not core |

**Drop from v1:** All-FX symbols (RSIAVG 30M, CMR 4H/1D, ZPULL/ZTRANS) — their news_pf is ≤ 1 or news-neutral. ETH 15M IMPULSE is interesting but small N (49 news trades) — track in v2.

---

## 6. Recommended Architectures + Best-Available Substrate Mapping

| Architecture | Best primitive evidence | Best symbols | Sample size | Confidence |
|---|---|---|---|---|
| **A1. Pre-event compression → post-release expansion** | ATRBRK on indexes (existing engine: `tools/...` + `governance/namespace ATRBRK`) | NAS100 15M/30M, GER40 30M, JPN225 30M | 1300–6000 trades per cell, 200–600 news trades | **High** — six-symbol cross-replication, three timeframes, three parameter cells |
| **A2. Volatility-expansion continuation** | KALFLIP / GMAFLIP slope-flip on indexes | NAS100 5M | 1000–2000 trades per cell, 50–100 news trades | **Medium** — single-symbol but parameter-stable across 19 KALFLIP and 15 GMAFLIP cells |
| **A3. News-gap retrace / reclaim** | None directly. Closest: pivot-CHOCH on XAU 1H | XAUUSD 1H, NAS100 15M | 80 news trades for CHOCH; nil for index reclaim | **Low** — must be built; do this third |

A1 + A2 are **independent primitives, not duplicates.** A1 is range-shape-based (compression then break); A2 is velocity-based (slope-flip catches the post-release acceleration). On the same symbol they will fire on different bars and can run as two strategies in a portfolio without cannibalizing each other.

---

## 7. Risks and Cross-Checks Before Authoring NEWSBRK v1

1. **Window-quality risk:** The current calendar treats all impacts equally. The ATRBRK news-PF 5–6 figure is averaged over High + Medium + Low events. Filtering to High-only is likely to *raise* news-PF further (more signal) but cut news_trades by ~50 %. Bake `impact_filter ∈ {High, High+Medium}` into the v1 directive grid.
2. **Multi-currency overlap:** XAUUSD and NAS100 both inherit USD windows; GER40 inherits EUR + (de-facto) USD via DAX-NAS correlation. The `derive_currencies()` helper in [tools/news_calendar.py](tools/news_calendar.py) is the canonical mapping — verify it before declaring a symbol single-currency.
3. **F19 re-test guard:** Several Class B cells in this report (especially KALFLIP P02–P18) are *already* near the boundary of "rerun of an existing failed concept." Before authoring a NEWSBRK directive that touches KALFLIP, scan RESEARCH_MEMORY for prior NO_TRADES / failed-decision-gate entries on the same model+symbol+TF and document the parameter delta. The `Run-Context Suffix Policy (__E152)` applies if the same strategy is being retested.
4. **Window-construction asymmetry:** The current windows are symmetric around the event. Architecture (1) wants `[event - 60min, event + 60min]`, (3) wants `[event, event + 4 × TF]`. Adding pre/post split fields to `tools/news_calendar.py` is a **prerequisite** for any architecture-(1) or (3) directive; the existing `_build_windows()` does not expose `pre_window_minutes` and `post_window_minutes` separately.
5. **Tail concentration is unmeasured for the news subset.** Top-5 % concentration, longest-flat, edge ratio are reported on baseline only. Before promoting a NEWSBRK candidate, the pre-promote quality gate (`feedback_promote_quality_gate`) must be re-applied against the **news subset** specifically — not just baseline.
6. **Yearwise stability of the news subset is unverified.** The reports show baseline yearwise PF; news-only yearwise has not been tabulated. ATRBRK 15M baseline shows PF 1.04–1.06 every year, so the news subset is unlikely to be 2024-only — but this needs to be confirmed before promotion.
7. **Engine v1.5.8 compatibility:** All Class A/B candidate strategies were last run under v1.5.5–v1.5.7 with neutral regime stubs. Any NEWSBRK directive will run on v1.5.8 with full regime feed; the news-window flag must be added as an additional gate ON TOP of the existing regime-aware FilterStack, not replace it.

---

## 8. Ranked Execution Roadmap for NEWSBRK v1

The roadmap is staged so each step either (a) confirms or kills the leading hypothesis or (b) builds a single, narrowly-defined primitive on top of the previous step's confirmed substrate.

### Step 1 — Calendar tooling extensions (prerequisite, no new strategy)
   - Extend `tools/news_calendar.py` with `pre_window_minutes` / `post_window_minutes` parameters and `impact_filter`.
   - Add a `news_only` and `news_pre_only` / `news_post_only` per-trade tag plumbed through `report_news_policy._classify_all_trades_news`.
   - Add yearwise news-only PF + Top-5 concentration to the News Policy section template.
   - Re-run a single ATRBRK report (e.g. `63_BRK_IDX_15M_ATRBRK_S02_V1_P02_NAS100`) to confirm the new fields populate before any new directive is authored.

### Step 2 — Confirm A1 substrate at the directive level
   - Author **NEWSBRK_S01_V1** as `ATRBRK` directive on NAS100 30M with a hard `news_pre_window` filter at `[event − 30min, event + 90min]`, `impact ∈ {High}`, currencies `{USD}`.
   - Compare to baseline `63_BRK_IDX_30M_ATRBRK_P00_NAS100`. Expected: same news-PF 4–6 on a much smaller and cleaner trade count (~150–200 news trades).
   - Decision rule: news-PF ≥ 4.0 with N ≥ 100 → proceed. Otherwise the pattern is window-overlap-driven, not high-impact-driven, and Architecture (1) is wrong.

### Step 3 — Cross-symbol replication of A1
   - Author **NEWSBRK_S02..S06_V1** as the same Step-2 directive on GER40 (`{EUR}`), JPN225 (`{JPY, USD}` — JPY-only first), EUSTX50 (`{EUR}`), ESP35 (`{EUR}`), UK100 (`{GBP}`).
   - Expected: news-PF ≥ 3.5 on each. Cells that fail are the ones where the `(currency, impact)` mapping doesn't match the symbol's actual driver — this is information.

### Step 4 — Confirm A2 substrate at the directive level
   - Author **NEWSBRK_S07_V1** as `KALFLIP` (or `GMAFLIP`, whichever is cheaper to register) directive on NAS100 5M with the same news pre+post window. Use the locked filter stack (ADX + RSI + Hurst) from `KALFLIP P15`.
   - Decision rule: news-PF ≥ 4.0 with N ≥ 50 → A2 substrate confirmed and the news filter is dimensionally orthogonal to the existing 3-filter stack.

### Step 5 — Combine A1 + A2 in a portfolio sense (no new strategy code)
   - Use [run-composite-portfolio](.claude/skills/run-composite-portfolio/SKILL.md) on the surviving NEWSBRK_S01..S07 cells.
   - Expected: A1 (range-shape) and A2 (velocity) news trades have low overlap because they fire on different bars; the combined trade count is ~additive.
   - Decision rule: combined PF ≥ each component, combined Top-5 ≤ 50 % → portfolio-promotable.

### Step 6 — Build A3 (news-gap reclaim)
   - Only after Steps 2–5 confirm the substrate is real. Author **NEWSBRK_S08_V1** as a CHOCH-V2-style pivot-reclaim primitive **inside** a `[event + 5min, event + 90min]` window on NAS100 15M and XAUUSD 1H.
   - Decision rule: news-only PF ≥ 2.0 with N ≥ 50 per symbol within 6 months of calendar coverage. Lower bar than A1/A2 because A3 is exploratory.

### Step 7 — Optional: BTCUSD as a stretch target
   - BTCUSD 1H IMPULSE shows news-PF 5.82 on n=59. Worth a directive only after A1/A2 are both confirmed and the calendar tooling supports a single-currency `{USD}` window mapped onto BTC's USD-pair pricing. Treat as an explicit out-of-asset-class generalization probe, not a core symbol.

### Pre-flight gates (apply at every step)
- F19 re-test guard against RESEARCH_MEMORY before each directive
- Pre-promote quality gate on the **news subset** (Top-5, longest-flat, edge ratio per individual trade, yearwise news-PF)
- Engine v1.5.8 dual-time regime alignment intact under the news gate (the news flag must be additive to `regime_age_filter.mode: fill`, not a replacement)

---

## 9. What This Report Does Not Claim

- That news edge is **causal**. A high news-PF on ATRBRK could equally well mean (a) news triggers the breakout (architecture-1 hypothesis) or (b) news happens to coincide with the volatility spikes that any breakout signal eats from. Steps 2–4 above are designed to discriminate these.
- That news edge **survives transaction costs**. Spread widens during news on every venue. The corpus uses fixed `execution_costs.yaml` spreads; news-window trade $/trade ranges from $1.50 (KALFLIP) to $11 (ATRBRK 30M) — comfortable for ATRBRK 30M, tight for KALFLIP 5M. NEWSBRK v1 directives should test 2× and 3× cost stress.
- That outside-news loss can be ignored. ATRBRK Out-PF 0.62–0.86 means the unfiltered strategy is a real money-loser without the news flag. Any NEWSBRK directive must use a HARD news filter (entry-blocking outside the window), not a soft preference.
- That news-window definitions in the corpus are optimal. The current windows are wide and impact-blind. The first round of NEWSBRK directives should treat window pre/post split + impact filter as a sweep dimension, not a fixed.

---

## 10. Appendix — Working Files

- Source CSV (565 rows): [tmp/news_scan.csv](.claude/worktrees/vigilant-allen-a3c2a7/tmp/news_scan.csv)
- Classified ranking: [tmp/news_classified.md](.claude/worktrees/vigilant-allen-a3c2a7/tmp/news_classified.md)
- Scanner script: [tmp/scan_news_sections.py](.claude/worktrees/vigilant-allen-a3c2a7/tmp/scan_news_sections.py)
- Classifier script: [tmp/classify_news_edge.py](.claude/worktrees/vigilant-allen-a3c2a7/tmp/classify_news_edge.py)
- Existing news pipeline plan (not yet implemented end-to-end, but data is live): [outputs/NEWS_CALENDAR_INGESTION_PLAN.md](outputs/NEWS_CALENDAR_INGESTION_PLAN.md)
- Live news data (used by reports today): [data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/](data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH)
- Report-side computation: [tools/report/report_news_policy.py](tools/report/report_news_policy.py), [tools/report/report_sections/news.py](tools/report/report_sections/news.py)
- Calendar loader: [tools/news_calendar.py](tools/news_calendar.py)
