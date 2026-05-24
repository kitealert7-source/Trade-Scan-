# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 6 uncommitted

> Generated: 2026-05-24T14:02:34Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 41 directives

## Ledgers

- **Master Filter:** 1257 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 122, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 381 rows — CORE: 14, FAIL: 241, LIVE: 13, RESERVE: 17, WATCH: 96

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-24** | Symbols: 221

## Artifacts
- Run directories: 980

## Git Sync
- Remote: IN SYNC
- Working tree: 6 uncommitted
- Last substantive commit: `0fffd85 indicators/INDICATOR_REGISTRY: backfill ratio_hedged_spread_zscore metadata`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-23 @ dbfa9c1a). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (next-session orientation only — not a record document)
<!-- Strict rule: each entry ≤3 lines + a pointer. Anything longer belongs in
     the linked authoritative doc. Entries removed once resolved/superseded;
     git log preserves history. -->

- **Active Charter:** h3_spread Window-C regime detector. V1 (binary halt) negative this session; V3 (soft gate, halve pyramid_add_lot) recommended next. Full charter + V2-V5 variations + decision rules: [`H3_SPREAD_WINDOW_C_CHARTER.md`](outputs/system_reports/06_strategy_research/H3_SPREAD_WINDOW_C_CHARTER.md).

- **Deployment baseline (UPDATED 2026-05-24 post Option-B fix):** H3_spread@3 EUR/USDJPY 15m d=8 e=5.0 r=1.0. Re-run S21 P06/P07/P08 under correct entry-bar PnL accounting (commit ac14d1e): Window A +267/-25/10.7 RetDD, Window B +210/-52/4.1 RetDD, Window C -97/-100/-1.0. **Window B's DD doubled vs prior +226/-21/10.9 reading — the "Pareto over @2 on A/B" narrative no longer holds; B's RetDD dropped from 10.87 to 4.06.** Window C still catastrophic. Deployment posture: still regime-conditional (Window C needs the Active Charter detector), but B's degraded DD profile warrants re-evaluation before any further commitment.

- **leg_direction_flip_bug RESOLVED via Option B (2026-05-24):** `BasketLeg.effective_direction` property + workaround removal in 3 rules. Commits 92fb187 (Option A pragmatic) → e0a1d8c (v1.2 cohort re-eval) → 2a40526 (25 V2 15M batch) → 51668d0 (rerun_backtest fix) → ac14d1e (Option B architectural). v1.2 retirement basis RE-OPENED: 3/5 winners post-fix vs 1/5 pre-fix; cointegration mean-reversion thesis NOT falsified. See RESEARCH_MEMORY 2026-05-24 entries.

- **Pine z_r reversal port LANDED + corrected (2026-05-24):** infrastructure in commits `d4237c7` + `1a6eda8` + `4de1f7a`; equity numbers corrected under Option B: CHFJPY/UK100 +335/-335 DD (DD was masked under buggy accounting), EURJPY/US30 +234/-84 DD (was never the −352% "blowup" — that was sign-flipped accounting on 100%-SHORT cycle cohort).

- **Daily broker-spec refresh chained** (2026-05-23): TS_Execution `extract_symbol_specs.py` migrated to DATA_INGRESS post-hook (`engines/ops/extract_broker_specs.py`). Daily run writes a JSON snapshot to `Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/BROKER_SPECS/symbol_specs_mt5.json`; the chained `tools/verify_broker_specs.py --patch` step then patches `data_access/broker_specs/OctaFx/*.yaml` in place — review with `git diff` and commit when ready. (DATA_INGRESS fc1e706 fixed a PS 5.1 BOM-less parse bug introduced by the migration; first clean run expected 2026-05-25 05:45 IST.)

- **`system_introspection.py` Manual-block preservation BROKEN (2026-05-24):** regen wiped the Manual section instead of preserving — apparently `_preserve_manual_section` only matches the old "deferred TDs, operational context" subheading and clobbers the "next-session orientation only" form (now-canonical, used since 2026-05-22 prune cycle). Restored by hand AGAIN in this session-close (2nd occurrence in 24h). Followup: fix the preserver to match either subheading form, OR revert to the old subheading. Filed.
