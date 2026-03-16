# Pipeline Architecture Invariants & Governance Locks

**Status**: Core System Invariants
**Objective**: Document the strict determinism points, runtime immutability guarantees, and known operational soft spots across the TradeScan pipeline.

---

## 1. Determinism Guarantees

The execution engine is bound by strict deterministic rules. Given identical inputs, the exact same state must be achievable on any machine at any time.

* **Code Immutability**: All executions are driven by a frozen snapshot copy of the strategy class. Future updates to the strategy source *cannot* retroactively change historical state.
* **Manifest Binding**: Execution footprints are cryptographically locked against unintentional mutations. The pipeline orchestrator forces a SHA-256 hash snapshot of the executed code and parameters.
* **Stable Event Ordering**: The portfolio capital simulation explicitly resolves asynchronous tick races via a composite sort key `(timestamp, type_priority, trade_id)`. Time-concurrent entries and exits resolve equivalently across all parallel systems.

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

---

*Note: For broader pipeline execution flow and procedural capabilities mapping, reference [pipeline_flow.md](pipeline_flow.md) and [capability_map_analysis.md](capability_map_analysis.md).*
