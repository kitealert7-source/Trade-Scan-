# H2 Second-Sleeve Challenge -- 2026-05-16

**Question:** Does B1 have any better second sleeve than B2?
**Verdict:** **No. B2 stays.** None of EUR+CAD, GBP+CAD, or AUD+CHF beats B2 as B1's companion under corrected (1.3.0-basket parquet) telemetry.
**Provisional live champion locked: B1+B2.**

Full report: [outputs/harvest_robustness/REPORT_sleeve_challenge_2026_05_16_20260516_131412.md](harvest_robustness/REPORT_sleeve_challenge_2026_05_16_20260516_131412.md)

---

## Headline -- B1 + second-sleeve candidates ranked by ROC

| Rank | Composite | Net PnL | Comp DD | DD%stake | CapDiv | **ROCDiv** |
|---|---|---|---|---|---|---|
| **1** | **B1+B2** (champion) | $1,600 | $464 | 23.21% | $928 | **172.4%** |
| 2 | B1+AJ (legacy) | $2,009 | $632 | 31.59% | $1,264 | 159.0% |
| 3 | B1+GC (GBP+CAD) | $1,427 | $699 | 34.93% | $1,397 | 102.1% |
| 4 | B1+EC (EUR+CAD) | $1,081 | $533 | 26.66% | $1,067 | 101.4% |
| 5 | B1+AC (AUD+CHF) | $1,297 | $658 | 32.88% | $1,315 | 98.6% |

B2 wins by **13.4 percentage points of ROC** over the next-best challenger (AJ, which is the prior incumbent now demoted to "legacy choice"). All three new sleeve candidates (EC, GC, AC) cluster around 100% ROC -- materially worse than B1+B2 by 70 percentage points of ROC.

---

## Per-basket profile under corrected telemetry

| Basket | Pair | Net PnL | Net PnL% | Peak DD | DD% | DDx | ROC | Worst-bar ts |
|---|---|---|---|---|---|---|---|---|
| **B1** | EUR+JPY | $1,007 | +100.7% | $325 | 32.51% | 0.33x | 154.9% | 2025-02-10 00:05 |
| **B2** | AUD+CAD | $593 | +59.3% | $331 | 33.10% | 0.33x | 89.6% | 2025-04-09 03:15 |
| AJ | AUD+JPY | $1,002 | +100.2% | $599 | 59.95% | 0.60x | 83.6% | 2025-04-09 03:15 |
| GC | GBP+CAD | $420 | +42.0% | $520 | 51.99% | 0.52x | 40.4% | 2026-03-09 06:55 |
| AC | AUD+CHF | $290 | +29.0% | $635 | 63.51% | 0.64x | 22.8% | 2025-04-09 03:15 |
| EC | EUR+CAD | $74 | +7.4% | $533 | 53.33% | 0.53x | 6.9% | 2026-03-09 13:30 |

Of the new sleeve candidates, **none harvested** (all "no exit" -- basket still open at end-of-data window 2026-05-09). They show modest realized PnL with significant intra-bar DD. EC is essentially flat (+7.4% PnL, 53% DD) -- not a viable sleeve. GC has the best PnL among new sleeves but still half of B2's PnL with 1.6x B2's DD.

---

## Diversification analysis -- worst-bar timestamp clustering

| Basket | Worst-bar | Date | Session/Window |
|---|---|---|---|
| B1 | 2025-02-10 00:05 | Feb 10 2025 | Asia overnight |
| B2 | 2025-04-09 03:15 | Apr 9 2025 | Asia liquidity gap |
| AJ | 2025-04-09 03:15 | Apr 9 2025 | **same as B2 + AC** |
| AC | 2025-04-09 03:15 | Apr 9 2025 | **same as B2 + AJ** |
| GC | 2026-03-09 06:55 | Mar 9 2026 | London open |
| EC | 2026-03-09 13:30 | Mar 9 2026 | **same date as GC, ~6 hours apart** |

**B1 is the unique diversifier.** Its worst-bar (Feb 2025) is alone in time. Every other basket clusters into two correlated tail dates:
- Apr 9 2025 03:15 UTC (Asia gap) -- hits AJ, B2, AC simultaneously
- Mar 9 2026 (London session) -- hits EC + GC same day

This explains the diversification ratios:
- B1+B2: 70.7% diversification (composite DD = 70.7% of sum-of-singles)
- B2+AJ: **99.9%** diversification -- ZERO (same worst-bar)
- EC+GC: would also synchronize on Mar 9 2026 (same date)

Pairing B1 with anything gives some diversification because B1's tail is uniquely-timed. But B2 contributes the most PnL of any non-B1 basket while still diversifying B1's tail.

---

## What about the 3-basket B1+B2+EC option?

A close-second worth noting: **B1+B2+EC at 137.9% ROC and 20.23% DD%** has the LOWEST DD% in the entire table. EC's contribution diversifies the tail further but adds only $74 PnL -- not worth the 35 ROC-points drop from B1+B2.

If capital-safety overrode return-maximization (e.g., a hard 25% DD-cap), B1+B2+EC would be preferred. With the current "stake + 2x DD" capital rule, B1+B2 wins on ROC.

---

## Updated provisional posture (locked)

**Deploy B1+B2 as the primary live composite.**

| Parameter | Value |
|---|---|
| Stake (nominal) | $2,000 ($1,000 per basket) |
| Capital required (CapDiv) | $928 |
| Capital required (CapSum, conservative) | $1,312 |
| Expected net PnL per cycle | $1,600 (+80% of stake) |
| Composite Max DD | $464 (23.21% of stake) |
| ROC (diversification-aware) | 172.4% |
| ROC (conservative naive) | 121.9% |
| Worst-bar synchronization risk | LOW (B1 and B2 worst-bars are 58 days apart) |
| Margin-call distance (min margin level) | >4,800% (basket equity >48x margin used at worst bar) |

**Next steps (not in scope today):**
- If operator wants to scale beyond 1x B1+B2: the 3-basket extension is **B1+B2+EC** (lowest DD%) or **E1 = B1+B2+AJ** (highest 3-basket ROC at 136.7%, but AJ's correlated-tail risk is real). Both are inferior to B1+B2 on capital efficiency.
- AJ remains in the dataset as a "high-PnL high-risk" outlier candidate -- could be useful in a future 4+-basket portfolio with an Asia-uncorrelated leg, but not as a primary deploy candidate.
- No further sleeves to re-run: the 3 best non-AJ S08 candidates per realized PnL (EC, GC, AC) have all been processed. The remaining S08 sleeves (P01 GBP+JPY, P02 NZD+JPY, P05 NZD+CAD, P06 EUR+CHF, P08 GBP+CHF, P09 NZD+CHF) had inferior realized PnL or known tail problems (GBP+JPY's 20% realized DD already disqualifies it from "low-DD second sleeve" consideration).

---

## Test suite + telemetry posture

- Suite refactor (commit `1deb177`) is parquet-only end-to-end.
- Sleeve re-run produced 3 new parquet ledgers + 3 new MPS Baskets rows under 1.3.0-basket schema.
- Suite runtime on 6-basket set: **~36 seconds for all 5 sections** (intrabar 2.6s, composite 15.6s on 35 combinations, deployment 16.1s, others trivial). Acceptable; main cost is C(N,2)+C(N,3) enumeration in composite + deployment posture.
- All composite and deployment metrics computed from `equity_total_usd` parquet column -- no reload+replay anywhere.

---

**Provisional champion locked: B1+B2.** Next: standby for new discovery direction.
