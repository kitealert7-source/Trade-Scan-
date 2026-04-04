# 11_deployment_and_burnin

Read before changing promotion logic, burn-in workflows, dry-run vault, go-live package, strategy guard, or portfolio.yaml deployment path.

## Active Documents

| Document | Contents |
|----------|----------|
| `LIFECYCLE_PLAN.md` | **Strategy lifecycle plan.** PROMOTE -> BURN_IN -> WAITING -> LIVE. 6-phase: vault completeness, explicit linkage, WAITING state, artifact protection, workflows, consistency guarantees. Current state audit, vault gap analysis, portfolio.yaml schema extension, file-level changes |
| `GOLIVE_PACKAGE_COMPATIBILITY_AUDIT.md` | Audit of go-live package vs current deployment path. Pipeline topology, dry-run vault overlap, coverage gaps, remediation options |
| `DEPLOYMENT_UNIFICATION_PLAN.md` | **Implementation plan.** 5-phase unification: vault extension, runtime safety (guard integration), promotion flow, dead code removal, verification tests. Before/after architecture, file-level changes, effort estimate (11-15h) |

## Scope

This folder covers the full deployment lifecycle from research completion to live execution:

- **Promotion:** How strategies move from PORTFOLIO_COMPLETE to candidate ledger (filter_strategies.py)
- **Selection:** IN_PORTFOLIO flag flow (sync_portfolio_flags.py, portfolio-selection-add/remove workflows)
- **Burn-in:** BURN_IN status automation from portfolio.yaml, cleanup protection
- **Vault:** Dry-run artifact snapshots (DRY_RUN_VAULT/, backup_dryrun_strategies.py)
- **Go-live package:** Stage-10 deployment artifacts (generate_golive_package.py) -- currently stale
- **Runtime safety:** Signal integrity guard + kill-switch (strategy_guard.py) -- exists but not wired
- **Orchestration:** MT5 launch, watchdog, market hours gate, clean shutdown

## Related Workflows

| Workflow | File |
|----------|------|
| Promote to burn-in | `.agents/workflows/promote.md` |
| Transition to waiting | `.agents/workflows/to-waiting.md` |
| Transition to live | `tools/transition_to_live.py` |
| Add strategy to portfolio | `.agents/workflows/portfolio-selection-add.md` |
| Remove strategy from portfolio | `.agents/workflows/portfolio-selection-remove.md` |
| Workspace vault snapshot | `.agents/workflows/update-vault.md` |

## Key Finding (2026-04-03)

The go-live package (Stage 10) and the dry-run vault workflow were built independently to solve overlapping problems. Neither fully covers the deployment safety surface:

- **Vault covers:** Immutable snapshots, git tracing, baseline preservation
- **Go-live covers:** Signal hash verification, kill-switch, profile tamper detection, broker spec freezing
- **Neither covers:** The other's strengths

Recommended path: merge go-live safety features into the dry-run vault (Option B in the audit).
