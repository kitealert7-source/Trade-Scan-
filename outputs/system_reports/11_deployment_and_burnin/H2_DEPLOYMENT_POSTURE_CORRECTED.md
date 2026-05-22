# H2 Deployment Posture — Corrected (Post-Emitter)

**Status:** Complete. Refactored `tools/harvest_robustness/` consumes parquet ledger only. Champions B1/AJ/B2 re-analyzed under the spec-correct emitter.
**Date:** 2026-05-16
**Full report:** [outputs/harvest_robustness/REPORT_champions_post_emitter_2026_05_16_20260516_130420.md](harvest_robustness/REPORT_champions_post_emitter_2026_05_16_20260516_130420.md)
**Reference:** [H2_TELEMETRY_PARITY_FORENSIC.md](H2_TELEMETRY_PARITY_FORENSIC.md), [H2_TELEMETRY_EMITTER_VALIDATION.md](H2_TELEMETRY_EMITTER_VALIDATION.md)

---

## Headline — corrected ranking changes the deployment call

| Rank | Composite | ROC (CapDiv) | DD%stake | Net PnL | Cap required |
|---|---|---|---|---|---|
| **1** | **B1+B2** | **172.4%** | **23.21%** | $1,600 | **$928** |
| 2 | B1+AJ | 159.0% | 31.59% | $2,009 | $1,264 |
| 3 | B1 alone | 154.9% | 32.51% | $1,007 | $650 |
| 4 | E1 (B1+B2+AJ) | 136.7% | 31.73% | $2,602 | $1,904 |
| 5 | B2 alone | 89.6% | 33.10% | $593 | $662 |
| 6 | AJ+B2 | 85.8% | 46.46% | $1,595 | $1,858 |
| 7 | AJ alone | 83.6% | 59.95% | $1,002 | $1,199 |

**Decision shift: B1+B2 dominates B1+AJ on every operator-facing axis.** Previously, research notes (RESEARCH/FX_BASKET_RECYCLE_RESEARCH.md §3.6/§3.7) treated E1 (= B1+AJ+B2) as the headline composite. The corrected analysis shows **AJ is capital-inefficient** — it has the highest DD%, the lowest single-basket ROC, and dragging it into composites worsens (rather than improves) capital efficiency.

---

## Operator question #1 — did capital numbers shrink materially?

**Mixed direction, not uniform.** The legacy module's bugs cut both ways:

| Basket | Legacy (h2_intrabar_floating_dd OLD) | Emitter (1.3.0-basket parquet) | Δ vs legacy |
|---|---|---|---|
| **B1** EUR+JPY | $495 (49.5% of stake) | **$325 (32.5%)** | **−34%** ⬇ |
| **AJ** AUD+JPY | $529 (52.9%) | **$599 (60.0%)** | **+13%** ⬆ |
| **B2** AUD+CAD | $342 (34.2%) | **$331 (33.1%)** | −3% ≈ |

**B1 shrank substantially** ($170 less DD = $340 less real capital required at the 2× rule). **AJ went the OTHER way** — the legacy reconstruction was actually UNDER-counting AJ's DD. The naive assumption "legacy always overstates" is wrong; the bugs interact with lot-growth trajectory and worst-bar timing in directionally-mixed ways. AJ's actual DD is materially worse than research notes claimed.

The corrected ranking of single-basket DD severity: **AJ ($600) > B2 ($331) > B1 ($325)** — AJ is the highest-risk single basket, almost 2× the DD of B1 or B2.

---

## Operator question #2 — composite interaction: B1+AJ vs B1+B2?

**B1+B2 wins on every metric.**

| Metric | B1+B2 | B1+AJ | Winner |
|---|---|---|---|
| Composite Max DD | $464 | $632 | B1+B2 |
| DD% of stake | 23.21% | 31.59% | B1+B2 |
| Net PnL | $1,600 | $2,009 | B1+AJ (absolute) |
| Capital required (CapDiv) | $928 | $1,264 | B1+B2 |
| **ROC (return / capital)** | **172.4%** | 159.0% | **B1+B2** |
| Diversification (composite DD ÷ Σsingles) | 70.7% | 68.3% | tied (~70%) |
| Worst-bar synchronization risk | low | AJ & B2 share Asia-03:15 worst bar | B1+B2 better |

**Diversification quality** (composite DD as fraction of sum-of-singles DD):
- B1+B2: 70.7% — strong (29% diversification credit)
- B1+AJ: 68.3% — strong (32% diversification credit)
- B2+AJ: 99.9% — **NO diversification** (AJ and B2 worst-bars are on the same timestamp)
- E1 (B1+B2+AJ): 75.8% — decent (24% credit)

The B2+AJ composite shows ZERO diversification because both baskets hit their worst-DD bar at the same moment (2025-04-09 03:15:00 — Asia-session liquidity gap). Adding AJ to anything brings that synchronized-tail risk.

**B1+AJ has higher absolute PnL ($2009 vs $1600) but at a 36% higher capital cost.** Capital efficiency favors B1+B2.

---

## Operator question #3 — real deployment posture

### Per-basket — capital required for live deployment

