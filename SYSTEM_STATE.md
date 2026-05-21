# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-20T14:51:05Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 292 directives

## Ledgers

- **Master Filter:** 1256 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 121, PROFILE_UNRESOLVED: 1, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 477 rows — CORE: 17, FAIL: 304, LIVE: 15, RESERVE: 22, WATCH: 119

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-20** | Symbols: 221

## Artifacts
- Run directories: 1650

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `07032ee fix(cointegration_state): backfill registry metadata + SIGNAL_PRIMITIVE`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-20 @ 112a300e). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **Phase 5b.3 carry-over — `lineage_pruner` blocked. RESOLVED 2026-05-21.** `tools/state_lifecycle/reconcile_portfolio_complete.py` built (commit ba6041f), tightened to match `lineage_pruner`'s two-gate integrity check (folder AND state JSON), and applied: 169 directives + 13 follow-up = 182 mutated, 193 dead child rids removed. `repair_integrity --action drop` then dropped 96 FSP rows and cell-edited 4 MPS portfolios. The 38 surgical orphans (29 RUN_INCOMPLETE + 9 ABORTED) were quarantined to `TradeScan_State/quarantine/20260521T014750Z_surgical_cleanup/`; reconcile follow-up scrubbed the 5 dead refs created; `system_registry --reconcile` marked the 6 missing entries invalid + auto-cleaned `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03/portfolio_evaluation/portfolio_metadata.json`. **Preflight RUNS RED → GREEN, REGISTRY RED → YELLOW** (only QUARANTINED_BUT_NOT_FOUND remaining; informational). The broader `lineage_pruner --execute` sweep (702 runs / 71 backtests / 293 directives / 33 portfolios / 87 deployed portfolios / 8 sandbox = 1204 items) was NOT run — deferred to a dedicated `/pipeline-state-cleanup` session for scoped review.

- **Phase 5b.3 carry-over — 13 broader-pytest TDs from directive_reconciler purge (commit a537940).** `directive_reconciler --execute` on 2026-05-20 removed 270 orphan PORTFOLIO_COMPLETE .txt files; 13 of those were test fixtures (e.g. `90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt` used by `test_basket_dispatch_phase5b`). Affected test files: `test_basket_directive_phase5` (5), `test_basket_dispatch_phase5b` (4), `test_basket_path_b_phase5b2::test_dispatch_produces_all_four_artifact_paths` (1), `test_basket_phase5c_real_data` (2), `test_basket_telemetry_end_to_end::test_mps_baskets_new_columns_populate` (1). **Proper fix (next session):** (a) restore the 13 fixture .txt files from `governance/directive_reconciler_audit.log`, AND (b) extend `tools/directive_reconciler.py` to recognize fixtures — either a `tests/_fixtures/directives.yaml` registry of preserved IDs OR a `protected: true` marker honored by `_directive_state_is_alive`. Vault snapshot `DR_BASELINE_2026_05_20_PHASE_5B_3` captures pre-purge state if a full restore is needed.

- **Phase 5b.3 carry-over — `68_PORT_FX_5M_PORT_S01_V1_P05` blocked in `PROFILE_UNRESOLVED`.** Surfaced by `system_preflight` LEDGER check 2026-05-20. Portfolio-evaluator Step 7 (`_resolve_deployed_profile`) failed to pick a profile. Either the profile candidates all scored below threshold or the candidate set was empty. Root-cause investigation needed; not a cleanup issue. **Triage 2026-05-21:** all 18 constituent run folders alive on disk; only 8 of 18 are in `Filtered_Strategies_Passed.xlsx`. Step 7 likely needs all 18 in FSP to pick a profile. Resolution paths: (a) rerun the directive via `/rerun-backtest` to regenerate the FSP rows, (b) patch Step 7 to handle partial FSP coverage, (c) accept PROFILE_UNRESOLVED as terminal status for partial-FSP portfolios. Defer to dedicated session.

- **Phase 5b.3 carry-over — `strategies/.format_backups` flagged YELLOW by `system_preflight`.** Created by the 2026-05-20 formatter patch — `tools/excel_format/styling.py::_preprocess_with_pandas` now snapshots MPS xlsx to `<dir>/.format_backups/<name>.bak_<ts>` before destructive rewrite (rolling last 5). The preflight warns "Unexpected content in strategies/". One-line whitelist in `tools/system_preflight.py` (or wherever the strategies/ allowlist lives) clears the YELLOW.

