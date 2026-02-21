# FSM & Resume Logic Audit Report

**Scope:** `tools/pipeline_utils.py`, `tools/run_pipeline.py`
**Mode:** Read-only — no code changes
**Date:** 2026-02-20

---

## 1. FSM Definitions

### 1.1 `PipelineStateManager` — Per-Symbol Run FSM (`pipeline_utils.py:142`)

Persists to: `runs/<RUN_ID>/run_state.json`

| From State | Allowed Next States |
| :--- | :--- |
| `IDLE` | `PREFLIGHT_COMPLETE`, `FAILED` |
| `PREFLIGHT_COMPLETE` | `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`, `FAILED` |
| `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID` | `STAGE_1_COMPLETE`, `FAILED` |
| `STAGE_1_COMPLETE` | `STAGE_2_COMPLETE`, `FAILED` |
| `STAGE_2_COMPLETE` | `STAGE_3_COMPLETE`, `FAILED` |
| `STAGE_3_COMPLETE` | `STAGE_3A_COMPLETE`, `FAILED` |
| `STAGE_3A_COMPLETE` | `COMPLETE`, `FAILED` |
| `COMPLETE` | *(terminal — empty)* |
| `FAILED` | *(terminal — empty)* |

**Enforcement:** `transition_to()` raises `RuntimeError` on invalid transitions. Logged via `_append_audit_log("ILLEGAL_TRANSITION_ATTEMPT")`. ✅ Strict.

---

### 1.2 `DirectiveStateManager` — Per-Directive Batch FSM (`pipeline_utils.py:322`)

Persists to: `runs/<DIRECTIVE_ID>/directive_state.json`

| From State | Allowed Next States |
| :--- | :--- |
| `INITIALIZED` | `PREFLIGHT_COMPLETE`, `FAILED` |
| `PREFLIGHT_COMPLETE` | `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`, `FAILED` |
| `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID` | `SYMBOL_RUNS_COMPLETE`, `FAILED` |
| `SYMBOL_RUNS_COMPLETE` | `PORTFOLIO_COMPLETE`, `FAILED` |
| `PORTFOLIO_COMPLETE` | `FAILED` *(only failure path)* |
| `FAILED` | `INITIALIZED` *(reset path)* |

**Notable:** `PORTFOLIO_COMPLETE` cannot transition to `COMPLETE` — it IS the terminal success state. And there is no `COMPLETE` state defined in `DirectiveStateManager`, yet the orchestrator treats `PORTFOLIO_COMPLETE` as done.

---

## 2. Actual Transition Call Sites in `run_pipeline.py`

### State READS

| Line | Operation | Variable / Context |
| :--- | :--- | :--- |
| 206 | `dir_state_mgr.get_state()` | `current_dir_state` — read once at start, then **stale** |
| 272 | `dir_state_mgr.get_state()` | `check_state` — re-fetched before semantic gate |
| 315 | `mgr.get_state_data()["current_state"]` | Per-symbol skip check in Stage-1 loop |
| 348 | `mgr.get_state_data()["current_state"]` | Stage-2 gate: skip if not `STAGE_1_COMPLETE` |
| 357 | `mgr.get_state_data()["current_state"]` | Stage-3 gate: skip if not `STAGE_2_COMPLETE` |

### State WRITES (transition_to calls)

