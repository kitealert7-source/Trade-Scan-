# H3 `leg_direction_flip_bug` Rehabilitation — Forensic Audit Trail

**Date:** 2026-05-25
**Trigger commit:** `ac14d1e` (BasketLeg.effective_direction — Option-B architectural fix)
**Scope:** 62 H3_spread bidirectional pre-Option-B rows transitioned to terminal governance state.

---

## What happened

The `leg_direction_flip_bug` was a rule-side PnL accounting error: `_leg_pnl_usd_universal`, `_liquidate`, and `_emit_record` all read `leg.direction` (YAML BASE) instead of `leg.state.direction` (engine's actual cycle direction). On every SHORT_SPREAD cycle, PnL was sign-flipped. The engine's open path was correct; the bug lived in rule-side helpers.

Three rules were affected:
- `pine_ratio_zrev_v1`
- `cointegration_meanrev_v1_2`
- `H3_spread@2` and `@3` with `bidirectional: true`

The fix landed as commit `ac14d1e` on 2026-05-24 15:59 UTC, adding `BasketLeg.effective_direction` as a property that returns `state.direction` when in position, falling back to YAML BASE otherwise. All 19 cycle-aware reads in 9 rule files were migrated to `effective_direction`. Three workaround patches from earlier in the day were removed.

After the fix, the existing MPS Baskets rows from pre-fix runs contained mathematically incorrect numbers — silently visible at CORE/WATCH ranks. This rehabilitation pass re-ran the bug-affected directives under correct accounting, established replacement lineage where the verdict-sensitivity was non-trivial, and closed the remaining tail.

## Scope summary

| Category | Count | New `quarantine_status` |
|---|---:|---|
| H3 first-pass tags (proven evidence chain) | 5 | `SUPERSEDED` |
| Phase 1: CORE bidirectional pre-fix reruns | 22 | `SUPERSEDED` |
| Phase 2: WATCH + near-threshold FAIL reruns | 16 | `SUPERSEDED` |
| Phase 2 terminal closure (triage-skipped FAILs) | 13 | `ARCHIVED_UNRESOLVED` |
| **Total H3 bidirectional rows governance-finalized** | **56** | |
| COINTREV v1 cohort (separate retirement, same session) | 49 | `RETIRED` |

The 5 initial proven tags + 22 Phase-1 + 16 Phase-2 + 13 archived = 56 H3 bidirectional rows. Plus 49 COINTREV v1 RETIRED tags from the separate equal-lot conflation retirement that ran in parallel = 105 governance row transitions total.

## `SUPERSEDED` vs `ARCHIVED_UNRESOLVED`

Both values live in the `quarantine_status` column on MPS Baskets. Both cause the row to be hidden from default views (formatter + aggregators filter on `quarantine_status.notna()`). They differ in semantic and operational meaning:

### `SUPERSEDED`
- **Meaning:** This row's metrics are mathematically incorrect (sign-flipped accounting on SHORT_SPREAD cycles). A replacement run under correct accounting exists.
- **Required fields:** `superseded_by_run_id` MUST be populated with the post-fix sibling's run_id. `quarantine_reason` cites the bug + commit `ac14d1e`.
- **Lifecycle:** Terminal — never un-tag. Replacement lineage is the authoritative reading from now on.
- **Discoverability:** Anyone investigating this directive can follow `superseded_by_run_id` to the canonical replacement.

### `ARCHIVED_UNRESOLVED`
- **Meaning:** This row is bug-affected but its pre-fix verdict is so far from any governance threshold that re-running under corrected accounting cannot plausibly change the outcome. Closed as low-value rehabilitation candidate, NOT forgotten debt.
- **Required fields:** `superseded_by_run_id` is explicitly NULL. `quarantine_reason` carries the verbatim triage rationale (catastrophic_dd / modest_loss / catastrophic_loss class).
- **Lifecycle:** Terminal unless a future methodological change materially alters the expected outcome space (e.g., quality-gate reweighting that could lift catastrophic-DD rows). Reruns are NOT auto-authorized.
- **Discoverability:** Anyone investigating sees the triage rationale directly in the row metadata; the absence of `superseded_by_run_id` is a positive signal (no replacement, by intent).

**Operational consequence:** `SUPERSEDED` rows have a 1:1 mapping to a post-fix run; `ARCHIVED_UNRESOLVED` rows do not and never will. Distinguishing these in tooling prevents the false-positive "this row has no replacement, must be unfinished work" interpretation.

## Frozen evaluator integrity

A single evaluator (`tmp/h3_supersession_dryrun_FROZEN_20260525.py`, sha256=`124f42978b92...`) was used across:
- Phase 1 manifest generation
- Phase 1 sibling validation + tagging
- Phase 2 manifest generation
- Phase 2 sibling validation + tagging
- Phase 2 closure drift-check (each archived row re-confirmed still unresolved before tagging)

The sha256 is recorded in every `checksums.json` and every `dispatch_order.json` in this audit trail. If a tooling change wants to claim downstream effect on this rehabilitation, it must demonstrate sha-difference is harmless.

## Directory layout

```
2026-05-25_h3_rehabilitation/
├── README.md  (this file)
├── phase1_core_batch/
│   ├── restoration_manifest.json   — 22 git commits + blob SHA-256 per directive
│   ├── dispatch_order.json         — frozen dispatch sequence + checksums
│   ├── dispatch_log.jsonl          — per-run telemetry (run_id, PASS/FAIL, timings)
│   ├── checksums.json              — frozen-evaluator + manifest hashes
│   ├── before_tagging_counts.json  — MPS state pre-tag (visible CORE/WATCH 105)
│   ├── after_tagging_counts.json   — MPS state post-tag
│   ├── reconciliation_report.md    — frozen-evaluator evidence-chain verification
│   └── final_reconciliation.md     — before/after + gate verification
│
└── phase2_watch_fail_triage/
    ├── triage_decisions.json       — 16 DISPATCH + 13 SKIP with per-row rationale
    ├── restoration_manifest.json   — 16 git commits + blob SHA-256
    ├── dispatch_order.json
    ├── dispatch_log.jsonl
    ├── checksums.json
    ├── archived_unresolved_manifest.json  — 13 terminal-closure records
    └── final_reconciliation.md
```

## Cross-references

- **Rule-side fix:** commit `ac14d1e` (basket_runner: BasketLeg.effective_direction property + remove Option-A workarounds)
- **Code-level guard:** `tools/basket_pipeline._validate_basket_id_convention` — enforces BIDIR/BEAR/BULL suffix convention so future bidirectional directives cannot ambiguously declare direction mode
- **CI regression guard:** `tests/test_quarantine_integrity.py` — both rule-side (retired rules tagged) and consumer-side (default projections exclude quarantined) integrity checks
- **Research memory:** `RESEARCH_MEMORY.md` 2026-05-25 entries:
  - `H3_rehabilitation_batch` (Phase 1)
  - `H3_rehabilitation_phase2` (Phase 2)
  - `terminal_closure / archived_unresolved_governance_state` (closure)
- **Related chip task output:** commits `0933560` through `9f7e040` (state lifecycle: admitted-sentinel design, recover_admitted_directive tool, 433-marker quarantine sweep, xlsx EOFError incident report)

## Replay protocol if needed

To re-derive any per-row provenance:

1. Look up the directive in MPS Baskets, read `quarantine_status` + `superseded_by_run_id` + `quarantine_reason`
2. If `SUPERSEDED`: locate the row in `phase{1|2}/restoration_manifest.json` for the source git commit; use `git show <commit>:backtest_directives/completed/<directive_id>.txt` to recover the pre-fix YAML
3. If `ARCHIVED_UNRESOLVED`: read `phase2/archived_unresolved_manifest.json` for the triage classification; do NOT auto-rerun

The scratch scripts (`01_*.py` through `06_*.py`) that produced these manifests lived in `tmp/rehabilitation_batch_20260525*/` and are NOT preserved here — they were the executable encoding of the policy, not the audit record. The audit record is the JSON/MD artifacts in this directory.
