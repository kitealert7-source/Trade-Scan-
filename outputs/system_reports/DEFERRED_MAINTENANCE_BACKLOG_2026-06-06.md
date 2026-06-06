# Deferred Maintenance Backlog — 2026-06-06

Archived from `SYSTEM_STATE.md ### Manual` on 2026-06-06 purge.
These are deferred *opportunities*, not problems. Nothing here is blocking.
SYSTEM_STATE now carries only a one-line pointer per category.

---

## SKILL_REFACTOR — Changes D + F (deferred 2026-06-02)

**Change D:** Move `/session-close §3.3 Artifact cleanup` into `/repo-cleanup-refactor §1d`. Keep only one minimal check in session-close: "any tracked file under `/tmp/`?" (real invariant-8 violation). The full root-untracked + scratch detection belongs in the cleanup skill. Earliest revisit: 2026-06-01+.

**Change F:** Strip `/system-health-maintenance` §5 / §6 / §8 overlap. §5 (vault) duplicates `/update-vault`; §6 (Excel format) duplicates `/format-excel-ledgers`; §8 (memory compaction) is the only home for the compaction logic but is also referenced from `/session-close §3.9`. Action: delete §5 + §6; keep §8 as canonical home, reference from elsewhere. Resulting scope: preflight + recovery + smoke tests + migration only. Defer this longest — cross-skill refactors create silent doc drift if rushed. Earliest revisit: 2026-06-01+.

---

## CODE_DRY — `_leg_pnl_usd` + `_safe_float` (deferred 2026-05-26 / 2026-06-02)

**`_leg_pnl_usd`:** Bodies are byte-identical modulo error-message rule-name across `tools/recycle_rules/h2_compression.py` + `h2_recycle.py` (52 lines each). NOT a candidate for unification with `h2_recycle_v3.py` (different signature). Surfaced by `/repo-cleanup-refactor` 2026-05-26. Deferred during high-stakes pre-deployment windows. Recommend: land after H2 strategy lock. One commit; new `tools/recycle_rules/_basket_pnl.py`; full basket regression suite (127+ tests).

**`_safe_float`:** Duplicated across 6 `tools/` files — `basket_report.py`, `idea_evaluation_gate.py`, `metrics_core.py`, `portfolio/portfolio_profile_selection.py`, `profile_selector.py`, `reconcile_portfolio_master_sheet.py`. Signatures vary slightly (`metrics_core` + `basket_report` take `default=0.0` AND guard NaN/inf; `idea_evaluation_gate` has no default). Recommend: consolidate into `tools/metrics_core.py:_safe_float` (most complete variant), import elsewhere. Earliest revisit: next focused DRY pass.

---

## DRIFT — pipeline-state-cleanup procedure (deferred 2026-06-02)

Diagnostics ran 2026-06-02; mutations deferred (TS_Execution was live).

**State:**
- **lineage_pruner hard-blocked** — `[BLOCK] TS_Execution is running`. Do NOT `--force-unlock` during live execution.
- **19 orphan `MPS::Baskets` rows** — run_id absent from disk, all COINTREV V2/V3 research baskets (e.g. `8099400b` CHFJPYUK100_1D_V3_L100__E002, `dc3fdf56` AUDJPYCADJPY_15M_V2_L252). FSP / Portfolios / SAC / Cointegration sheets CLEAN (0 orphans).

**Procedure (off-hours / non-live window):**
1. Confirm TS_Execution is not running
2. `cp ledger.db ledger.db.backup_$(date +%Y%m%d)`
3. `python tools/repair_integrity.py --action drop --execute` (verify Baskets drop hits `basket_sheet` in DB, not Excel-only)
4. `python tools/ledger_db.py --export-mps`
5. `python tools/format_excel_artifact.py --profile portfolio`
6. `python tools/lineage_pruner.py --execute`

---

## Z-cross edge localization — PROVISIONAL (first seen 2026-05-31)

Hypothesis-only result from 2026-05-31 cycle-level analysis on 451 paired (baseline / zcross) ZCRS corpus: decision-gate trips REGIME-CONCENTRATED (top-1 bucket = 68% of total ΔPnL, top-3 = 100%), but the "regime" is INSTRUMENT-FAMILY (CRY + MET via NaN `market_regime` proxy), NOT a market-state classification. BTC family +$10.64M net; FX/IDX (382 paired directives — actual design target) ≈ flat-to-mildly-negative (≈ -$1.6K, 45% win-rate). Edge fragility: dropping top 20 worst baseline cycles flips corpus Δ from +$11.08M to -$0.43M.

**Next step:** separate FX/IDX-only vs crypto/metals-inclusive Phase-3 backtests; walk-forward / LOO resampling on BTC specifically. Per Invariant #10 the bucket-level classification is ad-hoc; the BACKTEST validates.

Memo + dataset preserved at `C:/tmp/zcross_edge_localization_memo.md` / `C:/tmp/zcross_edge_localization_cycles.parquet`.

---

## QA — market_regime NaN on crypto/metals legs (first seen 2026-05-31)

Source `results_tradelevel.csv` rows for BTCUSD / ETHUSD / XAUUSD legs carry NULL `market_regime` despite the regime model attaching the column at leg-df level. Likely a regime-model coverage gap for non-FX symbols. Effect: any analysis grouping by `market_regime` will bucket these as UNKNOWN; `mae_r <= -3R` blowup heuristic evaluates trivially FALSE on NaN-`mae_r` subset. Fix scope: regime-model symbol-coverage audit + classification rule for non-FX leg types. Touches Protected Infra; plan + approval before landing.

---

## BASKET_REPORT Pass-3 polish backlog (first seen 2026-05-31)

5 items, all ACCEPTABLE-DEFER — mass refresh 2026-05-31 landed CLEAN at scale:
1. `pine_reversal` Event Taxonomy fallback verbosity — 22 rows mostly zero; tighten via family-specific template OR zero-row suppression.
2. Cycle-PnL Distribution degenerate single-bucket render when N_cycles < 3 — add parallel small-N guard.
3. Silent elision of MFE-Giveback + Asymmetry sections for pine_reversal — explicit "not applicable" stub.
4. `h3_holding` semantic mis-framing in Event Taxonomy (bar-count not event-count).
5. Spot-check higher-N report from a future mass-refresh batch.

Address only if BASKET_REPORT renderer is touched for another reason.

---

## Basket provenance follow-ups (parked 2026-06-01)

Two higher-bar reproducibility levers parked after the per-run code snapshot + reproducibility-identity work landed (PR #1, merged `95ff70d`):

**(a) Execute-from-snapshot for baskets** — load leg+rule code from `runs/<id>/basket_code/` at (re-)run time instead of importing live from `tools/`, for byte-deterministic re-runs. Bigger execution-path change; gate on real need (e.g. before promoting a basket to LIVE).

**(b) Leg-strategy code enforcement** — `recycle_strategies.py` is snapshotted (provenance) but not drift-enforced; if wanted, add it to the guard set (execution-path infra), NOT a registry pin.

See `tools/basket_reproducibility_check.py` + auto-memory `feedback_reproduction_truth_check`.

---

## CLAUDE.md topic-index candidate (first seen 2026-06-01)

New basket provenance/integrity surface from PR #1 not yet in CLAUDE.md's topic index / key-files:
- `tools/basket_provenance.py`
- `tools/basket_reproducibility_check.py`
- `tools/generate_recycle_rule_hashes.py`
- `governance/recycle_rules/rule_code_hashes.yaml`
- guard-set criterion in `tools/generate_guard_manifest.py`

Add a topic line next time CLAUDE.md is touched. Low priority (all self-documenting in-code).
