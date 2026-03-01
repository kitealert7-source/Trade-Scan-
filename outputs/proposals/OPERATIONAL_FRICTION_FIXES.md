# Operational Friction Fixes — Implementation Plan

Fix all 4 issues identified in the post-hardening system assessment. All changes are to Protected Infrastructure (user-authorized).

## Proposed Changes

---

### P0 — Stop `--provision-only` from Moving Directive to `completed/`

#### [MODIFY] [run_pipeline.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/run_pipeline.py)

**Lines 746-756** — `run_batch_mode()` currently moves directives to `completed/` unconditionally after `run_single_directive()` returns. When `--provision-only` is set, the function returns successfully at line 331 without completing execution.

```diff
             try:
                 run_single_directive(d_id)
-                final_dst = completed_dir / d_name
-                if final_dst.exists():
-                    os.remove(final_dst)
-                shutil.move(str(d_path), str(final_dst))
-                print(f"[BATCH] Completed: {d_name} -> {completed_dir}")
+                if "--provision-only" not in sys.argv:
+                    final_dst = completed_dir / d_name
+                    if final_dst.exists():
+                        os.remove(final_dst)
+                    shutil.move(str(d_path), str(final_dst))
+                    print(f"[BATCH] Completed: {d_name} -> {completed_dir}")
+                else:
+                    print(f"[BATCH] Provision-only: {d_name} remains in active/")
```

---

### P1 — Reset Tool Cleans Associated Run States

#### [MODIFY] [reset_directive.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/reset_directive.py)

After resetting directive state to `INITIALIZED`, scan `runs/` for run directories whose `run_state.json` contains `"directive_id": "<DIRECTIVE_ID>"` and archive those state files too.

Add after line 58 (`mgr.transition_to("INITIALIZED")`):

```python
# Clean associated per-symbol run states
runs_dir = PROJECT_ROOT / "runs"
if runs_dir.exists():
    import json
    cleaned = 0
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        state_file = run_dir / "run_state.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("directive_id") == directive_id:
                bak = state_file.with_suffix(f".json.bak.{timestamp.replace(':', '')}")
                state_file.rename(bak)
                print(f"[RESET] Archived run state: {run_dir.name}")
                cleaned += 1
        except Exception:
            pass
    if cleaned:
        print(f"[RESET] Cleaned {cleaned} associated run state(s)")
```

---

### P2 — Engine Manifest Generator

#### [NEW] [generate_engine_manifest.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/generate_engine_manifest.py)

Human-only tool mirroring `generate_guard_manifest.py`. Computes SHA-256 hashes for all `.py` files in the active engine version directory and writes `engine_manifest.json`.

Auto-detects engine version from `engine_dev/universal_research_engine/` (latest `v*` directory).

---

### P3 — Stage-4 Resume via `--to-stage4` Flag

#### [MODIFY] [reset_directive.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/reset_directive.py)

Add optional `--to-stage4` flag. When set, resets directive to `SYMBOL_RUNS_COMPLETE` instead of `INITIALIZED`. The pipeline already has resume logic at line 226 that detects this state and skips directly to Stage-4.

```diff
  parser.add_argument("--reason", required=True, ...)
+ parser.add_argument("--to-stage4", action="store_true",
+     help="Reset to SYMBOL_RUNS_COMPLETE (skip Stages 0-3 on re-run)")
```

When `--to-stage4` is set:

- Transition: `FAILED → SYMBOL_RUNS_COMPLETE` (not INITIALIZED)
- Do NOT clean per-symbol run states (they are needed for Stage-4)
- Log the different target state in audit trail

## Verification Plan

### Automated Tests

1. Run `python tools/run_pipeline.py --all --provision-only` → confirm directive stays in `active/`
2. Run full pipeline → confirm directive moves to `completed/`
3. Reset with `--to-stage4` → confirm re-run skips to Stage-4
4. Full reset → confirm run states are archived along with directive state
5. Run `python tools/generate_engine_manifest.py` → confirm `engine_manifest.json` updated
