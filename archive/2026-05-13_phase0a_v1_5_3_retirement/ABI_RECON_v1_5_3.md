# ABI_RECON — engine_abi.v1_5_3

**Phase:** 0a Step 1 (recon)
**Date:** 2026-05-13
**Status:** READ-ONLY findings — no code touched
**Plan reference:** `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` Phase 0a

---

## Purpose

Document the legacy engine surface that **TS_Execution** imports today, so the
`governance/engine_abi_v1_5_3_manifest.yaml` and `engine_abi/v1_5_3/` re-export
package can be derived mechanically. This is the consumer-driven contract for
the legacy ABI — every entry must trace to a current `consumed_by` reference.

Per the binding scope-discipline rule in Phase 0a Step 6:
> If a reviewer cannot point to a current `consumed_by` reference that justifies
> an export, it doesn't go in the ABI. Period.

The recon below enumerates exactly what TS_Execution imports today, with file
+ line citation for each consumer.

---

## Method

```
grep -rn '^(from|import)\s+(engines|engine_dev)' TS_Execution/
grep -rn 'engines\.|engine_dev\.'              TS_Execution/   # catches lazy imports
grep -rn 'importlib|__import__'                TS_Execution/   # catches reflective imports
```

Reflective-import scan found `importlib.util.spec_from_file_location` in
`TS_Execution/src/strategy_loader.py` — used to load strategy modules by path,
NOT to load engine symbols. No reflective access to `engines.*` or
`engine_dev.*` exists. The ABI surface is therefore a closed enumeration of
direct `from … import …` statements.

The harness `TS_Execution/harness/replay.py` has a v1_5_3 → v1_5_9 fallback
(lines 213-216) anticipating an eventual engine upgrade. For Phase 0a we treat
TS_Execution as a single consumer of `engine_abi.v1_5_3`; the harness's
v1_5_9 fallback path will become a Phase-0a-follow-up migration once
`engine_abi.v1_5_9` is wired (`harness/replay.py` is not in TS_Execution's
production boot path).

---

## v1_5_3 export surface — 6 symbols

| # | Export | Source module | Type | Source line |
|---|---|---|---|---|
| 1 | `admit`            | `engines.concurrency_gate`                              | function  | `engines/concurrency_gate.py:36` |
| 2 | `validate_cap`     | `engines.concurrency_gate`                              | function  | `engines/concurrency_gate.py:13` |
| 3 | `apply_regime_model` | `engines.regime_state_machine`                        | function  | `engines/regime_state_machine.py:145` |
| 4 | `REGIME_CACHE_DIR` | `engines.regime_state_machine`                          | constant  | `engines/regime_state_machine.py:35` |
| 5 | `StrategyProtocol` | `engines.protocols`                                     | Protocol  | `engines/protocols.py:51` |
| 6 | `ContextView`      | `engine_dev.universal_research_engine.v1_5_3.execution_loop` | class | `engine_dev/universal_research_engine/v1_5_3/execution_loop.py:39` |

---

## Per-export consumer map

### 1. `admit` (function)

- `TS_Execution/src/execution_adapter.py:39`
  - Alias: `from engines.concurrency_gate import admit as _admit_concurrency`
  - Call site: portfolio-level concurrency-cap dispatch gate.

### 2. `validate_cap` (function)

- `TS_Execution/src/execution_adapter.py:40`
  - Alias: `from engines.concurrency_gate import validate_cap as _validate_concurrency_cap`
  - Call site: portfolio.yaml exec_config validation.

### 3. `apply_regime_model` (function)

- `TS_Execution/src/main.py:116`
  - Phase-2 boot import, paired with `ContextView`. Drives regime state for every loaded strategy.
- `TS_Execution/harness/replay.py:209`
  - Replay harness mirrors main.py's import. NOT in production boot — kept for completeness.

### 4. `REGIME_CACHE_DIR` (constant)

