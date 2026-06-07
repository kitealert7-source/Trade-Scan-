# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-06-07T16:33:34Z
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
- Snapshots: 15 | Latest: `DRY_RUN_2026_06_07__75a53641`

## Data Freshness
- Latest bar: **2026-06-07** | Symbols: 221

## Artifacts
- Run directories: 3643

## Git Sync
- Remote: IN SYNC (vs `origin/main`)
- Working tree: 1 uncommitted
- Last substantive commit: `28aa8937 session: accept 5 known-nonfunctional test failures into broader-pytest baseline`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [CALENDAR] Sunday — weekly cadence slot for `/repo-cleanup-refactor` + `/system-health-maintenance` Phase 1 (run before close to land in the closing snapshot)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Max ~5 lines. Verbose detail → outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced). Promote to BUILD after ≥1 gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence (shipped 2026-06-07, ba3b82cf) doubled daily upserts (1860+126 vs 930+64 rows) and added ~80–180s/run (screener block ~3 min now). Promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `tools/refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass field to authorize refreshes (debt-marked in code + plan, operator-flagged). Promote to BUILD (dedicated refresh-intent signal) when a 2nd refresh use-case (baskets / master_filter) needs the auth path. First seen 2026-06-07.
- [SKILL_REFACTOR] Changes D+F deferred — session-close §3.3 → repo-cleanup-refactor §1d; system-health-maintenance §5/§6 overlap removal. Detail: backlog report.
- [DRIFT] pipeline-state-cleanup deferred — 19 orphan MPS::Baskets rows + lineage_pruner blocked (TS_Execution was live). Run off-hours; procedure in backlog report.
- [NEXT-FOCUS] CADJPYUSDCHF promoted (vault DRY_RUN_2026_06_07__75a53641 + strategy_pool descriptor) + basket SHIM BUILT (TS_Execution f462f5e) + daemon-hardened (Trade_Scan c9b8a068 / TS_Execution d30631a) + DRY-validated (Path A broker-free + Path B real-shim-vs-live-demo, both green; bridge dir pristine). ★NEXT = first LIVE demo lifecycle — BLOCKED on FX reopen (~Sun 21:00–22:00 UTC). Resume: 3-point pre-check (terminal/login+trade_mode/trade_allowed) THEN session-open check (ticks must be fresh, not 40h-stale) → producer ScriptedRunner writes IN to TradeScan_State/TS_SIGNAL_STATE/h2_live/CADJPYUSDCHF → `python src/basket_shim.py --live` opens both 0.01 legs → verify positions → producer writes FLAT → close → verify flat. Demo gate locked OctaFX-Demo 213872531.
- [DECISION 2026-06-07] Weekend scheduler (`TS_Friday_Shutdown` Windows task → `tools/orchestration/stop_execution.py`) audited → LIFECYCLE-REVIEW bucket with burn-in/shadow: DISABLED, delegate `TS_Execution/tools/stop_execution.py` MISSING, hardwired to old `src/main.py --phase 2` daemon (stood down), basket shim imports none of it. Shim's own weekend handling (heartbeat-stale skip-open + fill-verify ABORTED_FLAT + reconcile NOOP) makes it redundant. RESIDUAL GAP (design decision before go-live): no proactive weekend-flatten — a basket IN at Fri 22:00 is held across the 48h gap, and reactive close needs a live tick, so weekend-flat must come from the PRODUCER emitting FLAT before close (producer-policy choice).
- [BACKLOG] Smaller deferred items (Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, basket provenance, CLAUDE.md doc) → [`outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md`](outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md)

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 5 acknowledged failure(s) (last refreshed 2026-06-07 @ c9b8a068). Tests: test_vault_layout, test_dispatch_against_h2_directive_with_, test_install_sh_installs_pre_push_hook (+2 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### COINTREV live exit gap — DEPLOYMENT BLOCKER (found 2026-06-05)
COINTREV has **no cointegration-break exit** — a live position hangs on a broken spread with no stop (`DATA_END` backtests backstop doesn't exist live). **Follow-ups:** (a) `realized_net%` + `cycles≥1` ranking fix — DONE 2026-06-06 (`feat/coint-realized-net-and-break-exit`); (b) `coint_break_exit` gate — MERGED to main 2026-06-06 (capability now on main); remains a go-live prerequisite to ENABLE on the live runner (+ `coint_regime` feed). See `[[project_cointegration_exit_gap_and_cycle_metric]]`.
