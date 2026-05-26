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

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-23 @ dbfa9c1a). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
- [BACKGROUND_PROCESSES_RUNNING — 2026-05-26 close] Two long-running cointegration history backfills launched mid-session and continue past session close:
  - **A (1d backfill 2024-01-01 → 2025-05-22):** `tmp/backfill_4h_history.py --tf 1d`. ETA ~83 min from launch at 10:49 UTC. ~25 sec/date. Additive (INSERT OR REPLACE) — safe to interrupt and resume.
  - **B (4h backfill 2024-01-01 → today):** `tmp/backfill_4h_history.py --tf 4h`. ETA ~14 hours from launch at 10:49 UTC. ~85 sec/date. Same idempotent pattern.
  - Both write to `Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db` table `cointegration_daily` (tf column distinguishes rows). On next session start: verify completion via `python -c "import sqlite3; db = sqlite3.connect(r'...cointegration.db'); print(db.execute('SELECT tf, COUNT(*) FROM cointegration_daily GROUP BY tf').fetchall())"`. Expect 1d rows ≥ 240K + 1d backfill, 4h rows ~480K when fully done.
  - Unblocks: out-of-sample verification on Tier-A Pine pairs (Priority 1 from `PHASE2_PINE_PORT_CONSOLIDATED_2026-05-26.md`).
  - If processes died (server reboot etc.): re-run same commands; `INSERT OR REPLACE` makes them idempotent.
