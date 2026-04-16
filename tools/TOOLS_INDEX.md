# TradeScan Tools Index

This index provides a comprehensive map of the operational tools within the `tools/` layer. It serves as the authoritative surface for platform orchestration, maintenance, research validation, and post-run analysis.

## Primary Entry Tools
Primary Entry Tools are shortcuts to commonly used tools.
They are also listed in their operational categories below.

Tool | Purpose
--- | ---
run_pipeline | Primary pipeline execution entrypoint (directive -> Stage-4)
control_panel | Governance-authoritative CLI for lifecycle intent + composite-portfolio analysis selection
promote_to_burnin | Strategy promotion from PORTFOLIO_COMPLETE to BURN_IN (vault + portfolio.yaml)
run_portfolio_analysis | Composite portfolio analysis runner (Analysis_selection flagged rows)
burnin_evaluator | Read-only PASS / ON_TRACK / WARN / ABORT evaluation of BURN_IN strategies
system_introspection | Workspace system snapshot generator (SYSTEM_STATE.md)

---

## Tool Execution Convention
Tools are executed as Python modules from the repository root.

Example usage:

```bash
python -m tools.run_pipeline <DIRECTIVE_ID>
python -m tools.control_panel --list
python -m tools.capital_wrapper <STRATEGY_OR_PF_ID>
python -m tools.robustness.cli <PF_ID> --suite full
```

Operational tools live at the top level of the `tools/` directory.
Library modules inside subfolders (for example `tools/orchestration`, `tools/robustness`, `tools/state_lifecycle`, `tools/portfolio_core`, `tools/capital_engine`, `tools/utils`, `tools/system_logging`) are internal modules. Only `tools/robustness/cli` is a directly invokable entrypoint.

---

## Orchestration & Execution
Tools responsible for executing, coordinating, or wrapping pipeline runs and state transitions.

Tool | Purpose
--- | ---
run_pipeline | Master execution pipeline orchestrator (directive -> Stage-4 + post-complete chain)
run_stage1 | Stage-1 execution batch harness (multi-asset, invoked by run_pipeline)
strategy_provisioner | Preflight strategy artifact provisioner
exec_preflight | Pipeline execution preflight checks (stages -0 through 0.75)
system_preflight | General system readiness check
sweep_engine | Sweep variant execution engine
stage2_compiler | Stage-2 metric computation + presentation compiler
stage3_compiler | Stage-3 aggregation engine for Strategy Master Filter
apply_portfolio_constraints | Post-Stage-1 concurrency/capital enforcement
finalize_batch | Atomic post-Stage-4 orchestration chain (capital + selector + reconcile + format)
directive_reconciler | Directive-state reconciliation across FSM and registry
rerun_backtest | Friction-free rerun tool (DATA_FRESH / SIGNAL / PARAMETER / BUG_FIX / ENGINE)
new_pass | Creates a new P## pass from an existing pass (rehash + scaffold)
rehash_directive | Recomputes directive signature hash + updates sweep_registry atomically

## Control Panel & Lifecycle
Governance-authoritative human interface for portfolio and analysis intent.

Tool | Purpose
--- | ---
control_panel | Unified CLI: `--select / --burn / --drop / --deselect` for burn-in intent, `--select-analysis / --deselect-analysis / --clear-analysis / --list-analysis / --run-analysis` for composite-portfolio analysis intent
portfolio_interpreter | Drains portfolio_control intents into portfolio.yaml + burn_in_registry.yaml; regenerates Excel views
lifecycle_status | Read-only snapshot of each strategy's lifecycle (BURN_IN / WAITING / LIVE / DISABLED)

## Promotion / Burn-In / Go-Live
Pre-deployment and deployment-lifecycle tooling.

Tool | Purpose
--- | ---
promote_readiness | Readiness dashboard for promotion (CORE + WATCH gates, artifact checks)
pre_promote_validator | Multi-layer validator (schema / replay regression / expectancy / sanity exec)
promote_to_burnin | Promotion to BURN_IN (expectancy gate + 6-metric quality gate + vault snapshot + portfolio.yaml edit)
baseline_freshness_gate | Blocks burn-in promotion on stale replay baselines (threshold: 14 days)
backup_dryrun_strategies | Full deterministic vault snapshot creator (DRY_RUN_VAULT/{vault_id}/{ID}/)
burnin_evaluator | Burn-in PASS/ON_TRACK/WARN/ABORT evaluator against shadow_trades.jsonl
transition_to_waiting | BURN_IN -> WAITING lifecycle transition (PASS/FAIL decision gated)
transition_to_live | WAITING -> LIVE lifecycle transition (vault + portfolio.yaml)
validate_portfolio_integrity | Audits portfolio.yaml for governance violations (vault_id, lifecycle, profile fields)
sync_multisymbol_strategy | Syncs base strategy.py into per-symbol ID folders (for multi-symbol portfolios)

## Portfolio Analysis & Capital Profiles
Portfolio aggregation, per-profile simulation, and selection tools.

