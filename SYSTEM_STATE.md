# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-23T14:46:55Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 6 directives

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
- Latest bar: **2026-05-23** | Symbols: 221

## Artifacts
- Run directories: 945

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `7168f68 session: idea-gate refresh â€” tools_manifest regen for 5 changed tools`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-23 @ dbfa9c1a). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (next-session orientation only — not a record document)
<!-- Strict rule: each entry ≤3 lines + a pointer. Anything longer belongs in
     the linked authoritative doc. Entries removed once resolved/superseded;
     git log preserves history. -->

- **Active Charter:** h3_spread Window-C regime detector. V1 (binary halt) negative this session; V3 (soft gate, halve pyramid_add_lot) recommended next. Full charter + V2-V5 variations + decision rules: [`H3_SPREAD_WINDOW_C_CHARTER.md`](outputs/system_reports/06_strategy_research/H3_SPREAD_WINDOW_C_CHARTER.md).

- **Deployment baseline:** H3_spread@3 EUR/USDJPY 15m d=8 e=5.0 r=1.0 (locked 2026-05-22). Pareto over @2 on Windows A/B; Window C still −112% — deployment is regime-conditional, awaiting the detector above. Closed exploration axes (do NOT re-explore): macro filter, correlation filter, adverse-stop, reverse-cross timing, TF, entry-delay. Remaining axes: (a) the active-charter detector, (b) β-weighted cointegration → see next item, (c) different basket pair.

- **COINTREV v1.2 — ready to build:** Design doc locked at [`v1_2_strategy_design/DESIGN_DOC.md`](outputs/cointegration_screener_v1/v1_2_strategy_design/DESIGN_DOC.md). Trigger ledger populated (865 first-crossing events, 1y backfill). Phase 3 realized-backtest falsified v2.1's pessimistic prediction (realized 80-95% vs predicted 25-30%; see [`REPORT_2026-05-23.md`](outputs/cointegration_screener_v1/realized_backtest/REPORT_2026-05-23.md)). Implementation = ~4-6h dedicated session.

- **Daily broker-spec refresh chained** (2026-05-23): TS_Execution `extract_symbol_specs.py` migrated to DATA_INGRESS post-hook. Daily run auto-refreshes Trade_Scan YAMLs at `data_access/broker_specs/OctaFx/` — review with `git diff` and commit when ready.
