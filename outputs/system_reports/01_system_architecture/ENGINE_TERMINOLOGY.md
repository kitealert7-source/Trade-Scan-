# Engine & Execution Terminology — Canonical Glossary

> Naming hygiene for the research→execution stack. Adopted 2026-06-24 to remove the "engine"
> overload that caused repeated confusion this development arc (the v1_5_9-vs-v1_5_10 mislabel; the
> "execution engine" misnomer). **This file is the source of truth for the four terms below** — docs
> and comments should use them. Terminology hygiene only: it renames *concepts in prose*, not code
> artifacts (files/packages). Renaming code is a separate, deliberate step.

> **Update (2026-06-30 — ABI consolidation):** the `v1_5_9`-vs-`v1_5_10` ABI distinction this
> glossary teaches is now **historical** — both shims were retired and `engine_abi` collapsed to a
> **single canonical ABI, `engine_abi.v1_5_11`** (in prose: **LIVE_ABI_v1_5_11**), over RE v1.5.11.
> The `v1_5_9`/`v1_5_10` examples below are retained to illustrate the mislabel the glossary was
> created to resolve; substitute `v1_5_11` for the live surface. See `ENGINE_VAULT_CONTRACT.md` §14A.

## The four concepts — three on the research side, one on the execution side

| Term | Is (today) | Means | Is NOT |
|---|---|---|---|
| **RE — Research Compute Engine** | `engine_dev/universal_research_engine/<ver>/` | the actual bar-by-bar compute: `evaluate_bar`, `execution_loop`, fill/PnL simulation | the ABI package; the shared services |
| **ABI Surface** | `engine_abi/<ver>/` | a thin, manifest-governed, fail-closed **re-export** surface over RE compute | compute of its own (it imports + re-exports only) |
| **Shared Substrate** | `engines/` | version-**agnostic** services: regime state machine, `StrategyProtocol`, concurrency gate | versioned; part of any single engine release |
| **XR — Execution Reconciler** | the broker-facing consumer (e.g. `basket_shim.py`) | reads a target/signal, reconciles broker positions to it, places/closes orders | an **engine** — it runs **no** compute |

**Deliberately not "EE / Execution Engine".** The execution side runs no engine: for baskets it is a
stdlib-only reconciler; for single-asset it *hosts* the RE substrate but is still not a distinct
engine. Call it **XR**. (Earlier audit docs used "EE" — read EE as XR.)

## The v1_5_9 clarification (the important one)

`engine_abi.v1_5_9` is an **ABI Surface**, not an engine — in prose, name it **LIVE_ABI_v1_5_9**. It
currently re-exports **RE v1_5_10** compute (manifest-declared). Therefore:

- `v1_5_9` / `v1_5_10` are **not** "old engine / new engine." They are two **ABI Surface** versions;
  the live one (`v1_5_9`) sits *over* RE v1_5_10.
- Correct mental model:

  ```
  RE v1_5_10  →  ABI Surface (LIVE_ABI_v1_5_9)  →  XR (execution host)
  ```

- The name↔compute mismatch this names is a **separate, still-open structural decision**
  (restore-v1.5.9 vs ratify-v1.5.10) — see [`ENGINE_EVOLUTION_AUDIT.md`](ENGINE_EVOLUTION_AUDIT.md).
  **This glossary fixes the *naming* only; it does not resolve that.**

## Quick substitutions (for docs/comments — NOT a code refactor)

| Old (misleading) | New |
|---|---|
| "the engine" / "the frozen engine" (execution side) | **LIVE_ABI_v1_5_9** (the ABI Surface) over **frozen RE v1.5.10 compute** |
| "execution engine" / "EE" | **XR (Execution Reconciler)** |
| "the shim" (basket consumer) | **the reconciler** (XR) |
| "v1_5_9 = old engine, v1_5_10 = new engine" | two **ABI Surface** versions; live `v1_5_9` re-exports RE `v1_5_10` |

Related: [`ENGINE_EVOLUTION_AUDIT.md`](ENGINE_EVOLUTION_AUDIT.md),
[`SIGNAL_ABI_AND_XR_DESIGN.md`](SIGNAL_ABI_AND_XR_DESIGN.md),
[`UNIFIED_ENGINE_AUTHORITY_PLAN.md`](UNIFIED_ENGINE_AUTHORITY_PLAN.md).
