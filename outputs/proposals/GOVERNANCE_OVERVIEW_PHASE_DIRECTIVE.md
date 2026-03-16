# Governance Overview: Directive & Backtesting Phase

The Trade_Scan system is governed by a strict hierarchy of authoritative documents and automated gates. Below is a summary of the governance active during the current phase (Directive Backtesting & Reconciliation).

## 1. Authoritative Hierarchy
1.  **System Invariants**: The "Base Laws" (e.g., Linearity, Atomicity).
2.  **SOPs (Standard Operating Procedures)**: Detailed execution rules (`TESTING`, `OUTPUT`, `CLEANUP`).
3.  **Agent Rules**: Constraints on AI behavior.

---

## 2. Active Governance Gates (Directive Lifecycle)

Before a backtest executes, it must pass through several state-gated boundaries:

| Stage | Name | Authority | Purpose |
| :--- | :--- | :--- | :--- |
| **-0.30** | **Namespace Gate** | `namespace_gate.py` | Enforces naming patterns and Idea Registry binding. |
| **-0.35** | **Sweep Gate** | `sweep_registry_gate.py` | Prevents duplicate/colliding backtest sweeps. |
| **-0.25** | **Canonicalization** | `canonicalizer.py` | Enforces strict YAML structural standards. |
| **-0.10** | **Preflight** | `preflight.py` | Verifies data availability and temporal range integrity. |
| **0.50** | **Semantic Validation** | `semantic_validator.py` | Ensures `strategy.py` signature aligns with directive. |
| **0.75** | **Dry-Run** | Pipeline Engine | Executes a 1000-bar sample to ensure logic stability. |

---

## 3. Maintenance Protocols (`SOP_CLEANUP`)

Our recent reconciliation work followed the **Registry-First Authority Model**:
*   **Sole Authority**: `run_registry.json` is the only ledger that determines if a run is "valid."
*   **Zombie Management**: Any folder on disk not in the registry is a "zombie" and must be purged.
*   **Disposable UI**: The `backtests/` folder is considered a "Disposable UI View," safely deletable once the underlying run is no longer active.

---

## 4. Execution Invariants (Core Rules)

*   **Linearity**: States (e.g., STAGE_1 -> STAGE_2) are non-reentrant.
*   **Atomicity**: A directive remains in `active/` (or `active_backup/`) until the entire pipeline reaches `COMPLETE`.
*   **Immutability**: Once a run is complete, its artifacts (manifests, trades) are locked.
*   **Clean Repository**: All runtime data MUST be written to `TradeScan_State/`, never the repo root.

---

## 5. Reference Documents
*   [trade_scan_invariants_state_gated.md](file:///c:/Users/faraw/Documents/Trade_Scan/governance/SOP/trade_scan_invariants_state_gated.md)
*   [SOP_TESTING.md](file:///c:/Users/faraw/Documents/Trade_Scan/governance/SOP/SOP_TESTING.md)
*   [SOP_CLEANUP.md](file:///c:/Users/faraw/Documents/Trade_Scan/governance/SOP/SOP_CLEANUP.md)
*   [SOP_AGENT_ENGINE_GOVERNANCE.md](file:///c:/Users/faraw/Documents/Trade_Scan/governance/SOP/SOP_AGENT_ENGINE_GOVERNANCE.md)
