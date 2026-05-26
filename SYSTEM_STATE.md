# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: 2 symbol(s) stale (>3 days behind)
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-26T11:00:31Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 214 directives

## Ledgers

- **Master Filter:** 1257 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 122, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 381 rows — CORE: 15, FAIL: 242, RESERVE: 26, WATCH: 98

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-26** | Symbols: 221 | **Stale (>3d): 2**

## Artifacts
- Run directories: 1170

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `9020490 session: idea gate refresh â€” tools_manifest regen`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [SIZE] RESEARCH_MEMORY.md 37 KB / 91 lines (approaching 40 KB / 600 line cap) — compaction available via `python tools/compact_research_memory.py`

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Use this for deferral decisions that lack an auto-signal (e.g., 'deferred performance test until post-Phase-7b'). Distinct from Known Issues Manual: this section is for *deferred opportunities*, not unresolved problems. -->
- [SKILL_REFACTOR] **Change C — delete `/session-close §3.2 Document audit`.** Manual checklist with no detection signal; per the design-principle banner (2026-05-25, commit `b02656a`) it doesn't earn a slot in session-close. Action: either remove the section entirely (doc consolidation already covered by `/repo-cleanup-refactor §4` with stronger rules) OR convert it into a real doc-staleness scan. Earliest revisit: 2026-06-01.
- [SKILL_REFACTOR] **Change D — move `/session-close §3.3 Artifact cleanup` into `/repo-cleanup-refactor §1d`.** The full root-untracked + scratch detection belongs in the repo-cleanup skill. Keep one minimal check in session-close: "any tracked file under `/tmp/`?" (real invariant-8 violation). Earliest revisit: 2026-06-01.
- [SKILL_REFACTOR] **Change F — strip `/system-health-maintenance` §5 / §6 / §8 overlap.** §5 (vault) duplicates `/update-vault`; §6 (Excel format) duplicates `/format-excel-ledgers`; §8 (memory compaction) is the only home for the compaction logic but is also referenced from `/session-close §3.9`. Action: delete §5 + §6; keep §8 as canonical home, reference from elsewhere. Resulting scope of `/system-health-maintenance`: preflight + recovery + smoke tests + migration only. Earliest revisit: 2026-06-01. Defer this longest — cross-skill refactors create silent doc drift if rushed.
- [CODE_DRY] **Extract `_leg_pnl_usd` shared helper across `tools/recycle_rules/h2_compression.py` + `h2_recycle.py`.** Bodies are byte-identical modulo error-message rule-name (52 lines each). NOT a candidate for unification with `h2_recycle_v3.py` (different signature: takes `ref_closes` for cross-pair USD conversion). Surfaced by `/repo-cleanup-refactor` 2026-05-26. Deferred because `tools/recycle_rules/` was touched 2026-05-24 for the `leg_direction_flip_bug` Option-B fix — anti-pattern: "Don't extract refactors during high-stakes pre-deployment windows". Recommend: land after H2 strategy lock (per `[[project_h2_engine_promotion_plan]]` Phase 7b gate). One commit; new `tools/recycle_rules/_basket_pnl.py`; full basket regression suite (127+ tests). Earliest revisit: post-Phase-7a-ack.

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-23 @ dbfa9c1a). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
- [MPS_LINEAGE_DRIFT — 2026-05-26 weekend-maintenance — RESOLVED 2026-05-26 same-session] ~~17 orphan run_ids + 22 missing-folder rows in MPS — pruner --execute blocked.~~ Resolved by `tools/state_lifecycle/repair_integrity.py` rewrite (commits `2363ef9` lineage_pruner skip-quarantined filter + `08ead58` repair_integrity rewrite + `2df26ba` missing-folder coverage). 35 rows tagged `quarantine_status=ARCHIVED_DEPENDENCY_LOST` (5 Portfolios + 30 SAC); zero rows deleted (append-only invariant honored); all four MPS sheets + both FSP sheets row-counts unchanged. Lineage_pruner dry-run now exits cleanly. The rewrite simultaneously closed two critical data-loss bugs in the old tool (single-sheet write would have deleted SAC + Baskets + Notes; `--action drop` would have violated append-only). For future operators: tool is now mark-only + multi-sheet-safe + dry-run-default; legacy `--action drop` is rejected with rc=2.
- [BACKGROUND_PROCESSES_RUNNING — 2026-05-26 close, updated 2026-05-26 weekend-maintenance] Cointegration history backfills:
  - **A (1d backfill 2024-01-01 → 2025-05-22): ~~COMPLETE~~** as of 2026-05-26 weekend-maintenance check. DB now spans 2023-12-29 → 2026-05-26 with 563,068 1d rows; process not in PID list.
  - **B (4h backfill 2024-01-01 → today): STILL RUNNING** (PID 32516, age 167min at check time). 4h coverage now 2023-12-28 → 2024-08-08 (~7 months of ~17 backfilled, ~137K rows). At ~85 sec/date the remaining ~9 months ≈ ~6-8h more. ETA still consistent with original ~14h projection.
  - Writes to `Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db` table `cointegration_daily` (tf column distinguishes rows). Verify via `python -c "import sqlite3; db = sqlite3.connect(r'...cointegration.db'); print(db.execute('SELECT tf, COUNT(*) FROM cointegration_daily GROUP BY tf').fetchall())"`. Expect 4h rows ~480K when fully done.
  - Unblocks: out-of-sample verification on Tier-A Pine pairs (Priority 1 from `PHASE2_PINE_PORT_CONSOLIDATED_2026-05-26.md`).
  - If process B dies (server reboot etc.): re-run same command; `INSERT OR REPLACE` makes it idempotent.
