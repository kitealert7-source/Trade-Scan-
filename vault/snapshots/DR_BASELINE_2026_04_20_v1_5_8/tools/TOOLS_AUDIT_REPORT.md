# TradeScan Tools Audit Report

**Last Updated:** 2026-04-16
**Scope:** Operational classification of every `tools/` entrypoint and library module against current pipeline use.
**Authority:** Docstrings + call-graph evidence. Cross-reference `TOOLS_INDEX.md` for the navigational surface map.

---

## Audit Summary

| Classification | Count |
|---|---|
| **ACTIVE_TOOL** (on the pipeline hot path or daily human workflow) | 37 |
| **OPERATIONAL_TOOL** (periodic maintenance, validation, or analysis) | 33 |
| **CI / PRE-COMMIT** (internal hooks — not user-facing) | 4 |
| **TEST HARNESS** (CI-only, not part of operational surface) | 5 |
| **LEGACY / ARCHIVAL** (retained for reproducibility; no active callers) | 4 |
| **LIBRARY MODULES** (imported only — no CLI entrypoint) | 17 + subpackages |
| **Total CLI entrypoints** | 83 (top-level) + 1 (`tools.robustness.cli`) |

Tools layer is currently **100% accounted for** against the active operational surface. All tools appearing in this report either have live callers or are retained by governance for audit reproducibility.

---

## 1. Classification Criteria

| Class | Definition |
|---|---|
| ACTIVE_TOOL | Invoked by `run_pipeline.py`, lifecycle transitions, `control_panel.py`, or session-close workflow. Part of the pipeline hot path. |
| OPERATIONAL_TOOL | Invoked by humans or workflows on a periodic basis (promotion, robustness review, capital analysis, research memory management, directive reset). |
| CI / PRE-COMMIT | Enforcement hooks. Run in pre-commit or CI; never by the agent. |
| TEST HARNESS | Live only under pytest / CI. |
| LEGACY / ARCHIVAL | Retained for audit or migration reproducibility. No live call sites. |
| LIBRARY MODULE | Pure module — `import`-only API; not directly invokable. |

Classification evidence:
- `if __name__ == "__main__":` block ⇒ CLI entrypoint candidate.
- Script-on-import (logic at module top level) ⇒ documented explicitly.
- Presence in `run_pipeline.py`, `finalize_batch.py`, `.agents/workflows/*.md`, or `.claude/skills/*/SKILL.md` ⇒ ACTIVE.

---

## 2. ACTIVE_TOOL — Pipeline Hot Path

### Orchestration & Execution
- `run_pipeline` — master pipeline orchestrator (directive → Stage-4 → post-complete chain)
- `run_stage1` — Stage-1 engine execution harness (called by `run_pipeline`)
- `strategy_provisioner` — preflight strategy artifact provisioner
- `exec_preflight` — Stage -0 through 0.75 preflight chain
- `system_preflight` — general system readiness check
- `sweep_engine` — sweep variant execution engine
- `stage2_compiler` — Stage-2 metric + presentation compiler
- `stage3_compiler` — Stage-3 Strategy Master Filter aggregator
- `apply_portfolio_constraints` — post-Stage-1 concurrency enforcement
- `finalize_batch` — post-Stage-4 atomic chain (capital + selector + reconcile + format)
- `directive_reconciler` — FSM ↔ registry reconciliation
- `rerun_backtest` — DATA_FRESH / SIGNAL / PARAMETER / BUG_FIX / ENGINE rerun tool
- `new_pass` — P## scaffolding (rehash + new pass creation)
- `rehash_directive` — atomic signature-hash recomputation

### Control Panel & Lifecycle
- `control_panel` — unified CLI for burn-in intent + composite-portfolio analysis selection
- `portfolio_interpreter` — drains portfolio_control intents into `portfolio.yaml` + `burn_in_registry.yaml`; regenerates Excel views
- `lifecycle_status` — read-only lifecycle snapshot

### Promotion / Burn-In / Go-Live
- `promote_readiness` — CORE + WATCH gate readiness dashboard
- `pre_promote_validator` — schema / replay / expectancy / sanity validator
- `promote_to_burnin` — expectancy gate + 6-metric quality gate + vault snapshot + portfolio.yaml edit
- `baseline_freshness_gate` — blocks burn-in promotion on stale replay baselines (14-day threshold)
- `backup_dryrun_strategies` — deterministic vault snapshot creator
- `burnin_evaluator` — PASS / ON_TRACK / WARN / ABORT shadow-trade evaluator
- `transition_to_waiting` — BURN_IN → WAITING transition (gated)
- `transition_to_live` — WAITING → LIVE transition
- `validate_portfolio_integrity` — governance-field auditor for `portfolio.yaml`
- `sync_multisymbol_strategy` — per-symbol strategy.py sync for multi-symbol portfolios

