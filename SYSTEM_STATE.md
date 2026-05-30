# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-30T17:32:37Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 488 directives

## Ledgers

- **Master Filter:** 1257 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 126 rows — CORE: 4, FAIL: 117, WATCH: 5
  - **Single-Asset Composites:** 51 rows — CORE: 8, FAIL: 43

- **Candidates (FPS):** 381 rows — CORE: 15, FAIL: 242, RESERVE: 26, WATCH: 98

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-30** | Symbols: 221

## Artifacts
- Run directories: 1419

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last substantive commit: `4dc482f baseline: accept untagged COINTREV_meanrev rows after v1 cleanup`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- [SIZE] RESEARCH_MEMORY.md 37 KB / 86 lines (approaching 40 KB / 600 line cap) — compaction available via `python tools/compact_research_memory.py`
- [CALENDAR] Saturday — weekly cadence slot for `/repo-cleanup-refactor` + `/system-health-maintenance` Phase 1 (run before close to land in the closing snapshot)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen. Use this for deferral decisions that lack an auto-signal (e.g., 'deferred performance test until post-Phase-7b'). Distinct from Known Issues Manual: this section is for *deferred opportunities*, not unresolved problems. -->
- [SKILL_REFACTOR] **Change C — delete `/session-close §3.2 Document audit`.** Manual checklist with no detection signal; per the design-principle banner (2026-05-25, commit `b02656a`) it doesn't earn a slot in session-close. Action: either remove the section entirely (doc consolidation already covered by `/repo-cleanup-refactor §4` with stronger rules) OR convert it into a real doc-staleness scan. Earliest revisit: 2026-06-01.
- [SKILL_REFACTOR] **Change D — move `/session-close §3.3 Artifact cleanup` into `/repo-cleanup-refactor §1d`.** The full root-untracked + scratch detection belongs in the repo-cleanup skill. Keep one minimal check in session-close: "any tracked file under `/tmp/`?" (real invariant-8 violation). Earliest revisit: 2026-06-01.
- [SKILL_REFACTOR] **Change F — strip `/system-health-maintenance` §5 / §6 / §8 overlap.** §5 (vault) duplicates `/update-vault`; §6 (Excel format) duplicates `/format-excel-ledgers`; §8 (memory compaction) is the only home for the compaction logic but is also referenced from `/session-close §3.9`. Action: delete §5 + §6; keep §8 as canonical home, reference from elsewhere. Resulting scope of `/system-health-maintenance`: preflight + recovery + smoke tests + migration only. Earliest revisit: 2026-06-01. Defer this longest — cross-skill refactors create silent doc drift if rushed.
- [CODE_DRY] **Extract `_leg_pnl_usd` shared helper across `tools/recycle_rules/h2_compression.py` + `h2_recycle.py`.** Bodies are byte-identical modulo error-message rule-name (52 lines each). NOT a candidate for unification with `h2_recycle_v3.py` (different signature: takes `ref_closes` for cross-pair USD conversion). Surfaced by `/repo-cleanup-refactor` 2026-05-26. Deferred because `tools/recycle_rules/` was touched 2026-05-24 for the `leg_direction_flip_bug` Option-B fix — anti-pattern: "Don't extract refactors during high-stakes pre-deployment windows". Recommend: land after H2 strategy lock (per `[[project_h2_engine_promotion_plan]]` Phase 7b gate). One commit; new `tools/recycle_rules/_basket_pnl.py`; full basket regression suite (127+ tests). Earliest revisit: post-Phase-7a-ack.
- [MONITOR] RESEARCH_MEMORY.md size — 34->35.3 KB this session, 40 KB cap; promote to compaction (`compact_research_memory.py` / advance ARCHIVE_BEFORE) when >38 KB AND still growing; discard this monitor if a compaction resets it below first (first seen 2026-05-29, session-retro)
- [MONITOR] conclusion-write-path provenance gate — `research_memory_append` accepts an unvalidated run_id and auto-memory is ungated (AGENT.md Invariant #31 is STOP-doctrine, NOT yet mechanically gated for conclusions). Promote to BUILD only after >=1 operational gate-shakeout session (per the advisory-to-enforced standing directive). First seen 2026-05-29.
- [NEXT-FOCUS] Lifecycle granularity-mismatch — WORKING HYPOTHESIS (analysis-only, NO remedy decided): lifecycle burden originates from arc-level intent expressed at artifact level; high-fan-out arcs amplify one decision into 100-1000+ actions. Full evidence in auto-memory `project_lifecycle_granularity_mismatch.md`. Next session's question: smallest mechanisms to reduce decision fan-out without a new state system. Start from this framing, not lineage-contamination. (first seen 2026-05-29)
- [SIZE] auto-memory MEMORY.md at/over 200-line cap — run `/anthropic-skills:consolidate-memory` next session (HIGH-ROI from session-retro; index truncates beyond 200).
- [RETRO] Session retro 2026-05-30 — 9 findings parked as a durable report at `outputs/session_retros/SESSION_RETRO_2026-05-30.md`. HIGH ROI: gate-verify step in corpus generation (catches operator-locked-rule conflicts at the source). Companion snapshot: `outputs/system_reports/06_strategy_research/COINTEGRATION_V1_TO_V2_TRANSITION.md` (v1→v2 baseline + CR-EXIT-FIX rule revision + 488/473 corpus aggregation).
- [BLOCKED] Tag 20 retired COINTREV_meanrev rows DB-side — v1 cointegration cleanup (commit 950a7ab) exposed pre-existing untagged 91_PORT_*_COINTREV_S*_V1_P00 rows (idea 91, retired 2026-05-21). `tests/test_quarantine_integrity.py::test_deprecated_rules_have_all_mps_rows_tagged` acknowledged into broader-pytest baseline at close (commit 4dc482f). Spawned as a separate task chip; revert baseline after fix.
- [BLOCKED] Wire run_stage1's warmup pre-extension into basket pipeline — `_load_symbol_5m` strictly filters to `[start_date, end_date]`, no per-leg warmup bars. 15 short-window v2 directives silently failed at `pine_ratio_zrev_v1`'s `2 * n_window` assertion (488 → 473 ledger delta this session). Spawned as a separate task chip; details in COINTEGRATION_V1_TO_V2_TRANSITION.md §4.5.

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 17 acknowledged failure(s) (last refreshed 2026-05-30 @ e9856a41). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+14 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Charter COMPLETE — 2026-05-27 — advisory-to-enforced (closed 2026-05-28)
**Focus:** Convert five bypassed advisory checks into enforced gates / hooks / CI tests. Plan (archived): [`outputs/system_reports/09_incident_reports/ENFORCEMENT_PLAN_2026-05-27_CLOSED.md`](outputs/system_reports/09_incident_reports/ENFORCEMENT_PLAN_2026-05-27_CLOSED.md). **STATUS: COMPLETE — all 7 enforcement units landed 2026-05-28.** The original "advisory bypass" failure mode is now solved structurally, not rhetorically. F-series refactor backlog (F1-F3 in the plan) may now begin.

**Sessions on this charter:**
- 2026-05-27 — plan authored; commits 544c361 / 12455b9 / 478389b landed the retroactive fix for failure mode #5 (state_lifecycle Baskets blindness). Five gates A-E remain to build (8-10 hours estimated).
- 2026-05-27 (later) — appended refactoring backlog F1-F3 to plan (commit f4bfc3e). NEW deferred work surfaced: `ledger_db --export` reverted MPS row drops because cleanup tools operate on Excel only; SQL is source of truth. Pipeline-state-cleanup needs SQL-side parity (addendum candidate).
- 2026-05-28 — **CHARTER COMPLETE.** All units landed: A rule-binding gate (44b9506) + A2 strict flip (7f10de6); B window-validity continuous-span gate (5b954bc); C intent memory-hints (e65f0da); D methodology-citation gate (3eb6371); E1 sheet-coverage CI (692485f) + E2 registry state matrix + reconcile-authoritative cleanup (f4ceb51). Plan archived to `09_incident_reports/ENFORCEMENT_PLAN_2026-05-27_CLOSED.md`. MEMORY consolidated (enforcement-family entry + convention→mechanically-verified reframe). Key cross-cutting decision: every gate is repo-local + deterministic — D explicitly rejected ~/.claude auto-memory coupling in favor of an in-repo methodology_registry.yaml. Live preflight GREEN.
- **NEXT SESSION DIRECTIVE (operator, 2026-05-28): do NOT start the F1-F3 refactor immediately.** First spend ≥1 *operational* session using the hardened gates and observe natural friction — the repo now enforces assumptions that were historically only implied. Watch: (1) B rejects (is continuous-span over-constraining given 1-15 day cointegration spans? is methodology_override reached legitimately?); (2) A2 namespace strictness (does any real directive class hit unknown-pattern reject?); (3) D citation ergonomics (is the opt-in workflow usable?). F-series + pipeline-state-cleanup SQL-parity addendum come only after that. See [[project_governance_enforcement_family]].

<!-- (4h backfill gen-2 completed 2026-05-27;
     coverage 2023-12-28 → 2026-05-27, 561,685 rows in cointegration_daily) -->
