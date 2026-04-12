# 11_deployment_and_burnin

Read before changing promotion logic, burn-in workflows, dry-run vault, strategy guard, or portfolio.yaml deployment path.

> **Last updated:** 2026-04-12

## Active Documents

| Document | Contents | Status |
|----------|----------|--------|
| `PROMOTION_FRICTION_AUDIT.md` | **Promotion pipeline friction audit.** 7 structural friction points from directive to burn-in: run discovery fallback, composite promotion gap, quality gate inconsistency, post-pipeline non-blocking artifacts, multi-symbol sync, edge_quality misrouting, no automated quality gate. Waves 1-5 + R6-R10 all implemented. | IMPLEMENTED (2026-04-12) |
| `LIFECYCLE_PLAN.md` | **Strategy lifecycle plan.** PROMOTE -> BURN_IN -> WAITING -> LIVE. 6-phase: vault completeness, explicit linkage, WAITING state, artifact protection, workflows, consistency guarantees. Includes quality gates, strategy traceability, and runtime guard integration. | FULLY IMPLEMENTED (2026-04-12) |
| `GOLIVE_PACKAGE_COMPATIBILITY_AUDIT.md` | Audit of go-live package vs current deployment path. All gaps resolved: go-live archived, guard wired via vault, validate_safety_layers rewritten. | ARCHIVED (2026-04-12) — retained for historical reference |
| `CLASSIFICATION_REFERENCE.md` | **Classification terminology reference.** CORE/WATCH/FAIL gates across filter_strategies, portfolio_evaluator, and promote quality gate. Metric disambiguation (edge_quality vs edge_ratio vs SQN). Composite promotion usage. | REFERENCE (2026-04-12) |
| `DEPLOYMENT_UNIFICATION_PLAN.md` | 5-phase unification plan: vault extension, runtime safety (guard integration), promotion flow, dead code removal, verification tests | FULLY IMPLEMENTED (2026-04-12) |

## Scope

This folder covers the full deployment lifecycle from research completion to live execution:

- **Promotion:** `promote_to_burnin.py` — single entry point (vault snapshot + portfolio.yaml append)
- **Selection:** IN_PORTFOLIO flag flow (sync_portfolio_flags.py, auto-chained by promote)
- **Burn-in:** BURN_IN status automation from portfolio.yaml, cleanup protection
- **Vault:** Immutable artifact snapshots in DRY_RUN_VAULT/ (~100+ files per strategy)
- **Runtime safety:** Signal integrity guard + kill-switch (`strategy_guard.py` + `guard_bridge.py`) — **wired into TS_Execution** (two-tier signal validation, 3-rule kill-switch, MismatchTracker)
- **Go-live package:** ARCHIVED to `archive/tools/` — superseded by vault-based guard system
- **Orchestration:** MT5 launch, watchdog, market hours gate, clean shutdown

## Current State (2026-04-12)

- **19 entries** in portfolio.yaml: 11 LEGACY (pre-vault), 8 BURN_IN (4 strategies x symbols)
- **0 WAITING**, **0 LIVE** — transitions not yet exercised
- **Vault:** Full snapshots with run_snapshot/, all 7 profiles, broker specs, selected_profile.json
- **Runtime guards:** `guard_bridge.py` constructs `StrategyGuard` per slot from vault at TS_Execution startup; `require_vault: false` (transition period)
- **Traceability:** `strategy_ref.json` pointer files with SHA-256 code_hash in TradeScan_State/strategies/
- **Quality gates:** edge_quality (Portfolios) and SQN (Single-Asset) enforced at portfolio classification
- **Validation:** `validate_safety_layers.py` — 6 vault-based tests (all pass)

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

**2026-04-10:** Option B partially implemented. Vault now includes broker specs, selected_profile.json, full run snapshot, and all 7 deployable profiles. Step 7 is sole authority for deployed_profile selection.

**2026-04-12:** Option B **fully implemented**. Guard integration complete: `strategy_guard.py` extended with `from_vault()` + two-tier `validate_signal()`; `guard_bridge.py` created in TS_Execution; 3 hooks wired into `main.py` (construct, validate, record). `generate_golive_package.py` archived. `validate_safety_layers.py` rewritten with 6 vault-based tests. All deployment safety gaps closed. System is ready for `require_vault: true` after clean observation period.
