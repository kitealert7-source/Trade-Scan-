# Post-Execution Report: Lessons Learned & Smooth Run Recommendations

Based on the recovery of the orphaned morning runs and the subsequent ledger reconciliation, here are the critical lessons and recommended modifications to ensure the next batch runs efficiently.

## 1. Technical Lessons Learned

### Indentation Sensitivity in Templates
*   **Issue**: Manual logic patching in `strategy.py` caused semantic validation failures because the `prepare_indicators`, `check_entry`, and `check_exit` methods were not properly indented relative to the `class Strategy` block.
*   **Lesson**: Never trust manual line-replacement for method implementation.
*   **Modification**: The `strategy_provisioner.py` and the `patch_strategies.py` script now enforce strict 4-space indentation for all injected blocks.

### Directive-Indicator Mismatch
*   **Issue**: Directives for S08-S12 families were missing the declaration of the `momentum.ultimate_c_percent` indicator, leading to "Undeclared Indicator" preflight errors.
*   **Lesson**: Preflight Admission Gates are working exactly as intended—they caught a configuration drift that would have caused silent runtime errors.
*   **Adjustment**: Ensure the `.txt` directive file exactly matches the indicator imports used in the logic.

### Numerical Volatility Regimes
*   **Issue**: The v1.5.3 engine outputs numerical regimes (e.g., `-1`, `0`), but the Stage-2 report generator expected strings (`"low"`, `"normal"`).
*   **Lesson**: Tooling must be backward-compatible with engine-emitted data schemas.
*   **Fix Applied**: `stage2_compiler.py` has been patched to handle both string and numerical mappings.

---

## 2. "Smooth Run" Modifications (The Pre-Flight Checklist)

To run the next batch efficiently, follow this checklist:

### A. Pre-Execution (Directive Audit)
1.  **Check Indicators**: Verify that every `from indicators...` line in your implementation plan exists in the `indicators:` section of the `.txt` directive.
2.  **Verify Suffixes**: If re-running a strategy, add a `__v2` or similar suffix to the directive `name` to avoid ID collisions in the registry.

### B. Execution (The Orchestrator)
1.  **Use `--reset` carefully**: If a directive fails, use `tools/reset_directive.py` to move it back to `INITIALIZED` state before re-running the pipeline.
2.  **Monitor Admission Gates**: If the pipeline pauses at "Admission Gate: Human Implementation Required", it means the `strategy.py` is still a boilerplate. Apply your logic and resume.

### C. Post-Execution (Auto-Ledger)
1.  **Physical-Only Sync**: If you stop or restart mid-batch, run the `full_regeneration` script (from our reconciliation task) to ensure the Excel files match the actual folders.
2.  **Avoid Manual Edits**: Do not manually add rows to `Strategy_Master_Filter.xlsx`; always use the `stage3_compiler.py` or the recovery script to keep it authoritative.

---

## 3. Recommended Infrastructure Updates
> [!TIP]
> **Consolidate State Managers**: We should eventually merge the "Legacy" `run_metadata.json` and "Modern" `manifest.json` parsing into a single authoritative `ContainerHandler` to prevent future mismatch errors in stage-2 reports.