| Line | Call | Notes |
| :--- | :--- | :--- |
| 222 | `dir_state_mgr.transition_to("INITIALIZED")` | Force reset on `--force` flag |
| 235 | `state_mgr.initialize()` | Per-symbol: creates IDLE state (writes directly via `_write_atomic`, bypasses FSM) |
| 252 | `PipelineStateManager(rid).transition_to("PREFLIGHT_COMPLETE")` | All symbols at once |
| 254 | `dir_state_mgr.transition_to("PREFLIGHT_COMPLETE")` | Directive level |
| 281–284 | `PipelineStateManager(rid).transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")` | All symbols |
| 284 | `dir_state_mgr.transition_to("PREFLIGHT_COMPLETE_SEMANTICALLY_VALID")` | Directive level |
| 291 | `PipelineStateManager(rid).transition_to("FAILED")` | Semantic failure cleanup |
| 293 | `dir_state_mgr.transition_to("FAILED")` | Semantic failure cleanup |
| 331 | `mgr.transition_to("STAGE_1_COMPLETE")` | Per-symbol after Stage-1 succeeds |
| 336 | `mgr.transition_to("FAILED")` | Per-symbol Stage-1 failure |
| 350 | `mgr.transition_to("STAGE_2_COMPLETE")` | Conditional: only if in STAGE_1_COMPLETE |
| 360 | `mgr.transition_to("STAGE_3_COMPLETE")` | Conditional: only if in STAGE_2_COMPLETE |
| 368 | `mgr.transition_to("FAILED")` | No snapshot |
| 376 | `mgr.transition_to("FAILED")` | Source strategy missing |
| 383 | `mgr.transition_to("FAILED")` | Snapshot hash mismatch |
| 405 | `mgr.transition_to("FAILED")` | Missing artifact for binding |
| 428 | `mgr.transition_to("STAGE_3A_COMPLETE")` | After manifest binding |
| 429 | `mgr.transition_to("COMPLETE")` | Run terminal success |
| 435 | `dir_state_mgr.transition_to("SYMBOL_RUNS_COMPLETE")` | After all symbol Stage-3 loops |
| 446 | `mgr.transition_to("FAILED")` | Missing manifest pre-Stage-4 |
| 465 | `mgr.transition_to("FAILED")` | Manifest key mismatch |
| 471 | `mgr.transition_to("FAILED")` | Artifact missing in re-verification |
| 477 | `mgr.transition_to("FAILED")` | Artifact hash tamper |
| 485 | `dir_state_mgr.transition_to("PORTFOLIO_COMPLETE")` | Directive terminal success |
| 492 | `dir_state_mgr.transition_to("FAILED")` | Catch-all exception handler |
| 506 | `mgr.transition_to("FAILED")` | Catch-all: non-terminal runs |

---

## 3. Resume Behavior Matrix

### Scenario A — Resume at `PREFLIGHT_COMPLETE` (directive-level)

- **`current_dir_state` read at L206:** `PREFLIGHT_COMPLETE`
- **L210 guard:** not `PORTFOLIO_COMPLETE`, not `FAILED` → falls through
- **L243 guard:** `current_dir_state != "PREFLIGHT_COMPLETE"` → **FALSE** → skips preflight block
- BUT `current_dir_state` is the **stale variable from L206** — not re-fetched
- **L272:** `check_state = dir_state_mgr.get_state()` → re-fetched → `PREFLIGHT_COMPLETE`
- **L273:** `check_state == "PREFLIGHT_COMPLETE"` → TRUE → runs semantic validation

**✅ Correct.** Preflight is skipped, semantic validation runs.

---

### Scenario B — Resume at `STAGE1_COMPLETE` (per run; directive is `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`)

Wait — there is no `STAGE1_COMPLETE` in the **directive** FSM. The directive jumps directly from `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID` → `SYMBOL_RUNS_COMPLETE`. There is no intermediate directive state for Stage-1.

- **`current_dir_state`:** `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`
- **L239:** `current_dir_state == "SYMBOL_RUNS_COMPLETE"` → FALSE → runs full block
- **L243:** skips preflight (not in PREFLIGHT_COMPLETE)
- **L273:** `check_state == "PREFLIGHT_COMPLETE"` → FALSE
- **L296:** `check_state == "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID"` → TRUE → prints "already COMPLETE"
- **L311:** enters Stage-1 loop
- Per-symbol: **L315** reads state → `STAGE_1_COMPLETE` → **L316:** `if st == "COMPLETE"` → FALSE → **re-executes Stage-1** for that symbol

> [!CAUTION]
> **VIOLATION B-1 (HIGH):** The Stage-1 skip guard at L315–317 only skips if `st == "COMPLETE"`, NOT if `st == "STAGE_1_COMPLETE"`. A symbol at `STAGE_1_COMPLETE` will be re-executed unnecessarily (no artifact corruption, but wasteful and non-idempotent).

