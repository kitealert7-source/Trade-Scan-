# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 1 commits not pushed to origin

> Generated: 2026-06-06T10:49:56Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 6963 directives

## Ledgers

- **Master Filter:** 1257 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 126 rows — CORE: 4, FAIL: 117, WATCH: 5
  - **Single-Asset Composites:** 51 rows — CORE: 8, FAIL: 43

- **Candidates (FPS):** 381 rows — CORE: 15, FAIL: 242, RESERVE: 26, WATCH: 98

## Portfolio (TS_Execution)
- **Total entries:** 0 | **Enabled:** 0
- LIVE: 0 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-06-06** | Symbols: 221

## Artifacts
- Run directories: 3642

## Git Sync
- Remote: **1 commits ahead of origin/feat/live-basket-bridge-v0** (vs `origin/feat/live-basket-bridge-v0`)
- Working tree: clean
- Last substantive commit: `894b257e fix(introspection): compare vs origin/<branch> not origin/main`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [CALENDAR] Saturday — weekly cadence slot for `/repo-cleanup-refactor` + `/system-health-maintenance` Phase 1 (run before close to land in the closing snapshot)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Max ~5 lines. Verbose detail → outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced). Promote to BUILD after ≥1 gate-shakeout session. First seen 2026-05-29.
- [MONITOR — CLEARED 2026-06-06] All 3 branches pushed to origin (feat/live-basket-bridge-v0, feat/coint-realized-net-and-break-exit, feat/basket-execution-p2). Next: merge to main.
- [SKILL_REFACTOR] Changes D+F deferred — session-close §3.3 → repo-cleanup-refactor §1d; system-health-maintenance §5/§6 overlap removal. Detail: backlog report.
- [CODE_DRY] `_leg_pnl_usd` + `_safe_float` deduplication deferred (Protected Infra; revisit next DRY pass). Detail: backlog report.
- [DRIFT] pipeline-state-cleanup deferred — 19 orphan MPS::Baskets rows + lineage_pruner blocked (TS_Execution was live). Run off-hours; procedure in backlog report.
- [NEXT-FOCUS] Research roadmap: sizing arc CLOSED 2026-06-04 (GP frozen). Pivot: capital model → portfolio construction → live-deployment-sizing.
- [BACKLOG] Smaller deferred items (Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, basket provenance, CLAUDE.md doc) → [`outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md`](outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md)

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-06-01T12:03:48+00:00 @ bf217717.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### COINTREV live exit gap — DEPLOYMENT BLOCKER (found 2026-06-05)
COINTREV has **no cointegration-break exit** — a live position hangs on a broken spread with no stop (`DATA_END` backtests backstop doesn't exist live). **Follow-ups:** (a) `realized_net%` + `cycles≥1` ranking fix — DONE 2026-06-06 (`feat/coint-realized-net-and-break-exit`); (b) `coint_break_exit` gate — implemented on same branch, NOT yet merged. Go-live prerequisite. See `[[project_cointegration_exit_gap_and_cycle_metric]]`.
