# STAGE-0.5 IMPACT ANALYSIS

## Section A: Stage-0.5 Summary

1. **Scope**: Performs **Semantic Validation** between the Directive (Intent) and the Strategy Code (Implementation).
2. **Position**: Executes **immediately after** `exec_preflight.py` (`PREFLIGHT_COMPLETE`) and **strictly before** `run_stage1.py`.
3. **State Transition**: Moves run state from `PREFLIGHT_COMPLETE` → `SEMANTIC_VALIDATION_START` → `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`.
4. **Identity Check**: Verifies that the `Strategy` field in the Directive resolves to a valid `strategy.py` on disk.
5. **Parameter Alignment**: Verifies that parameters declared in the Directive exist in the Strategy's `parameters` dict (if applicable).
6. **Indicator verification**: Verifies that indicators requested in the Directive are actually imported/used by the Strategy code.
7. **No Artifacts**: Does **NOT** produce trade records, charts, or JSON reports.
8. **No Logic Modification**: Does **NOT** alter the strategy code or the directive content.
9. **No Vault Interaction**: Does **NOT** read from or write to the Vault.
10. **State Gating**: Acts as a **mandatory gate**; `run_stage1.py` will reject execution if state is not `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`.
11. **Failure Mode**: **Hardware Stop** (Exit Code 1) if validation fails.
12. **Independence**: Can be run standalone or as part of the `run_pipeline.py` chain.

## Section B: Files to Modify

### 1. `tools/pipeline_utils.py`

* **Justification**: The `PipelineStateManager` class enforces valid state transitions. The new stage introduces new states.
* **Modification**: Update `ALLOWED_TRANSITIONS` dictionary to include:
  * `PREFLIGHT_COMPLETE` → `SEMANTIC_VALIDATION_START`
  * `SEMANTIC_VALIDATION_START` → `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`
  * `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID` → `STAGE_1_START`

### 2. `tools/run_pipeline.py`

* **Justification**: This is the master orchestrator. It must invoke the new validation logic and manage the new state transitions.
* **Modification**:
  * Import the new validation module.
  * Insert a new execution step (Step 0.5) after Preflight and before Stage 1.
  * Call `state_manager.transition_to("SEMANTIC_VALIDATION_START")`.
  * Execute validaton.
  * Call `state_manager.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")`.

### 3. `tools/semantic_validator.py` (NEW FILE)

* **Justification**: A distinct module is required to encapsulate the semantic validation logic, keeping `run_pipeline.py` clean and `exec_preflight.py` focused on structural checks.
* **Content**:
  * Function to parse `Strategy` from Directive.
  * Function to load `strategy.py` source (AST parsing or regex).
  * Logic to compare Directive requirements vs Code implementation.

## Section C: Files Explicitly Untouched

1. **`tools/run_stage1.py`**: Execution logic (Stage 1) is immutable. It only reads the *result* of previous stages via state.
2. **`tools/exec_preflight.py`**: Stage 0 logic (Structural Check) remains unchanged.
3. **`engine_dev/.../main.py` & `execution_loop.py`**: Core engine logic is strictly code-frozen.
4. **`strategies/.../strategy.py`**: Strategy files are read-only targets for validation.
5. **`tools/portfolio_evaluator.py`**: Downstream Stage 4 logic is unaffected.
6. **`tools/stage3_compiler.py`**: Downstream Stage 3 logic is unaffected.

## Section D: Risk Assessment

1. **Parsing Fragility**: If the Directive parser used in Stage 0.5 differs slightly from `run_stage1.py`'s internal parser, valid directives might fail validation. *Mitigation: Use shared `pipeline_utils.parse_directive`.*
2. **Strategy Resolution**: If `run_stage1.py` has complex fallback logic for locating strategies that Stage 0.5 doesn't replicate, it could flag valid strategies as missing.
3. **State Synchronization**: Failing to update `ALLOWED_TRANSITIONS` correctly will cause the pipeline to crash with an "Illegal State Transition" error immediately.
4. **Orchestration Overhead**: Adding another subprocess call increases total pipeline latency slightly (negligible).
5. **False Positives**: Strict semantic checks (e.g. parameter name matching) might block legacy strategies that use different internal variable names. *Mitigation: Start with loose validation (existence check).*
