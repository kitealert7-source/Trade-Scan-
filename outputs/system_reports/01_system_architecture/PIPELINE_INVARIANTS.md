# Pipeline Architecture Invariants & Governance Locks

**Status**: Core System Invariants
**Objective**: Document the strict determinism points, runtime immutability guarantees, and known operational soft spots across the TradeScan pipeline.

---

## 1. Determinism Guarantees

The execution engine is bound by strict deterministic rules. Given identical inputs, the exact same state must be achievable on any machine at any time.

* **Code Immutability**: All executions are driven by a frozen snapshot copy of the strategy class. Future updates to the strategy source *cannot* retroactively change historical state.
* **Manifest Binding**: Execution footprints are cryptographically locked against unintentional mutations. The pipeline orchestrator forces a SHA-256 hash snapshot of the executed code and parameters.
* **Stable Event Ordering**: The portfolio capital simulation explicitly resolves asynchronous tick races via a composite sort key `(timestamp, type_priority, trade_id)`. Time-concurrent entries and exits resolve equivalently across all parallel systems.
* **Registry-First Authority Model**: `run_registry.json` serves as the singular, central source of truth for all run lifecycle tiers. Run execution states and their physical subdirectory locations merely project from this authoritative registry state.

---

## 2. Governance Risk & Locks

The execution pipeline enforces strict layer decoupling governed by immutable checks to eliminate manual errors and silent research drift.

| Risk Area | Status | Mitigation Mechanism |
| :--- | :--- | :--- |
| **Logic Drift** | **LOCKED** | The atomic execution phase freezes `strategy.py` explicitly per-run. |
| **Silent Overwrite** | **LOCKED** | Ledger update events explicitly enforce hard-failure over mutation. |
| **Namespace Leak** | **LOCKED** | `semantic_validator` AST analysis guarantees no engine logic bypasses or global regime leaks. |
| **Sorting Drift** | **LOCKED** | Event ingestion relies exclusively on stable sort keys prioritizing sequence structure. |
| **Unknown Keys** | **STRICT** | Extraneous keys encountered in YAML directives mathematically alter the `run_id`, producing unique state lineages. |
| **Registry Scope** | **STRICT** | Registries store lifecycle state only and must not contain research metadata. |

---

## 3. Residual Soft Spots

Despite governance coverage, certain edge-cases should be operationally acknowledged.

1. **Directive Grammar Whitelist**: Extraneous inputs produce unique lineages, but pass YAML parsing cleanly. The system currently tolerates semantic clutter.
2. **Family Validation**: `family` metadata is processed structurally, but not functionally validated against physical source code directory scopes.
3. **Floating Point Accumulation**: Operational logic manages presentation rounding locally, but multi-year compounding tests (>10,000 deep) accumulate minute simulated drag within the portfolio execution wrappers prior to terminal rounding events.

### Resolved Soft Spots (2026-03-19)

4. **~~Stale `run_registry.json` on partial reset~~** *(FIXED)*: Previously, `reset_directive.py` only deleted individual run sub-folders and `run_state.json`, leaving the directive-level `TradeScan_State/runs/<DIRECTIVE_ID>/run_registry.json` intact. On re-run, `claim_next_planned_run` found no `PLANNED` entries and returned `None` silently — Stage 1 exited with no work done. Manifested as phantom completion states and blocked pipelines with no error output. **Fix**: `reset_directive.py` now calls `shutil.rmtree` on the entire directive-level run folder, making reset atomic and deterministic.

5. **~~Stale `constituent_run_ids` in `portfolio_metadata.json`~~** *(FIXED)*: When runs were marked invalid by the reconciler, their run IDs remained in `portfolio_metadata.json` files. On the next pipeline pass, the Portfolio Dependency Check fired a `[FATAL] Consistency Violation` that blocked execution. Required manual cleanup. **Fix**: `reconcile_registry()` in `system_registry.py` now auto-cleans stale run IDs from all `portfolio_metadata.json` files immediately after marking runs invalid, before the Dependency Check fires.

### Resolved Soft Spots (2026-03-23)

