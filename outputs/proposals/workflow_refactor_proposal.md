# Proposal: Workflow Refactoring & Simplification

## 1. Audit Report

### Redundancy & Fragmentation
- **Admission Gate Fragmentation**: Steps 1.75 (Canonicalization), 1.80 (Namespace), and 1.85 (Sweep Registry) are redundant as standalone manual steps because they are already auto-enforced by Stage-0 of `run_pipeline.py`.
- **Manual Strategy Patching**: Step 1.5 (Classification) and manual patching often lead to the "Boilerplate Failure" (missing markers) encountered in recent runs. This should be a consolidated validation gate.
- **Workflow Bloat**: The document currently mixes 13+ steps including spreadsheet formatting and directory cleanup, which obscures the critical execution path.

### Friction Points
| Point | Description |
| :--- | :--- |
| **Ambiguous Termination** | The pipeline "stops" multiple times (dry-run, research boundary, capital wrapper) without a clear terminal state. |
| **Manual Gate Checks** | Manual invocation of `canonicalizer.py` and `namespace_gate.py` is error-prone and duplicates internal orchestrator logic. |
| **Maintenance Noise** | Spreadsheet formatting (`format_excel_artifact`) and workspace hygiene are presented as "next steps" in execution, causing distraction from the backtest mission. |

---

## 2. Proposed Simplified Workflow

### Objective: The "Golden Path" to Candidates
A streamlined 7-step process focused exclusively on moving an idea from directive to candidates registry.

**Step 0: Directive Admission Gate** (Pre-check)
- *Internal Enforcement*: Temporal coverage, Canonicalization, Namespace, and Sweep Registry.
- *Command*: `python tools/preflight_gate.py <DIRECTIVE>` (Consolidated tool)

**Step 1: Provision-Only Validation**
- *Action*: Generate strategy skeleton and verify imports.
- *Command*: `python tools/run_pipeline.py --all --provision-only`

**Step 2: Human Strategy Review**
- *Action*: Implement entry/exit logic and obtain manual approval.
- *Gate*: Must contain `# --- STRATEGY SIGNATURE ---` markers.

**Step 3: Warmup Verification Test**
- *Action*: Regression test for data integrity.
- *Command*: `python tools/tests/test_warmup_extension.py`

**Step 4: Full Pipeline Execution**
- *Action*: Run Stages 1-4 (Execution to Portfolio Evaluation).
- *Command*: `python tools/run_pipeline.py --all`

**Step 5: Capital Wrapper**
- *Action*: Generate deployable risk profiles.
- *Command*: `python tools/capital_wrapper.py <BATCH_NAME>`

**Step 6: Candidate Promotion**
- *Action*: Physical migration of passing runs.
- *Command*: `python tools/filter_strategies.py`

**STOP** - Mission Complete.

---

## 3. Maintenance Task Separation

The following operations are relocated to a new `OPERATOR_MAINTENANCE.md` guide:
- **Workspace Hygiene**: `cleanup_reconciler.py`
- **Artifact Aesthetics**: `format_excel_artifact.py`
- **Deep Research**: Robustness suites and optional seasonality analysis.

---

## 4. Migration Plan (Edits to `execute-directives.md`)

1.  **Header**: Truncate existing text. Replace with "Core Execution Workflow".
2.  **Admission Gate**: Delete individual 1.xx gates. Insert "Step 0: Directive Admission Gate" with a unified checklist.
3.  **Strategy Generation**: Simplify "GENESIS/PATCH/CLONE" into a single "Strategy Admission Gate".
4.  **Completion Boundary**: Delete spreadsheet formatting (Step 13). Insert "Step 6: Candidate Promotion" as the final authoritative step.
5.  **Appendix**: Move "Protected Infrastructure" and "System Contract" to a consolidated `GOVERNANCE_CHARTER.md`.

---

## 5. Impact Confirmation

> [!IMPORTANT]
> **SYSTEM INVARIANTS PRESERVED**
> This refactor is purely a **documentation restructuring**. 
> - No internal stage ordering in `run_pipeline.py` is changed.
> - The authoritative `run_registry.json` and logic gates remain identical.
> - The result is a reduced manual cognitive load with zero impact on engine behavior.
