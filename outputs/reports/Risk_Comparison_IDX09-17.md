# Risk Comparison: IDX09–17

**Report Date:** 2026-02-12

| ID | Description | Vol Filter | Time Exit |
|:---|:---|:---|:---|
| IDX09 | Baseline | ≤75 | 4 bars |
| IDX10 | Barbell | ≤60 OR ≥72 | 4 bars |
| IDX11 | No filter | None | 4 bars |
| IDX12 | Tight filter | ≤66 | 4 bars |
| IDX13 | Redundant filter | ≤75 & ≤90 | 4 bars |
| IDX14 | Shorter exit | ≤75 | **3 bars** |
| IDX15 | Longer exit | ≤75 | **5 bars** |
| IDX16 | Extended exit | ≤75 | **6 bars** |
| IDX17 | **Loose + 5-bar** | **≤85** | **5 bars** |

---

## Master Comparison Table

| Strategy | Net PnL | Sharpe | Return/DD | Max DD % | Avg Trade PnL | Trade Count |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **IDX09** (≤75, 4-bar) | $3,383 | **1.19** | 1.32 | **6.0%** | $1.67 | 2,028 |
| **IDX10** (Barbell, 4-bar) | $4,885 | 1.04 | 1.24 | 8.0% | $1.88 | 2,600 |
| **IDX11** (No filter, 4-bar) | **$5,042** | 1.04 | 1.38 | 8.3% | $1.78 | 2,825 |
| **IDX12** (≤66, 4-bar) | $3,005 | 1.20 | 1.10 | 6.2% | $1.64 | 1,833 |
| **IDX13** (≤75+≤90, 4-bar) | $3,383 | 1.19 | 1.32 | 6.0% | $1.67 | 2,028 |
| **IDX14** (≤75, **3-bar**) | $2,535 | 0.74 | 0.78 | 7.0% | $1.09 | 2,329 |
| **IDX15** (≤75, **5-bar**) | $3,570 | 1.17 | **1.46** | **6.0%** | $1.99 | 1,797 |
| **IDX16** (≤75, **6-bar**) | $3,494 | 1.12 | 1.14 | 7.0% | **$2.10** | 1,661 |
| **IDX17** (≤85, **5-bar**) | $3,537 | 0.91 | 1.25 | 7.0% | $1.78 | 1,984 |

---

## Winners by Category

| Category | Winner | Value | Runner-Up |
|:---|:---|---:|:---|
| **Net PnL** | IDX11 | $5,042 | IDX10 ($4,885) |
| **Sharpe** | IDX09 | 1.19 | IDX15 (1.17) |
| **Return/DD** | IDX15 | 1.46 | IDX11 (1.38) |
| **Lowest DD** | IDX09/15 | 6.0% | IDX12 (6.2%) |
| **Avg Trade PnL** | IDX16 | $2.10 | IDX15 ($1.99) |
| **Trade Count** | IDX11 | 2,825 | IDX10 (2,600) |

---

## Time Exit Analysis (IDX09 vs IDX14 vs IDX15 vs IDX16)

All use identical entry logic. IDX14-16 use ≤75 filter; IDX17 uses ≤85 filter.

| Metric | 3-bar (IDX14) | 4-bar (IDX09) | 5-bar (IDX15) | 6-bar (IDX16) | **5-bar ≤85 (IDX17)** |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **Net PnL** | $2,535 | $3,383 | **$3,570** | $3,494 | $3,537 |
| **Sharpe** | 0.74 | **1.19** | 1.17 | 1.12 | 0.91 |
| **Return/DD** | 0.78 | 1.32 | **1.46** | 1.14 | 1.25 |
| **Max DD %** | 7.0% | **6.0%** | **6.0%** | 7.0% | 7.0% |
| **Avg Trade PnL** | $1.09 | $1.67 | $1.99 | **$2.10** | $1.78 |
| **Win Rate** | 56% | 58% | 58% | **59%** | 58% |
| **Trade Count** | 2,329 | 2,028 | 1,797 | 1,661 | 1,984 |
| **K-Ratio** | 3.59 | **12.49** | 9.08 | 6.02 | **13.12** |
| **SQN** | 0.70 | **1.10** | 1.05 | 0.96 | 0.86 |
| **Sortino** | 0.68 | **1.04** | 1.01 | 0.93 | 0.74 |

### Key Findings:

1. **3-bar exit (IDX14) is clearly worst** — cuts trades too short, reducing PnL by 25% and Sharpe by 38%
2. **5-bar exit (IDX15) is the surprise winner** — best Return/DD (1.46), +6% more PnL than baseline, highest per-trade efficiency
3. **6-bar exit (IDX16) has diminishing returns** — per-trade PnL is best ($2.10) but fewer trades hurt total profit
4. **4-bar baseline (IDX09) has best Sharpe** (1.19) and K-Ratio (12.49), indicating smoothest equity curve

### Optimal Time Exit: **5 bars (IDX15)**

IDX15 is the overall winner when considering all factors:
- Matches IDX09 on Max DD (6.0%)
- **Best Return/DD ratio** (1.46 vs 1.32)
- +6% more PnL ($3,570 vs $3,383)
- Better per-trade efficiency ($1.99 vs $1.67)
- Competitive Sharpe (1.17 vs 1.19)

---

## Volatility Bucket Breakdown

| Strategy | Low Vol PnL | Normal Vol PnL | High Vol PnL | Net PnL |
| :--- | ---: | ---: | ---: | ---: |
| IDX09 (4-bar) | $2,871 | $3,528 | -$3,017 | $3,383 |
| IDX14 (3-bar) | $2,438 | $3,514 | -$3,416 | $2,535 |
| **IDX15 (5-bar)** | **$3,396** | **$4,150** | **-$3,976** | **$3,570** |
| IDX16 (6-bar) | $3,616 | $4,686 | -$4,808 | $3,494 |
| IDX17 (≤85, 5-bar) | $3,879 | $5,127 | -$5,470 | $3,537 |

**Insight:** Longer exits make more in Low/Normal vol but lose more in High vol. IDX15 strikes the best balance.

---

## Final Rankings

### Overall (balanced scoring):
1. 🥇 **IDX15** (≤75, 5-bar) — Best Return/DD (1.46), low DD (6.0%), strong PnL
2. 🥈 **IDX11** (No filter, 4-bar) — Maximum absolute profit ($5,042)
3. 🥉 **IDX09** (≤75, 4-bar) — Best Sharpe (1.19), lowest DD (6.0%)
4. **IDX17** (≤85, 5-bar) — Good K-Ratio (13.12), but Sharpe drops to 0.91
5. **IDX16** (≤75, 6-bar) — Best per-trade PnL ($2.10) but diminishing returns
6. **IDX10** (Barbell) — High PnL but worst risk-adjusted
7. **IDX12** (≤66) — Over-filtered
8. **IDX14** (3-bar) — Too aggressive, worst performer

### IDX17 Verdict:
Loosening the filter from ≤75 to ≤85 with 5-bar exit **did NOT improve results** over IDX15:
- PnL similar ($3,537 vs $3,570) but Sharpe much worse (0.91 vs 1.17)
- Higher DD (7.0% vs 6.0%) with no extra profit
- High-vol losses jump to -$5,470 (worst of all time-exit variants)

### Recommendation:
**IDX15 remains the overall champion.** The ≤75 filter + 5-bar exit is the optimal configuration.
Future tests should explore position sizing or stop-loss mechanisms.
