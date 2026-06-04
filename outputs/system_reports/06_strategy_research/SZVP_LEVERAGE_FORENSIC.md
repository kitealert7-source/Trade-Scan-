# SZVP Leverage Forensic + Engine No-Liquidation Finding

**Date:** 2026-06-04   **Status:** CLOSED (research artifact archived; finding recorded)
**Scope:** the 14 `COINTREV_V3_L30_SZVP` runs (vol-parity sizing arm of the halted sizing experiment) and the engine-fidelity issue they exposed.
**Constraint honoured:** read-only forensic; the FROZEN `v1_5_8` engine was NOT modified; no run-halting logic introduced; no production research re-run.

---

## Executive summary

The SZVP runs' extreme metrics (net to **+5,299%**, final_equity to **$53,992**, ret/dd to **144.6**) are a **leverage artifact**, not trading edge and not compounding. SZVP is the *vol-parity* sizer: `lot = $1,000 target_risk / (ATR x usd_per_pu)`, **uncapped**. On low-relative-ATR instruments (indices, JPY crosses) it inflates lots to **15-712** (vs notional sizing's 0.01-0.07) -> position notional **$1.7M-$6.2M on a $1,000 stake (~1,700-6,200x leverage)**. The recycle loop places 24-148 such bets per run; each bet's PnL (ordinary 0.5-2.4% market moves x $M notional = +/-$1k-31k) accumulates **linearly** into +/-thousands-percent. A **missing liquidation model** lets equity run to **-$67k** (margin level -2,061%; 13/14 runs go negative; up to 31% of bars trade insolvent) - impossible live. The **matched notional control on the identical pair/window/signal nets ~5%**, isolating the cause entirely to the sizer.

**Classification: leverage artifact, enabled by an engine implementation defect (no liquidation). NOT compounding, NOT edge. Non-deployable.**

---

## 1. Mechanism (amplification decomposition)

`tools/recycle_rules/pine_ratio_zrev_v1.py::_vol_parity_lots`: `raw_lot = target_risk_usd / (ATR * usd_per_pu)`, floored at `min_lot`, **no upper cap**. Position notional = `target_risk * (price / ATR)` -> tiny relative-ATR => huge notional => extreme leverage.

| factor | contribution | evidence (ETHUSD/US30 + all 14) |
|---|---|---|
| trade edge | negligible | per-cycle moves 0.5-2.4% (normal noise); matched notional control nets ~5% |
| position sizing | dominant | total_lot 15-712 vs notional 0.01-0.07 |
| leverage | dominant | notional $1.7M-$6.2M on $1k stake; median max ~4,467x |
| volatility | the trigger | inverse-ATR sizer; low-vol instruments balloon the lot |
| recycle | the multiplier | 24-148 cycles accumulate additively |
| **compounding** | **none** | corr(lot, equity) median **+0.01** (several negative); cycle-24 lot < cycle-0 lot despite 53x equity |

Verdict: (B) leverage x (C) vol-targeting x (E) implementation defect -> (D) interaction. Not (A) edge.

## 2. Matched controls - divergence at cycle 0

Same pair / window / signal; only sizing differs (notional control from the pre-cleanup ledger backup):

| pair / window | SZVP net% / dd% | notional ctrl net% / dd% | base net% / dd% |
|---|---|---|---|
| ETHUSD/US30 06-27 | 5299 / 94 | 14 / 15 | 14 / 15 |
| CHFJPY/EURJPY 06-26 | 4438 / 31 | 3 / 1 | 3 / 1 |
| CHFJPY/UK100 01-02 | 3918 / 107 | 5 / 5 | 5 / 5 |
| ... (14/14) | | | |

The notional control **reproduces base exactly** and stays normal (1-14%). Divergence is **immediate, at cycle 0** (first entry): notional sizes 0.01 lots, SZVP sizes 15-712. No gradual separation.

## 3. Capital path (top winner ETHUSD/US30, +5,299%)

$1,000 -> cycle 0 **+$1,027 (+100% in one cycle)** -> swings of +$16,051, -$31,402, +$22,597 -> $53,992. Each cycle bets ~$1-4M notional **regardless of equity** (cycle 8 lost -$31,402, reducing $35.5k->$4.1k). **Without re-staking (cycle-0 only): $2,027.** The magnitude is additive accumulation of leveraged cycles, not compounding and not an exceptional edge.

## 4. Failure mode