Tool | Purpose
--- | ---
run_portfolio_analysis | Composite portfolio analysis runner (reads Analysis_selection flags from master_filter DB)
portfolio_evaluator | Multi-instrument portfolio construction, governance, and metrics engine
capital_wrapper | Deployable capital wrapper — simulates `RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1` (v3.0 retail model)
profile_selector | Ledger enrichment validator (reads `deployed_profile` chosen in Step 7 — see SOP_PORTFOLIO_ANALYSIS §4.6)
real_model_evaluator | Always-on pooled-equity reference cross-check for CORE-status portfolios (writes `Real_Model_Evaluation.xlsx`)
post_process_capital | Enriches `profile_comparison.json` with utilization-based capital insights
analyze_capital_models | Offline analysis of configured capital models
reconcile_portfolio_master_sheet | Rebuilds Master Portfolio Sheet from authoritative per-profile artifacts

## Research Gates & Hypothesis Tools
Pre-execution gates, diagnostic probes, and hypothesis analysis.

Tool | Purpose
--- | ---
namespace_gate | Stage -0.30 namespace governance gate (identity + tokens + idea registry)
sweep_registry_gate | Stage -0.35 sweep registry governance gate (idempotent reuse + collision detection)
idea_evaluation_gate | Stage -0.20 idea evaluation gate (reads run_summary + hypothesis_log + RESEARCH_MEMORY)
classifier_gate | Directive-diff + indicator-hash classifier gate (SIGNAL / PARAMETER / COSMETIC / UNCLASSIFIABLE)
directive_diff_classifier | Library + CLI that classifies structural deltas between two directives
hypothesis_tester | Structured trade-level insight extractor (report mode + programmatic)
filter_strategies | Strict append-only Strategy Master Filter gate
regime_alignment_guard | Warn-mode audit of dual-time regime_age fields (signal vs fill)

## Validation & Compliance
Schema, integrity, safety, and formatting verification.

Tool | Purpose
--- | ---
semantic_validator | Authoritative Stage-0.5 strategy semantic validation
strategy_dryrun_validator | Isolated dry-run validation of strategy code
canonicalizer | Directive structure canonicalization engine
canonical_schema | Schema enforcement for canonicalized directives (library)
directive_schema | Schema enforcement for research directives (library)
directive_linter | YAML directive lint (grammar + tokens)
audit_compliance | System-wide compliance audit tool
verify_engine_integrity | Engine-modification detection (manifest hash check)
verify_broker_specs | MT5-verified broker spec integrity (tick_value / tick_size / contract_size)
verify_batch_robustness | Batch robustness and stability verification
verify_batch_trend | Batch trend scoring and verification
verify_collision_fix | Collision-randomization fix verifier
verify_registry_coverage | Indicator registry coverage verifier
verify_formatting | Excel formatting compliance check
validate_high_vol | High-volatility data validation guard
validate_lookahead | Lookahead bias detection and prevention utility
validate_safety_layers | Signal integrity and strategy kill-switch validation
format_excel_artifact | Unified Excel formatter + rounding governance (delegation target — no engine imports openpyxl directly)
safe_append_excel | Non-destructive Excel data appender
indicator_hasher | Content-hash hasher for imported indicator modules (semantic, cosmetic-tolerant)
shadow_filter | What-if filter evaluator (library-level; used by hypothesis_tester + report_generator)
news_calendar | News-window classifier (library + macro filter data source)
metrics_core | Shared metric primitives (library used by stage2 / shadow_filter / report_generator)

## Reporting & Introspection
Artifact generation, system snapshots, research memory management.

Tool | Purpose
--- | ---
system_introspection | Workspace snapshot (writes SYSTEM_STATE.md — engine / queue / ledgers / portfolio / git sync)
create_audit_snapshot | Operational audit snapshot generator
create_vault_snapshot | Point-in-time workspace vault archival
report_generator | Core automated report generation engine (library)
rebuild_all_reports | Utility to rebuild all system reports
regenerate_all_reports | Regenerates historical per-directive reports (script-on-import)
generate_strategy_card | Per-strategy card generator (identity + config + active logic + diff)
generate_run_summary | Regenerates `TradeScan_State/research/run_summary.csv`
generate_research_memory_index | RESEARCH_MEMORY machine-readable index generator (+ `--check` mode)
generate_sweep_08 | Strategy research sweep generator
generate_engine_manifest | Authority manifest generator for engine files
generate_guard_manifest | Authority manifest generator for guard layers (SHA-256 pre-commit)
add_strategy_hyperlinks | Adds per-strategy hyperlinks to candidates + MPS Excel views
inspect_trend_score | Utility to inspect trend scoring metrics
inspect_master_filter | Utility to inspect the Strategy Master Filter (script-on-import)
research_memory_append | Append-only write to RESEARCH_MEMORY.md (human-approved entries only)
compact_research_memory | Line/size-governed compaction of RESEARCH_MEMORY (dry-run + apply)

