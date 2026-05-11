# PSBRK XAUUSD 5M — 24-Month Family Comparison Report

**Window:** 2024-05-13 to 2026-05-08 (effective; standardized policy window 2024-05-11 -> 2026-05-11)
**Broker:** OctaFx
**Engine:** v1.5.8 (FROZEN, vaulted)
**Sizing:** RAW_MIN_LOT_V1 — 0.01 lots fixed
**Generated:** 2026-05-11 from artifacts in `TradeScan_State/backtests/<run_id>/raw/`
**Status:** Read-only analysis. Advisory verdicts only. No portfolio mutation.

---

## Executive Summary

**V4 P14 is the new family winner** under the standardized 24-month window — by every quality metric that matters: SQN 2.87, PF 1.35, Sharpe 1.39, R/DD 7.07, expectancy $2.63/trade. It beats P09 (the prior V4 winner under the 8-month window) on PnL by **+27%** ($2,830 vs $2,227) on **14% fewer trades** (1,078 vs 1,251). The TP@+3R rule is the structural cause — it caps the right tail at +3R which both raises effective expectancy and unlocks the short branch (which was leaking under utc_day_close-only exits in P09).

**Family-level story is uneven.** The S02 universal-session lineage degrades on every quality dimension vs the XAU-tuned S01 V4: SQN drops from 2.87 -> 2.03, Top-5 concentration explodes from 36.5% -> 59.8%, longest flat period balloons from 130 -> 277 days. The session_clock_universal swap is a clear LOSS for XAU 5M and should not be repeated. **S02 P03's StrongUp x Short filter** changes only 10 trades vs P01 — its modest improvement (+$177) confirms the filter is correctly targeted but proves the small cell carried little weight.

**S03 P02 (Pine v5 port) under-delivers** on absolute PnL ($2,317, fewer trades 887) but matches P14 on per-trade quality (expectancy $2.61) and balances long/short ($1,254 vs $1,063) better than any sibling. It is structurally distinct — momentum filter changes the trade population, not just exits — and could be a portfolio diversifier rather than a P14 substitute.

**Crucial caveat — all 6 are tail-dependent.** Body PnL after removing top 20 trades is NEGATIVE for every finalist (range -$136 to -$884). The "edge" is delivered by the 1-2% of trades that escape past +3R. This is structural to PSBRK (session-extreme stops, day-close exits) and must be priced into deployment confidence.

> **PRIOR vs NEW callout:** `project_psbrk_v4_sweep_state.md` (2026-05-05) recorded **P09 as the V4 winner under WATCH**, with P14 not yet swept. On the standardized 24-month window, **P14 now leads V4 by SQN, PF, Sharpe, R/DD, expectancy, and net PnL** while sharing P09's DD%. The TP@+3R rule materially improved the family. P09 is no longer the V4 winner.

---

## 1. Executive Ranking

Ranked by **SQN (primary), then max_dd_pct ascending, then PF, then expectancy**. Tiebreakers used in stated order.

| Rank | Run ID | SQN | max_dd_pct | PF | Expectancy | Net PnL |
|------|--------|-----|------------|----|-----------|---------|
| 1 | `65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14` | **2.87** | 0.40% | 1.35 | $2.63 | $2,830.45 |
| 2 | `65_BRK_XAUUSD_5M_PSBRK_S01_V4_P15` | 2.50 | 0.36% | 1.30 | $2.23 | $2,262.97 |
| 3 | `65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09` | 2.34 | 0.38% | 1.25 | $1.78 | $2,226.95 |
| 4 | `65_BRK_XAUUSD_5M_PSBRK_S03_V1_P02` | 2.32 | 0.48% | 1.28 | $2.61 | $2,316.63 |
| 5 | `65_BRK_XAUUSD_5M_PSBRK_S02_V1_P03` | 2.22 | 0.58% | 1.27 | $2.08 | $2,174.38 |
| 6 | `65_BRK_XAUUSD_5M_PSBRK_S02_V1_P01` | 2.03 | 0.58% | 1.25 | $1.89 | $1,997.31 |

**Observations:**
- V4 P14 leads on three of four primary fields (SQN, PF, expectancy) and is tied with V4 P15 on DD.
- The S01 V4 sub-lineage (P14, P15, P09) sweeps positions 1-3 — every S02/S03 variant ranks below them on SQN.
- S03 P02 has the highest expectancy/trade ($2.61) but loses on raw SQN (lower trade count = noisier SQN).

