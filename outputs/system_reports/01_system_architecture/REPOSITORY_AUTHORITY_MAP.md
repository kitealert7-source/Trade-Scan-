# Repository Authority Classification Map

This document provides a comprehensive classification of all top-level folders and files within the Trade_Scan repository. This categorization defines the authoritative role of each artifact and serves as a mechanical guide for system hygiene and state separation.

---

## SECTION 1 — Functional Categories

| Category | Authority Type | Responsibility |
| :--- | :--- | :--- |
| **SOURCE** | Structural | Core codebase, documented intent, and active strategies. |
| **GOVERNANCE** | Compliance | Safety gates, validation rules, and admission controllers. |
| **ENGINE** | Logic | Execution engines, signal generators, and indicator libraries. |
| **DATA_AUTHORITY** | Input | Data ingress logic, access layers, and data root references. |
| **TRUST_AUTHORITY** | Truth | Authoritative ledgers, snapshots, and vault configurations. |
| **STATE** | Output | Runtime artifacts, generated reports, and execution results. |
| **LEGACY** | Obsolete | Decommissioned strategies, archives, and old engine variants. |

---

## SECTION 2 — Authority Classification Table

| Folder / File | Category | Architectural Role |
| :--- | :--- | :--- |
| `.agents/`, `.claude/`, `.skills/` | **SOURCE** | Agentic workflows and skill definitions. |
| `.git/`, `.gitignore` | **SOURCE** | Version control infrastructure. |
| `AGENT.md`, `README.md` | **SOURCE** | System documentation and agent instructions. |
| `RESEARCH_MEMORY.md` | **SOURCE** | Active research log and cross-conversation context. |
| `SYSTEM_STATE.md` | **SOURCE** | High-level system health and state summary. |
| `backtest_directives/INBOX/` | **GOVERNANCE** | Staging area for unverified directives. |
| `backtest_directives/ACTIVE/` | **SOURCE** | Authority: Admitted research intent and execution instructions. |
| `config/` | **SOURCE** | System paths, data roots, and operational constants. |
| `strategies/` | **SOURCE** | Active/tested trading strategies. |
| `tests/` | **SOURCE** | System-wide validation and regression suite. |
| `tools/` | **SOURCE** | Operational control surface and entry points. |
| `research/` | **SOURCE** | Research scratchpads and unstructured documentation. |
| `governance/` | **GOVERNANCE** | Safety gates, admission gates, and compliance logic. Verified clean of runtime state. |
| `validation/` | **GOVERNANCE** | Data, economic, and signal validation modules. |
| `engines/`, `engine_dev/` | **ENGINE** | Core execution engines and development versions. |
| `execution_engine/` | **ENGINE** | Specialized execution guards and engine components. |
| `indicators/` | **ENGINE** | Authoritative technical indicator library. |
| `regimes/` | **ENGINE** | Market regime detection and classification logic. |
| `scanners/` | **ENGINE** | Strategy discovery and parameter scanning tools. |
| `signals/` | **ENGINE** | Trade signal generation and processing logic. |
| `data_access/` | **DATA_AUTHORITY** | Data ingress adapters and ingestion logic. |
| `data_root` | **DATA_AUTHORITY** | Symbolic reference to authoritative data storage. |
| `registry/` | **TRUST_AUTHORITY** | Authoritative ledgers and run-lifecycle tracking. |
| `vault/` | **TRUST_AUTHORITY** | System snapshots and authoritative rollbacks. |
| `TradeScan_State/runs/` | **STATE** | Authoritative raw execution history and run state. |
| `TradeScan_State/backtests/` | **STATE** | Aggregated reports and strategy filters. |
| `TradeScan_State/candidates/` | **STATE** | Passed strategies awaiting portfolio allocation. |
| `TradeScan_State/registry/` | **TRUST_AUTHORITY** | Authoritative run and sweep lifecycle ledgers. |
| `outputs/system_reports/` | **SOURCE** | Authority: System architecture maps and audit reports. Protected. |
| `BACKUPDATA/` | **STATE** | Temporary system backups. |
| `archive/` | **LEGACY** | Decommissioned repository artifacts. Candidate for archival. |
| `laegacy_strategies/` | **LEGACY** | Obsolete/Archived trading strategies. Candidate for archival. |

---

## SECTION 3 — Cleanup & Externalization Strategy

Based on this classification, the following mechanical rules apply:

1.  **Immutability Protection**: Folders marked as **SOURCE**, **GOVERNANCE**, **ENGINE**, **DATA_AUTHORITY**, and **TRUST_AUTHORITY** must be protected. No automated process should delete artifacts here without a manual peer review.
2.  **State Externalization (Completed)**: Folders mapped to **STATE** are externalized under the `TradeScan_State/` directory to preserve repository cleanliness. The root directory is strictly for **SOURCE** and **ENGINE** artifacts.
3.  **Mechanical Pruning**: Folders marked as **LEGACY** are safe for compression and removal to the long-term archive if their registry hash persists in the `vault/`.

---
**Status**: Authoritative Classification Map | **Version**: 1.0.0
