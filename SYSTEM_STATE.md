# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-06-20T14:09:02Z
>
> SESSION SNAPSHOT — regenerated at session **start and end** (`python tools/system_introspection.py`).
> If `Generated:` is >16 h old this file is stale — re-run before trusting the numbers.
> Ephemeral content only. Durable entries (invariant proposals, code-cited decisions) belong in `INVARIANT_PROPOSALS.md`.

## Engine
- **Version:** 1.5.10 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 13 directives

## Ledgers

- **Master Filter:** 1268 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 126 rows — CORE: 4, FAIL: 117, WATCH: 5
  - **Single-Asset Composites:** 51 rows — CORE: 8, FAIL: 43

- **Candidates (FPS):** 386 rows — CORE: 15, FAIL: 245, RESERVE: 26, WATCH: 100

## Portfolio (TS_Execution)
- **Total entries:** 0 | **Enabled:** 0
- LIVE: 0 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 19 | Latest: `DRY_RUN_2026_06_09__ca6acb78`

## Data Freshness
- Latest bar: **2026-06-20** | Symbols: 221

## Artifacts
- Run directories: 3334

## Git Sync
- Remote: IN SYNC (vs `origin/main`)
- Working tree: 1 uncommitted
- Last substantive commit: `3bcdf705 docs(research): SPX500 RSI MR â€” Stage-2 regime-survival + 10-index breadth`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [SIZE] RESEARCH_MEMORY.md 36 KB / 186 lines (approaching 40 KB / 600 line cap) — compaction available via `python tools/compact_research_memory.py`
- [CALENDAR] Saturday — weekly cadence slot for `/repo-cleanup-refactor` + `/system-health-maintenance` Phase 1 (run before close to land in the closing snapshot)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Max ~5 lines. Verbose detail → outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced). Promote to BUILD after ≥1 gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence (shipped 2026-06-07, ba3b82cf) doubled daily upserts (1860+126 vs 930+64 rows) and added ~80–180s/run (screener block ~3 min now). Promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `tools/refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass field to authorize refreshes (debt-marked in code + plan, operator-flagged). Promote to BUILD (dedicated refresh-intent signal) when a 2nd refresh use-case (baskets / master_filter) needs the auth path. First seen 2026-06-07.
- [MONITOR] RESEARCH_MEMORY.md size — 32.6 KB / 40 KB ceiling (154 lines), ~81% of cap (corrected; prior note said 36 KB/90%). Compaction is a no-op until entries predate `ARCHIVE_BEFORE=2026-05-22`; to create headroom, bump `ARCHIVE_BEFORE` then `--apply`. Freeze watch-item (see Active Charter). First seen 2026-06-19.
- [SKILL_REFACTOR] Changes D+F deferred — session-close §3.3 → repo-cleanup-refactor §1d; system-health-maintenance §5/§6 overlap removal. Detail: backlog report.
- [NEXT-FOCUS] ★FULL 5-BASKET FLEET LIVE on canonical z=2.5 (2026-06-19). All 5 cointegration baskets (CADJPYUSDCHF/CHFJPYEURUSD/EURJPYGBPJPY/GBPAUDUSDCHF/EURJPYUSDJPY) signal-driven + HEALTHY on OctaFX-Demo 213872531; TS_Basket_Supervisor RE-ENABLED (5-min daemon, crash-survival). **Substrate hardened — immutable deployment descriptors:** the 06-16 corpus prune had deleted all 5 baskets' directives from `backtest_directives/completed/` (live producers read from there → would SystemExit on cold-start). FIX (operator-approved, protected-infra): producer now reads `strategy_pool/<ID>/directive.txt` (prune-immune, deployment-owned) first, falls back to completed/; promotion co-locates it; consistency-gated on directive_id. Canonical config = z_entry=2.5 + coint_break_exit=true + entry_fill_timing=current_bar_open (the LAST-DEPLOYED 06-13 config; vault z=2.0 snapshot was stale — reconstructed from producer.log banner, faithfulness-verified). See [[immutable-deployment-descriptors]], [[restore-source-fidelity-gap]]. Entry regime-gated: only EURJPYGBPJPY currently 'cointegrated'; other 4 'breaking' → FLAT until re-cointegration. OPEN: (a) provenance smell — canonical directive keeps ID while params changed (signature should fold params); (b) promotion run receipts ALSO pruned (golden test can't run — same artifact-loss class); (c) weekend-flat policy (see DECISION below); (d) collect live evidence (regime-gated).
- [DECISION 2026-06-07] Weekend scheduler (`TS_Friday_Shutdown` Windows task → `tools/orchestration/stop_execution.py`) audited → LIFECYCLE-REVIEW bucket with burn-in/shadow: DISABLED, delegate `TS_Execution/tools/stop_execution.py` MISSING, hardwired to old `src/main.py --phase 2` daemon (stood down), basket shim imports none of it. Shim's own weekend handling (heartbeat-stale skip-open + fill-verify ABORTED_FLAT + reconcile NOOP) makes it redundant. RESIDUAL GAP (design decision before go-live): no proactive weekend-flatten — a basket IN at Fri 22:00 is held across the 48h gap, and reactive close needs a live tick, so weekend-flat must come from the PRODUCER emitting FLAT before close (producer-policy choice).
- [NOTE-FOR-FUTURE / post-freeze] Engine header stamp drift — the basic/current engine still stamps an old `1.5.8` version in a header in some place(s), while canonical COMPUTE is `v1.5.10` (charged, FROZEN 2026-06-17). STAMP/label mismatch, NOT a compute defect (per [[engine-identity-is-compute-not-stamp]]: the imported module defines the result; the stamp can mislabel). Operator decision 2026-06-19: do NOT rectify during the freeze — note only. Post-freeze: locate the exact stale stamp + correct to 1.5.10. Verification scope, if any: **1.5.10 only** (do NOT touch the legitimate archived `engine_dev/.../v1_5_8` frozen-engine dir, which correctly contains 1.5.8).
- [BACKLOG] Smaller deferred items (Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, basket provenance, CLAUDE.md doc) → [`outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md`](outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md)
- [DRIFT] retire backlog (~330 superseded runs un-retired, incl. this session's Stage-1 SPX500 RSI run aa2a6d → superseded by Stage-2 51d49c9b). Retire tooling (rerun-backtest Phase C) is still PENDING → un-actionable until built; defer, not a fire. First seen 2026-06-20.

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-06-16T08:14:14+00:00 @ ae7e29ae.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Active Charter — 2026-06-20 — infra-freeze
**Focus:** Business-as-usual EXCEPT the heavy stuff — **no big pipeline refactors, no heavy infra sessions, no new engine/capability builds** (FROZEN 2026-06-20 → ~2026-06-27, 1 week). Research proceeds but **adapts to EXISTING engine capabilities — do NOT add a new capability to enable a research idea**. Infra/pipeline work only if absolutely required (a fatal criterion below); defer the rest past 2026-06-27.
**Routine carve-out (NOT frozen — runs as usual):** session-lifecycle skills `/session-start`, `/session-close`, `/session-retro`. Their routine core — commit/push, SYSTEM_STATE regen + vault snapshot, memory writes/consolidation — is normal session hygiene, not frozen infra. The boundary: session-close's heavier ROUTED extras (`/repo-cleanup-refactor`, `/pipeline-state-cleanup`, `/system-health-maintenance`, `/skill-maintenance`) stay deferred under the freeze unless fatal.
**Fatal-only exception criteria (the ONLY reasons to break the freeze):** (1) NAS/DR backup broken (no disaster recovery); (2) data or ledger corruption / integrity breach; (3) the pipeline cannot run ANY directive at all (research fully blocked); (4) the live 5-basket fleet failing with capital/risk exposure; (5) security/credential compromise. Everything else — performance, cleanup, refactors, cosmetic, single-tool bugs, memory-cap approach — **log and defer past 2026-06-27**.
**Freeze watch-items (non-fatal; monitor, do not fix mid-freeze):** MEMORY.md 173/200 lines + RESEARCH_MEMORY.md ~32.6 KB/40 KB — if a research-heavy week nears a cap, archive/consolidate is the fix *after* the freeze (or the one allowed lightweight exception). Live 5-basket fleet runs through the freeze (operational, not infra) — leave it unless criterion (4) trips.
**Sessions on this charter:**
- 2026-06-19 — set up pre-freeze: NAS-backup DR repaired (persistent credential — was a reboot-dropped session credential) + hardened (`/XD data_root`, `/XF` SQLite sidecars, `TS_Obsidian_Vault` added) + version-controlled at `infra/`; pipeline-state cleanup done; preflight `REF_INTEGRITY` tripwire + git-hygiene fixes landed. Freeze begins 2026-06-20.
- 2026-06-20 — research session; 2 operator-approved freeze overrides (MPS: drop redundant `all_profitable` column + add SQL-backed `universe` elite/all column with elite-default AutoFilter; build idea-69 SPX500 RSI-MR strategy). Research: cointegration BTCUSDEUSTX50 episode-vs-strategy study (full-window run = regime-conditional, not a portable edge) + Cointegration Research Universe report/funnel (265→36); new SPX500 RSI Power Zone MR arc (idea 69) Stage-1/2 + 10-index breadth — edge real (SPX500/NAS100 PF ~1.7) but ~8 trades/yr, too sparse to deploy standalone. Freeze otherwise held.

#### Engine no-liquidation fidelity limitation — ACCEPTED-WITH-MITIGATION (disclosed 2026-06-16)
The frozen execution engine (v1.5.8 / v1.5.9 / v1.5.10) models NO margin-call/liquidation. Under leveraged sizing — `granular_parity` (the cointegration baseline default since 2026-06-04) and `vol_parity` — a basket can run to NEGATIVE equity intra-run instead of liquidating at the stake, so modeled net%/maxDD% can exceed 100% or show a fictitious recovery. **Scope: backtest-FIDELITY only** — live trades at fixed 0.01 lot are broker-margined; notional sizing is mathematically bounded (floor is a no-op there). **Mitigation (now LIVE):** analysis-layer floor `tools/leverage_liquidation_adjust.py` (net→-100 / maxDD→100 / ret_dd→-1 when maxDD>100%, i.e. trough equity < 0), wired into `tools/cointegration_aggregator.py` (default-on; 8 of 2,377 current corpus rows floored). NOT fixed in the frozen engine by design (run-halting would stall corpus generation — operator decision 2026-06-04). Also disclosed on `engine_dev/universal_research_engine/v1_5_10/engine_manifest.json` (`known_limitations`). Ref: `outputs/system_reports/06_strategy_research/SZVP_LEVERAGE_FORENSIC.md`, `[[project-v1_5_10-canonical-readiness]]` R7/R8.

#### COINTREV live exit gap — RESOLVED + LIVE 2026-06-19 (was DEPLOYMENT BLOCKER, found 2026-06-05)
**Verified wired + effective end-to-end on 2026-06-19** (this status corrects the prior "remains a go-live prerequisite / not yet wired"). The full chain runs live: `basket_producer.py` `_fetch_daily_regime` reads the daily regime from `cointegration.db` → `_attach_coint_regime` ffill-projects it onto the 15m bars as `coint_regime` → `pine_ratio_zrev_v1._regime_break_fires` (`tools/recycle_rules/pine_ratio_zrev_v1.py:544-567`) liquidates to FLAT + latches `_regime_broken` the moment the pair leaves `cointegrated` (anything ≠ 'cointegrated', i.e. breaking OR broken). The canonical directive for all 5 live baskets carries `coint_break_exit: true` (deployed via the immutable-descriptor migration 2026-06-19). producer.log confirms it ran `coint_break_exit=True` 06-11→06-13 already. So a live position can no longer hang on a broken spread. **Follow-ups (historical):** (a) `realized_net%` + `cycles≥1` ranking fix — DONE 2026-06-06; (b) `coint_break_exit` gate — MERGED 2026-06-06, now ENABLED + verified live 2026-06-19. See `[[project_cointegration_exit_gap_and_cycle_metric]]`, `[[immutable-deployment-descriptors]]`.

#### Engine-identity contradictory stamp — RESOLVED + BULLETPROOFED 2026-06-16 (charter task_edc22e4d, commits `22112c5b` + hardening `4f5ac8fb`, branch `fix/engine-identity-convergence`)
Per-path consolidation landed, then an adversarial 5-dimension audit drove a full bulletproofing pass (operator: "everything, all paths"): gate-enforced lock (pre-commit roster + `_GATE_TEST_SUITE`), single-source basket ABI via `basket_runner` re-export (kills drift both directions), single-strategy verifies the loaded module's own ENGINE_VERSION (catches the live `v1_5_3`→1.5.4 folder skew), cointegration writer requires engine_version, AST+behavioral guard over all 4 basket surfaces, live-heartbeat + pre-promote-replay engine stamps. Locked by `tests/test_engine_identity_convergence.py` (11 cases, in the commit gate). Details: `[[engine-identity-is-compute-not-stamp]]`. **Basket:** all four stamps (manifest/input_provenance, run_metadata.json, STRATEGY_CARD.md, cointegration_sheet row) route through the new single source `run_pipeline.py:_basket_compute_engine_version()` = `engine_abi.v1_5_9.ENGINE_VERSION`, override-inert. Investigation finding: the *committed* basket dispatch was ALREADY converged on the compute (1.5.9); the "1.5.10" in run 28e7277b's `manifest.json` was a transient 2026-06-14 working-tree relic (operator's active v1_5_10 work), not reproducible with committed code — so the basket change is a drift-lock, behaviour unchanged. **Single-strategy (the genuinely-live divergence):** `run_stage1.py:run_engine_logic` silently fell back to v1_5_6 compute while keeping the requested label on `ModuleNotFoundError` (live under override=1.5.10; v1_5_10 ships no `main.py`) — now fail-fast. The shared `get_engine_version()` was left untouched (charter constraint honoured). Doctrine: `[[engine-identity-is-compute-not-stamp]]`.

#### Baskets promoted to CHARGED v1.5.10 — Phase B (baskets) + Phase C (single-asset active_engine) flips DONE 2026-06-17 (supersedes the "v1.5.9 / behaviour-unchanged" + "active_engine stays v1_5_8" status)
The single-source basket ABI now resolves to **`engine_abi.v1_5_10`** (charged), not v1.5.9. `basket_runner` re-points via `config.engine_authority.CANONICAL_ENGINE_ABI`; direction-aware spread is charged at the fast-path entry (`basket_runner._run_fast_path`) and the PineZRev `_liquidate` exit (cycle-aware via `effective_direction`); round-trip pays exactly one spread/leg/side; strict no-op at spread=0 (byte-identical to v1.5.9). The 2026-06-16 "1.5.10 was a transient relic / basket behaviour unchanged" note is **deliberately reversed** — v1.5.10 is now the **FROZEN canonical basket compute** (vaulted `vault/engines/Universal_Research_Engine/v1_5_10/`, manifest `vaulted:true`/`FROZEN`/`freeze_date:2026-06-17`). `active_engine` is now **v1_5_10** (single-asset Phase C flip DONE 2026-06-17, commit bb15c768; single-asset runs self-report the cost regime via run_stage1 `spread_model`/`spread_coverage_pct`, charging trade-level-proven). Positive proof `tests/test_v1510_fast_path_charge.py`; convergence gate re-proves stamp==compute==1.5.10. Commits `363c8179` (flip) + `cd2e229b` (promotion). The cost regime of NEW basket runs is now `spread_charged`. Refs: `[[project-v1_5_10-canonical-readiness]]`, `outputs/system_reports/01_system_architecture/V1_5_10_CANONICAL_FLIP_DESIGN.md`.
