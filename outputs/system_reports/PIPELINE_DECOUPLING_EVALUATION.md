# Pipeline Architecture Evaluation: Decoupling Portfolio Generation

**Concept:** Stop the core directive pipeline at the `run` generation stage. Make `portfolio` generation an explicit, separate, on-demand step rather than an automatic trailing stage. This respects the fact that **a pipeline should only produce atomic research units.**

---

## Status Update (2026-03-12)

This evaluation is **partially adopted**:
- Adopted: directive execution now plans independent runs into persistent registry and executes through worker claims.
- Adopted: registry-backed resume safety and per-run lifecycle control.
- Not adopted as default: pipeline still performs automatic Stage-4 portfolio evaluation (`portfolio_evaluator.py`) in the main orchestration path.
- Available manual path: `run_portfolio_analysis.py --run-ids ...` remains explicit/on-demand and is not called automatically by `run_pipeline.py`.

---

## 1. Architectural Assessment & Workflow

Currently, the orchestration pipeline forces a multi-asset directive through to Stage-4 (Portfolio Evaluation), automatically aggregating the assets into a combined portfolio. 

**The Decoupled Workflow:**
1. **Directive Pipeline (Stops Early):** The pipeline processes a directive (e.g., 10 forex pairs) and generates 10 individual atomic run artifacts in the `runs/` directory. **It stops here.**
2. **Registry Logging:** Upon completion, the runs are logged into the central authoritative `runs/run_registry.json` with a tier of `"sandbox"`.
3. **Review & Promotion:** The researcher evaluates the individual asset runs via their UI workspace (`Strategy_Master_Filter.xlsx`). They select high-performing individual runs (e.g., EURUSD from test 1, GBPUSD from test 10) and promote them to the candidate tracking sheet.
4. **Explicit Portfolio Construction:** The researcher explicitly fires up a dedicated portfolio tool, feeding it the specific `run_ids` they wish to combine: `run_portfolio_evaluator([R21, R44, R98])`.

**Key Benefits:**
1. **Radical artifact reduction:** No disposable or automatic portfolios generated. 
2. **Reduced pipeline complexity:** The pipeline stops at run execution, decoupling Stage-4 failures from core run generation.
3. **Research flexibility:** Portfolios are no longer bound by individual multi-asset directives—researchers can easily combine asset runs from vastly different historical directive executions.

---

## 2. Storage & Reproducibility Impact

Decoupling portfolio generation enables the **Runs as Immutable Shared Libraries** paradigm.

When the `portfolio_evaluator` builds a new snapshot in `strategies/P001/`, it does **not** copy the run artifacts. It simply generates a `portfolio_composition.json` file documenting the `run_ids` it used:
```json
{
  "portfolio_id": "P003",
  "run_ids": ["R042", "R055", "R081"]
}
```

**Storage Math (Old vs New):**
*   **Old System:** 10 directives × 10 assets = 100 runs + 10 automatic portfolios. High redundancy.
*   **New System:** Pipeline generates 100 atomic runs. Cleanup sweeps 85 unpromoted/unreferenced sandbox runs. The researcher builds 3 portfolios entirely composed of the 15 retained candidate/portfolio runs. Total disk footprint: **~15 runs.**

This guarantees perfect reproducible math because the constituent runs are immutable and explicitly preserved by the central `run_registry.json` cleanup logic.

---

## 3. Recommended Implementation Changes

1.  **Pipeline Flag:** Add a `--skip-portfolio` flag to the orchestrator (or default to `--no-portfolio`). The pipeline terminates when the atomic artifacts hit the `runs/` folder.
2.  **Portfolio Generator:** Refactor `tools/portfolio_evaluator.py` to accept lists of `run_ids` as input arguments, building aggregations entirely dynamically on demand.