- `TS_Execution/src/pipeline.py:130`
  - Lazy import inside `_probe_regime_cache()` — probes cache existence before `apply_regime_model` runs. Same source-of-truth path the engine writes to.

### 5. `StrategyProtocol` (Protocol class)

- `TS_Execution/src/strategy_loader.py:153`
  - Lazy import inside strategy load loop. `isinstance(strategy, StrategyProtocol)` enforces the strategy interface at module-load time.

### 6. `ContextView` (class)

- `TS_Execution/src/main.py:115`
  - Subclassed at runtime into `NormalizedContextView` (lowercase key normalization wrapper).
- `TS_Execution/harness/replay.py:213`
  - Harness mirror. v1_5_9 fallback at line 216 is OUT of scope for v1_5_3 ABI; tracked as follow-up.

---

## Modules explicitly NOT in the v1_5_3 ABI

| Considered | Decision | Reason |
|---|---|---|
| `engines.filter_stack.FilterStack` | NOT exported | No `consumed_by` in TS_Execution. Only Trade_Scan tools use it (pipeline-side). |
| `engines.indicator_warmup_resolver.*` | NOT exported | Used by Trade_Scan stage1 only. |
| `engines.utils.timeframe.parse_freq_to_minutes` | NOT exported | Used by Trade_Scan stage1 + Trade_Scan tests. |
| `engines.research_recorders.*` | NOT exported | Research-side only. |
| `engine_dev.universal_research_engine.v1_5_3.execution_loop.run_execution_loop` | NOT exported | TS_Execution does NOT run the batch loop; it drives bar-by-bar via its own pipeline. |
| `engine_dev.universal_research_engine.v1_5_3.execution_loop.resolve_exit` | NOT exported | Lifted into v1_5_9 evaluator; v1_5_3 callers don't reach it from TS_Execution. |
| `engine_dev.universal_research_engine.v1_5_3.execution_loop.ENGINE_VERSION/ENGINE_STATUS` | NOT exported | TS_Execution doesn't read engine metadata from this surface; portfolio.yaml will pin `abi_version` per Phase 0a Step 5. |
| `engine_dev.universal_research_engine.v1_5_3.execution_emitter_stage1.*` | NOT exported | Stage-1 research only. |
| `engine_dev.universal_research_engine.v1_5_3.stage2_compiler.*` | NOT exported | Stage-2 research only. |
| `engine_dev.universal_research_engine.v1_5_3.main.run_engine` | NOT exported | Stage-1 research orchestrator only. |
| `engines.concurrency_gate` (full module) | NOT exported as module | Only `admit` + `validate_cap` are consumed. Module re-export would widen scope without justification. |
| `engines.protocols.ContextViewProtocol` | NOT exported | Defined in `engines/protocols.py` but no TS_Execution consumer. Only used by engine internals + v1_5_9. |

If any of these surfaces a real TS_Execution consumer in future review, the
manifest gets a deliberate update commit per Section 6.8.

---

## Anticipated runtime assertion

`engine_abi/v1_5_3/__init__.py` will import each of the 6 symbols from its
source module and expose them via `__all__`. On import, a runtime assert
compares `__all__` to the manifest's `exports[*].name` list. Equality →
proceed; inequality → `RuntimeError` at import time, before TS_Execution can
boot.

---

## Open follow-ups (NOT Phase 0a scope)

1. `TS_Execution/harness/replay.py:216` — v1_5_9 fallback path. Migrate once
   `engine_abi.v1_5_9` is stable; produces no day-zero risk because harness
   isn't on the live boot path.
2. `TS_Execution/portfolio.yaml` will gain `abi_version: v1_5_3` field
   (Phase 0a Step 5).
3. `TS_Execution/src/phase0_validation.py` (creation deferred per plan
   Section 8) — runtime ABI assertion at TS_Execution boot.

---

*End of recon — author the manifest from this list.*