## Ledger DB & Run Index
SQLite-authoritative state, Excel exports, and retroactive backfill.

Tool | Purpose
--- | ---
ledger_db | SQLite authority for master_filter / portfolio_sheet / portfolio_control — `--export` regenerates both Excel ledgers
run_index | Registry-level run index helper (library)
update_registry_summary | Updates indicator-registry summary counts
backfill_ledger_db | Backfills ledger DB from Excel ledgers (with --verify round-trip)
backfill_run_index | Append-only backfill of `index.csv` from BACKTESTS_DIR (legacy schema)
backfill_hypothesis_log | Backfill `hypothesis_log.json` from P00-vs-Pxx backtest diffs

## Maintenance & State Repair
Reset, cleanup, purge, and integrity tools.

Tool | Purpose
--- | ---
cleanup_reconciler | Safe registry-governed artifact cleanup sweep (dry-run -> execute -> convergence)
reset_directive | Governance-authorized directive reset (FSM + registry cleanup)
reset_runtime_state | Full reset of the external research state folder
purge_run_id | Purge specific run ID from registry (break-glass operational tool)

## Migration
Tools used to transition data, directives, or state between models and versions.

Tool | Purpose
--- | ---
convert_directive | Flat-text to YAML scaffold utility
convert_promoted_directives | Convert legacy directives into governed namespace
migrate_atomic_runs_v2 | One-time migration script for atomic runs v2 (archival)
migrate_trade_density | Migration tool for trade density metrics (archival)

## Robustness CLI (nested)
Tool | Purpose
--- | ---
tools.robustness.cli | Robustness test suite CLI (`python -m tools.robustness.cli <ID> --suite full`)

## Internal Hooks & Linters
Pre-commit / CI surface, not user-facing.

Tool | Purpose
--- | ---
lint_encoding | Pre-commit: enforce `encoding="utf-8"` on every `.read_text()` / `open()`
lint_no_hardcoded_paths | Pre-commit: block hardcoded user-path literals
skill_loader | Agentic skill loader (used by the agent loop)
event_log | Structured append-only event logging to `governance/events.jsonl` (library)
system_registry | Run-registry loader with fail-hard semantics on corruption (library)
pipeline_utils | Shared pipeline utilities (library)
directive_utils | Directive YAML load/parse helpers (library)
execution_emitter_stage1 | Stage-1 execution event emitter (called by run_stage1)
analyze_range_breakout_vol | Analysis module for range breakout volatility (library, called by research notebooks)

## Test Harnesses
CI-only; not part of the operational surface.

Tool | Purpose
--- | ---
test_artifact_hash | Artifact-hash reconciliation test
test_concurrent_pipeline | Concurrency invariant test
test_integrity_guards | Integrity-guard test battery
test_portfolio_rebuild | MPS rebuild round-trip test
test_registry_sync | Registry-sync round-trip test

## Scratch Tools
Temporary debugging or one-off scripts located in: `tools/tmp/`. These scripts are not considered permanent system tools and are not indexed here.

---

## System Layering
Repository layers are organized as follows:

- `tools/`       -> operational utilities and execution entrypoints
- `tools/orchestration/` -> startup launcher, watchdog daemon, reconciler internals (library)
- `tools/state_lifecycle/` -> directive FSM + repair utilities (library)
- `tools/portfolio_core/` -> portfolio evaluator / selector internals (library)
- `tools/capital_engine/` -> capital wrapper simulation kernel (library)
- `tools/robustness/` -> robustness test suite (library + `cli` module)
- `tools/system_logging/` -> event logging internals (library)
- `tools/utils/` -> shared utilities (library)
- `engines/`    -> filter stack + runtime gates
- `engine_dev/` -> versioned core research engines (e.g. `universal_research_engine/v1_5_4/`)
- `governance/` -> SOPs, namespace, sweep registry, guard manifests
- `strategies/` -> generated and human-authored strategy code

## Tool Governance Rules
- New operational tools MUST be added to `TOOLS_INDEX.md` and `TOOLS_AUDIT_REPORT.md`.
- One-off scripts belong in `tools/tmp/`.
- If a `tmp/` script becomes reused, move it to a permanent category.
- The index must always reflect the current operational tool surface (docstrings are canonical).
- Tools must not contain core engine logic. Engines belong in `engines/` or `engine_dev/`, not `tools/`.
- Any tool that mutates an Excel ledger MUST delegate styling to `format_excel_artifact.py` (no direct `openpyxl` imports).
- Tools must encode UTF-8 on every file read/write (enforced by `lint_encoding`).
- Tools must never hardcode absolute user paths (enforced by `lint_no_hardcoded_paths`).

---
Last Updated: 2026-04-16
Capital profile set: v3.0 Retail Amateur Model (`RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1`)
Total CLI Tools Indexed: 83 (top-level) + 1 (nested `tools.robustness.cli`)
Library Modules: 17 (top-level) + internal submodule trees
