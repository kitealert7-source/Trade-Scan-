# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-06-29T16:59:24Z
>
> SESSION SNAPSHOT — regenerated at session **start and end** (`python tools/system_introspection.py`).
> If `Generated:` is >16 h old this file is stale — re-run before trusting the numbers.
> Ephemeral content only. Durable entries (invariant proposals, code-cited decisions) belong in `INVARIANT_PROPOSALS.md`.

## Engine
- **Version:** 1.5.11 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 1 directives

## Ledgers

- **Master Filter:** 27 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 0 rows — no status column
  - **Single-Asset Composites:** 0 rows — no status column

- **Candidates (FPS):** 17 rows — FAIL: 6, WATCH: 11

## Portfolio (TS_Execution)
- **Total entries:** 0 | **Enabled:** 0
- LIVE: 0 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 19 | Latest: `DRY_RUN_2026_06_09__ca6acb78`

## Data Freshness
- Latest bar: **2026-06-26** | Symbols: 221

## Artifacts
- Run directories: 490

## Git Sync
- Remote: IN SYNC (vs `origin/main`)
- Working tree: clean
- Last substantive commit: `cf3c13f9 docs(engine): engine consolidation plan â€” single active engine (DESIGN APPROVED)`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- (none — no drift signals exceed threshold this session)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Max ~5 lines. Verbose detail → outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced). Promote to BUILD after ≥1 gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence (shipped 2026-06-07, ba3b82cf) doubled daily upserts (1860+126 vs 930+64 rows) and added ~80–180s/run (screener block ~3 min now). Promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `tools/refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass field to authorize refreshes (debt-marked in code + plan, operator-flagged). Promote to BUILD (dedicated refresh-intent signal) when a 2nd refresh use-case (baskets / master_filter) needs the auth path. First seen 2026-06-07.
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

#### Active Charter — (none — PARKED 2026-06-29)

> **No active charter.** The `2026-06-20 infra-freeze` charter was **PARKED 2026-06-29** (operator-confirmed: "the first infra freeze is lifted completely"). It was fulfilled: freeze lifted 2026-06-24, **v1.5.11 Patch A promoted CANONICAL** (steps 1–4 + H6, byte-identical; commits `7f6d982` / `f94bc097`), demo fleet stood down, post-purge store charged-only + RED reconcile cleared, broader-pytest gate parallelized. Full history → `[[project_v1_5_11_patch_a_canonical]]`. Open follow-ups (operator's call, none urgent): Patch A.1 event-log · `CURRENT`/`LIVE_ABI` dispatch convergence (DESIGNED+DEFERRED). Set a new charter when the next multi-session focus is chosen.

#### Stage-1 emitter drops `entry_reason` — minor open follow-up (from RESOLVED worker NO_TRADES investigation, 2026-06-21)
Native signal-overlap means `entry_reason` is dropped at emit and must be reconstructed downstream. Low priority; the parent worker NO_TRADES / anti-masking investigation is RESOLVED (full record in git history + `[[worker-stage1-complete-not-run-proof]]`).

#### Engine no-liquidation fidelity limitation — ACCEPTED-WITH-MITIGATION (disclosed 2026-06-16)
The frozen execution engine (v1.5.8 / v1.5.9 / v1.5.10) models NO margin-call/liquidation. Under leveraged sizing — `granular_parity` (the cointegration baseline default since 2026-06-04) and `vol_parity` — a basket can run to NEGATIVE equity intra-run instead of liquidating at the stake, so modeled net%/maxDD% can exceed 100% or show a fictitious recovery. **Scope: backtest-FIDELITY only** — live trades at fixed 0.01 lot are broker-margined; notional sizing is mathematically bounded (floor is a no-op there). **Mitigation (now LIVE):** analysis-layer floor `tools/leverage_liquidation_adjust.py` (net→-100 / maxDD→100 / ret_dd→-1 when maxDD>100%, i.e. trough equity < 0), wired into `tools/cointegration_aggregator.py` (default-on; 8 of 2,377 current corpus rows floored). NOT fixed in the frozen engine by design (run-halting would stall corpus generation — operator decision 2026-06-04). Also disclosed on `engine_dev/universal_research_engine/v1_5_10/engine_manifest.json` (`known_limitations`). Ref: `outputs/system_reports/06_strategy_research/SZVP_LEVERAGE_FORENSIC.md`, `[[project-v1_5_10-canonical-readiness]]` R7/R8.

> _Pruned 2026-06-29 (weekly maintenance): 5 fully-resolved entries removed from this notepad — EXEMPT_SHEETS `Notes` (RESOLVED 06-25), worker NO_TRADES anti-masking (RESOLVED 06-21), COINTREV live exit gap (RESOLVED + LIVE 06-19), engine-identity contradictory stamp (RESOLVED + BULLETPROOFED 06-16), baskets→CHARGED v1.5.10 Phase B/C (DONE 06-17). Full text in git history; durable homes in `[[project_cointegration_exit_gap_and_cycle_metric]]`, `[[engine-identity-is-compute-not-stamp]]`, `[[project-v1_5_10-canonical-readiness]]`, `[[project_v1_5_11_patch_a_canonical]]`._
