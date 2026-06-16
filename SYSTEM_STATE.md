# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 7 symbol(s) stale (>3 days behind)

> Generated: 2026-06-16T08:17:49Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 1 directives

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
- Snapshots: 19 | Latest: `DRY_RUN_2026_06_09__ca6acb78`

## Data Freshness
- Latest bar: **2026-06-16** | Symbols: 221 | **Stale (>3d): 7**

## Artifacts
- Run directories: 3316

## Git Sync
- Remote: IN SYNC (vs `origin/main`)
- Working tree: clean
- Last substantive commit: `8857f863 skills: maintenance audit 2026-06-16 â€” 1 soft fix (friction-log char cap)`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [SIZE] RESEARCH_MEMORY.md 34 KB / 124 lines (approaching 40 KB / 600 line cap) — compaction available via `python tools/compact_research_memory.py`

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Max ~5 lines. Verbose detail → outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced). Promote to BUILD after ≥1 gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence (shipped 2026-06-07, ba3b82cf) doubled daily upserts (1860+126 vs 930+64 rows) and added ~80–180s/run (screener block ~3 min now). Promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `tools/refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass field to authorize refreshes (debt-marked in code + plan, operator-flagged). Promote to BUILD (dedicated refresh-intent signal) when a 2nd refresh use-case (baskets / master_filter) needs the auth path. First seen 2026-06-07.
- [SKILL_REFACTOR] Changes D+F deferred — session-close §3.3 → repo-cleanup-refactor §1d; system-health-maintenance §5/§6 overlap removal. Detail: backlog report.
- [DRIFT] pipeline-state-cleanup deferred — 19 orphan MPS::Baskets rows + lineage_pruner blocked (TS_Execution was live). Run off-hours; procedure in backlog report.
- [NEXT-FOCUS] CADJPYUSDCHF: pipeline COMPLETE through ★FIRST LIVE DEMO LIFECYCLE (DONE 2026-06-08). Promoted (vault DRY_RUN_2026_06_07__75a53641 + strategy_pool) → shim built (TS_Execution f462f5e) → daemon-hardened (c9b8a068/d30631a) → DRY-validated (Path A/B) → LIVE demo FLAT→IN→FLAT clean on OctaFX-Demo 213872531: CADJPY buy 0.01 tkt 5672856680 @114.968 + USDCHF sell 0.01 tkt 5672856682 @0.79640; dispatch_group OPEN → close_group CLOSED → flat independently verified; bridge restored pristine. Proven LIVE: reconcile→dispatch/close→LiveBasketBroker→MT5→fill-verify, demo gate, per-leg magics, atomic bridge, rate-limiter. NEXT (next session) = signal-driven producer — wire StreamingBasketRunner to live 15m feed (today's targets were scripted, not mechanic-derived). Go-live-to-REAL prereqs (NOT demo-blocking): coint_break_exit enable + coint_regime feed; weekend-flat policy (producer emits FLAT before Fri 22:00 — see DECISION below); supervised-task wrapper for unattended 24/5.
- [DECISION 2026-06-07] Weekend scheduler (`TS_Friday_Shutdown` Windows task → `tools/orchestration/stop_execution.py`) audited → LIFECYCLE-REVIEW bucket with burn-in/shadow: DISABLED, delegate `TS_Execution/tools/stop_execution.py` MISSING, hardwired to old `src/main.py --phase 2` daemon (stood down), basket shim imports none of it. Shim's own weekend handling (heartbeat-stale skip-open + fill-verify ABORTED_FLAT + reconcile NOOP) makes it redundant. RESIDUAL GAP (design decision before go-live): no proactive weekend-flatten — a basket IN at Fri 22:00 is held across the 48h gap, and reactive close needs a live tick, so weekend-flat must come from the PRODUCER emitting FLAT before close (producer-policy choice).
- [BACKLOG] Smaller deferred items (Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, basket provenance, CLAUDE.md doc) → [`outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md`](outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md)

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-06-16T08:14:14+00:00 @ ae7e29ae.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### COINTREV live exit gap — DEPLOYMENT BLOCKER (found 2026-06-05)
COINTREV has **no cointegration-break exit** — a live position hangs on a broken spread with no stop (`DATA_END` backtests backstop doesn't exist live). **Follow-ups:** (a) `realized_net%` + `cycles≥1` ranking fix — DONE 2026-06-06 (`feat/coint-realized-net-and-break-exit`); (b) `coint_break_exit` gate — MERGED to main 2026-06-06 (capability now on main); remains a go-live prerequisite to ENABLE on the live runner (+ `coint_regime` feed). See `[[project_cointegration_exit_gap_and_cycle_metric]]`.

#### Engine-identity contradictory stamp — RESOLVED + BULLETPROOFED 2026-06-16 (charter task_edc22e4d, commits `22112c5b` + hardening `4f5ac8fb`, branch `fix/engine-identity-convergence`)
Per-path consolidation landed, then an adversarial 5-dimension audit drove a full bulletproofing pass (operator: "everything, all paths"): gate-enforced lock (pre-commit roster + `_GATE_TEST_SUITE`), single-source basket ABI via `basket_runner` re-export (kills drift both directions), single-strategy verifies the loaded module's own ENGINE_VERSION (catches the live `v1_5_3`→1.5.4 folder skew), cointegration writer requires engine_version, AST+behavioral guard over all 4 basket surfaces, live-heartbeat + pre-promote-replay engine stamps. Locked by `tests/test_engine_identity_convergence.py` (11 cases, in the commit gate). Details: `[[engine-identity-is-compute-not-stamp]]`. **Basket:** all four stamps (manifest/input_provenance, run_metadata.json, STRATEGY_CARD.md, cointegration_sheet row) route through the new single source `run_pipeline.py:_basket_compute_engine_version()` = `engine_abi.v1_5_9.ENGINE_VERSION`, override-inert. Investigation finding: the *committed* basket dispatch was ALREADY converged on the compute (1.5.9); the "1.5.10" in run 28e7277b's `manifest.json` was a transient 2026-06-14 working-tree relic (operator's active v1_5_10 work), not reproducible with committed code — so the basket change is a drift-lock, behaviour unchanged. **Single-strategy (the genuinely-live divergence):** `run_stage1.py:run_engine_logic` silently fell back to v1_5_6 compute while keeping the requested label on `ModuleNotFoundError` (live under override=1.5.10; v1_5_10 ships no `main.py`) — now fail-fast. The shared `get_engine_version()` was left untouched (charter constraint honoured). Doctrine: `[[engine-identity-is-compute-not-stamp]]`.