### Portfolio Analysis & Capital Profiles (v3.0 Retail Amateur Model)
- `run_portfolio_analysis` — composite portfolio analysis runner (reads `Analysis_selection` flag)
- `portfolio_evaluator` — multi-instrument portfolio construction + governance + metrics. **Authoritative selector** for `deployed_profile` (Step 7).
- `capital_wrapper` — deployable capital wrapper; simulates `RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1` (v3.0 retail, $1k seed)
- `profile_selector` — ledger enrichment validator only; reads Step 7 choice (Step 8.5). `select_deployed_profile()` raises `RuntimeError`.
- `real_model_evaluator` — always-on pooled-equity reference cross-check for CORE portfolios (writes `Real_Model_Evaluation.xlsx`)
- `post_process_capital` — utilization-based capital enrichment of `profile_comparison.json`
- `reconcile_portfolio_master_sheet` — authoritative MPS rebuild from per-profile artifacts

### Research Gates
- `namespace_gate` — Stage -0.30 identity governance
- `sweep_registry_gate` — Stage -0.35 sweep reuse + collision detection
- `idea_evaluation_gate` — Stage -0.20 idea evaluation
- `filter_strategies` — strict append-only Strategy Master Filter gate

### Validation & Compliance
- `semantic_validator` — authoritative Stage-0.5 semantic validation
- `strategy_dryrun_validator` — isolated dry-run validation
- `canonicalizer` — directive canonicalization engine
- `execution_emitter_stage1` — Stage-1 event emitter (called by `run_stage1`)
- `format_excel_artifact` — Excel formatting + rounding authority
- `safe_append_excel` — non-destructive Excel appender
- `verify_engine_integrity` — engine manifest hash verifier
- `verify_broker_specs` — MT5-verified broker spec integrity

### Ledger DB & Run Index
- `ledger_db` — SQLite authority; `--export` regenerates both Excel ledgers
- `generate_run_summary` — regenerates `TradeScan_State/research/run_summary.csv`

### Reporting & Introspection
- `system_introspection` — workspace snapshot → `SYSTEM_STATE.md`
- `report_generator` — library for automated AK/PDF report generation
- `generate_strategy_card` — per-strategy card generator (identity + config + active logic + diff)

### Maintenance
- `reset_directive` — governance-authorized FSM + registry reset
- `cleanup_reconciler` — registry-governed cleanup sweep

---

## 3. OPERATIONAL_TOOL — Periodic / Human-Invoked

### Analysis & Diagnostics
- `analyze_capital_models` — offline analysis of configured capital models
- `analyze_range_breakout_vol` — range breakout volatility analysis (library used by research notebooks)
- `hypothesis_tester` — structured trade-level insight extractor
- `classifier_gate` — directive-diff classifier gate
- `directive_diff_classifier` — library + CLI for structural directive deltas
- `inspect_trend_score` — trend scoring inspection
- `inspect_master_filter` — Strategy Master Filter inspection (script-on-import)

### Schema & Safety
- `canonical_schema` — canonical schema enforcement library
- `directive_schema` — research directive schema library
- `directive_linter` — YAML directive lint (grammar + tokens)
- `audit_compliance` — system-wide compliance audit
- `verify_batch_robustness` — batch robustness + stability verifier
- `verify_batch_trend` — batch trend scoring verifier
- `verify_collision_fix` — collision-randomization fix verifier
- `verify_registry_coverage` — indicator registry coverage verifier
- `verify_formatting` — Excel formatting compliance (script-on-import)
- `validate_high_vol` — high-volatility data validation
- `validate_lookahead` — lookahead bias detection
- `validate_safety_layers` — signal integrity + kill-switch validation
- `indicator_hasher` — semantic content-hash hasher
- `shadow_filter` — what-if filter evaluator (library)
- `news_calendar` — news-window classifier (library + data source)
- `metrics_core` — shared metric primitives (library)
- `regime_alignment_guard` — warn-mode dual-time regime alignment audit

### Reporting & Research Memory
- `create_audit_snapshot` — operational audit snapshot generator
- `create_vault_snapshot` — workspace vault archival
- `rebuild_all_reports` — batch report regeneration
- `regenerate_all_reports` — historical per-directive regeneration (script-on-import)
- `generate_research_memory_index` — RESEARCH_MEMORY index generator (+ `--check` mode)
- `generate_sweep_08` — research sweep generator
- `generate_engine_manifest` — engine manifest generator (human-only)
- `generate_guard_manifest` — guard-layer manifest generator (human-only)
- `add_strategy_hyperlinks` — Excel hyperlink augmentation
- `research_memory_append` — append-only RESEARCH_MEMORY writer
- `compact_research_memory` — line/size-governed compaction (dry-run + apply)

### State & Index
- `run_index` — registry-level run index helper (library)
- `update_registry_summary` — indicator-registry summary updater
- `backfill_ledger_db` — Excel → SQLite ledger backfill (`--verify`)
- `backfill_run_index` — append-only `index.csv` backfill
- `backfill_hypothesis_log` — P00-vs-Pxx hypothesis log backfill
- `reset_runtime_state` — full research state folder reset
- `purge_run_id` — break-glass registry purge