- After re-execution of Stage-1: `mgr.transition_to("STAGE_1_COMPLETE")` at L331 — this is **an illegal transition** from `STAGE_1_COMPLETE` → `STAGE_1_COMPLETE` (not in `ALLOWED_TRANSITIONS[STAGE_1_COMPLETE]` = `["STAGE_2_COMPLETE", "FAILED"]`). **Will raise RuntimeError.**

> [!CAUTION]
> **VIOLATION B-2 (HIGH):** Re-running Stage-1 for a symbol already at `STAGE_1_COMPLETE` will crash the orchestrator with an illegal state transition error.

---

### Scenario C — Resume at `STAGE2_COMPLETE` (per run; directive is `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`)

- Same flow as B above through Stage-1 loop
- At L315: state is `STAGE_2_COMPLETE` → `if st == "COMPLETE"` → FALSE → Stage-1 **re-executes**
- At L331: `transition_to("STAGE_1_COMPLETE")` from `STAGE_2_COMPLETE` → **illegal** → crash

> [!CAUTION]
> **VIOLATION C-1 (HIGH):** Same crash pattern as B-2. Worse because Stage-2 work is discarded.

- If Stage-1 somehow completed without a crash, at L348: `if current == "STAGE_1_COMPLETE"` → might transition to `STAGE_2_COMPLETE` from `STAGE_2_COMPLETE` → **illegal**, crash again.

---

### Scenario D — Resume at `COMPLETE` (per run; directive is `SYMBOL_RUNS_COMPLETE` or `PORTFOLIO_COMPLETE`)

**If directive is `SYMBOL_RUNS_COMPLETE`:**

- **L239:** `current_dir_state == "SYMBOL_RUNS_COMPLETE"` → TRUE → **skips entire Stage 1–3 block**
- Goes directly to manifest re-verification (L441)
- Per-symbol: manifest exists ✅ → Stage-4 runs → `PORTFOLIO_COMPLETE` ✅

**If directive is `PORTFOLIO_COMPLETE`:**

- **L210:** `current_dir_state == "PORTFOLIO_COMPLETE"` → TRUE → **aborts immediately** ✅

**✅ Scenario D is correct for both sub-cases.**

---

## 4. Violations Summary

| ID | Location | Description | Severity |
| :--- | :--- | :--- | :--- |
| **V-1** | `pipeline_utils.py:190–206` | `initialize()` re-assigns `current_state = "IDLE"` via direct dict mutation and `_write_atomic()`, **bypassing `transition_to()`** and FSM validation. A run at `STAGE_3_COMPLETE` can be silently reset to `IDLE`. | **HIGH** |
| **V-2** | `run_pipeline.py:315–317` | Stage-1 skip guard: `if st == "COMPLETE"` — does not skip `STAGE_1_COMPLETE`, `STAGE_2_COMPLETE`, etc. Causes re-execution of already-complete symbols on resume. | **HIGH** |
| **V-3** | `run_pipeline.py:206` vs `272` | `current_dir_state` is read once at L206 and used stale through the logic at L239, L243, L262. A separate re-fetch exists at L272 only for the semantic gate. All other gates use the stale variable. | **MEDIUM** |
| **V-4** | `run_pipeline.py:252` | `PipelineStateManager(rid)` is constructed ad-hoc (new instance, no `directive_id` set) for the PREFLIGHT_COMPLETE transition, inconsistent with other sites that use `mgr = PipelineStateManager(rid)` with the directive ID. | **LOW** |
| **V-5** | `pipeline_utils.py:296–297` | `verify_state()` silently passes if run is in a **forward** state without logging. This is not a fallback but an undocumented tolerance that bypasses the check. | **MEDIUM** |
| **V-6** | `pipeline_utils.py:327` | `PORTFOLIO_COMPLETE: ["FAILED"]` — the only transition out of the terminal success state leads to failure. There is no graceful re-run path. Attempting any re-run from `PORTFOLIO_COMPLETE` will crash unless `--reset` is added. | **MEDIUM** |
| **V-7** | `run_pipeline.py:232` | Symbol state init is **conditionally skipped** when `current_dir_state in ["SYMBOL_RUNS_COMPLETE", "PORTFOLIO_COMPLETE"]`. This is correct but relies on state files persisting from a previous run — if `runs/` is cleaned, manifest re-verification at L441 will fail for every symbol. | **MEDIUM** |

