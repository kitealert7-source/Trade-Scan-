# Legacy CORE/RESERVE Charged Re-Validation — Batch 1 Report

**Date:** 2026-06-29
**Scope:** Families F6 (VOLEXP IDX 1d) + F5 (CMR FX 1d) of the legacy re-validation arc.
**Engine:** v1.5.11, spreads charged (`spread_charged_diraware_v1_5_11`, ~89% coverage).
**Status:** GOVERNANCE-GRADED 2026-06-29 (was PROVISIONAL). The 28 per-symbol batch-1 runs were
graded into the authoritative ledger via the **grade-existing** path (no re-execution) — see
"## Governance grading" below. Governed grades **refined the per-asset read on 2 of 6 survivors.**

---

## Method

Faithful re-validation of legacy strategies whose original directives are unrecoverable and/or
whose filter vocab is rejected by the current directive canonical schema. Per asset:

1. `run_stage1` over the existing **byte-faithful `strategy.py`** (verified signature-identical for
   F6/P03), charged, full history — no re-provisioning, no canonicalizer.
2. `REPORT_*.md` via report_generator; `run_state.json` backfilled to `STAGE_1_COMPLETE` (accurate —
   Stage 1 genuinely completed); `AK_Trade_Report.xlsx` via the v1.5.11 Stage-2 compiler.
3. Capital-wrapper `deployable/` reports.

**Key principle (corrected mid-batch):** a multi-asset series is a **screening universe**, not a
single strategy. Judge **per asset**; keep survivors, retire only dead components. Never
aggregate-retire.

---

## F6 — VOLEXP IDX 1d (S00/P03, best uncharged variant), 10 indices, 2016→2026 charged

Portfolio: PF **1.21**, Ret/DD **1.95**, net $3,548, 2,103 trades, maxDD $1,816, 9/11 years positive.

| symbol | net | trades | PF | Ret/DD | SQN | +yrs | verdict |
|---|---|---|---|---|---|---|---|
| NAS100 | 1324 | 180 | 1.57 | 3.46 | 2.29 | 7/10 | **KEEP** |
| US30 | 1522 | 217 | 1.31 | 1.44 | 1.56 | 10/11 | **KEEP** |
| JPN225 | 115 | 239 | 1.21 | 1.13 | 1.12 | 7/11 | **KEEP** |
| SPX500 | 152 | 196 | 1.25 | 0.87 | 1.17 | 10/11 | watch |
| EUSTX50 | 131 | 227 | 1.17 | 1.32 | 0.91 | 9/11 | watch |
| AUS200 | 112 | 244 | 1.14 | 0.84 | 0.80 | 6/11 | watch |
| GER40 | 179 | 85 | 1.14 | 0.89 | 0.50 | 2/5 | watch |
| ESP35 | 79 | 245 | 1.03 | 0.13 | 0.21 | 8/11 | drop |
| FRA40 | -54 | 234 | 0.96 | -0.20 | -0.23 | 6/11 | drop |
| UK100 | -11 | 236 | 0.99 | -0.05 | -0.04 | 6/11 | drop |

**Verdict:** SURVIVES — real charged edge, concentrated in US indices + Nikkei. Keepers: NAS100, US30,
JPN225 (+4 watch). Not a recency mirage (9/11 years +).

---

## F5 — CMR FX 1d (S02/P06, 3-consecutive-close probe), 18 FX pairs, 2016→2026 charged

Portfolio: PF **1.06**, Ret/DD **0.70**, net $478, 2,144 trades — DEAD in aggregate, but the
aggregate masks strong per-asset survivors.

| symbol | net | trades | PF | Ret/DD | SQN | +yrs | verdict |
|---|---|---|---|---|---|---|---|
| USDJPY | 309 | 111 | 1.95 | 5.14 | 2.56 | 9/11 | **KEEP** |
| CHFJPY | 224 | 122 | 1.61 | 4.12 | 2.01 | 9/11 | **KEEP** |
| USDCAD | 177 | 128 | 1.59 | 4.57 | 2.06 | 9/11 | **KEEP** |
| AUDJPY | 98 | 113 | 1.24 | 0.95 | 0.87 | 5/11 | watch |
| AUDUSD | 56 | 111 | 1.18 | 0.64 | 0.65 | 5/11 | drop |
| CADJPY | 65 | 118 | 1.16 | 0.78 | 0.61 | 7/11 | drop |
| EURGBP | 31 | 115 | 1.08 | 0.37 | 0.32 | 5/11 | drop |
| EURJPY | 33 | 126 | 1.06 | 0.36 | 0.25 | 6/11 | drop |
| GBPJPY | 33 | 124 | 1.04 | 0.11 | 0.16 | 7/11 | drop |
| (9 more) | <0 | | <1.0 | <0 | <0 | | drop |