### Robustness
- `tools.robustness.cli` — robustness test suite CLI (`python -m tools.robustness.cli <ID> --suite full`)

---

## 4. CI / PRE-COMMIT HOOKS

- `lint_encoding` — enforces `encoding="utf-8"` on every read/write (blocks commit on violation)
- `lint_no_hardcoded_paths` — blocks hardcoded user-path literals (enforces `config/state_paths.py`)
- `skill_loader` — agentic skill loader (used by agent loop; not human-invoked)
- `event_log` — structured event logging library (`governance/events.jsonl`)

---

## 5. TEST HARNESSES (CI-only)

- `test_artifact_hash`
- `test_concurrent_pipeline`
- `test_integrity_guards`
- `test_portfolio_rebuild`
- `test_registry_sync`

These are not part of the operational surface. Do not invoke manually.

---

## 6. LEGACY / ARCHIVAL

Retained for reproducibility / one-time migrations only. **No active call sites.**

- `migrate_atomic_runs_v2` — one-time atomic runs v2 migration (complete)
- `migrate_trade_density` — one-time trade density migration (complete)
- `convert_directive` — flat-text → YAML scaffold utility (rarely invoked)
- `convert_promoted_directives` — legacy → namespaced directive converter

**Deliberate retention rationale:** these scripts document the migration path and are referenced by audit artifacts under `vault/snapshots/`. Do not delete without governance approval.

---

## 7. LIBRARY MODULES (No CLI)

Not directly invokable from the shell. Called via `import`:

- `pipeline_utils` — shared pipeline utilities
- `directive_utils` — directive YAML load/parse helpers
- `system_registry` — run-registry loader (fail-hard on corruption)
- `event_log` — event logging primitives
- `metrics_core` — metric primitives
- `shadow_filter` — filter evaluator
- `news_calendar` — news-window data source
- `indicator_hasher` — semantic content hasher
- `report_generator` — report engine
- `run_index` — registry helper
- `canonical_schema` / `directive_schema` — schema enforcement
- `directive_diff_classifier` — classifier library (also has CLI)
- `analyze_range_breakout_vol` — analysis library
- `post_process_capital` — capital enrichment library (also has CLI)

### Library Subpackages

- `tools/orchestration/` — startup launcher, watchdog daemon, reconciler internals
- `tools/state_lifecycle/` — directive FSM + repair utilities
- `tools/portfolio_core/` — portfolio evaluator / selector internals
- `tools/capital_engine/` — capital wrapper simulation kernel (houses `RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1` execution)
- `tools/robustness/` — robustness suite (library + `cli`)
- `tools/system_logging/` — event logging internals
- `tools/utils/` — shared utilities

---

## 8. Governance Rules (Unchanged)

- Every new operational tool **MUST** be added to both `TOOLS_INDEX.md` and `TOOLS_AUDIT_REPORT.md`.
- One-off scripts belong in `tools/tmp/`. If a `tmp/` script becomes reused, it must be promoted to a permanent category.
- Tools must **not** contain core engine logic. Engines live in `engines/` or `engine_dev/`.
- Any tool that mutates an Excel ledger **MUST** delegate styling to `format_excel_artifact.py` (no direct `openpyxl` imports).
- Tools must encode UTF-8 on every file read/write (enforced by `lint_encoding`).
- Tools must never hardcode absolute user paths (enforced by `lint_no_hardcoded_paths`).

---

## 9. Capital Profile Surface (v3.0 Retail — 2026-04-16)

The capital profile set was narrowed from 7 institutional profiles to **3 retail profiles** on 2026-04-16. Affected tools: `capital_wrapper`, `profile_selector`, `portfolio_evaluator`, `real_model_evaluator`, `post_process_capital`, `analyze_capital_models`, `reconcile_portfolio_master_sheet`.

Active profiles:

| Profile | Seed | Risk Logic | Notes |
|---|---|---|---|
| `RAW_MIN_LOT_V1` | $1,000 | 0.01 lot unconditional (diagnostic) | Honest retail XAUUSD edge probe |
| `FIXED_USD_V1` | $1,000 | max(2% equity, $20 floor) | Retail conservative; leverage/heat caps disabled |
| `REAL_MODEL_V1` | $1,000 | Tier-ramp 2% → 5% per equity doubling; `retail_max_lot=10` | Retail aggressive |

Retired profiles (`DYNAMIC_V1`, `CONSERVATIVE_V1`, `MIN_LOT_FALLBACK_V1`, `MIN_LOT_FALLBACK_UNCAPPED_V1`, `BOUNDED_MIN_LOT_V1`, institutional `FIXED_USD_V1`/$10k) are no longer simulated. Historical references live under `outputs/system_reports/05_capital_and_risk_models/` (sections labeled "Historical — Institutional Model, Retired").

---

**Audit Conclusion:** The tools layer has zero orphaned tools. All 83 CLI entrypoints + 17 top-level library modules map to a documented operational category. The tool surface is drift-free as of 2026-04-16.
