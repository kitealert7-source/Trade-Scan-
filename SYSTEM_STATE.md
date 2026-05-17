# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-17T02:16:02Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 321 directives

## Ledgers

- **Master Filter:** 1151 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 121, PROFILE_UNRESOLVED: 1, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 521 rows — CORE: 14, FAIL: 351, LIVE: 13, RESERVE: 25, WATCH: 118

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-15** | Symbols: 235

## Artifacts
- Run directories: 1418

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last substantive commit: `b969135 test: re-anchor session-close Â§6b expectations to Â§3.5 post-refactor`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-05-15T18:47:52+00:00 @ fbccd79d.

### Manual (unresolved + operationally relevant only)
<!-- Policy: items here drive startup decisions for the NEXT session.
     Resolved / superseded / struck-through / informational-only entries
     must be REMOVED (not archived) — git preserves history. Session-close
     §3.2 prunes closed entries before the closing snapshot. -->

- **Phase 7a Stage 5 — pending operational supervisor.** Windows Task Scheduler XML + heartbeat-stale monitor (per earlier spec) — no longer a code blocker; just needs the supervisor configuration.

- **Broader-pytest failures outside gate suite (3 pre-existing remaining):**
  - `tests/test_state_paths_worktree.py` ×2 — pre-existing from 2026-05-11.
  - `tests/test_basket_directive_phase5.py::test_directive_legs_match_h2_spec` — pre-existing; the test asserts legacy H2 spec (USDJPY-short) but the directive was corrected to USDJPY-long in commit `5528ff1` (Phase 5d.1.1). Test needs to be updated to reflect the corrected spec; the directive is right, the test is stale.