**Verdict:** the raw 3-close probe is dead as a basket, BUT **USDJPY (PF 1.95, Ret/DD 5.14), CHFJPY,
USDCAD survive charged at deployment grade**. Keep those 3; drop the other 15. Retiring F5 wholesale
(as the PF-1.06 aggregate suggested) would have discarded the strongest assets in the entire batch.

---

## Batch-1 survivors (6) — keep + carry forward

| family | survivors |
|---|---|
| F6 VOLEXP IDX 1d | NAS100, US30, JPN225 |
| F5 CMR FX 1d | USDJPY, CHFJPY, USDCAD |

Watch list (5): SPX500, EUSTX50, AUS200, GER40 (F6); AUDJPY (F5).

---

## Governance grading (2026-06-29) — grade-existing path

The 28 per-symbol batch-1 runs already existed as complete `STAGE_1_COMPLETE` runs (charged v1.5.11,
full-history 2016→2026-06-25, real `run_id`s, valid Stage-2 `AK_Trade_Report`s). Rather than re-execute,
they were graded into the ledger directly:

1. Advance each run `STAGE_1_COMPLETE → STAGE_2_COMPLETE` via `PipelineStateManager.transition_to`
   (Stage-2 reports genuinely existed; the transition records reality).
2. `tools/stage3_compiler.py <prefix>` → 28 per-symbol rows into `master_filter` (DB-SSOT) + Excel.
3. Backfill `engine_version=1.5.11` (stage3's report-extractor doesn't thread it from metadata).
4. `tools/filter_strategies.py` → `candidate_status` (CORE/WATCH/FAIL) + FSP write.

**Governed grades — survivors:**

| Survivor | PF | Ret/DD | Sharpe | maxDD% | Grade | Note |
|---|---|---|---|---|---|---|
| USDJPY | 1.95 | 5.14 | 3.86 | 6.0 | **WATCH** | strongest |
| CHFJPY | 1.61 | 4.12 | 2.89 | 5.4 | **WATCH** | |
| USDCAD | 1.59 | 4.57 | 2.89 | 3.9 | **WATCH** | |
| NAS100 | 1.57 | 3.46 | 2.70 | 38.3 | **WATCH** | |
| US30 | 1.31 | 1.44 | 1.68 | **105.5** | excluded from FSP | maxDD >100% = no-liquidation fidelity artifact; leverage-floor decision DEFERRED |
| JPN225 | 1.21 | 1.13 | 1.15 | 10.2 | excluded from FSP | expectancy $0.48 < $0.50 INDEX gate (marginal) |

**Refinement vs the PROVISIONAL per-asset read (the Invariant-#31 payoff):** the governed pass changed
2 of 6 verdicts. **US30** — the largest NetPnL in F6 ($1522), a clean "KEEP" above — carries a
**>100% drawdown** (the documented leveraged no-liquidation artifact; per-symbol stage3 does not apply
the `leverage_liquidation_adjust` floor), so its survivor status is **fidelity-suspect**, not a clean
keep. **JPN225** fails the INDEX expectancy deployment gate by $0.02. The 4 clean WATCH survivors
(USDJPY, CHFJPY, USDCAD, NAS100) stand as decision-grade. None reach CORE — all capped at WATCH by
`trade_density < 50` (expected for low-frequency Daily strategies).

> All 28 runs persist in `master_filter` (the full append-only ledger); FSP carries only the rows
> clearing the inclusion gate (4 survivors among them). US30 leverage-floor handling left OPEN.

## Caveats / open items

- **Provenance note (accepted):** these are `run_stage1`-direct (non-admitted) runs graded by advancing
  FSM state. Invariant #31's *mechanical* requirement (ledger writes need a real `run_id`) is satisfied;
  re-executing identical computation purely to launder admission provenance was judged unnecessary
  busywork (operator decision 2026-06-29, the purge-then-rerun-vs-grade-existing fork).
- **Root friction:** the governed pipeline is blocked for F6 by directive-schema drift (the
  `outside_band`/`cooldown_bars` volatility-filter vocab was dropped). F5's directive passes the
  canonicalizer and could run governed. → motivates a strategy.py-direct-injection pipeline mode so
  legacy strategies generate ALL artifacts (incl. FSP rows) without admission friction.
- **Survivorship note:** F5/P06 chosen over P08 to avoid P08's 2-symbol-dropped basket. F6 used the
  best uncharged variant P03; P00/P02 (Stage-2 surface) not yet charged.
- **Housekeeping:** `active_backup/` staging directives + dead-component run artifacts are cleanup
  candidates once verdicts are locked.

---

## Next

- Batch 2: F4 (JPY LIQSWEEP) on the same per-asset method.
- Governance grading — **RESOLVED** via the grade-existing path above (no strategy.py-injection infra
  needed; advance-state + `stage3_compiler` over the existing runs sufficed).
- US30 leverage-floor decision (apply `leverage_liquidation_adjust` to the per-symbol >100%-DD row, or
  accept FSP exclusion) — **DEFERRED** (operator, 2026-06-29).
