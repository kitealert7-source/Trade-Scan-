# System Hardening & Implementation Framework

The TradeScan system is now governed by a formalized 4-stage execution framework to ensure deterministic outcomes and eliminate repetitive failure patterns.

## Stage 1: Directive Admission Gate
- **Temporal Coverage Check**: Mandatory verification of data availability in `MASTER_DATA` before directive creation.
- **Canonical Schema Enforcement**: Automatic validation of YAML structure via `tools/canonicalizer.py`.
- **Namespace Governance**: Re-verification of naming conventions to prevent registry collisions.

## Stage 2: Strategy Admission Gate
- **Governance-Native Boilerplate**: All `strategy.py` files must include the `# --- STRATEGY SIGNATURE ---` markers.
- **Semantic Coverage Verification**: Automated check ensuring all directive parameters are referenced in the logic.
- **Human Review Checkpoint**: Mandatory approval gate before execution begins.

## Stage 3: Pipeline Execution
- **Root-of-Trust Integrity**: Verification of tool hashes and engine versions.
- **Warmup Extension Assertion**: Pre-execution regression test to prevent uninitialized indicator data.
- **Automatic Metadata Binding**: Immutable linking of runs to their originating directives and strategy code.

## Stage 4: Batch Finalization
- **Capital Wrapper Evaluation**: Sequential execution of all risk profiles.
- **Authoritative Ledger Update**: Ranking and enrichment of the Master Portfolio Sheet.
- **Candidate Promotion**: Physical migration of passing runs to the `candidates/` folder.
- **Final Handover**: Presentation of the Promotion Report as the completion artifact.

---

## Technical Guards Summary

| Guard | Mechanism | Benefit |
| :--- | :--- | :--- |
| **Data Sensor** | Step 0 Pre-check | Eliminates "Data Range Insufficient" failures |
| **Logic Anchor** | START/END Markers | Ensures compatibility with StrategyProvisioner |
| **Reconciler Sweep** | Cleanup Reconciler | Prevents directory drift and registry mismatches |
| **Chain Automation** | finalize_batch.py | Eliminates manual orchestration gaps |

> [!IMPORTANT]
> **COMPLIANCE RULE**
> No core orchestrator (`run_pipeline.py`) or engine code was modified to implement this framework. 
> Hardening is achieved through workflow governance and pre-execution validation gates.
