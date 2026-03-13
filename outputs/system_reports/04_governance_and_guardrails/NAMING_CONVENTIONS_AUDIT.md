# Naming Conventions & Nomenclature Audit

**Objective:** Audit the proposed Run Lifecycle & Decoupled Pipeline design against the existing TradeScan naming schemas, metadata standards, and directory layouts to ensure clean integration without introducing conflicting logic.

---

## 1. Identifiers & Hashes

### `run_id` Nomenclature
- **Proposed:** Examples use `R001`, `R042`.
- **Current TradeScan Standard:** A 12-character deterministic hex hash generated via `tools/pipeline_utils.py::generate_run_id` (e.g., `a1b2c3d4e5f6`).
- **Audit Result:** Compatible. The proposal's logic holds perfectly if `R001` is strictly treated as a shorthand for the 12-char hex hash.
- **Recommendation:** No codebase naming changes required. The registry and physical folders will natively absorb the 12-char hex hashes.

### `portfolio_id` Nomenclature
- **Proposed:** Examples use `P001`, `P00x`.
- **Current TradeScan Standard:** Portfolios are currently named matching the `strategy_id` (e.g., `01_MR_FX_1H_ULTC_REGFILT_S07_V1_P00`) automatically, or via `deterministic_portfolio_id(run_ids)` which generates an MD5-like string.
- **Audit Result:** Compatible, but requires standardizing the generation schema.
- **Recommendation:** Use the existing `deterministic_portfolio_id(run_ids)` function natively found in `tools/run_portfolio_analysis.py` for on-demand portfolios, or allow operators to pass a natural string identifier. Do not invent a new `P001` auto-incrementing schema.

---

## 2. Directory Structure & Atomic Cohesion

### The Split Artifact Problem (CRITICAL CONFLICT)
- **Proposed Layout:** Implies that an atomic run lives entirely within `runs/<run_id>/` and can be easily moved to `candidates/<run_id>/`.
- **Current TradeScan Standard:** A single execution is fundamentally split in two:
  1. `runs/<run_id>/`: Contains state flow (`run_state.json`), code snapshots, and manifests.
  2. `backtests/<strategy_id>_<symbol>/`: Contains the actual raw data arrays (`results_tradelevel.csv`, `equity_curve.csv`).
- **Audit Result:** Conflict. If the operator promotes `runs/<run_id>/` to `candidates/`, the actual trade data is left behind in `backtests/`, meaning the portfolio evaluator cannot construct a portfolio using only the promoted folder.
- **Recommendation:** Refactor Stage-1 (`tools/run_stage1.py`) to write **all** execution artifacts, data frames, and manifests strictly into `runs/<run_id>/data/`. This successfully unifies the run into the single "atomic library" payload specified by the new architecture. `backtests/` should then be reserved exclusively for the operator Excel UI views.

### Location of `Master_Portfolio_Sheet.xlsx` (MINOR DEVIATION)
- **Proposed Layout:** Placed under `backtests/`.
- **Current TradeScan Standard:** Located under `strategies/Master_Portfolio_Sheet.xlsx`. 
- **Audit Result:** Deviation.
- **Recommendation:** Keep `Master_Portfolio_Sheet.xlsx` in its native location (`strategies/`). Moving it to `backtests/` would needlessly break existing downstream tools (e.g., `tools/reconcile_portfolio_master_sheet.py`).

---

## 3. The `run_registry.json` Location
- **Proposed:** `runs/run_registry.json`
- **Current TradeScan Standard:** The `runs/` directory exclusively holds timestamped or hashed subdirectories. Dropping a singular flat file into it is unconventional but completely valid.
- **Audit Result:** Safe. However, for extreme cleanliness scaling to 10k items, creating a dedicated `run_registry/` or `registry/` folder at the project root ensures namespace isolation. `runs/run_registry.json` is perfectly acceptable for Phase 1.

---

## Conclusion
The architectural logic is flawless, but physical pathing needs to respect the existing codebase. 

**Required actions for seamless integration:**
1. Maintain 12-char hex hashes for `run_id`.
2. Consolidate **all** output data (CSV files currently going to `backtests/`) into `runs/<run_id>/` so the run is actually a complete, movable atomic asset.
3. Leave `Master_Portfolio_Sheet.xlsx` in the `strategies/` folder.
