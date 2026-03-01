# Research Pipeline Authority & Determinism Trace

**Audit Version**: 1.1.0 (Post-Micro-Audit Correction)
**Scope**: Stage-0 to Capital Wrapper (Stage-6)
**Objective**: Architectural trace of authority flow and identity propagation.

## 1. Trace Summary Table

| Stage | Name | Authority | Determinism Point | Output Artifact |
| :--- | :--- | :--- | :--- | :--- |
| **0** | **Preflight** | `governance/preflight.py` | N/A (Pure Analysis) | Terminal Result |
| **0.5**| **Semantic Gate** | `tools/semantic_validator.py` | AST Architectural Lock | `ABORT_GOVERNANCE` if invalid |
| **0.75**| **Dry-Run** | `tools/strategy_dryrun_validator.py` | Execution Health Check | Terminal Result |
| **0.9** | **Snapshot** | `run_pipeline.py` (Orchestrator) | **CODE IMMUTABILITY** | `runs/<RID>/strategy.py` |
| **1** | **Execution** | `engine_dev/v1_4_0/execution_loop.py` | Bar-by-Bar Determinism | `results_tradelevel.csv` |
| **2** | **Reporting** | `tools/stage2_compiler.py` | **PURE DERIVATIONAL** | `AK_Trade_Report.xlsx` |
| **3** | **Aggregation** | `tools/stage3_compiler.py` | Master Identity Logic | `Strategy_Master_Filter.xlsx` |
| **3A** | **Binding** | `run_pipeline.py` (Orchestrator) | **SHA-256 MANIFEST** | `snapshot.manifest.json` |
| **4** | **Evaluation** | `portfolio_evaluator.py` | **LEDGER CROSS-CHECK** | `portfolio_summary.json` |
| **5/6** | **Cap Wrapper** | `tools/robustness/` | **EVENT STABILITY** | `.md` Robustness Reports |

---

## 2. Layer-by-Layer Detailed Trace

### 2.1 Entry Layer: CLI & Directive Ingestion

* **Entry Point**: `python tools/run_pipeline.py <DIRECTIVE_ID>`
* **Parsing Strictness**:
  * **Duplicate Keys**: Hard abort via `NoDuplicateSafeLoader`.
  * **Unknown Keys**: Permitted during parsing but **captured in the `run_id` hash**. Any stray key (e.g. `foo: bar`) creates a unique execution lineage.
  * **Comments**: Stripped before hashing; do not affect identity.
* **Identity Creation**: `run_id` is generated immediately.
  * **Determinism**: Derived from a legacy flat-parser output to ensure long-term hash stability across YAML versions.
* **Field Classification**:
  * **Structural**: `symbols`, `indicators`, `execution_rules` drive the engine.
  * **Informational**: `family` is informational; it is explicitly stripped from the technical `STRATEGY_SIGNATURE` by the provisioner.

### 2.2 Orchestrator & Preflight (Stage-0)

* **Admission Gate**: `exec_preflight.py` checks for manual implementation requirements.
* **Semantic Hardening**: `semantic_validator.py` uses AST analysis to enforce regime-access and `FilterStack` usage.
* **Immutability Lock**: Stage-0.9 copies source to `runs/<run_id>/strategy.py`. **Execution loads ONLY from this snapshot**.

### 2.3 Execution Layer (Stage-1)

* **Authority Enforcement**: `FilterStack` acts as the final bar-by-bar gatekeeper for trade signals.
* **Emission Integrity**: `results_tradelevel.csv` carries the `run_id`, `content_hash`, and `signature_hash`.

### 2.4 Reporting Layer (Stage-2)

* **Derivational Purity**: `stage2_compiler.py` re-computes all metrics from raw Stage-1 data. It does not store state or placeholders.
* **Rounding**: Floating-point drift is managed by rounding all presentation metrics to 2–4 decimal places in the final report.

### 2.5 Portfolio & Robustness (Stage-5/6)

* **Event Queue Determinism**: `capital_wrapper.py` decomposes trades into ENTRY/EXIT events.
  * **Sorting**: Sorted by `(timestamp, type_priority, trade_id)`. This ensures identical trade ordering across parallel runs or system architectures.
* **Observational Integrity**: This layer cannot modify Stage-1 results. It only filters or simulates constraints.
* **Artifact Output**: Final governance reports are emitted as fixed-format Markdown (`.md`) files via `tools/robustness/formatter.py`.

---

## 3. Governance Risk Assessment

| Risk Area | Status | Mitigation Mechanism |
| :--- | :--- | :--- |
| **Silent Overwrite** | **LOCKED** | `update_master_portfolio_ledger` hard-fails on mutation. |
| **Logic Drift** | **LOCKED** | Stage-0.9 Atomic Snapshot freezes code. |
| **Namespace Leak** | **LOCKED** | `semantic_validator` AST analysis. |
| **Sorting Drift** | **LOCKED** | Capital Wrapper uses stable composite sort keys (TS + ID). |
| **Unknown Keys** | **STRICT** | Any top-level unknown key forces a NEW `run_id`. |

---

## 4. Residual Soft Spots

1. **Directive Grammar Whitelist**: While unknown keys affect the `run_id`, they are currently allowed without warning. This preserves determinism but allows "grammar clutter."
2. **Family Validation**: The `family` field is not cross-checked against the strategy directory name.
3. **Floating Point Accumulation**: While artifacts are rounded, the internal simulation in the capital wrapper accumulates small float errors over very long timelines (>10,000 trades) before rounding the final result.

---

## 5. Conclusion

**System Deterministic & Governance-Safe.**
The research pipeline architecture is structurally hardened. Authority flows from **Directive Intent** to **Snapshot Immutability** to **Ledger Finality**. The addition of composite event sorting in the capital wrapper ensures that portfolio-level simulation is as deterministic as bar-by-bar execution.