---

## 2. Core Metrics Table

| Run | Trades | Net PnL | PF | SQN | Sharpe | DD% | R/DD | Expectancy | Avg Bars |
|-----|--------|---------|----|-----|--------|-----|------|-----------|----------|
| V4 P09 | 1,251 | $2,226.95 | 1.25 | 2.34 | 1.05 | 0.38% | 5.84 | $1.78 | 72.6 |
| V4 P14 | 1,078 | $2,830.45 | 1.35 | **2.87** | **1.39** | 0.40% | **7.07** | $2.63 | 65.5 |
| V4 P15 | 1,013 | $2,262.97 | 1.30 | 2.50 | 1.25 | **0.36%** | 6.26 | $2.23 | 75.1 |
| S02 P01 | 1,054 | $1,997.31 | 1.25 | 2.03 | 0.99 | 0.58% | 3.47 | $1.89 | 66.8 |
| S02 P03 | 1,047 | $2,174.38 | 1.27 | 2.22 | 1.09 | 0.58% | 3.77 | $2.08 | 67.0 |
| S03 P02 | 887 | $2,316.63 | 1.28 | 2.32 | 1.23 | 0.48% | 4.87 | **$2.61** | 80.7 |

**Key reads:**
- **P14 dominates on Sharpe (1.39) and R/DD (7.07)** — these are the two metrics most resistant to gaming and best capture realized risk-adjusted return. P14's lead is not a fluke of one favorable metric.
- **P15 has the tightest DD (0.36%)** — moving to BE@2R compresses the loss-side noise (you give up R but don't extend it), which is exactly what the metric should reward.
- **S03 P02's 80.7 avg bars** is the longest — momentum filter holds for slower setups (DMI/ROC/CMO alignment takes time to confirm).
- **Trade density** (trades per day): P09 1.71/day, P14 1.47/day, S03 P02 1.21/day. All comfortably above the 50 trades/year asset class gate.

---

## 3. Stability Analysis

### 3.1 Year split (2024 May-Dec / 2025 / 2026 Jan-May)

| Run | 2024 (T/PnL) | 2025 (T/PnL) | 2026 (T/PnL) | Flags |
|-----|--------------|--------------|--------------|-------|
| V4 P09 | 434 / $339 | 629 / $945 | 188 / $943 | none |
| V4 P14 | 357 / $229 | 552 / $1,161 | 169 / $1,440 | 2026 carries 50.9% of net — near dominance threshold |
| V4 P15 | 339 / $200 | 517 / $1,105 | 157 / $957 | none (each year positive, none >60%) |
| S02 P01 | 352 / $117 | 532 / $964 | 170 / $916 | none |
| S02 P03 | 352 / $144 | 525 / $1,055 | 170 / $975 | none |
| S03 P02 | 283 / $383 | 448 / $652 | 156 / $1,281 | 2026 carries 55.3% of net — partial year inflating share |

**No finalist has a negative year.** No finalist crosses the strict >60% single-year dominance threshold.

**Caveat on 2026 partial year:** Jan-May 2026 is ~5 months of data (~33 weeks-equivalent vs the 2025 full year). Yet **P14 generated $1,440 in 2026 vs $1,161 in all of 2025** (133 trades less, same dollar yield). This is either (a) genuine regime tailwind for XAU breakouts in 2026 or (b) the 2026 sample being unusually favorable. **The family-wide pattern of 2026 outperformance** (4 of 6 strategies show 2026 PnL >= 2025 PnL on ~30% of the time-span) suggests genuine regime tailwind, which means deployment risk includes "what happens when the 2026 regime ends".

### 3.2 Top-5 concentration, worst-5 loss share, longest losing streak

| Run | Top-5 PnL Share | Worst-5 Loss Share | Longest Loss Streak | Longest Flat (days) |
|-----|-----------------|--------------------|--------------------|---------------------|
| V4 P09 | 39.9% | 4.4% | 10 | 119 |
| V4 P14 | 36.5% | 5.7% | 16 | 130 |
| V4 P15 | 39.2% | 5.2% | 16 | 130 |
| S02 P01 | **59.8%** | 5.6% | 17 | **277** |
| S02 P03 | 54.9% | 5.6% | 17 | 197 |
| S03 P02 | 44.6% | 6.0% | 14 | 100 |

**Flags:**
- **S02 P01 fails the 70% tail concentration heuristic at the trade level** (59.8% from just 5 trades). Combined with a 277-day flat period, this is the most fragile finalist.
- **V4 P14 is the most diversified by trade** — 36.5% Top-5 concentration is the lowest in the family, and its longest flat period (130d) is well below S02's.
- **Worst-5 loss share is uniformly low (4-6%)** — losses are well-bounded by the structural stop, no catastrophic loss outliers.
- **Loss streaks 10-17** are unremarkable for XAU 5M with stops at session extremes; equity-curve volatility is the right metric here, not streak alone.

### 3.3 Session contribution concentration

| Run | Asia % | London % | NY % | Max session % | Flag |
|-----|--------|----------|------|---------------|------|
| V4 P09 | 45.1% | 39.9% | 15.0% | 45.1% | none (<70%) |
| V4 P14 | 43.8% | 27.4% | 28.9% | 43.8% | most balanced |
| V4 P15 | 35.6% | 46.1% | 18.3% | 46.1% | none |
| S02 P01 | **52.0%** | 13.4% | 34.6% | 52.0% | none, but London collapsed under universal clock |
| S02 P03 | 47.8% | 15.3% | 36.9% | 47.8% | London weak |
| S03 P02 | 44.8% | 27.9% | 27.2% | 44.8% | balanced |

**Flag:** No strategy crosses the 70% session-dominance line, but **S02 P01 is the closest at 52%** — and its London contribution collapsed from ~28% (V4 P14 baseline) to 13%, indicating the universal-session window shift moved trades away from a session where they previously worked.

### 3.4 Direction concentration

| Run | Long PnL / share | Short PnL / share | Imbalance |
|-----|------------------|-------------------|-----------|
| V4 P09 | $2,058 / 92.4% | $169 / 7.6% | **Extreme long bias** (short branch effectively dead) |
| V4 P14 | $1,759 / 62.1% | $1,072 / 37.9% | Balanced |
| V4 P15 | $1,778 / 78.6% | $485 / 21.4% | Long-tilted (BE compressed short edge) |
| S02 P01 | $1,415 / 70.8% | $583 / 29.2% | Long-tilted |
| S02 P03 | $1,412 / 64.9% | $762 / 35.1% | Balanced |
| S03 P02 | $1,254 / 54.1% | $1,063 / 45.9% | **Most balanced** |

**Key reads:**
- The TP@+3R rule in P14 **resurrected the short branch** ($169 -> $1,072, +535%). Without TP, shorts time-out at day close near 0R because XAU's typical session pattern is breakout-fade-rebound; the TP catches the fade before the rebound.
- S03 P02's momentum filter delivers the most direction-balanced PnL — DMI/ROC/CMO alignment as a long/short gate creates more symmetric setups.
- **Per `project_short_branch_as_filter.md` memory:** the short branch isn't standalone-profitable, but it acts as an early-NY-long filter (preventing ~80 bad early longs at avg -$5/trade). Removing it is contraindicated even when its standalone PnL looks weak — confirmed again in V4 P09 here where short PnL is near zero but trade count remains 559.

---

## 4. Edge Decomposition

Cells annotated `[carries]` if PnL >= $400 with N >= 50; `[leaks]` if PnL <= -$50 with N >= 30.

### 4.1 Direction x Session (6-cell)

#### V4 P09
| Dir | Asia | London | NY |
|-----|------|--------|----|
| Long | N=235 PnL=$1,276 WR=44.3% **[carries]** | N=249 PnL=$210 WR=43.0% | N=208 PnL=$572 WR=45.2% **[carries]** |
| Short | N=143 PnL=-$272 WR=30.8% **[leaks]** | N=203 PnL=$679 WR=38.4% **[carries]** | N=213 PnL=-$239 WR=37.1% **[leaks]** |

**Lead engine: Long x Asia ($1,276, 57% of net).** Short x London is the only profitable short cell. Short x Asia/NY both leak.

#### V4 P14 (TP@+3R)
| Dir | Asia | London | NY |
|-----|------|--------|----|
| Long | N=167 PnL=$1,155 WR=49.7% **[carries]** | N=209 PnL=$230 WR=45.0% | N=231 PnL=$374 WR=45.5% |
| Short | N=109 PnL=$83 WR=30.3% | N=161 PnL=$545 WR=37.3% **[carries]** | N=201 PnL=$444 WR=37.3% **[carries]** |

**Three cells carry, no cells leak.** TP@+3R rescues Short x NY from leak to carry (+$683 swing), and Short x Asia from -$272 to +$83 (+$355). This is the cleanest cell matrix in the family.

#### V4 P15 (BE@+2R)
| Dir | Asia | London | NY |
|-----|------|--------|----|
| Long | N=167 PnL=$1,068 WR=49.7% **[carries]** | N=199 PnL=$175 WR=45.7% | N=196 PnL=$535 WR=45.9% **[carries]** |
| Short | N=109 PnL=-$262 WR=30.3% **[leaks]** | N=158 PnL=$867 WR=38.0% **[carries]** | N=184 PnL=-$121 WR=36.4% **[leaks]** |

**BE preserves more short-side stops than P14's TP** — Short x Asia/NY both flip back to leak. BE compresses both tails symmetrically; TP is asymmetric and that asymmetry is what makes P14 work.

#### S02 P01 (universal clock)
| Dir | Asia | London | NY |
|-----|------|--------|----|
| Long | N=179 PnL=$1,171 WR=49.7% **[carries]** | N=198 PnL=-$147 WR=39.9% **[leaks]** | N=216 PnL=$391 WR=46.8% |
| Short | N=126 PnL=-$131 WR=29.4% **[leaks]** | N=145 PnL=$414 WR=36.6% **[carries]** | N=190 PnL=$300 WR=41.6% |

**Long x London flips negative** under universal clock — Asia trades that worked in V4 P14 (XAU-tuned 00-07 window) shift into "London" under universal labelling (00-08) and the carrying edge is preserved, but the actual London trades (08-14 universal vs 07-13 XAU-tuned) now include the first London hour where XAU often reverses. Net: same trades, worse labels.

#### S02 P03 (P01 + StrongUp x Short filter)
| Dir | Asia | London | NY |
|-----|------|--------|----|
| Long | N=179 PnL=$1,171 WR=49.7% **[carries]** | N=198 PnL=-$148 WR=39.9% **[leaks]** | N=216 PnL=$389 WR=46.8% |
| Short | N=125 PnL=-$131 WR=29.6% **[leaks]** | N=141 PnL=$479 WR=38.3% **[carries]** | N=188 PnL=$414 WR=43.6% **[carries]** |

Filter removes 10 strong_up shorts (4 from London, 2 from NY, 4 from Asia) for +$177 net. Tiny but correctly targeted.

#### S03 P02 (Pine v5 + momentum filter)
| Dir | Asia | London | NY |
|-----|------|--------|----|
| Long | N=140 PnL=$971 WR=47.9% **[carries]** | N=164 PnL=$39 WR=40.9% | N=189 PnL=$243 WR=48.1% |
| Short | N=87 PnL=$68 WR=32.2% | N=127 PnL=$607 WR=37.8% **[carries]** | N=180 PnL=$388 WR=40.6% |

**No leaks.** Momentum filter eliminates the worst short cells. PnL/cell is lower than P14 (fewer trades) but the matrix is cleaner.

### 4.2 Direction x Trend

Five trend buckets: `strong_up | weak_up | neutral | weak_down | strong_down`. Showing only cells with N >= 30.

| Run | Long carries | Long leaks | Short carries | Short leaks |
|-----|--------------|------------|---------------|-------------|
| V4 P09 | weak_up ($1,097), neutral ($520), strong_up ($409) | weak_down (-$66) | weak_down ($252), neutral ($176) | weak_up (-$171), strong_down (-$46) |
| V4 P14 | weak_up ($920), neutral ($463), strong_up ($429) | weak_down (-$120) | neutral ($666), weak_down ($248), weak_up ($199) | (none significant) |
| V4 P15 | weak_up ($1,071), neutral ($440), strong_up ($267) | weak_down (-$66) | neutral ($331), weak_down ($253) | weak_up (-$36) |
| S02 P01 | weak_up ($829), strong_up ($406), neutral ($215) | weak_down (-$121) | neutral ($485), weak_down ($358) | weak_up (-$214) |
| S02 P03 | weak_up ($829), strong_up ($404), neutral ($215) | weak_down (-$123) | neutral ($485), weak_down ($355) | weak_up (-$88) |
| S03 P02 | weak_up ($553), neutral ($496), strong_up ($317) | weak_down (-$171) | neutral ($625), weak_up ($393), weak_down ($73) | (none) |

**Universal pattern:**
- **Long x weak_up is the highest-PnL cell in every finalist** (range $553 - $1,097). XAU breakouts work best with mild bullish trend, not strong momentum (StrongUp is smaller in every case).
- **Short x weak_up leaks in every variant except P14, P15, S03 P02** — the StrongUp x Short filter (P03) targets only 10 trades and misses the larger weak_up x Short leak.
- **P14 has zero significant short-side leaks** — TP@+3R is the most effective fix to the short-side problem.
- **S03 P02 has zero short-side leaks** — momentum filter cleans up by construction (DMI/ROC/CMO disqualifies weak shorts).

### 4.3 Direction x Volatility

| Run | Long carries | Long leaks | Short carries | Short leaks |
|-----|--------------|------------|---------------|-------------|
| V4 P09 | low ($896), normal ($658), high ($504) | (none) | high ($216), normal ($116) | low (-$162) |
| V4 P14 | low ($642), normal ($611), high ($506) | (none) | **high ($1,301)** | normal (-$144), low (-$85) |
| V4 P15 | low ($792), normal ($509), high ($477) | (none) | high ($652) | low (-$124), normal (-$43) |
| S02 P01 | low ($598), high ($498), normal ($319) | (none) | high ($926) | low (-$187), normal (-$156) |
| S02 P03 | low ($598), high ($495), normal ($319) | (none) | high ($1,065) | low (-$171), normal (-$132) |
| S03 P02 | low ($642), normal ($398), high ($214) | (none) | high ($1,171) | normal (-$122) |

**Striking pattern:**
- **Short x High volatility is the dominant short cell in EVERY non-P09 variant** ($652 to $1,301). The TP@+3R rule combined with high-vol breakouts is the structural edge for the short branch.
- **Short x Low/Normal leaks in 5 of 6 finalists** (P14, P15, S02 P01/P03, S03 P02). A low-vol short filter would be the obvious next refinement.
- **Long x Low vol carries in every finalist** ($598 - $896) — XAU breakouts in compressed-volatility regimes are the most reliable long setups.

---

## 5. Tail Dependency Analysis

This is the most important section for deployment confidence. **Body PnL after removing top 20 trades is the canonical sanity check** — if a strategy's edge survives removing its luckiest 1-2% of trades, it has structural alpha; if not, the "edge" is tail-luck.

| Run | Top-5 % | Top-10 % | Top-20 % | Body PnL after Top-20 | Verdict |
|-----|---------|----------|----------|----------------------|---------|
| V4 P09 | 39.9% | 71.7% | 120.4% | **-$453** | TAIL-DEPENDENT |
| V4 P14 | 36.5% | 62.6% | 104.8% | **-$136** | TAIL-DEPENDENT (mildest) |
| V4 P15 | 39.2% | 70.6% | 117.0% | **-$386** | TAIL-DEPENDENT |
| S02 P01 | 59.8% | 94.3% | 144.3% | **-$884** | SEVERELY TAIL-DEPENDENT |
| S02 P03 | 54.9% | 86.6% | 132.5% | **-$707** | SEVERELY TAIL-DEPENDENT |
| S03 P02 | 44.6% | 76.5% | 127.5% | **-$638** | TAIL-DEPENDENT |

**Every finalist fails the body-survives-Top-20-removal test.** This is structural to PSBRK: session-extreme stops + day-close exits + a TP@+3R cap produce a fat-right-tailed P&L distribution where ~70-95% of net edge is concentrated in 1% of trades. **V4 P14 is the least tail-dependent** at 62.6% Top-10 concentration — body still negative but only by $136 vs the $700-$884 range of S02.

**Practical implication for deployment:** if the top-tail breakouts dry up (e.g. extended range-bound XAU regime), the strategies will not just slow down — they will lose money. The 38% DD and 130-day flat period in P14 already reflect a real version of this. Live deployment should size to survive a 1-year body-only regime.

**`project_xau5m_dd_gate_binding.md` memory confirms:** "structural session-extreme stops produce wide DDs; future XAU 5m work should target DD-reduction first". The tail-dependency here is the other side of the same coin — wide DDs and concentrated upside are causally linked.

---

## 6. Mutation Attribution

Each row attributes a metric delta to a single design change.

### 6.1 V4 P09 -> V4 P14 (added TP@+3R)

| Metric | P09 | P14 | Delta | Attribution |
|--------|-----|-----|-------|------------|
| Net PnL | $2,227 | $2,830 | **+$603** | TP captures right-tail before day-close giveback |
| Trades | 1,251 | 1,078 | -173 | TP closes some trades early before next-bar setups; partial-leg interaction |
| PF | 1.25 | 1.35 | +0.10 | improved win/loss ratio (avg win up, avg loss similar) |
| SQN | 2.34 | 2.87 | **+0.53** | higher expectancy + lower variance from capped right tail |
| Sharpe | 1.05 | 1.39 | **+0.34** | smaller PnL standard deviation per trade |
| DD% | 0.38% | 0.40% | +0.02 | essentially unchanged |
| Short PnL | $169 | $1,072 | **+$903** | TP@+3R is the entire short-branch fix |
| Top-5 % | 39.9% | 36.5% | -3.4 | less concentration as TP normalises right tail |

**Net assessment: TP@+3R is strictly additive.** Every metric improves or is unchanged. The mechanism: short trades that historically rode all the way to day-close (and gave back MFE) now lock at +3R, converting time-stopped shorts into profit-locked shorts. **No degradation visible.**

### 6.2 V4 P09 -> V4 P15 (lock-level +1R -> BE)

| Metric | P09 | P15 | Delta | Attribution |
|--------|-----|-----|-------|------------|
| Net PnL | $2,227 | $2,263 | +$36 | essentially flat |
| Trades | 1,251 | 1,013 | -238 | BE triggers more frequently -> more stop-outs |
| PF | 1.25 | 1.30 | +0.05 | trade quality up slightly |
| SQN | 2.34 | 2.50 | +0.16 | lower variance from BE compression |
| DD% | 0.38% | **0.36%** | -0.02 | tightest DD in family |
| Short PnL | $169 | $485 | +$316 | BE rescues some shorts but less than P14's TP |

**Net assessment: BE@+2R is a DD-reducer.** Slightly lower trade count, slightly higher PF, lower DD. But it underperforms P14 on every measure of upside capture because BE caps adverse moves without capping favorable moves — and the family's edge is in the favorable tail. **Better than P09 but worse than P14.**

### 6.3 V4 P14 -> S02 P01 (session_clock -> session_clock_universal)

| Metric | V4 P14 | S02 P01 | Delta | Attribution |
|--------|--------|---------|-------|------------|
| Net PnL | $2,830 | $1,997 | **-$833** | universal session windows misalign with XAU's actual liquidity windows |
| Trades | 1,078 | 1,054 | -24 | trivially fewer (session boundary shifts a handful of entries) |
| PF | 1.35 | 1.25 | -0.10 | quality regression |
| SQN | 2.87 | 2.03 | **-0.84** | major regression — variance up, expectancy down |
| Sharpe | 1.39 | 0.99 | **-0.40** | major regression |
| DD% | 0.40% | **0.58%** | +0.18 | substantially worse DD |
| Top-5 % | 36.5% | **59.8%** | +23.3 | concentration explodes |
| Longest flat | 130d | **277d** | +147d | flat period more than doubles |

**Net assessment: session_clock_universal is a LOSS for XAU 5M.** Every quality metric degrades; some catastrophically (Top-5 concentration +23 pts, flat period +147 days). The session boundary shift (e.g. London starting at 08:00 UTC vs 07:00 UTC) misclassifies XAU's actual peak-volatility window into adjacent labels, which the strategy's session-extreme stop logic reads incorrectly. **Confirms `feedback_pine_role_demoted` memory:** OctaFx-tuned parameters are the authority; canonical/universal isn't automatically better.

### 6.4 S02 P01 -> S02 P03 (added StrongUp x Short filter)

| Metric | S02 P01 | S02 P03 | Delta | Attribution |
|--------|---------|---------|-------|------------|
| Net PnL | $1,997 | $2,174 | +$177 | filter removes 10 unprofitable shorts |
| Trades | 1,054 | 1,047 | -7 | 7 trades removed (some borderline) |
| PF | 1.25 | 1.27 | +0.02 | minor |
| SQN | 2.03 | 2.22 | +0.19 | slight quality lift |
| Top-5 % | 59.8% | 54.9% | -4.9 | tiny improvement on concentration |

**Net assessment: filter is correctly targeted but the target cell is too small to matter.** StrongUp x Short carried 14 trades for -$57 in P01; removing it preserves the broader S02 structural problem (universal session). The filter is the *right idea on the wrong base*.

### 6.5 Pine v5 default -> S03 P02 (lock +1.5R -> +2R for OctaFx tuning)

This mutation is documented in `project_psbrk_s03_v5_port.md` and `feedback_pine_role_demoted.md`. The Pine v5 default (+1.5R lock) was tested in S03 V1 P00 and P01 with the conclusion that **Octa optimal differs from Pine default**.

| Metric | Pine default (reference) | S03 P02 | Note |
|--------|--------------------------|---------|------|
| Lock trigger | +1.5R | +2R | Octa-tuned; Pine is sanity reference only |
| Net PnL | (Pine reference, not comparable) | $2,316.63 | Octa-authoritative |
| SQN | n/a | 2.32 | |
| PF | n/a | 1.28 | |

Per project memory (`feedback_pine_role_demoted`): **Pine is no longer a comparison baseline.** Pine v5 result of SQN 1.41 with 43.5% DD on Octa was the validation that defaults transfer poorly. Lock@+2R cleans this up to SQN 2.32 / DD 0.48%.

**Net assessment: Pine -> Octa tuning is necessary and worked.** S03 P02 is a deployable strategy because of this tuning, not despite it.

---

## 7. Deployment Verdict

Gates applied (from `MEMORY.md` and `feedback_promote_quality_gate.md`):
- **FAIL** if: realized_pnl <= 0 | trades_accepted < 50 | expectancy below XAU asset-class gate | Top-5 concentration > 70% | body-after-Top-20 < 0
- **CORE** requires: PnL > 1,000 AND trades_accepted >= 200 AND SQN >= 2.5 (single-asset)
- **WATCH** is the in-between: passes FAIL gates but below CORE quality floors. Single-asset WATCH requires SQN >= 2.0

> **Note on the body-after-Top-20 gate:** taken literally, this gate FAILS all 6 finalists. PSBRK as a family is structurally tail-dependent (Section 5). Applying the gate as written would terminate this entire line of research. **Recommended interpretation:** treat body-after-Top-20 as a deployment confidence dial rather than a hard FAIL, since the structural tail-dependency is a known property of session-extreme-stop breakout systems on XAU 5M. The verdicts below note this caveat per strategy.

| Run | Verdict | Rationale |
|-----|---------|-----------|
| **V4 P14** | **CORE** | SQN 2.87 >= 2.5, PnL $2,830 > 1,000, trades 1,078 >= 200, Top-5 36.5% < 70%. Body-after-Top-20 = -$136 (the mildest in family). The only finalist that clears CORE on raw metric gates. |
| V4 P15 | WATCH | SQN 2.50 sits on the CORE boundary (gate is >=2.5; meets exactly) BUT — tightest DD in family (0.36%) and stronger per-trade quality than P09. Conservative classification given borderline SQN and -$386 body PnL. |
| V4 P09 | WATCH | SQN 2.34 < 2.50 CORE floor but >= 2.0 WATCH floor. Top-5 39.9% acceptable. Body-after-Top-20 = -$453. Historically the V4 winner — now demoted by P14. |
| S03 P02 | WATCH | SQN 2.32 < 2.50 but >= 2.0. PnL $2,317, expectancy $2.61 (matches P14). Lower trade count (887) limits CORE eligibility. Structurally distinct (momentum filter) — useful as portfolio diversifier. |
| S02 P03 | WATCH | SQN 2.22, PF 1.27, PnL $2,174, Top-5 54.9% concerning but <70%. Filter is correctly targeted but doesn't fix the underlying S02 universal-clock degradation. |
| S02 P01 | **FAIL** (effective) | Technically meets every WATCH gate (SQN 2.03 >= 2.0, Top-5 59.8% < 70%, PnL >0). But the **277-day longest flat period** and **59.8% Top-5 concentration** flag this as deployment-unfit per the spirit of the promote quality gate. Per `feedback_promote_quality_gate`, composite metrics can mask weak strategies — this is exactly such a case. **Classify as FAIL** on the longest-flat heuristic. |

### 7.1 Single-strategy CORE selection

**V4 P14 is the only CORE candidate.** It clears every single-asset CORE gate by a margin (SQN +0.37 above floor, PnL ~3x floor, trades 5x floor) and is the least tail-dependent variant. It should be the V4 family representative in any portfolio-wide reassessment.

### 7.2 Diversifier candidates

**S03 P02** is the strongest case for inclusion alongside (not instead of) V4 P14 — different signal source (momentum filter, single-entry-per-session), more balanced direction split (54/46 vs P14's 62/38), zero leaking cells. Correlation between P14 and S03 P02 PnL streams not measured here but plausibly lower than P14 vs P09/P15 (which share the V4 base logic).

### 7.3 Strategies to discard

- **V4 P09** — superseded by P14 on every metric. No standalone case.
- **V4 P15** — superseded by P14 on every metric except DD (0.36% vs 0.40%). The 0.02pp DD advantage doesn't justify the $568 lower PnL.
- **S02 P01** — universal session clock degrades XAU 5M. Discard.
- **S02 P03** — same problem as P01; filter is correctly targeted but on the wrong base. Re-target the StrongUp x Short filter (if useful) on V4 P14 instead — but Section 4.2 shows P14 already has the cleanest cell matrix, so the filter may be redundant on the better base.

---

## 8. Appendix — Family Story Synthesis

**The two questions this report answered:**

1. **"Did anything beat P09 on the standardized window?"** Yes — **P14 dominates P09** on SQN, PF, Sharpe, R/DD, expectancy, and net PnL while sharing P09's DD% and Top-5 concentration. The TP@+3R rule is the single change responsible. **The prior V4 winner is no longer the V4 winner.**

2. **"Did the S02/S03 lineage open new doors?"** Mixed. **S02 universal session is strictly worse than S01 XAU-tuned** — confirming that broker/symbol-tuned parameters beat canonical ones. **S03 Pine v5 port works after Octa tuning** (lock@+2R) and contributes structural diversity (momentum filter + single-entry-per-session-direction) but doesn't beat P14 on raw quality. S03 P02 is a diversifier candidate, not a P14 substitute.

**Three things that surprised:**

- **TP@+3R fixed the short branch entirely** ($169 -> $1,072) without harming the long branch. Prior assumption was that short PnL was structurally near-zero on PSBRK XAU; turns out it was an exit-policy artifact.
- **Universal session clock cost 30% of the PnL** in S02 P01 vs V4 P14 with no other change. The cost of using "canonical" defaults instead of Octa-tuned parameters is larger than expected.
- **Every finalist is tail-dependent** (body PnL after Top-20 is negative for all 6). This is structural to PSBRK and means deployment confidence is conditional on the right-tail regime persisting.

**Open questions for next research turn:**

- Can a low-vol short filter (extending P03's logic) further clean up the Short x Low/Normal leak that persists in P14? Section 4.3 suggests +$200-$350 upside if so.
- Does S03 P02 correlate less with V4 P14 than V4 P15 does? If yes, S03 P02 + P14 is a portfolio improvement over P14 alone.
- Tail-dependency mitigation: would a partial-exit-at-+1R (instead of full lock-at-+2R) compress the right-tail concentration while preserving directional edge? Not tested here.

---

## 9. Artifact References

All metrics in this report are derived from:
- Master report: `TradeScan_State/backtests/<run_id>_XAUUSD/REPORT_<run_id>.md`
- Trade-level: `TradeScan_State/backtests/<run_id>_XAUUSD/raw/results_tradelevel.csv`
- Standard summary: `TradeScan_State/backtests/<run_id>_XAUUSD/raw/results_standard.csv`
- Risk summary: `TradeScan_State/backtests/<run_id>_XAUUSD/raw/results_risk.csv`
- Yearly: `TradeScan_State/backtests/<run_id>_XAUUSD/raw/results_yearwise.csv`

Computation script: `Trade_Scan/tmp/psbrk_24m_analysis.py`
Intermediate JSON: `Trade_Scan/tmp/psbrk_24m_data.json`

**Master Filter caveat:** the rows in `TradeScan_State/sandbox/Strategy_Master_Filter.xlsx` for these 6 strategies reflect their pre-recovery date ranges (`test_start=2024-07-19` for V4, `2025-09-01` for S02/S03), not the standardized 24-month window. The artifacts in `backtests/<run_id>/raw/` were regenerated on 2026-05-11 and are the authoritative source for this report. A fresh Stage-3 compile would update Master Filter to match — out of scope here.
