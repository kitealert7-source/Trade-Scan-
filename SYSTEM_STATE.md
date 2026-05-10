# SYSTEM STATE

## SESSION STATUS: BROKEN
- BROKEN: 5 commits not pushed to origin

> Generated: 2026-05-10T05:33:09Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 226 directives

## Ledgers

- **Master Filter:** 1068 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 479 rows — CORE: 14, FAIL: 314, LIVE: 13, RESERVE: 25, WATCH: 113

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-10** | Symbols: 243

## Artifacts
- Run directories: 1286

## Git Sync
- Remote: **5 commits ahead of origin**
- Working tree: clean
- Last substantive commit: `be1b260 meta: add no-naked-fuzzy doctrine rule + enforcement test`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch:** 1/5 observed; status=ACTIVE; commit=1b6cc7b.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
- **3 pre-existing test failures (outside gate suite, not session-caused):**
  - `tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive`
  - `tests/test_state_paths_worktree.py::test_real_state_paths_module_resolves_to_existing_dirs`
  - `tests/test_state_paths_worktree.py::test_trade_scan_root_invalid_env_falls_through`

  Last touched 2026-05-08 (`ada0f45`, `1e306d2`) — predate this session. Gate suite (idea_evaluation, namespace, sweep_registry, fvg, td004, known_issues, intent_injector) is 175/175 green.
- **Branch state:** closing on feature branch `claude/sharp-benz-68250e`; HEAD pushed to origin. The introspection's `commits_ahead` counter compares to `origin/main` and shows 5 unmerged feature commits — that is the intended PR-pending state, not a push gap.
