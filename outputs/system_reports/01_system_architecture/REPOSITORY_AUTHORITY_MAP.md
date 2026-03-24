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
| .agents/, .claude/, .skills/ | **SOURCE** | Agentic workflows and skill definitions. |
| .git/, .gitignore | **SOURCE** | Version control infrastructure. |
| AGENT.md, README.md | **SOURCE** | System documentation and agent instructions (25 codified SYSTEM INVARIANTS). |
| RESEARCH_MEMORY.md | **SOURCE** | Active research log and cross-conversation context. |
| SYSTEM_STATE.md | **SOURCE** | High-level system health and state summary. |
| acktest_directives/INBOX/ | **GOVERNANCE** | Staging area for unverified directives pending sweep/namespace/canonical admission. |
| acktest_directives/ACTIVE/ | **SOURCE** | Authority: Admitted research intent and execution instructions. |
| acktest_directives/completed/ | **STATE** | Completed directives moved from ACTIVE on PORTFOLIO_COMPLETE. |
| config/ | **SOURCE** | System paths, data roots, and operational constants. |
| strategies/ | **SOURCE** | Active/tested trading strategies. |
| 	ests/ | **SOURCE** | System-wide validation and regression suite. |
| 	ools/ | **SOURCE** | Operational control surface and entry points. Protected Infrastructure (INVARIANT 11). |
| 	ools/orchestration/ | **SOURCE** | Pipeline stage coordination infrastructure. Protected Infrastructure. |
| 	ools/system_logging/ | **SOURCE** | Centralized failure logging with 5 MB / 7-day auto-rotation. |
| 
esearch/ | **SOURCE** | Research scratchpads and unstructured documentation. |
| governance/ | **GOVERNANCE** | Safety gates, admission gates, and compliance logic. Protected Infrastructure (INVARIANT 11). |
| governance/namespace/ | **GOVERNANCE** | Token dictionaries and alias policy for namespace enforcement. |
| governance/SOP/ | **GOVERNANCE** | Standard Operating Procedures for pipeline governance. |
| alidation/ | **GOVERNANCE** | Data, economic, and signal validation modules. |
| engines/, engine_dev/ | **ENGINE** | Core execution engines. Protected Infrastructure (INVARIANT 11). |
| execution_engine/ | **ENGINE** | Specialized execution guards and engine components. |
| indicators/ | **ENGINE** | Authoritative technical indicator library. |
| 
egimes/ | **ENGINE** | Market regime detection and classification logic. |
| scanners/ | **ENGINE** | Strategy discovery and parameter scanning tools. |
| signals/ | **ENGINE** | Trade signal generation and processing logic. |
| data_access/ | **DATA_AUTHORITY** | Data ingress adapters and ingestion logic. |
| data_root | **DATA_AUTHORITY** | Symbolic reference to authoritative data storage. |
| 
egistry/ | **TRUST_AUTHORITY** | Authoritative ledgers and run-lifecycle tracking. |
| ault/ | **TRUST_AUTHORITY** | System snapshots and authoritative rollbacks. 
oot_of_trust.json is human-only. |
| TradeScan_State/runs/ | **STATE** | Authoritative raw execution history and per-run state. |
| TradeScan_State/backtests/ | **STATE** | Aggregated reports and strategy filters. |
| TradeScan_State/candidates/ | **STATE** | Passed strategies awaiting portfolio allocation. |
| TradeScan_State/registry/ | **TRUST_AUTHORITY** | Authoritative run and sweep lifecycle ledgers. |
| TradeScan_State/strategies/ | **STATE** | Deployable capital artifacts per strategy (atomic and composite portfolios). |
| outputs/system_reports/ | **SOURCE** | Authority: System architecture maps and audit reports. Protected. |
| outputs/logs/ | **STATE** | Pipeline failure logs. Auto-rotated at 5 MB or 7 days, retaining 4 archives. |
| BACKUPDATA/ | **STATE** | Temporary system backups. |
| rchive/ | **LEGACY** | Decommissioned repository artifacts. Candidate for archival. |
| laegacy_strategies/ | **LEGACY** | Obsolete/Archived trading strategies. Candidate for archival. |

> **Note on Scratch Scripts**: All ad-hoc, diagnostic, or utility scripts created during agent sessions must be placed in /tmp/ exclusively (INVARIANT 25). Any such script appearing in the repository root without being part of the governed toolset constitutes a governance violation.

---

## SECTION 3 — Cleanup & Externalization Strategy

Based on this classification, the following mechanical rules apply:

1. **Immutability Protection**: Folders marked as **SOURCE**, **GOVERNANCE**, **ENGINE**, **DATA_AUTHORITY**, and **TRUST_AUTHORITY** must be protected. No automated process should delete artifacts here without a manual peer review.
2. **State Externalization (Completed)**: Folders mapped to **STATE** are externalized under the TradeScan_State/ directory to preserve repository cleanliness. The root directory is strictly for **SOURCE** and **ENGINE** artifacts.
3. **Mechanical Pruning**: Folders marked as **LEGACY** are safe for compression and removal to the long-term archive if their registry hash persists in the ault/.
4. **Deployable Artifact Root**: TradeScan_State/strategies/ is the authoritative location for all deployable capital artifacts. No capital output goes into the repository root.

---
**Status**: Authoritative Classification Map | **Version**: 2.0.0 | **Last Updated**: 2026-03-23
