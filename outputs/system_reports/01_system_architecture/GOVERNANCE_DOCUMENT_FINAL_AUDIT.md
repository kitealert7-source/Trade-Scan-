# Governance Document Final Audit Report

This report summarizes the final consistency audit of the TradeScan governance framework following the repository infrastructure hardening.

---

## 1. Governance Document Inventory

The following authoritative documents define the governance layer of Trade_Scan:

| File Name | Purpose | Referenced by Pipeline/Tools |
| :--- | :--- | :--- |
| `governance/README.md` | Orientation & Hierarchy | - |
| `governance/directive_execution_model.md` | Core execution strategy | Descriptive |
| `governance/RELEASE_GATE.md` | Engine release standards | Descriptive |
| `governance/preflight.py` | Admission gate logic | **Master Orchestrator** |
| `governance/semantic_coverage_checker.py` | Parameter usage verification | **Master Orchestrator** |
| `governance/SOP/SOP_TESTING.md` | Backtest & Artifact law | Authorititive SOP |
| `governance/SOP/ORCHESTRATION_CONTRACT.md` | Software contract for pipeline | Tools Layer |
| `governance/SOP/TRADE_SCAN_DOCTRINE.md` | System philosophy | High-Level |
| `governance/SOP/trade_scan_invariants_state_gated.md` | System Laws (Non-negotiable) | Authoritative Law |
| `governance/SOP/SOP_OUTPUT.md` | Presentation & Metrics | Results Layer |
| `governance/SOP/SOP_CLEANUP.md` | Filesystem hygiene | Maintenance Tools |
| `governance/SOP/STRATEGY_PLUGIN_CONTRACT.md` | Strategy isolation rules | Engine/Validators |

---

## 2. Architecture Alignment Findings

**CRITICAL MISMATCH**: Core governance documents still reference repository-local runtime paths. This contradicts the Clean Repository architecture.

| Document | Outdated References Found | Recommended Alignment |
| :--- | :--- | :--- |
| `SOP_TESTING.md` | `backtests/<strategy_name>/` | `TradeScan_State/backtests/` |
| `trade_scan_invariants_state_gated.md` | `runs/`, `backtests/`, `run_registry.json` | `TradeScan_State/...` |
| `ORCHESTRATION_CONTRACT.md` | `runs/`, `run_registry.json` | `TradeScan_State/...` |
| `TRADE_SCAN_DOCTRINE.md` | `runs/`, `backtests/` | `TradeScan_State/...` |
| `directive_execution_model.md` | `runs/` | `TradeScan_State/` |

> [!WARNING]
> While `AGENT.md` and `SYSTEM_SURFACE_MAP.md` are updated, the "laws" in the `governance/SOP/` directory still permit local state creation. This creates a risk of "governance drift."

---

## 3. Pipeline Stage Consistency

The audit detected discrepancies in the definition of pipeline stages across the documentation hierarchy.

| Source | Stage Model Described | Status |
| :--- | :--- | :--- |
| **AGENT.md / SURFACE_MAP** | **10-Stage Model** (incl. -0.25, -0.30, -0.35, 0, 0.5, 0.55, 0.75, 1, 2, 3, 3A, 4) | **Authoritative & Hardened** |
| `SOP_TESTING.md` | Partial list (Stage-1, 2, 3, 3A emphasized) | Incomplete |
| `trade_scan_invariants_state_gated.md` | Legacy list (FSM states only) | Outdated |

**Findings**:
- `SOP_TESTING.md` correctly references the Namespace Gate (-0.30) and Sweep Gate (-0.35) but lacks explicit mapping for Stage 0.55 (Coverage) and Stage 0.75 (Dry Run).
- `trade_scan_invariants_state_gated.md` Invariant 2 needs to include Stage 0.55 and Stage 0.75 as mandatory FSM transitions.

---

## 4. Rule Alignment Review

The system invariants and SOPs were reviewed against the newly established "Hardened Invariants."

| Rule | Document Presence | Alignment Status |
| :--- | :--- | :--- |
| **Clean Repository Rule** | `AGENT.md` ONLY | **MISSING from `governance/SOP/`** |
| **Root-of-Trust Vault Binding** | `AGENT.md`, `preflight.py` | Accurate |
| **Guard Manifest Integrity** | `AGENT.md` | Accurate |
| **Directive Schema Freeze** | `AGENT.md`, `SOP_TESTING` | Accurate |
| **Namespace Governance** | `SOP_TESTING`, `AGENT.md` | Accurate |
| **Sweep Registry Gate** | `SOP_TESTING`, `AGENT.md` | Accurate |
| **Human Approval Admission Gate** | `AGENT.md`, `SOP_TESTING` | Accurate |
| **Protected Infrastructure Rule** | `AGENT.md` | Accurate |

---

## 5. Cross-Document Consistency

- **`SYSTEM_SURFACE_MAP.md` vs `SOP_TESTING.md`**: SURFACE_MAP correctly identifies the `TradeScan_State/` root; `SOP_TESTING.md` incorrectly identifies `backtests/` as a local folder.
- **`REPOSITORY_AUTHORITY_MAP.md` vs `TRADE_SCAN_DOCTRINE.md`**: AUTHORITY_MAP correctly classifies `runs/` as a target for removal; DOCTRINE still treats it as a governed local path.
- **`AGENT.md` vs `trade_scan_invariants_state_gated.md`**: `AGENT.md` defines the modern "Clean Repo" reality; the Invariants document lacks the "Clean Repository Rule" (Invariant 24).

---

## 6. Recommended Documentation Adjustments

To achieve full documentation parity with the hardened architecture, the following updates are recommended:

1.  **Update Path References**: Perform a global documentation swap in the `governance/` directory:
    - `runs/` → `TradeScan_State/runs/`
    - `backtests/` → `TradeScan_State/backtests/`
    - `registry/` → `TradeScan_State/registry/`
2.  **Harmonize FSM States**: Update `trade_scan_invariants_state_gated.md` Invariant 2 to include Stage 0.55 (SEMANTIC_COVERAGE) and Stage 0.75 (DRY_RUN).
3.  **Formalize Clean Repo Rule**: Move the **Clean Repository Rule** from `AGENT.md` into `trade_scan_invariants_state_gated.md` as Invariant 11.
4.  **Reference State Root**: Update `SOP_TESTING.md` Section 5 to explicitly designate `TradeScan_State/` as the only authoritative state root.

---

## 7. Audit Verdict: PASS (Conditional)

The system documentation is **functionally correct** regarding safety and logic but **architecturally outdated** regarding pathing and stage numbering. The infrastructure hardening is successful, but the governance "paper trail" requires a final synchronization pass to match the reality of `TradeScan_State/`.

**Audit ID**: GOV-DOC-AUDIT-2026-03-13
**Status**: COMPLETE
