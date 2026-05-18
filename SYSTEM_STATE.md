# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-18T07:01:59Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 479 directives

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
- Latest bar: **2026-05-15** | Symbols: 1

## Artifacts
- Run directories: 1577

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `17747e4 session: idea-gate refresh post H3_spread infrastructure`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 1 acknowledged failure(s) (last refreshed 2026-05-17 @ 66f15bd2). Tests: test_basket_dispatch_emits_run_state_and. Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **freshness_index ACL workaround**: MASTER_DATA root has `DENY INTERACTIVE` ACL (service-account architecture per 2026-05-07 incident). `build_freshness_index.py`'s `glob("*_MASTER")` fails to enumerate from interactive sessions, producing an empty index. Per-symbol path access still works. Long-term fix: trigger the daily scheduled task before pipeline runs, or refactor `build_freshness_index.py` to accept a symbol-universe parameter and bypass `glob`. Workaround pattern (per-symbol manual enumeration from a hardcoded universe list) was demonstrated this session.

- **H3_spread@1 per-bar parquet schema gap (cosmetic, non-blocking)**: `H3SpreadV1Rule._emit_record` writes a simpler per-bar dict than the 1.3.0-basket 35-column standard schema (active_legs, dd_freeze_active, equity_total_usd, etc.). Strategy logic + Master Filter + MPS work correctly; downstream BASKET_REPORT can't generate per-window cycle metrics until the emission is extended. Fix is straightforward, just enumeration; defer to next-session v2 work.

- **H3_spread next move: slope-gated direction, NOT BEAR+BULL symmetry test.** BEAR variant (LONG EURUSD + SHORT USDJPY, UP-cross entry) ran cleanly with deployment-grade metrics on Window A 2024-05 -> 2026-05 (+60.08% / 31% DD / PF 1.33 / RR 1.93). Original plan was to run BULL on same window for symmetry — operator (2026-05-18) flagged this as wasted effort: charts clearly show macro regimes are multi-year and asymmetric; symmetry on a single window CANNOT exist, so running BULL on Window A would just confirm the regime-mirror finding from the screening (Window A: UP-LONG wins; Window B: DN-SHORT wins). Revised plan = slope-gated direction selection.

  **Revised v2 design (next-session work):**
    1. Add `spread_slope_30d` column to basket_data_loader (trailing 30-day change of log(EURUSD)-log(USDJPY)). Analogous to fx_corr_1h join pattern.
    2. Add slope-gate to H3_spread rule (or H3_spread@2 variant): at entry time, only fire if slope sign matches entry_direction. Reject mismatched cross signals.
    3. Architectural choice: simplest path is Option C — pre-compute desired direction per bar, gate entries through a single directive. Two-runner (A) or mid-run leg-direction-flip (B) deferred unless v2 evidence demands.
    4. Build SINGLE slope-gated directive on Window A → expect ~identical to BEAR baseline (Window A is mostly USD-weakening, so slope positive throughout, BEAR trades fire).
    5. Then run on FULL 10-year window (2016+) that spans BOTH regimes (USD-weakening 2016-2018, USD-strengthening 2018-2024, USD-weakening 2024-2026). This is the real regime-robustness test — does the architecture extract edge in BOTH macro regimes when correctly aligned, or only one direction regardless of slope?

  Build BULL-on-Window-A directive is DROPPED from pending. Not informative given the charts + screening already establish the regime-mirror behavior.
