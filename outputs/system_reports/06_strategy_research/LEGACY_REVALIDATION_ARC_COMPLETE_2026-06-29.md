# Legacy CORE/RESERVE Charged Re-Validation — ARC COMPLETE

**Date:** 2026-06-29 · **Engine:** v1.5.11, spreads charged · **Status:** ARC CLOSED.

Goal: re-run legacy CORE/RESERVE strategies on charged v1.5.11 to see which concepts survive costs.
Companion: `LEGACY_REVALIDATION_BATCH1_2026-06-29.md` (F5/F6 detail).

---

## Verdict — survivors (WATCH+ / research-kept)

| strategy | TF | PF | Ret/DD | SQN | grade | note |
|---|---|---|---|---|---|---|
| 53_MR_FX_1D_CMR_S02_V1_P06 · **USDJPY** | 1d | 1.95 | 5.14 | 2.55 | WATCH | strongest of arc |
| 53_MR_FX_1D_CMR_S02_V1_P06 · **CHFJPY** | 1d | 1.61 | 4.12 | 2.01 | WATCH | |
| 53_MR_FX_1D_CMR_S02_V1_P06 · **USDCAD** | 1d | 1.59 | 4.57 | 2.06 | WATCH | |
| 02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P03 · **NAS100** | 1d | 1.57 | 3.46 | 2.28 | WATCH | |
| ~~18_REV_XAUUSD_1H_LIQSWEEP_S01_V1_P02 · XAUUSD~~ | 1h | 1.34 | 2.08 | 0.98 | FAIL → **DROPPED** | lone LIQSWEEP charged survivor BUT FAIL-grade (SQN<1.5, 131 tr/11yr) — run artifacts + ledger row dropped 2026-06-29 (run_stage1-direct lacks `manifest.json` → perpetual RUNS-RED if kept; FAIL fails the keep-WATCH+ rule). **Finding preserved here only** — re-runnable from the documented recipe if ever worth iterating (1h dodges the spread drag that killed 15m FX). |

**Final keep-set = the 4 WATCH survivors above (CMR ×3 + NAS100).** Everything else in the arc is dead charged and was pruned (operator-authorized, keep-WATCH+ rule, 2026-06-29): arc FAIL rows + the full accumulated backlog via `lineage_pruner --execute` (**1,351 artifacts quarantined** to `quarantine/20260629_213410_cleanup`, reversible) + registry reconciled. Post-cleanup `system_preflight`: all structural checks GREEN (the session-start RED drift cleared).

---

## Family-by-family results

| family | scope | verdict |
|---|---|---|
| **CMR** FX 1d (F5) | 18 FX | mostly dead; **USDJPY/CHFJPY/USDCAD survive** (screening universe, judge per-asset) |
| **VOLEXP** IDX 1d (F6) | 10 indices | survives in US indices; **NAS100** clean WATCH (US30 >100%-DD fidelity-flag; JPN225 marginal exp-gate) |
| **LIQSWEEP** FX/cross 15m (F4, idea 42) | 25 runs (13 base + 12 tuned) | **DEAD** — max PF 1.01, best net $7, 0 WATCH; tuned/`regime_age` patches did NOT rescue the dead base (uniform cost-mirage) |
| **LIQSWEEP** XAU 1h (idea 18) | 5 patches | mostly dead; **P02 survives** (PF 1.34 / Ret-DD 2.08) — 1h's low frequency dodges the spread drag that killed 15m FX |
| **SPKFADE** XAU 1h | Arm A/B | DEAD — Arm A (2024-26) PF 1.50 is a vol-regime mirage; Arm B (full-history) PF 1.06 (9/12 yrs negative) |
| **PSBRK** XAU 5m | — | dead (prior) |
| **AUDJPY-family** ("lone CORE survivor" per memory) | FX-30m | **UNCONFIRMED** — no v1.5.11 row, no vault identity; a pre-purge characterization never reproduced on the current engine |

**Pattern:** charged survival concentrates in **low-frequency, large-range** setups (FX/IDX *daily*, XAU *1h*). High-frequency intraday FX (15m) and XAU (5m/15m) are uniformly charged cost-mirages — spread drag dominates.

---

## Method findings (reusable)

1. **Check `backtests/` before planning a rerun.** F5/F6 already had complete STAGE_1 runs → *grade-existing* (advance state → `stage3_compiler` → `filter_strategies`) beats purge-then-rerun with zero re-execution.
2. **Governed admission is structurally blocked for multi-symbol-same-idea-prefix families.** The Classifier Gate keys an "idea" on family+model+symbol+TF; `42_REV_*` bundles ~20 symbols under idea 42 → every non-registered symbol is rejected as an identity change. Viable path = **`run_stage1`-direct + grade** (single-symbol/XAU families admit fine governed; multi-symbol don't).
3. **`run_stage1`-direct harness** (proven): restore directive (git) → stage faithful `strategy.py` (vault) into repo `strategies/<id>/` → `run_stage1` → `generate_backtest_report` (REPORT card) → backfill `run_state` STAGE_1 → `stage2_compiler` (AK report) → set STAGE_2 → `stage3_compiler` → `filter_strategies`. Run with `PYTHONIOENCODING=utf-8` (legacy docstrings crash cp1252 capability resolution).
4. **Staleness landmines hit:** DATA_GATE needs `start_date` after the first-bar datetime (per-pair data start varies: 2016-06 / 2022-02 / 2024-01); `volatility_regime` not provisioned to the FilterStack in run_stage1-direct (HTF-isolation shadowing) → blocks regime-filtered strategies; v1.5.3-era `check_exit` returns numpy bool → violates v1.5.11 contract (FORM cast `return bool(...)` fixes it); v1.5.3 strategies lack `_schema_sample`/`REQUIRED_CAPABILITIES` (only matters for governed preflight).
5. **Strategic takeaway (operator, 2026-06-29):** *fresh tests are smoother than recreating old ones.* The staleness gauntlets (contract drift, missing schema, regime provisioning, classifier identity rules) make faithful re-validation of pruned legacy strategies costly; whole-family re-screening is low-yield (survivors are a handful of assets). Default to fresh hypotheses; re-validate selectively only when a specific legacy result is genuinely promising.
