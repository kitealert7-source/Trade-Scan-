# 02_engine_core

Read before touching anything in `engine_dev/` or `engines/`.

| Document | When to read |
|---|---|
| `ENGINE_EXECUTION_AUDIT_v1_5_3.md` | Before modifying execution logic, stop/TP rules, or FilterStack. Covers all execution items with PASS/FAIL verdicts. |
| `ENGINE_VALIDATION_AUDIT.md` | Before changing stage validation, schema enforcement, or admission logic. Maps each stage to its validation code. |

**Engine version locked to `v1_5_3`.** Do not modify frozen engine files.
Changes require a new versioned directory and registry update in `config/engine_registry.json`.
