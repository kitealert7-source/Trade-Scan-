# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-06-30T08:27:59Z
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
- Last substantive commit: `9d079e69 chore(tmp): auto-prune cointegration backfill workdirs at the source (cause fix)`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- (none — no drift signals exceed threshold this session)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Max ~5 lines. Verbose detail → outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced); promote to BUILD after a gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence, screener block ~3 min/run; promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass; promote to BUILD when a 2nd refresh use-case needs the auth path. First seen 2026-06-07.
- [DRIFT] retire backlog (~330 superseded runs un-retired) — un-actionable until rerun-backtest Phase-C retire tooling is built; defer, not a fire. First seen 2026-06-20.
- [BACKLOG] smaller deferred items (Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, skill-refactor D+F, basket weekend-flatten policy) → [DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md](outputs/system_reports/DEFERRED_MAINTENANCE_BACKLOG_2026-06-06.md)

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-06-16T08:14:14+00:00 @ ae7e29ae.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Active Charter — (none — PARKED 2026-06-29)

> **No active charter.** The 2026-06-20 infra-freeze charter was fulfilled + PARKED 2026-06-29 (freeze lifted, v1.5.11 Patch A canonical, demo fleet stood down). 2026-06-30: engine compute + ABI consolidations completed (single active engine + single ABI) → the `CURRENT`/`LIVE_ABI` dispatch-convergence follow-up is now largely MOOT (nothing left to select). History → [[project_v1_5_11_patch_a_canonical]] + [[project_engine_consolidation_2026_06_30]]. Set a new charter when the next multi-session focus is chosen.
