# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 77 symbol(s) stale (>3 days behind)
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-18T15:15:07Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 483 directives

## Ledgers

- **Master Filter:** 1151 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 121, PROFILE_UNRESOLVED: 1, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 521 rows — CORE: 14, FAIL: 351, LIVE: 13, RESERVE: 25, WATCH: 118

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-18** | Symbols: 221 | **Stale (>3d): 77**

## Artifacts
- Run directories: 1581

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `01bfc85 test(basket-path-b): drop legacy REPORT.md assertion (suppressed for baskets)`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-05-18T10:51:43+00:00 @ dff23e7e.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **H3_spread BEAR P03 (-$20 adverse stop) is the leading deployment candidate (2026-05-18).** Adverse-stop sweep P00 (-$2 baseline) → P01 (-$10) → P02 (-$15) → P03 (-$20) shows Pareto improvement across all axes: adverse-rate 91.4% → 65.2%, win-rate 6.7% → 18.5%, net PnL $2,198 → $6,553 (+198%), max DD% (peak-relative) −35.55% → −16.11%, R/DD 6.18 → 40.67. Same 313 cycles in every variant (entry signal invariant; only cycle DURATION + EXITS change). Authoritative per the new BASKET_REPORT.md (canonical_metrics from per-bar parquet); the prior +60.08% / 31% DD figure was the legacy REPORT.md's trade-level lens which mis-counts cycle-mechanic strategies — that lens is now suppressed for baskets. Trajectory across -$2..-$20 hasn't plateaued, so -$25/-$30 are reasonable next probes if appetite returns. Cross-pair / cross-direction (e.g., BULL on different window, AUDUSD+USDCAD) validation pending before promotion.

- **H3_spread peak-relative trail-stop ABANDONED for BEAR (2026-05-18, P04 structural test).** P04 = clone of P03 + trail_arm_floating_usd=$25, trail_retrace_pct=50%, evaluated before reverse-cross. Result: net PnL −76% vs P03 ($+1,571 vs $+6,553), mean cycle PnL collapsed from $20.94 → $5.02, max DD% degraded −16% → −31%, longest underwater 28k → 80k bars. 131 TRAIL_STOP exits substituted for adverse + reverse exits, but at half-peak the captures are tiny and cycles that would have run multi-hundred-dollar peaks get chopped at $25-tier exits. The strategy is structurally lottery-shaped — trail-stop is not the right exit lever for THIS strategy. Trail-stop infrastructure (params + canonical_metrics tag + report row) is retained and available for any future strategy family with different exit characteristics; defaults are 0.0 (disabled) so P00-P03 unaffected. Do not re-test trail-stop on H3_spread without changing the mechanic shape.

- **Pyramid-2 bifurcation at firing bar has NO predictive signal in standard observable features (2026-05-18).** Audited at the exact bar where lot[0] transitions 0.15 → 0.20: of 194 cycles that fired pyramid-2, 38 ran +$50+ above (tail-runners), 143 slid back >$5 below (slide-back, mostly to adverse-stop). Tested features: signed SMA separation, Δdiff over 2/3/4 bars, 10-bar diff slope, rolling 50-bar EUR/JPY correlation, EUR bar range (absolute + z-scored), UTC hour, bars-since-entry. All effect sizes ≤ 0.25 with 40-85% IQR overlap. Top features paradoxically go the WRONG direction (sliders have HIGHER bar range; runners come from QUIETER pyr-2 bars; sliders have HIGHER current SMA gap; runners have lower current gap with still-positive velocity). Implication: the bifurcation is NOT predictable from these features at the pyr-2 firing instant. Either need different features (cross-pair flow, broader USD basket dynamics, term structure) OR accept the strategy as fundamentally tail-driven (improve via entry-side filtering or position-sizing-by-regime, not per-cycle in-flight prediction). Reverse-cross MFE audit on P03: 44.1% capture rate (sum_realized / sum_MFE positive), $10,141 of $18,154 peak surrendered to reverse-cross lag; smarter exit IS possible but trail-stop is not it.

- **Preserved diagnostic scripts in tmp/ pending integration into basket_report (FUTURE WORK).** Five forex-basket-specific analyses kept for next-session review: tmp/replay_h3_no_adverse_stop.py + CSV (counterfactual adverse-stop sweep), tmp/stage0_sma_separation_signal.py (entry-feature signal-vs-noise partition; abandoned branch), tmp/p03_reverse_cross_mfe.py + CSV (MFE vs realized give-back per cycle), tmp/p03_pyr2_bifurcation_features.py + CSV (feature audit at pyr-2 — null result), tmp/create_pairx_variants.py (utility). When promoting, move analytics to tools/basket_hypothesis/ + add report sections: stop-sensitivity sweep, entry-feature predictiveness, MFE give-back distribution, pyr-2 bifurcation. Forex-basket scoped until generalized.

- **H3_spread next move (LEGACY plan, pre-dates P03 result): slope-gated direction, NOT BEAR+BULL symmetry test.** BEAR variant (LONG EURUSD + SHORT USDJPY, UP-cross entry) ran cleanly with deployment-grade metrics on Window A 2024-05 -> 2026-05 (+60.08% / 31% DD / PF 1.33 / RR 1.93 — note: legacy trade-level numbers; canonical BASKET_REPORT now shows +219.81% / −35.55% peak-relative DD for baseline P00). Original plan was to run BULL on same window for symmetry — operator (2026-05-18) flagged this as wasted effort: charts clearly show macro regimes are multi-year and asymmetric; symmetry on a single window CANNOT exist, so running BULL on Window A would just confirm the regime-mirror finding from the screening (Window A: UP-LONG wins; Window B: DN-SHORT wins). Revised plan = slope-gated direction selection.

  **Revised v2 design (next-session work):**
    1. Add `spread_slope_30d` column to basket_data_loader (trailing 30-day change of log(EURUSD)-log(USDJPY)). Analogous to fx_corr_1h join pattern.
    2. Add slope-gate to H3_spread rule (or H3_spread@2 variant): at entry time, only fire if slope sign matches entry_direction. Reject mismatched cross signals.
    3. Architectural choice: simplest path is Option C — pre-compute desired direction per bar, gate entries through a single directive. Two-runner (A) or mid-run leg-direction-flip (B) deferred unless v2 evidence demands.
    4. Build SINGLE slope-gated directive on Window A → expect ~identical to BEAR baseline (Window A is mostly USD-weakening, so slope positive throughout, BEAR trades fire).
    5. Then run on FULL 10-year window (2016+) that spans BOTH regimes (USD-weakening 2016-2018, USD-strengthening 2018-2024, USD-weakening 2024-2026). This is the real regime-robustness test — does the architecture extract edge in BOTH macro regimes when correctly aligned, or only one direction regardless of slope?

  Build BULL-on-Window-A directive is DROPPED from pending. Not informative given the charts + screening already establish the regime-mirror behavior.
