# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 2 uncommitted

> Generated: 2026-05-27T13:37:42Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 0 directives

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
- Latest bar: **2026-05-27** | Symbols: 221

## Artifacts
- Run directories: 1057

## Git Sync
- Remote: IN SYNC
- Working tree: 2 uncommitted
- Last substantive commit: `5b178e3 tests: update lineage_pruner_quarantine_filter for build_keep_runs 3-tuple`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- (none — no drift signals exceed threshold this session)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Use this for deferral decisions that lack an auto-signal (e.g., 'deferred performance test until post-Phase-7b'). Distinct from Known Issues Manual: this section is for *deferred opportunities*, not unresolved problems. -->
- [SKILL_REFACTOR] **Change C — delete `/session-close §3.2 Document audit`.** Manual checklist with no detection signal; per the design-principle banner (2026-05-25, commit `b02656a`) it doesn't earn a slot in session-close. Action: either remove the section entirely (doc consolidation already covered by `/repo-cleanup-refactor §4` with stronger rules) OR convert it into a real doc-staleness scan. Earliest revisit: 2026-06-01.
- [SKILL_REFACTOR] **Change D — move `/session-close §3.3 Artifact cleanup` into `/repo-cleanup-refactor §1d`.** The full root-untracked + scratch detection belongs in the repo-cleanup skill. Keep one minimal check in session-close: "any tracked file under `/tmp/`?" (real invariant-8 violation). Earliest revisit: 2026-06-01.
- [SKILL_REFACTOR] **Change F — strip `/system-health-maintenance` §5 / §6 / §8 overlap.** §5 (vault) duplicates `/update-vault`; §6 (Excel format) duplicates `/format-excel-ledgers`; §8 (memory compaction) is the only home for the compaction logic but is also referenced from `/session-close §3.9`. Action: delete §5 + §6; keep §8 as canonical home, reference from elsewhere. Resulting scope of `/system-health-maintenance`: preflight + recovery + smoke tests + migration only. Earliest revisit: 2026-06-01. Defer this longest — cross-skill refactors create silent doc drift if rushed.
- [CODE_DRY] **Extract `_leg_pnl_usd` shared helper across `tools/recycle_rules/h2_compression.py` + `h2_recycle.py`.** Bodies are byte-identical modulo error-message rule-name (52 lines each). NOT a candidate for unification with `h2_recycle_v3.py` (different signature: takes `ref_closes` for cross-pair USD conversion). Surfaced by `/repo-cleanup-refactor` 2026-05-26. Deferred because `tools/recycle_rules/` was touched 2026-05-24 for the `leg_direction_flip_bug` Option-B fix — anti-pattern: "Don't extract refactors during high-stakes pre-deployment windows". Recommend: land after H2 strategy lock (per `[[project_h2_engine_promotion_plan]]` Phase 7b gate). One commit; new `tools/recycle_rules/_basket_pnl.py`; full basket regression suite (127+ tests). Earliest revisit: post-Phase-7a-ack.

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 16 acknowledged failure(s) (last refreshed 2026-05-26 @ 255f2d84). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+13 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Active Charter — 2026-05-27 — advisory-to-enforced
**Focus:** Today's session surfaced five separate cases where existing advisory tools (skills, memory entries, "MANDATORY FIRST STEP" notes) were bypassed during execution. The fix is structural — convert each advisory check into an enforced gate / hook / CI test. Full plan + acceptance criteria + priority order in [`outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md`](outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md). Start next session by reading that document, picking task A (directive-naming ↔ rule_name validator), and implementing per the acceptance criteria.

**Sessions on this charter:**
- 2026-05-27 — plan authored; commits 544c361 / 12455b9 / 478389b landed the retroactive fix for failure mode #5 (state_lifecycle Baskets blindness). Five gates A-E remain to build (8-10 hours estimated).
- 2026-05-27 (later) — appended refactoring backlog F1-F3 to plan (commit f4bfc3e); 1700-line `run_pipeline.py` and 422-line `load_basket_leg_data` flagged as decomposition targets. NEW deferred work surfaced at session-close: `ledger_db --export` reverted today's MPS row drops because cleanup tools (repair_integrity, custom Baskets drop) operate on Excel only; SQL is the source of truth. The whole pipeline-state-cleanup workflow needs SQL-side parity. Added as enforcement plan addendum candidate next session.

<!-- (4h backfill gen-2 completed 2026-05-27;
     coverage 2023-12-28 → 2026-05-27, 561,685 rows in cointegration_daily) -->
