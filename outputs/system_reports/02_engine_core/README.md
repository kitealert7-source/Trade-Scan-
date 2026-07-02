# 02_engine_core

Read before touching anything in `engine_dev/` or `engines/`.

| Document | When to read |
|---|---|
| `ENGINE_EXIT_STOP_CAPABILITY_MATRIX_v1_5_11_2026-07-02.md` | Before classifying a hypothesis's exit/stop needs as `rule_build_required` vs `engine enhancement required`. Native/Emulated/Not-Supported matrix for partial close, BE, ATR trailing, dynamic stops, multi-exit/OCO, scale-out+trail — with exact `execution_loop.py` line cites. |
| `ENGINE_EXECUTION_AUDIT_v1_5_3.md` | Before modifying execution logic, stop/TP rules, or FilterStack. Covers all execution items with PASS/FAIL verdicts. |
| `ENGINE_VALIDATION_AUDIT.md` | Before changing stage validation, schema enforcement, or admission logic. Maps each stage to its validation code. |
| `REGIME_FIELD_CAUSALITY_AUDIT_2026-06-23.md` | Before gating a strategy entry on `market_regime` / `trend_label` (or trusting a trade decomposition sliced on them). Proves the `_signal` variants are causal/point-in-time/engine-owned (use `_signal`, never `_fill`). |

**Engine version locked to `v1_5_3`.** Do not modify frozen engine files.
Changes require a new versioned directory and registry update in `config/engine_registry.json`.