Sizing is equity-decoupled (fixed target_risk), so a losing cycle can exceed remaining equity -> **negative equity (13/14 runs, to -$67k)**. The engine's `margin_freeze_active` / `dd_freeze_active` / `engine_paused` **never fired** (margin level to -2,061%). So SZVP **alters the payoff shape** (unbounded downside) rather than being a bounded leverage transform; the "wins" are computed on positions a broker would have liquidated.

## 5. Generalization

Instrument-dependent (low-relative-ATR: indices, JPY crosses; FRA40/SPX500 hit lot 712), not pair-specific edge. Only an **uncapped inverse-volatility sizer** replicates it; notional/granular_parity (bounded lots) and beta_capped (0.25-4.0x cap) cannot.

---

## The cross-cutting finding: engine enforces no liquidation - blast radius

**True (confirmed):** across **326 runs scanned** - including margin levels to -12,169% and equity to -$67k - **zero freezes ever fired**. No functioning margin-call/liquidation in the engine.

**But narrowly scoped.** Ledger-exact filter: `dd_vs_stake <= 100%` => trough >= 0 (peak >= stake always), so a run cannot go negative unless it exceeds that. Only two series do:

| series | runs | could-go-negative | confirmed negative equity |
|---|---|---|---|
| SZVP (vol-parity) | 14 | 14 | 14 excursions |
| GP (granular-parity) | 474 | 12 | 6 (to -$828) |
| base / GPN / ZCRS / P0x / ... | ~4,500 | **0** | **0** (mathematically bounded; 300-run sample confirmed: 0 negative, 0 freeze, worst margin +12,121%) |

**Implications:**
- **Production (notional) research is unaffected** - bounded by construction; prior tail-risk conclusions stand.
- **granular_parity tail is partly inflated** - 6 runs went negative; with liquidation they cap at -100%. Corrected tail (analysis-layer floor): worst maxDD **172.6% -> 100%**, worst net **-132% -> -100%**, impossible >100% DDs **6 -> 0**; but tail **frequency unchanged** (41 runs >50% DD vs notional 2; 12 catastrophic vs 1). **The granular verdict holds** - only the fictitious magnitudes were corrected.
- **Live is broker-protected** - MT5/OctaFx margins/liquidates at fixed 0.01 lot (RAW_MIN_LOT_V1). The engine never touches a live position; this is a backtest-fidelity issue only, with no live exposure.

---

## Decisions + actions (2026-06-04, operator-directed)

**Do:**
- **Recorded** the finding (this report + RESEARCH_MEMORY + project memory).
- **Kept raw results** - the 14 SZVP ledger rows (is_current=0) and backtests artifacts are preserved intentionally (do not prune).
- **Added liquidation-adjusted analysis** for leveraged studies: `tools/leverage_liquidation_adjust.py` (`liquidation_adjusted()` + `min_equity_usd()`, 7 unit tests). Apply the floor (intra-run `min(equity) < 0` => net -100 / maxDD 100 / ret_dd -1.0) when ranking or tail-analysing any leveraged sizing cohort. No-op on notional.
- **Archived SZVP** - tombstoned from the active Cointegration tab (is_current=0, supersede_kind `archived_research_artifact`); the tab's max ret/dd dropped 144.6 -> 26.3 and max final_equity $53,992 -> $1,844.

**Do NOT (and did not):**
- Modify the frozen `v1_5_8` engine.
- Introduce run-halting liquidation logic (would stall corpus generation for screening).
- Re-run production research (it is bounded and unaffected).

**Rationale:** the evidence moved this from an engine problem to a research-interpretation problem; those are solved in the analysis layer, not by changing the execution engine.

---

## References

- Sizer: `tools/recycle_rules/pine_ratio_zrev_v1.py::_vol_parity_lots`
- Floor: `tools/leverage_liquidation_adjust.py` + `tests/test_leverage_liquidation_adjust.py`
- Sample run_ids (SZVP, now is_current=0): ETHUSD/US30 `e8208ba06643d3bca2b60270`; per-bar artifacts under `TradeScan_State/backtests/*_SZVP*/raw/results_basket_per_bar.parquet`
- Pre-cleanup ledger backups: `TradeScan_State/ledger.db.bak.pre_sz_cleanup_*`, `ledger.db.bak.pre_szvp_archive_*`
- Sizing decision context: `~/.claude/.../memory/project_cointegration_leg_sizing_experiment.md`