| Basket | Stake | Net PnL | Peak DD | Peak Margin | MinML% | Peak Lot | Real Cap | DD× | ROC% |
|---|---|---|---|---|---|---|---|---|---|
| B1 EUR+JPY | $1,000 | $1,007 | $325 | $34.86 | 5,196% | 0.160 | **$650** | 0.33× | **154.9%** |
| AJ AUD+JPY | $1,000 | $1,002 | $599 | $38.66 | 4,853% | 0.260 | **$1,199** | 0.60× | 83.6% |
| B2 AUD+CAD | $1,000 | $593 | $331 | $26.72 | 5,408% | 0.180 | **$662** | 0.33× | 89.6% |

**Real capital = max(peak_margin, 2 × peak_floating_DD)** per FX_BASKET_RECYCLE_RESEARCH §4.15. For all three baskets, 2× DD dominates margin by 10–30×, so the DD term is the binding constraint. Margin call distance (MinML%) is comfortable in all three — the broker margin level stays >4,800% (i.e., basket equity is >48× margin used at the worst bar). The DD-budget rule, not the broker margin, is what determines deployment sizing.

**Peak lot per leg** — operator can read this as "the biggest single-leg lot the basket grew to at any point in the cycle." Helpful for understanding the position-size profile during late-cycle drawdowns.

### Composite — capital sizing for parallel deployment

Two views: **CapSum** = naive sum of per-basket real capitals (no diversification credit) vs **CapDiv** = diversification-aware total real capital.

| Composite | N | Net PnL | Comp DD | DD% | CapSum | CapDiv | ROC Sum | ROC Div |
|---|---|---|---|---|---|---|---|---|
| **B1+B2** | 2 | $1,600 | $464 | 23.21% | $1,312 | **$928** | 121.9% | **172.4%** |
| B1+AJ | 2 | $2,009 | $632 | 31.59% | $1,849 | $1,264 | 108.7% | 159.0% |
| E1 B1+B2+AJ | 3 | $2,602 | $952 | 31.73% | $2,511 | $1,904 | 103.6% | 136.7% |
| AJ+B2 | 2 | $1,595 | $929 | 46.46% | $1,861 | $1,858 | 85.7% | 85.8% |

**B1+B2 is the deployment sweet spot.** Lowest capital ask, lowest DD%, highest ROC. The diversification credit is largest in absolute terms here too: CapSum $1,312 → CapDiv $928, saving $384 (29% capital reduction).

---

## Updated recommendation

1. **Deploy B1+B2 as the primary composite.** $928 deployed capital → +$1,600 expected PnL → 172.4% ROC over the basket cycle. DD-budget 23.21% (≈$232 worst floating loss on $1,000 stake-per-basket).

2. **Drop AJ as a standalone candidate.** Its corrected 60% DD is too high; the worst-bar synchronizes with B2's worst-bar (Asia 03:15 UTC) so adding it provides zero diversification on the JPY/CAD side. AJ may still be useful in a 4+ basket portfolio if a leg uncorrelated from Asia-session moves can be found, but on the current champion set it underperforms.

3. **E1 (B1+B2+AJ) is the next-best 3-basket option** if scale is desired — $1,904 capital → $2,602 PnL → 136.7% ROC — but the marginal AJ contribution costs 36% more capital for 63% more PnL, which is worse on the margin than just running B1+B2 twice (if the operator could re-allocate the same dollar across two B1+B2-equivalent positions).

4. **Re-run additional champions** to expand the composite-candidate set: the harvest_robustness suite now requires a 1.3.0-basket parquet on disk for any basket to be analyzed. Pre-emitter baskets (S08_P01-P09 = GBP+JPY, NZD+JPY, EUR+CAD, GBP+CAD, NZD+CAD, EUR+CHF, AUD+CHF, GBP+CHF, NZD+CHF) need to be re-run through the pipeline before they can enter ranking.

5. **Past research notes** citing the legacy module's DD numbers — especially in `RESEARCH/FX_BASKET_RECYCLE_RESEARCH.md` §3.7, §4.13, §4.15 — are inflated for B1 (by 52%) and B2 (by 3%), but **understate AJ** (by 12%). Future analyses must use the parquet ledger directly.

---

## What changed in the suite (refactor summary)

| Module | Before | After |
|---|---|---|
| `h2_intrabar_floating_dd.py` | Reload+replay from events.jsonl + 5m OHLC (~7s/basket, buggy) | Parquet read of `equity_total_usd` column (~0.5s/basket, spec-correct) |
| `h2_harvesters_composite_analysis.py` | Tradelevel CSV + realized equity | Parquet `equity_total_usd` composite sum; ranking by PnL/DD and DD%stake |
| `h2_floating_dd_at_events.py` | recycle_events.jsonl floating snapshots | Parquet filtered on `recycle_executed=True`; new "between-event gap" metric |
| `h2_s08_results_extract.py` | results_tradelevel.csv only | Adds `intraDD` column from parquet when present |
| `h2_deployment_posture.py` | (NEW) | Real capital, margin buffer, DD multiple, ROC — per-basket + composite |
| `sections.yaml` | 4 sections, legacy semantics | 5 sections, parquet-only, new "Deployment Posture" headline section |

Suite runtime: **8.5s for 5 sections** (vs ~70s for legacy reload+replay on the old 4 sections). Per-basket and composite analyses now return in well under a second — analytics are no longer bottlenecked on bar-replay.

**Modules can now run on any basket with a 1.3.0-basket parquet ledger on disk.** Pre-1.3.0 baskets appear as "SKIP — no parquet" and must be re-run before inclusion.