6. **~~Blind Preflight crash reporting~~** *(FIXED)*: When `exec_preflight.py` crashed with a Python exception, the orchestrator logged only `returned non-zero exit status 1` — the actual traceback was invisible in the failure log, making root-cause diagnosis impossible. **Fix**: `tools/orchestration/execution_adapter.py` now captures `stderr=subprocess.PIPE` and prints the full subprocess traceback before re-raising, making exact exception lines visible in pipeline logs.

7. **~~Aggregation stage crash on truncated/zero-byte CSVs~~** *(FIXED)*: When the engine crashed mid-write during Stage-1, it could leave a 0-byte `results_tradelevel.csv`. The manifest binding stage naively called `pd.read_csv()` producing an unhandled `Truncated file header` crash that propagated up as an orchestrator-level `PIPELINE_ERROR`. **Fix**: `tools/orchestration/stage_symbol_execution.py` now validates `path.stat().st_size > 0` before reading and hashing all required artifacts. Zero-byte files trigger a clean `FAILED` state transition with an actionable error message instead of an unhandled crash.

8. **~~Illegal State Transition on cached semantic validation~~** *(FIXED)*: When the semantic validation step was already cached (state remained `PREFLIGHT_COMPLETE`), Stage-1 attempted `transition_to("STAGE_1_COMPLETE")` from `PREFLIGHT_COMPLETE`, which was illegal per the strict FSM. This produced `[FATAL] Illegal State Transition` errors. **Fix**: `tools/pipeline_utils.py` `ALLOWED_TRANSITIONS` now allows `PREFLIGHT_COMPLETE → STAGE_1_COMPLETE` as a valid skip-path. Additionally, `transition_to()` no longer raises `FileNotFoundError` when a run's state directory is missing — it logs a `[WARN]` and skips gracefully.

### Resolved Soft Spots (2026-03-24)

9. **~~Provenance fields absent from BACKTESTS_DIR run_metadata.json~~** *(FIXED)*: `content_hash` was computed and injected into `RUNS_DIR/run_metadata.json` via PATCH 3 in `run_stage1.py`, but the BACKTESTS_DIR copy (`backtests/{strategy_id}_{symbol}/metadata/run_metadata.json`) was written before PATCH 3 ran — so it never received provenance fields. Additionally, `git_commit` and `execution_model` were absent from all runs entirely. **Fix**: `run_stage1.py` now captures `git_commit` at the top of `emit_result()`, injects `content_hash`, `git_commit`, `execution_model`, and `schema_version="1.3.0"` into PATCH 3, and adds a mirror write block that propagates all provenance fields to BACKTESTS_DIR after PATCH 3 completes.

10. **~~No central run index — discoverability required scanning 223 folders~~** *(FIXED)*: Answering a single filtered query (e.g. PF > 1.5, DD < 10%) required opening 669 files across 223 folders with no join mechanism. **Fix**: `tools/run_index.py` (new) is called automatically in `stage_symbol_execution.py` at `STAGE_1_COMPLETE`, appending one row per completed run to `TradeScan_State/research/index.csv` (15 columns: run_id, strategy_id, symbol, timeframe, date_start/end, profit_factor, max_drawdown_pct, net_pnl_usd, total_trades, win_rate, content_hash, git_commit, execution_timestamp_utc, schema_version). FileLock-protected. Non-blocking (failure never blocks pipeline). `tools/backfill_run_index.py` (new) populated 167 legacy rows with `schema_version="legacy"` in a one-time backfill.

11. **~~DRY_RUN backups stored inside Trade_Scan repo~~** *(FIXED)*: `dry_run_backups/` was inside the repository, gitignore-dependent, and reachable by pipeline processes. **Fix**: Backup output relocated to `C:\Users\faraw\Documents\DRY_RUN_VAULT\` (outside all repos). `backup_dryrun_strategies.py` updated to capture `git_commit` at backup time, compute `config_hash` (SHA256 of directive content), write `meta.json` per strategy (execution_model, data_signature, code_version), and enrich `index.json` with per-strategy PF, DD, trades, win_rate. `dry_run_backups/` entry removed from `.gitignore`.

---

*Note: For broader pipeline execution flow and procedural capabilities mapping, reference [pipeline_flow.md](pipeline_flow.md) and [capability_map_analysis.md](capability_map_analysis.md).*
