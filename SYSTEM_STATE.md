# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 2 commits not pushed to origin

> Generated: 2026-05-25T13:45:05Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 125 directives

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
- Latest bar: **2026-05-25** | Symbols: 221

## Artifacts
- Run directories: 1064

## Git Sync
- Remote: **2 commits ahead of origin**
- Working tree: 2 uncommitted
- Last substantive commit: `0704c1e session-close: narrow skill-maintenance trigger to SKILL.md modifications`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [SIZE] RESEARCH_MEMORY.md 37 KB / 129 lines (approaching 40 KB / 600 line cap) — compaction available via `python tools/compact_research_memory.py`

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Use this for deferral decisions that lack an auto-signal (e.g., 'deferred performance test until post-Phase-7b'). Distinct from Known Issues Manual: this section is for *deferred opportunities*, not unresolved problems. -->
- (none)

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-23 @ dbfa9c1a). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
