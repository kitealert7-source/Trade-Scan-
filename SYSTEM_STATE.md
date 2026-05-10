# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-10T12:51:19Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 229 directives

## Ledgers

- **Master Filter:** 1069 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 480 rows — CORE: 14, FAIL: 315, LIVE: 13, RESERVE: 25, WATCH: 113

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-10** | Symbols: 243

## Artifacts
- Run directories: 1288

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `a29b73c chore: pipeline auxiliary â€” stop_contract_audit + tools_manifest`

## Known Issues
### Auto-detected (regenerated each run)
- **Post-merge watch:** 2/5 observed; status=ACTIVE; commit=1b6cc7b.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
- **3 pre-existing test failures (outside gate suite, not session-caused):**
  - `tests/test_indicator_semantic_contracts.py::test_referenced_indicators_declare_signal_primitive`
  - `tests/test_state_paths_worktree.py::test_real_state_paths_module_resolves_to_existing_dirs`
  - `tests/test_state_paths_worktree.py::test_trade_scan_root_invalid_env_falls_through`

  Last touched 2026-05-08 (`ada0f45`, `1e306d2`). Gate suite (70 tests in pre-commit) is green this session.
- **Intent-index audit (2026-05-10 close):** exit 1 (warnings only, errors=0). MISS clusters concentrated in `[promote]` (8 hits) and `[registry/governance/portfolio]` (1 each). 24h MISS rate 78/112 prompts — mostly old infrastructure conversation snippets, no genuine coverage gap surfaced.
- **PSBRK S03 V1 P00 (Pine v5 port) — closed FAIL** (SQN 1.41 / dd_pct 43.52% / top-5 86.5%). Parity-restored vs Pine; cross-broker friction + OctaFx-suboptimal Pine v5 params explain residual PnL gap. Tomorrow's open question: re-tune for Octa, run apples-to-apples vs P09 baseline, or move to a different idea. Full analysis in `~/.claude/projects/.../memory/project_psbrk_s03_v5_port.md`.
