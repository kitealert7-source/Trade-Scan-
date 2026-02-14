# Governance Friction Audit: Data Bias (CLEAN vs RESEARCH)
**Date:** 2026-02-09
**Status:** READ-ONLY DIAGNOSIS
**Scope:** SOPs, Codebase, Naming Conventions

## 1. Confirmed CLEAN Bias Points

### A. Codebase Defaults (HIGH RISK)
The following files contain hardcoded dependencies on `CLEAN` data, which may cause execution failures or invalid metrics when `RESEARCH` data is required (v5 standard).

| File | Line | Risk | Observation |
|------|------|------|-------------|
| `engine_dev/vrs001_executor.py` | 30 | HIGH | `DATA_ROOT` hardcoded to `.../CLEAN`. Runtime will fail if `RESEARCH` is effectively enforced. |
| `tools/diagnose_vrs003.py` | 11 | HIGH | Diagnosis logic explicitly looks in `.../CLEAN`. Will report "No Data" for Research-based runs. |
| `tools/run_stage1.py` | 110 | HIGH | (FIXED in v5) Previously hardcoded to `CLEAN`. Served as the template for other scripts. |

### B. Developer Instructions & Docstrings (MEDIUM RISK)
Documentation and comments implying `CLEAN` is the only valid state.

| File | Location | Risk | Observation |
|------|----------|------|-------------|
| `universal_research_engine/.../main.py` | Docstring (L49) | MED | Explicitly defines `df` arg as "DataFrame with OHLCV data (**clean, pre-processed**)". Discourages raw research data use. |
| `governance/preflight.py` | N/A | LOW | Variable names like `clean` used for string sanitization (unrelated but adds noise). |

### C. SOPs & Governance (LOW RISK)
| File | Section | Risk | Observation |
|------|---------|------|-------------|
| `SOP_TESTING.md` | General | LOW | No explicit bias found, but lacks explicit authorization for `RESEARCH` data, leaving "Clean" as the implicit safe choice. |

## 2. RESEARCH Data Status
*   **Current Status**: Treated as **Secondary / Optional**.
*   **Implicit Handling**: Not mentioned in `main.py` contracts or Engine templates.
*   **Friction**: Developers copying `vrs001_executor.py` or reading `main.py` will default to `CLEAN` without realizing `RESEARCH` is the v5 standard.

## 3. Do NOT Fix List (Strict Read-Only)
*   Do NOT update `vrs001_executor.py` (Legacy Engine).
*   Do NOT update `diagnose_vrs003.py` (Legacy Tool).
*   Do NOT rewrite `main.py` docstrings (Immutable Engine Code).
*   Do NOT modify `SOP_TESTING.md` (Governance scope).

## 4. Conclusion
Systemic bias exists primarily in **Developer Examples** (`vrs001_executor.py`) and **Interface Contracts** (`main.py`). While `run_stage1.py` has been patched for v5, the surrounding ecosystem still nudges developers toward `CLEAN` data paths.
