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

---

*Note: For broader pipeline execution flow and procedural capabilities mapping, reference [pipeline_flow.md](pipeline_flow.md) and [capability_map_analysis.md](capability_map_analysis.md).*
