# 11_deployment_and_burnin

Read before changing promotion logic, burn-in workflows, dry-run vault, go-live package, strategy guard, or portfolio.yaml deployment path.

> **Last updated:** 2026-04-10

## Active Documents

| Document | Contents | Status |
|----------|----------|--------|
| `PROMOTION_FRICTION_AUDIT.md` | **Promotion pipeline friction audit.** 7 structural friction points from directive to burn-in: run discovery fallback, composite promotion gap, quality gate inconsistency, post-pipeline non-blocking artifacts, multi-symbol sync, edge_quality misrouting, no automated quality gate. Waves 1-5 + R6-R10 all implemented. | IMPLEMENTED (2026-04-12) |
| `LIFECYCLE_PLAN.md` | **Strategy lifecycle plan.** PROMOTE -> BURN_IN -> WAITING -> LIVE. 6-phase: vault completeness, explicit linkage, WAITING state, artifact protection, workflows, consistency guarantees. Includes quality gates and strategy traceability addendum. | IMPLEMENTED (Phase 1-5 done, Phase 3.3 burnin_monitor --json deferred) |
| `GOLIVE_PACKAGE_COMPATIBILITY_AUDIT.md` | Audit of go-live package vs current deployment path. Pipeline topology, dry-run vault overlap, coverage gaps, remediation options | REFERENCE (Option B partially implemented — guard wiring deferred) |
| `CLASSIFICATION_REFERENCE.md` | **Classification terminology reference.** CORE/WATCH/FAIL gates across filter_strategies, portfolio_evaluator, and promote quality gate. Metric disambiguation (edge_quality vs edge_ratio vs SQN). Composite promotion usage. | NEW (2026-04-12) |
| `DEPLOYMENT_UNIFICATION_PLAN.md` | 5-phase unification plan: vault extension, runtime safety (guard integration), promotion flow, dead code removal, verification tests | PARTIALLY IMPLEMENTED (vault extension done, guard integration NOT done) |

## Scope

This folder covers the full deployment lifecycle from research completion to live execution:

- **Promotion:** `promote_to_burnin.py` — single entry point (vault snapshot + portfolio.yaml append)
- **Selection:** IN_PORTFOLIO flag flow (sync_portfolio_flags.py, auto-chained by promote)
- **Burn-in:** BURN_IN status automation from portfolio.yaml, cleanup protection
- **Vault:** Immutable artifact snapshots in DRY_RUN_VAULT/ (~100+ files per strategy)
- **Go-live package:** Stage-10 deployment artifacts (generate_golive_package.py) — **functionally orphaned**
- **Runtime safety:** Signal integrity guard + kill-switch (strategy_guard.py) — exists but **not wired** into TS_Execution
- **Orchestration:** MT5 launch, watchdog, market hours gate, clean shutdown

## Current State (2026-04-10)

- **19 entries** in portfolio.yaml: 11 LEGACY (pre-vault), 8 BURN_IN (4 strategies x symbols)
- **0 WAITING**, **0 LIVE** — transitions not yet exercised
- **Vault:** Full snapshots with run_snapshot/, all 7 profiles, broker specs, selected_profile.json
- **Traceability:** `strategy_ref.json` pointer files with SHA-256 code_hash in TradeScan_State/strategies/
- **Quality gates:** edge_quality (Portfolios) and SQN (Single-Asset) enforced at portfolio classification

## Related Workflows

| Workflow | File |
|----------|------|
| Promote to burn-in | `.agents/workflows/promote.md` + `tools/promote_to_burnin.py` |
| Transition to waiting | `.agents/workflows/to-waiting.md` + `tools/transition_to_waiting.py` |
| Transition to live | `tools/transition_to_live.py` |
| Add strategy to portfolio | `.agents/workflows/portfolio-selection-add.md` |
| Remove strategy from portfolio | `.agents/workflows/portfolio-selection-remove.md` |
| Workspace vault snapshot | `.agents/workflows/update-vault.md` |

## Key Findings

**2026-04-03:** The go-live package (Stage 10) and the dry-run vault workflow were built independently to solve overlapping problems. Recommended path: merge go-live safety features into the dry-run vault (Option B).

**2026-04-10:** Option B partially implemented. Vault now includes broker specs, selected_profile.json, full run snapshot, and all 7 deployable profiles. Guard integration (signal verification, kill-switch) remains an open gap — accepted as deferred risk during burn-in observation phase. Step 7 is sole authority for deployed_profile selection.
