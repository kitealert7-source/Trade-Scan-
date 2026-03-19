# TradeScan Documentation Audit: Stale & Redundant Reports

**Date:** 2026-03-17  
**Objective:** Identify stale, point-in-time, or redundant documentation within `outputs/system_reports/` for cleanup and logical refactoring, adhering to proper system hygiene.

---

## 1. Delete Candidates (Stale / Redundant)

The following files are historical point-in-time implementation plans, step-by-step migration logs, or superseded evaluations. They no longer describe the current state of the architecture and clutter the documentation map. They are safe to delete or shift to an external cold-archive.

### `03_pipeline_orchestration/`
*These documents heavily reference "Phase 2" implementation steps, "proposed" decoupling evaluations, and superseded execution blueprints.*
- `PHASE2_IMPLEMENTATION_PLAN_UPDATE.md`
- `PHASE2_READINESS_SANITY_TEST.md`
- `PIPELINE_DECOUPLING_EVALUATION.md`
- `PIPELINE_EXECUTION_AUDIT.md`
- `PIPELINE_STRUCTURAL_AUDIT.md`
- `walkthrough_execution_audit.md`

### `07_system_complexity_reduction/`
*This entire directory is a historical log of the 7-step orchestration simplification refactoring. The system has thoroughly stabilized post-refactor.*
- `SYSTEM_COMPLEXITY_REFACTOR_PLAN.md`
- `SYSTEM_COMPLEXITY_STEP1_BASELINE.md`
- `SYSTEM_COMPLEXITY_STEP2_MODULE_EXTRACTION.md`
- `SYSTEM_COMPLEXITY_STEP3_ORCHESTRATION_CORE.md`
- `SYSTEM_COMPLEXITY_STEP4...`
- `SYSTEM_COMPLEXITY_STEP5...`
- `SYSTEM_COMPLEXITY_STEP6...`
- `SYSTEM_COMPLEXITY_STEP7...`

### `09_experiment_logs/`
*These contain point-in-time reviews of specific one-off pipeline runs (P04, S07) early in the development lifecycle.*
- `MODULAR_IMPACT_VALIDATION.md`
- `RESEACH_SEPARATION_PLAN_S07.md`
- `RESRCH_PHASE2_ENG_REVIEW_P04.md`

### Root Level `outputs/system_reports/`
- `ADMISSION_STABILIZATION_AUDIT_2026-03-16.md`: Reflected the implementation plan for the admission gate from yesterday. The gates are fully integrated and documented in `01_system_architecture/`; this file is redundant.

---

## 2. Refactoring Candidates (Keep & Move)

The following files are accurate and active but located in the wrong directory or naming scheme.

- **`RESEARCH_INFRASTRUCTURE_AUDIT.md` (Root Level)**
  - *Status:* Active and highly relevant.
  - *Refactor:* Move to `06_strategy_research/RESEARCH_INFRASTRUCTURE_AUDIT.md` to prevent root-level clutter.
- **`README_SYSTEM_CAPABILITIES.md` (Root Level)**
  - *Status:* Duplicate/similar to `capability_map_analysis.md`.
  - *Refactor:* Consider merging unique information into `01_system_architecture/capability_map_analysis.md` and then deleting this file.

---

## 3. Active & Healthy (Do Not Touch)

The following groups of files were audited and verified to accurately represent the current state of the execution pipeline, including the latest Engine v1.5.3 updates and Registry-First architecture:

- `01_system_architecture/*` *(Fully up-to-date as of 2026-03-17)*
- `02_engine_core/*` *(Updated specifically for Engine v1.5.3 & Admission constraints)*
- `02_pipeline_audit/pipeline_integrity_report.md` *(Up-to-date schemas)*
- `04_governance_and_guardrails/*` *(Accurately reflects the preflight, sizing, and registry bounds)*
- `05_capital_and_risk_models/*` *(Accurately details the Capital Wrapper structures)*

---

### Recommended Next Action
Run a sweeping deletion/movement command for Categories 1 and 2 to officially sanitize the `system_reports` directory.
