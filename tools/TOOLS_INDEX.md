# TradeScan Tools Index

This index provides a comprehensive map of the operational tools within the `tools/` layer. It serves as the authoritative surface for platform orchestration, maintenance, and research validation.

## Primary Entry Tools
Primary Entry Tools are shortcuts to commonly used tools.
They are also listed in their operational categories below.

Tool | Purpose
--- | ---
run_pipeline | Primary pipeline execution entrypoint (v3.2)
run_stage1 | Multi-asset batch execution harness
generate_sweep_08 | Strategy research sweep generator
run_portfolio_analysis | Governance-grade portfolio analysis engine

---

## Tool Execution Convention
Tools are executed as Python modules from the repository root.

Example usage:

```bash
python -m tools.run_pipeline
python -m tools.analyze_capital_models
```

Running tools via module execution ensures consistent imports and environment resolution.

Operational tools live at the top level of the `tools/` directory.
Library modules inside subfolders (for example `tools/orchestration`, `tools/utils`, `tools/robustness`) are internal modules and are not considered executable tools.

---

## Orchestration
Tools responsible for executing, coordinating, or wrapping pipeline runs and state transitions.

Tool | Purpose
--- | ---
run_pipeline | Master execution pipeline orchestrator (v3.2)
run_stage1 | Minimal stage-1 execution batch harness
strategy_provisioner | Preflight strategy artifact provisioner
exec_preflight | Pipeline execution preflight checks
system_preflight | General system preflight validation
profile_selector | Ledger enrichment from profile comparison data
skill_loader | Utility to load and initialize agent skills
sweep_engine | Engine for sweep variant execution
execution_emitter_stage1 | Emits execution events for stage-1 runs
stage2_compiler | Stage-2 metric computation presentation compiler
stage3_compiler | Stage-3 aggregation engine for master filter
apply_portfolio_constraints | Post-Stage-1 concurrency enforcement
capital_wrapper | Deployable capital wrapper for runtime execution

## Maintenance
Tools used to repair, rebuild, reconstruct, or clean system artifacts and ledgers.

Tool | Purpose
--- | ---
cleanup_reconciler | Safe registry-governed artifact cleanup sweep
reset_directive | Governance-authorized directive reset tool
reconcile_portfolio_master_sheet | Rebuilds master portfolio sheet from profiles
generate_golive_package | Stage-10 go-live package generator
generate_guard_manifest | Authority manifest generator for guard layers
generate_engine_manifest | Authority manifest generator for engine files
purge_run_id | Purge specific run ID from registry
create_audit_snapshot | Generates system audit snapshots
create_vault_snapshot | Point-in-time workspace vault archival
system_introspection | Workspace system snapshot generator (SYSTEM_STATE.md)
rebuild_all_reports | Utility to rebuild all system reports
configure_portfolio | Portfolio configuration and setup utility
report_generator | Core automated report generation engine
research_memory_append | Append entries to RESEARCH_MEMORY.md

## Migration
Tools used to transition data, directives, or state between models and versions.

Tool | Purpose
--- | ---
convert_directive | Flat-text to YAML scaffold utility
convert_promoted_directives | Convert legacy directives into governed namespace
migrate_atomic_runs_v2 | One-time migration script for atomic runs v2
migrate_trade_density | Migration tool for trade density metrics

## Analysis
Tools used to inspect or analyze results, strategy behavior, and research sweeps.

Tool | Purpose
--- | ---
run_portfolio_analysis | Governance-grade portfolio engine (v3.0)
portfolio_evaluator | Multi-instrument portfolio analysis and archival
generate_sweep_08 | Strategy research sweep generator
analyze_capital_models | Analysis of configured capital models
analyze_range_breakout_vol | Analysis of range breakout volatility
inspect_trend_score | Utility to inspect trend scoring metrics
inspect_master_filter | Utility to inspect the Strategy Master Filter

## Validation
Tools that verify integrity, correctness, or compliance of system outputs and directives.

Tool | Purpose
--- | ---
semantic_validator | Core semantic validation for trading directives
strategy_dryrun_validator | Validates strategy code via isolated dry-run
sweep_registry_gate | Phase-2 sweep registry governance gate
namespace_gate | Phase-1 namespace governance gate
filter_strategies | Strict strategy filter with ledger authority
audit_compliance | System-wide compliance audit tool
canonicalizer | Directive structure canonicalization engine
format_excel_artifact | Unified Excel formatter and rounding governance
safe_append_excel | Non-destructive Excel data appender
validate_high_vol | High-volatility data validation guard
validate_lookahead | Lookahead bias detection and prevention utility
validate_safety_layers | Signal integrity and strategy kill-switch validation
verify_batch_robustness | Batch robustness and stability verification
verify_batch_trend | Batch trend scoring and verification
verify_collision_fix | Verifies collision-randomization fixes
verify_engine_integrity | Core engine integrity verification tool
verify_formatting | Code and artifact formatting compliance check
directive_schema | Schema enforcement for research directives
canonical_schema | Schema enforcement for canonicalized directives

## Scratch Tools
Temporary debugging or one-off scripts located in: `tools/tmp/`. These scripts are not considered permanent system tools and are not indexed here.

---

## System Layering
Repository layers are organized as follows:

- `tools/`       → operational utilities and execution entrypoints
- `pipeline/`    → pipeline orchestration logic
- `engines/`     → core research engines
- `governance/`  → system integrity and safety layers
- `strategies/`  → generated trading strategies

## Tool Governance Rules
- New operational tools must be added to `TOOLS_INDEX.md`.
- One-off scripts belong in `tools/tmp/`.
- If a `tmp/` script becomes reused, move it to a permanent category.
- The index should always reflect the current operational tool surface.
- Tools must not contain core engine logic.
- Engines belong in `engines/` or `pipeline/`, not `tools/`.

---
Last Updated: 2026-03-13
Total Tools Indexed: 58