- **Phase 5b.3 carry-over — 359 `master_filter` rows reference missing `runs/<id>/`.** Audit CSV: `TradeScan_State/reports/master_filter_missing_state_20260520.csv`. 350 are `is_current=1`, 9 already `is_current=0`. The row data itself is intact (full metrics); only the pipeline state lineage is broken. Affects `mark_superseded()`, `verify_state()`, and `rerun_backtest.py` for these run_ids. Three resolution options: (a) flip the 350 `is_current=0` (soft-archive, mirrors how 173 overwritten basket rows were handled — recommended), (b) DROP outright (loses audit history), (c) extend `lineage_pruner` to exclude `is_current=0` rows from its integrity check (helps with carry-over #1 too).

- **H3_spread BEAR P03 (-$20 adverse stop) is the leading deployment candidate (2026-05-18).** Adverse-stop sweep P00 (-$2 baseline) → P01 (-$10) → P02 (-$15) → P03 (-$20) shows Pareto improvement across all axes: adverse-rate 91.4% → 65.2%, win-rate 6.7% → 18.5%, net PnL $2,198 → $6,553 (+198%), max DD% (peak-relative) −35.55% → −16.11%, R/DD 6.18 → 40.67. Same 313 cycles in every variant (entry signal invariant; only cycle DURATION + EXITS change). Authoritative per the new BASKET_REPORT.md (canonical_metrics from per-bar parquet); the prior +60.08% / 31% DD figure was the legacy REPORT.md's trade-level lens which mis-counts cycle-mechanic strategies — that lens is now suppressed for baskets. Trajectory across -$2..-$20 hasn't plateaued, so -$25/-$30 are reasonable next probes if appetite returns. Cross-pair / cross-direction (e.g., BULL on different window, AUDUSD+USDCAD) validation pending before promotion.

- **H3_spread peak-relative trail-stop ABANDONED for BEAR (2026-05-18, P04 structural test).** P04 = clone of P03 + trail_arm_floating_usd=$25, trail_retrace_pct=50%, evaluated before reverse-cross. Result: net PnL −76% vs P03 ($+1,571 vs $+6,553), mean cycle PnL collapsed from $20.94 → $5.02, max DD% degraded −16% → −31%, longest underwater 28k → 80k bars. 131 TRAIL_STOP exits substituted for adverse + reverse exits, but at half-peak the captures are tiny and cycles that would have run multi-hundred-dollar peaks get chopped at $25-tier exits. The strategy is structurally lottery-shaped — trail-stop is not the right exit lever for THIS strategy. Trail-stop infrastructure (params + canonical_metrics tag + report row) is retained and available for any future strategy family with different exit characteristics; defaults are 0.0 (disabled) so P00-P03 unaffected. Do not re-test trail-stop on H3_spread without changing the mechanic shape.

- **Pyramid-2 bifurcation at firing bar has NO predictive signal in standard observable features (2026-05-18).** Audited at the exact bar where lot[0] transitions 0.15 → 0.20: of 194 cycles that fired pyramid-2, 38 ran +$50+ above (tail-runners), 143 slid back >$5 below (slide-back, mostly to adverse-stop). Tested features: signed SMA separation, Δdiff over 2/3/4 bars, 10-bar diff slope, rolling 50-bar EUR/JPY correlation, EUR bar range (absolute + z-scored), UTC hour, bars-since-entry. All effect sizes ≤ 0.25 with 40-85% IQR overlap. Top features paradoxically go the WRONG direction (sliders have HIGHER bar range; runners come from QUIETER pyr-2 bars; sliders have HIGHER current SMA gap; runners have lower current gap with still-positive velocity). Implication: the bifurcation is NOT predictable from these features at the pyr-2 firing instant. Either need different features (cross-pair flow, broader USD basket dynamics, term structure) OR accept the strategy as fundamentally tail-driven (improve via entry-side filtering or position-sizing-by-regime, not per-cycle in-flight prediction). Reverse-cross MFE audit on P03: 44.1% capture rate (sum_realized / sum_MFE positive), $10,141 of $18,154 peak surrendered to reverse-cross lag; smarter exit IS possible but trail-stop is not it.

- **Preserved diagnostic scripts in tmp/ — DELETED 2026-05-19.** The four forex-basket-specific analyses + one authoring utility (replay_h3_no_adverse_stop, stage0_sma_separation_signal, p03_reverse_cross_mfe, p03_pyr2_bifurcation_features, create_pairx_variants — plus 3 paired CSVs) were removed without promotion. Rationale: `p03_reverse_cross_mfe.py` was already superseded by [tools/basket_hypothesis/mfe_giveback.py](tools/basket_hypothesis/mfe_giveback.py) (generalized to all rule families, wired into BASKET_REPORT.md); the other three were H3_spread-specific forensics whose findings are already captured in this file's Manual entries above (P03 adverse-stop sweep verdict, pyr-2 bifurcation null-result, trail-stop abandoned). No reusable infra value remained; rebuild on demand if a future basket strategy needs equivalent forensics.

- **H3_spread next move (LEGACY plan, pre-dates P03 result): slope-gated direction, NOT BEAR+BULL symmetry test.** BEAR variant (LONG EURUSD + SHORT USDJPY, UP-cross entry) ran cleanly with deployment-grade metrics on Window A 2024-05 -> 2026-05 (+60.08% / 31% DD / PF 1.33 / RR 1.93 — note: legacy trade-level numbers; canonical BASKET_REPORT now shows +219.81% / −35.55% peak-relative DD for baseline P00). Original plan was to run BULL on same window for symmetry — operator (2026-05-18) flagged this as wasted effort: charts clearly show macro regimes are multi-year and asymmetric; symmetry on a single window CANNOT exist, so running BULL on Window A would just confirm the regime-mirror finding from the screening (Window A: UP-LONG wins; Window B: DN-SHORT wins). Revised plan = slope-gated direction selection.

  **Revised v2 design (next-session work):**
    1. Add `spread_slope_30d` column to basket_data_loader (trailing 30-day change of log(EURUSD)-log(USDJPY)). Analogous to fx_corr_1h join pattern.
    2. Add slope-gate to H3_spread rule (or H3_spread@2 variant): at entry time, only fire if slope sign matches entry_direction. Reject mismatched cross signals.
    3. Architectural choice: simplest path is Option C — pre-compute desired direction per bar, gate entries through a single directive. Two-runner (A) or mid-run leg-direction-flip (B) deferred unless v2 evidence demands.
    4. Build SINGLE slope-gated directive on Window A → expect ~identical to BEAR baseline (Window A is mostly USD-weakening, so slope positive throughout, BEAR trades fire).
    5. Then run on FULL 10-year window (2016+) that spans BOTH regimes (USD-weakening 2016-2018, USD-strengthening 2018-2024, USD-weakening 2024-2026). This is the real regime-robustness test — does the architecture extract edge in BOTH macro regimes when correctly aligned, or only one direction regardless of slope?

  Build BULL-on-Window-A directive is DROPPED from pending. Not informative given the charts + screening already establish the regime-mirror behavior.

- **H3_spread@2 architectural arc complete; deployment is REGIME-CONDITIONAL not regime-robust (2026-05-19).** Session built and tested H3_spread@2 — a research-validated extension of @1 composing four structural improvements: (1) max_exposure_multiple cap on bidirectional pyramid growth, (2) symmetric harvest scale-out above the cap, (3) harvest_keeps_core (floor=initial_lot, persistent CORE_HOLD), (4) bidirectional cycle direction set from cross_side at basket-open. Committed `7f33a8c feat(h3_spread@2)`.

  **Best variants on 2-window cross-regime test (EUR+USDJPY only, S10 mechanic):**
  - **Window A (2024-05 → 2026-05 USD-weakening):** S08 (1d macro) +184% / DD −24%; **S10 (4h-scaled macro)** +198% / DD −23% / Ret/DD 8.54
  - **Window B (2021-05 → 2023-05 USD-strengthening):** S08 +153% / DD −27%; **S10** +156% / DD −26% / Ret/DD 6.01
  - 1d and 4h-scaled (same daily calendar lookback) deliver equivalent results; 4h sampled finer is marginally better.

  **Two negative-result probes (committed under follow-on S11/S12/S13/S14 directives, NOT in `7f33a8c`):**
  - **Cross-pair fails:** GBPUSD+USDJPY −72%/−152% on A/B; AUDUSD+USDCAD −146%/−80% on A/B. Mechanism does NOT transfer to other pair combinations. GBP/USDJPY has only marginally weaker correlation profile than EUR/JPY but loses anyway (higher 5m vol + Brexit idiosyncratic shocks); AUD/USDCAD has STRONGER inverse correlation but the spread captures commodity-vs-oil dynamics rather than USD direction.
  - **Window C 2018-05 → 2020-05 fails:** −130% Net / −124% DD on the EUR/JPY/S10 mechanic that won the other two windows. Multi-regime period (trade war 2018 + Brexit + Fed pivot 2019 + COVID March 2020). 74% of loss is PRE-COVID (worst single quarter 2019Q1 = −$536 with no COVID involvement). Direction was right 99.7% of cycles; 5m chop within macro-coherent segments + correlation breakdown (25% of days corr > −0.2 vs 5% on Window A) were the proximate drivers.

  **EUR/JPY 20-day return correlation predicts win/loss monotonically across the 3 windows:**
  - Window A: mean corr −0.594, 69% strongly inverse (< −0.5) → **+198% Net**
  - Window B: mean corr −0.408, 36% strongly inverse → **+156% Net**
  - Window C: mean corr −0.342, 24% strongly inverse → **−130% Net**

  **Correlation filter approach TESTED AND DROPPED (S13/S14 directives in completed/, code in basket_data_loader.py with default=off).** Adding `macro_correlation_window + macro_correlation_threshold` params to gate cross_event by daily rolling correlation works directionally (Window C loss reduced 74% at threshold=−0.5, 30% at −0.2) but the cost on Windows A/B is non-trivial (−0.5: lose 62-76% of edge; −0.2: lose 4-41%). No single threshold preserves A/B edge while making Window C profitable — per-cycle PF on Window C stays 0.75-0.78 regardless of threshold, meaning the strategy lacks per-cycle edge on Window C structurally, not just from "broken correlation" entries. **Decision: leave correlation filter OUT of deployment; let portfolio-level max-DD constraints do the risk-management work.** Filter code retained as research diagnostic (default macro_correlation_window=None preserves legacy behavior).

  **Deployment posture (locked, end of session 2026-05-19):**
  - EUR/JPY is the SINGLE deployable pair (cross-pair attempts negative).
  - 2/3 windows positive; 1/3 catastrophically negative. Strategy is regime-conditional, not regime-robust.
  - Required: portfolio-level max-DD discipline to bound the Window-C-like tail when it recurs.
  - Open structural question: how to DETECT regime-condition (correlation health + 5m intra-macro coherence + macro flip frequency) BEFORE deployment damage accumulates. Operator-side review of macro indicators per quarter is the manual baseline.

  **Research artifacts (not yet committed at session-close; will be committed by /session-close):**
  S11 V1 P00/P01 (GBPUSD+USDJPY × A/B), S12 V1 P00/P01 (AUDUSD+USDCAD × A/B), S10 V1 P02 (EUR/JPY × Window C), S13 V1 P00/P01/P02 (corr filter −0.5 × 3 windows), S14 V1 P00/P01/P02 (corr filter −0.2 × 3 windows). Plus correlation-filter code + 6 new tests in `tests/test_basket_data_loader_macro_filter.py`.

- **Reading list for next session.** Operator will think over the picture. Key strategic questions to consider before next probe:
  1. Accept EUR/JPY-only deployment with manual regime gating + portfolio-level DD?
  2. Build a second filter (5m intra-macro coherence — realized vol within macro-stable segments)?
  3. Search for a different basket structure where the cross-pair mechanism transfers (e.g., truly USD-anchored synthetic spreads, not naive pair-combinations)?
  4. Park the mechanism and pursue a different strategy family?

- **COINTREV v1 retired 2026-05-21 (commit 605317c). Screener universe expanded to XAU/BTC/ETH (commit b8f4251).** The polluted strategy chain (cointegration_meanrev_v1.py + generate_cointrev_directives.py + CointMeanRevLegStrategy + cohort report tool + 48 backtest directives + tradability/corr_504d columns in the Excel viewer) was retired in one commit. Pollution was equal-lot sizing in the strategy + a correlation-based "tradability filter" added at directive-generation time to mask the equal-lot bug — together they made COINTREV correlation-pair-trading dressed in cointegration language. 98 directive admission records quarantined to `TradeScan_State/quarantine/20260521T032947Z_coint_v1_retirement/` with full manifest.

  Clean infrastructure retained: screener (`cointegration_screen.py`), SQLite ingest (`cointegration_db.py`), history matrix (`cointegration_history_matrix.py`), Excel viewer (`cointegration_excel.py`, now strictly cointegration), runtime feature lookup (`indicators/stats/cointegration_state.py`), data-loader `load_cointegration_factor` + `compute_intra_z`, daily runner (`cointegration_daily_runner.py`), event study output (annotated). Output reports POLLUTED-banner annotated (COHORT, CONCURRENCY); EVENT_STUDY annotated with regime-trust caveat (methodology clean, actionable claim re-validation pending).

  **Universe expansion (commit b8f4251):** 18 FX → 21 symbols by adding XAUUSD/BTCUSD/ETHUSD. 153 → 210 pair-pairs. First-run findings (BOTH-window cointegrated cross-asset pairs): **BTCUSD/NZDJPY** (p252=0.0015, p504=0.0210, hl=5.8d/19.4d), **GBPJPY/XAUUSD** (p252=0.0135, p504=0.0437, hl=9.7d/25.4d), **EURJPY/XAUUSD** (p252=0.0165, p504=0.0370, hl=11.7d/25.9d). CHFJPY/XAUUSD one tick from BOTH (504d p=0.0531). Yen-cross / XAU cluster is economically intuitive (risk-off / inflation-hedge drivers); BTC/NZDJPY surprising and warrants follow-up sanity check.

  **Deferred (future sessions):** β-weighted COINTREV v1.2 strategy build (if/when pursued — would test cointegration mean-reversion fairly with β-weighted lots); stocks-universe pivot (cointegration has rich literature on equity pairs but requires new data ingestion + execution path). Today's daily screener continues to run as monitoring infra independent of any strategy.
