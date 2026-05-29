# Re-evaluation of two retired GBPJPY single-asset composites (PF_0C0C974A75F7, PF_548451C1675C)

**Date:** 2026-05-29
**Trigger:** During the 2026-05-29 pruner-breach cleanup, two `portfolio_sheet` (Single-Asset
Composites) rows with strong-looking metrics but no on-disk artifacts and no `portfolio.yaml`
deployment were retired from `ledger.db`. This note re-constructs them from their constituents
to decide whether the headline metrics (ret/dd 8.75 & 5.52; max_dd −0.19% & −0.20%; SQN 4.90 &
3.35) reflected a real, recoverable edge or an artifact.
**Method:** Read-only. Independent RAW pooled-equity reconstruction from the four constituents'
`results_tradelevel.csv` (still present in `TradeScan_State/{runs,sandbox}/`), plus a `ledger.db`
peer cross-check. **No ledger writes; the deleted rows were NOT re-appended** (the verdict is
do-not-promote, so re-running `portfolio_evaluator` would only re-pollute the just-cleaned ledger).

## Bottom line — ARTIFACT (composite quality masking). Do not promote either composite or the "shared core."

The exceptional headline was an artifact of **composite metrics masking individually weak
strategies** — the exact failure mode the Promote Quality Gate already guards. In fact
**`PF_0C0C974A75F7` is already the canonical worked example** of that gate
(`.claude/skills/promote/SKILL.md` §"Why this exists"; `11_deployment_and_burnin/PROMOTION_FRICTION_AUDIT.md`).
This re-evaluation independently re-derived that verdict from different metrics and confirms it
extends to its sibling `PF_548451C1675C`.

**The only genuine edge is the single strategy `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05`
(run `a25710978…`), which is ALREADY LIVE on GBPJPY** (`../TS_Execution/portfolio.yaml`) and
survives as its own CORE single-asset row (rank 2). Nothing recoverable that is not already deployed.

## Constituents (all GBPJPY, RSIAVG mean-reversion family — same symbol, same family)

| run_id | strategy | TF | trend filter | standalone MPS status | r/dd | SQN |
|---|---|---|---|---|---|---|
| `a25710978…` | S02_V1_P05 | 30m | ON (58.6% cov) | **CORE (rank 2) — LIVE** | 14.04 | 4.10 |
| `1bd2216f…` | S11_V1_P02 | 30m | OFF | **FAIL** (rank 36) | 3.14 | 2.42 |
| `b0527749…` | S12_V1_P01 | 1h | OFF | **FAIL** (rank 45) | 2.32 | 1.38 |
| `8fa54533…` | S02_V1_P03 | 30m | ON (60% cov) | no standalone row; **2024-2026 only** | 3.15 | 1.88 |

- `PF_0C0C974A75F7` = a25710978 + 1bd2216f + b0527749 (532 trades; 134+324+74 reconciles)
- `PF_548451C1675C` = 8fa54533 + 1bd2216f + b0527749 (374 trades; 166+134+74 reconciles)
- The **shared "core"** = the two **standalone-FAIL** legs (1bd2216f + b0527749).

## Evidence

**1. The headline ret/dd is INFERIOR to the star leg alone (same MPS column, apples-to-apples).**
Composite 8.75 (0C0C) / 5.52 (548451C) vs a25710978 standalone **14.04**. Bundling the CORE star
with two FAIL legs *diluted* risk-adjusted return. Sharpe agrees: star leg 5.97 standalone > 4.33
composite. The composite "wins" only on SQN (4.90 > 4.10), and SQN ∝ √trades — 532 vs 324 trades
fully accounts for it while per-trade edge actually fell. RAW reconstruction agrees: pooled ret/dd
**7.10 / 4.48**, below the star's RAW 14.04.

**2. The "tiny ~0.2% DD" is neither tiny-in-context nor a diversification effect.**
- Peer context: surviving single-asset **CORE** rows span max_dd_pct **−0.069% … −1.888%**. ~0.2%
  is mid-range and unremarkable — an artifact of the capital-model dd% convention for low-per-trade-
  risk FX strategies, not a special property of these composites.
- Relative to its OWN constituents (same metric): composite **−0.19/−0.20%** is *larger (worse)*
  than every leg standalone (a25 −0.069, 1bd −0.137, b05 −0.135). Combining them **increased** DD%.
- RAW confirms: pooled max DD **$24.13** > worst single leg **$15.34** ($15.34 b05 + $6.91 a25 +
  $13.69 1bd; sum $35.94). Pooled/worst-single = 1.57 → no absolute DD reduction; only a modest
  per-unit-capital reduction (~1.2% avg leg → 0.80% pooled on $3000 base).

**3. The "shared core anti-correlation" hypothesis is FALSE.**
Monthly-return correlation of the shared pair **1bd2216f vs b0527749 = +0.60** (positively
correlated; both no-filter GBPJPY). They produced **100% of the composite max drawdown in a single
day, 2022-04-28** (−$8.79 + −$15.34 = −$24.13), a correlated mean-reversion cluster loss into a
trending yen move. The only genuine (mild) hedge is the **trend-filter-ON** star leg a25710978,
which is −0.16/−0.15 correlated with the no-filter legs. In `PF_548451C`, 8fa54533's hedge is near
zero (+0.06/−0.08) and only exists from 2024 → that composite is strictly weaker.

**4. Sub-period / quality-gate stress (Promote Quality Gate).**
- `PF_0C0C`: 2023 effectively dead (net +1.88, retDD 0.16); 2024 carries 40% of net; longest flat
  218 days; pooled top-5 = 18.3% of net. Per-*component* top-5 concentration (from the existing
  promote-gate writeup): **96% and 51%** for the two FAIL legs.
- `PF_548451C`: **two consecutive losing years (2022 −7.25, 2023 −6.12)**; longest flat **852 days**
  (~2.3 yr underwater); pooled top-5 = **29.1%** of net. Would have been deeply unconvincing in real
  time through end-2023.

## Decision

- **Do NOT promote `PF_0C0C974A75F7` or `PF_548451C1675C`.** Composite masking; both inferior to
  their own best leg.
- **Do NOT promote the shared `1bd2216f`+`b0527749` core.** Both are standalone FAIL, +0.60
  correlated, and were the *source* of the max drawdown — the opposite of a diversifier.
- **No recovery needed.** The genuine edge (a25710978 = `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05`)
  is already LIVE on GBPJPY and CORE in the MPS. The DRY_RUN snapshots
  (`DRY_RUN_2026_04_09__1bd2216f`, `DRY_RUN_2026_04_09__b0527749`) are snapshots of the two
  standalone-FAIL legs and carry no incremental value.

## Why this should not be re-flagged

A future cleanup/triage pass may rediscover these two deleted rows (strong headline metrics) or the
two DRY_RUN snapshots and wonder if value was lost. It was not: the headline was a known
composite-masking pattern, the edge is already deployed, and the bundle's "extra" legs are FAILs
that *added* drawdown. The retirement during the 2026-05-29 pruner-breach cleanup was correct.

**Reconstruction script:** `tmp/composite_recon.py` (read-only; reproduces all RAW figures above).
**Related:** `.claude/skills/promote/SKILL.md` (Promote Quality Gate); this folder's
`QUARANTINE_JUSTIFICATION_AUDIT_2026_05_29.md` (the broader 2026-05-29 cleanup / pruner-breach context).