---

## 5. Minimal Surgical Corrections

### Fix V-1 — `initialize()` bypasses FSM on existing runs

**File:** `pipeline_utils.py:190–206`

```diff
- existing_data["current_state"] = "IDLE"
+ # Do NOT mutate state directly — this silently undoes committed states.
+ # For re-runs, transition via transition_to() only, or refuse if non-IDLE.
+ if existing_data["current_state"] not in ("IDLE", "FAILED"):
+     raise RuntimeError(
+         f"Cannot re-initialize run {self.run_id}: already at {existing_data['current_state']}"
+     )
```

*Or* only call `initialize()` if no state file exists, and route re-runs through `--force` reset logic.

---

### Fix V-2 — Stage-1 skip guard is too narrow

**File:** `run_pipeline.py:315–317`

```diff
- if st == "COMPLETE":
+ TERMINAL_STATES = {"COMPLETE", "STAGE_1_COMPLETE", "STAGE_2_COMPLETE",
+                    "STAGE_3_COMPLETE", "STAGE_3A_COMPLETE"}
+ if st in TERMINAL_STATES:
      continue
```

This makes resume idempotent for any symbol that has progressed past Stage-1.

---

### Fix V-3 — Stale `current_dir_state` used in resume guards

**File:** `run_pipeline.py:239`

```diff
- if current_dir_state == "SYMBOL_RUNS_COMPLETE":
+ if dir_state_mgr.get_state() == "SYMBOL_RUNS_COMPLETE":
```

One-line fix. Live state fetch at the resume decision point eliminates the stale read risk.

---

### Fix V-4 — Inconsistent `PipelineStateManager` construction (Low priority)

**File:** `run_pipeline.py:252`

```diff
- PipelineStateManager(rid).transition_to("PREFLIGHT_COMPLETE")
+ PipelineStateManager(rid, directive_id=clean_id).transition_to("PREFLIGHT_COMPLETE")
```

---

### Fix V-6 — `PORTFOLIO_COMPLETE` terminal deadlock

**File:** `pipeline_utils.py:327`

```diff
- "PORTFOLIO_COMPLETE": ["FAILED"],
+ "PORTFOLIO_COMPLETE": [],  # Terminal: use --force reset (FAILED → INITIALIZED)
```

And update the orchestrator's `PORTFOLIO_COMPLETE` guard (L210) to call `--reset` / `dir_state_mgr.transition_to("INITIALIZED")` if `--force` is passed, consistent with the FAILED reset path.

---

## 6. Risk Assessment

| Risk | Likely Trigger | Impact |
| :--- | :--- | :--- |
| Re-execution crash on partial resume | Any `--force` re-run with partial prior progress | Pipeline aborts all symbols mid-batch (**active, confirmed**) |
| Silent state regression via `initialize()` | `--force` on already-committed run | Run ID state blown back to IDLE silently |
| Stale state variable in resume logic | Multi-stage resume branch | Wrong branch taken, silent double-execution |
| `PORTFOLIO_COMPLETE` deadlock | Successful run followed by any re-trigger | No path out without manual state file deletion |

> [!WARNING]
> V-2 (wrong skip guard) is the root cause of the `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID → PREFLIGHT_COMPLETE` crash observed in the current session. When `--force` is passed and the directive is reset to `INITIALIZED`, per-symbol states remain at their prior position (e.g. `COMPLETE`). The orchestrator re-inits them via `initialize()` (V-1 blows them back to `IDLE`), re-runs Stage-1, then transitions to `STAGE_1_COMPLETE` — but the new instance created at L252 re-uses the stale in-memory `current_dir_state` variable, leading to a misfire. The real crash came from the inverse: on the prior session's partial run, the directive was at `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID` but the orchestrator tried `PREFLIGHT_COMPLETE → stage1` directly, triggering the illegal transition.
