# Phase 2 Path B — RSIAVG FX 15M EURUSD

**Date:** 2026-05-03
**Backtest analyzed:** `22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P03_EURUSD` (selected by discovery; 1,322 trades, 2024-01-01 → 2026-03-20)
**Method:** Post-hoc subset masks on existing trade-level CSV. Calendar = USD High-impact only (`derive_currencies('EURUSD')` returns `['EUR','USD']`; only USD events appear in this run's window).
**Gates (FROZEN, exploratory tier):** `N ≥ 40`, `trim_pf ≥ 1.10`, `expectancy > 0`, `news_pf ≥ outside_pf × 1.20`

---

## Headline

| subset | N | PF | trim_PF | PnL$ | expectancy | WR | PF 95 % CI |
|---|--:|--:|--:|--:|--:|--:|---|
| Baseline | 1,322 | 1.43 | 1.05 | +202.55 | $0.153 | 64.7 % | [1.24, 1.68] |
| **Full-window** | **54** | **2.78** | **1.76** | **+20.30** | **$0.376** | **70.4 %** | **[1.27, 7.63]** |
| Post-only | 27 | 1.65 | 1.04 | +5.08 | $0.188 | 63.0 % | [0.49, 5.93] |
| Pre-only | 27 | 5.26 | 4.23 | +15.22 | $0.564 | 77.8 % | [1.58, 66.38] |
| Outside | 1,268 | 1.40 | 1.03 | +182.25 | $0.144 | 64.4 % | [1.21, 1.63] |

Per-trade expectancy in news windows is **2.4×** the per-trade expectancy outside news ($0.376 vs $0.144). PF lifts from 1.43 → 2.78. Trim-PF lifts from 1.05 → 1.76 — the news edge is *not* tail-carried.

---

## Yearly stability

| year | Full-window | Post-only | Pre-only | Outside |
|---|---|---|---|---|
| 2024 | N=17 PF=6.02 | N=5 PF=22.58 | N=12 PF=3.31 | N=491 PF=1.34 |
| 2025 | N=29 PF=2.34 | N=17 **PF=0.92** | N=12 PF=6.63 | N=606 PF=1.45 |
| 2026 | N=8 PF=1.29 | N=5 PF=0.98 | N=3 PF=26.5 | N=171 PF=1.35 |

**Critical finding:** Post-only loses in 2025 (PF 0.92, N=17) and is flat in 2026 — the 2024 PF=22.58 was a 5-trade tail. Pre-only is stable across all three years (PF 3.31 / 6.63 / 26.5). The Full-window subset passes only because Pre-only carries Post-only's weakness.

This **inverts the conventional NEWSBRK assumption** — for this strategy, the edge is pre-event positioning, not post-event continuation.

---

## Gate verdict per sub-test

| Sub-test | N ≥ 40 | trim_pf ≥ 1.10 | expectancy > 0 | news ≥ 1.2× outside | **Verdict** |
|---|:-:|:-:|:-:|:-:|:-:|
| **Full-window** | ✓ (54) | ✓ (1.76) | ✓ ($0.38) | ✓ (2.78 vs 1.40) | **PASS** |
| Post-only | ✗ (27) | ✗ (1.04) | ✓ ($0.19) | ✗ (1.65 < 1.68) | FAIL |
| Pre-only | ✗ (27) | ✓ (4.23) | ✓ ($0.56) | ✓ (5.26 vs 1.40) | FAIL (N only) |

Pre-only fails **only on the sample-size gate**. Every other metric is the strongest in the table.

---

## Final: **EXPLORATORY-VALID — proceed to Path A**

1/3 sub-tests passes all four exploratory gates (Full-window). Pre-only would pass everything except sample size — it is **the most interesting structural finding in this Phase**. Post-only is genuinely weak under proper-year scrutiny.

Recommended path forward:

1. **Author Path A wrapper for the Full-window sub-test** as the primary causally-clean confirmation. If it survives at the same N+gates, this is the first intentionally-tradable news edge in the project.
2. **Run a Pre-only Path A sub-test as a secondary directive.** Restricted-trading may free up additional pre-event opportunities (the strategy is currently using up flat-state on outside trades). Sample could grow from 27 toward 40+ — and if it does, Pre-only on its own becomes the cleaner instrument.
3. **Drop Post-only.** Two of four gates fail; the apparent 2024 lift was a 5-trade tail. Not a viable subset.

Path A is the minimum work needed to convert Phase 2 Path B's directional result into a confirmed causal answer. No deployment until Path A confirms.

---

## Caveats

- **No execution-realism stress test yet.** All numbers assume the original backtest's spread/slippage model. The pre-event window is exactly when execution realism degrades most. Phase 3 (stressed execution) is mandatory before any live consideration; this Phase 2 result alone does not justify deployment.
- **Trim PF (top-5 % removed) for Full-window is 1.76** — the news edge is not tail-carried. This is the single most important number against the EVENT_CONCENTRATED bucket failure mode.
- **Outside subset PF is 1.40** — the strategy *does* have an outside-news edge, just at half the per-trade expectancy. A "block news" filter (the suppression direction) would *hurt* this strategy. The right operation is to *add* news-window emphasis, not to block it.
- **Post-only's 2024 PF of 22.58 from 5 trades** is a textbook tail-luck artefact. Useful reminder that Phase-1 discovery numbers can mask sub-period instability — this is exactly why Phase 2 yearly breakdown matters.

---

## Artifacts

- Analysis script: `tmp/rsiavg_phase2_pathb.py` (frozen-threshold constants in module header)
- Source backtest: `TradeScan_State/backtests/22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P03_EURUSD/`
- Anchor: `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
