# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 3 uncommitted

> Generated: 2026-05-13T15:40:12Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 242 directives

## Ledgers

- **Master Filter:** 1133 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 130 rows — CORE: 4, FAIL: 120, PROFILE_UNRESOLVED: 1, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 511 rows — CORE: 14, FAIL: 342, LIVE: 13, RESERVE: 25, WATCH: 117

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-13** | Symbols: 1

## Artifacts
- Run directories: 1320

## Git Sync
- Remote: IN SYNC
- Working tree: 3 uncommitted
- Last substantive commit: `2130e3b docs(CLAUDE.md): add topic-index entries for basket pipeline + engine_abi`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch CLOSED_OK:** 5/5 runs clean (commit 1b6cc7b). Run `python tools/post_merge_watch.py --archive` to clear.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **Broader-pytest failures outside gate suite (3 pre-existing):**
  - `tests/test_state_paths_worktree.py` ×2 — pre-existing from 2026-05-11.
  - `tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive` — pre-existing; 4 new indicator primitives missing from the Classifier Gate `_ALLOWED_PRIMITIVES` allowlist. Separate concern from the Stage-0.5 allowlist landed today.
  Note: the 2 `test_registry_integrity` failures from earlier today's close were closed by commit `7388453` (22-stub metadata backfill).
- ~~Manual-section persistence caveat~~ — **closed by commit `670bf02`** (`tools/system_introspection.py` now preserves the Manual section across regen verbatim; tests pinned in `tests/test_system_state_manual_persist.py`). This entry's own survival across the next regen is the validation proof.

- **Adversarial-test sys.modules ordering bug (introduced 2026-05-13 by Phase 0a):**
  `tests/test_engine_abi_adversarial.py::_force_reload_abi` deletes every
  `engine_abi*` entry from `sys.modules` and re-imports. When subsequent
  test modules then import `engine_abi.v1_5_9`, the runtime manifest
  assertion in `__init__.py:79` fires because module identity differs
  from the cached reference. All 5 tests in `test_engine_abi_adversarial.py`
  and `test_basket_phase5c_real_data.py::test_dispatch_against_h2_directive_with_real_data`
  fail in full-suite pytest runs while passing individually. Pre-commit
  gate roster is unaffected (does not include these tests).
  Fix candidate: `_force_reload_abi` should `importlib.reload()` instead
  of bare `del + import_module`, OR add a session-scoped pytest fixture
  that re-imports `engine_abi.v1_5_9` after any adversarial test. Filed
  as Phase 0a follow-up; not blocking H2 promotion plan execution.
