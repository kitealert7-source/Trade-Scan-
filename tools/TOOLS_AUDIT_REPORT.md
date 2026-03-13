# TradeScan Tools Audit Report

## Audit Summary
- **Total Tools Analyzed**: 57
- **Active Tools**: 19
- **Operational Tools**: 32
- **Legacy Tools**: 4
- **Unknown Usage**: 2

---

## Tool Classification

### ACTIVE_TOOL
*Entry point used in normal system operation.*

- `run_pipeline`: Master pipeline orchestration
- `run_stage1`: Core execution harness
- `strategy_provisioner`: Core preflight provisioning
- `exec_preflight`: Direct execution preflight checks
- `generate_guard_manifest`: Integrity guard management
- `generate_engine_manifest`: Engine integrity authority
- `cleanup_reconciler`: Authoritative state reconciliation
- `report_generator`: Core automated reporting
- `run_portfolio_analysis`: Standard portfolio analysis loop
- `semantic_validator`: Authoritative directive validation
- `strategy_dryrun_validator`: Code-level strategy validation
- `directive_schema`: Single source of truth for YAML schema
- `canonical_schema`: Single source of truth for canonical schema
- `canonicalizer`: Core structural validation
- `execution_emitter_stage1`: Engine execution event emitter
- `stage2_compiler`: Core metric computation engine
- `stage3_compiler`: Core aggregation engine
- `format_excel_artifact`: System-wide formatting authority
- `safe_append_excel`: Concurrent-safe Excel appending

### OPERATIONAL_TOOL
*Occasionally used for maintenance or analysis.*

- `create_vault_snapshot`: Part of the `/update-vault` workflow
- `system_introspection`: Generates `SYSTEM_STATE.md`
- `create_audit_snapshot`: Operational audit snapshots
- `reset_directive`: Manual state correction tool
- `reconcile_portfolio_master_sheet`: Portfolio sheet reconstruction
- `profile_selector`: Ledger enrichment utility
- `rebuild_all_reports`: Batch report regeneration
- `configure_portfolio`: Portfolio setup/config utility
- `research_memory_append`: Research logging management
- `portfolio_evaluator`: Historical multi-instrument analysis
- `generate_sweep_08`: Targeted research sweep generator
- `analyze_capital_models`: Capital model performance analysis
- `analyze_range_breakout_vol`: Range breakout volatility analysis
- `inspect_trend_score`: Trend scoring inspection utility
- `inspect_master_filter`: Master filter inspection utility
- `sweep_registry_gate`: Phase-2 sweep governance gate
- `namespace_gate`: Phase-1 namespace governance gate
- `filter_strategies`: Strategy append-only filtering
- `audit_compliance`: Compliance audit utility
- `validate_high_vol`: Data integrity validation guard
- `validate_lookahead`: Lookahead bias detection utility
- `validate_safety_layers`: Safety layer validation guard
- `verify_batch_robustness`: Batch stability verification
- `verify_batch_trend`: Batch trend scoring verification
- `verify_collision_fix`: Systemic collision verification
- `verify_engine_integrity`: Engine modification detection
- `verify_formatting`: Formatting compliance check
- `convert_directive`: Migration/scaffold utility
- `convert_promoted_directives`: Directive namespace migration
- `system_preflight`: General system readiness check
- `skill_loader`: Skill initialization for agentic operations
- `sweep_engine`: Secondary sweep execution engine

### LEGACY_TOOL
*Appears unused or tied to older architecture.*

- `migrate_atomic_runs_v2`: One-time migration script (Task Complete)
- `migrate_trade_density`: Archival migration utility; no current references
- `apply_portfolio_constraints`: Replacement candidate for current orchestration
- `capital_wrapper`: Legacy deployable wrapper; superseded by orchestration

### UNKNOWN_USAGE
*Usage cannot be determined automatically.*

- `purge_run_id`: Operational script for manual state cleaning
- `system_introspection`: While used for state files, not explicitly in the pipeline loop

---

## Potential Legacy Tools
The following tools are candidates for archival:
1. `migrate_atomic_runs_v2`: The migration is finished; script is dead wood.
2. `migrate_trade_density`: No active references in the current pipeline structure.
3. `capital_wrapper`: Superseded by the `execution_engine` and `orchestration` flows.

## Tools Requiring Manual Review
1. `purge_run_id`: Likely a "Break Glass" tool for developers; should be moved to `tools/tmp` if rarely used.
2. `profile_selector`: Usage is sparse in the main loop; confirm if this is still the authoritative method for ledger enrichment.

---
**Audit Conclusion**: The Tools layer is 89% active or operational. The remaining 11% (Legacy/Unknown) represents negligible risk but should be pruned to maintain documentation hygiene.
