# Second-Pass Remediation — Walkthrough

## Summary

8 surgical fixes applied. 15/15 tests passing. System upgraded from **CONDITIONALLY STABLE** → **STRUCTURALLY SEALED**.

---

## Changes Made

### HIGH Risk — Eliminated

| Fix | File | What Changed |
|---|---|---|
| 1. Stale-state gate | [run_pipeline.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/run_pipeline.py#L231-L248) | Replaced `current_dir_state` (read once at startup) with live `dir_state_mgr.get_state()`. Added `_PREFLIGHT_SKIP` set covering all forward states. Removed dead stale-gate block. |
| 2. Resume-safe summary | [run_pipeline.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/run_pipeline.py#L285-L299) | Gated `batch_summary_*.csv` deletion — only deletes if ≥1 symbol needs Stage-1 rerun. Prevents `RuntimeError` on resume. |

### MEDIUM Risk — Eliminated

| Fix | File | What Changed |
|---|---|---|
| 3. Preflight parser | [preflight.py](file:///c:/Users/faraw/Documents/Trade_Scan/governance/preflight.py#L105-L290) | Layered YAML-first / regex-fallback. Tries `parse_directive()` for safety gates; falls back to existing regex scanner if directive isn't strict YAML. |
| 4. Resume FSM tests | [test_resume_fsm.py](file:///c:/Users/faraw/Documents/Trade_Scan/tests/test_resume_fsm.py) | 4 tests: backward transition rejection, skip set coverage, transition table forward-only validation |
| 5. Artifact tests | [test_resume_artifacts.py](file:///c:/Users/faraw/Documents/Trade_Scan/tests/test_resume_artifacts.py) | 2 tests: no-deletion guard when all symbols past Stage-1, deletion trigger when symbols need rerun |
| 6. Legacy test guard | [test_pipeline_parsing.py](file:///c:/Users/faraw/Documents/Trade_Scan/tests/legacy/test_pipeline_parsing.py) | Wrapped body in `if __name__ == "__main__":` — no more file writes on import |

### LOW Risk — Fixed

| Fix | File | What Changed |
|---|---|---|
| 7. Docstring | [pipeline_utils.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/pipeline_utils.py#L126) | `1.2.0` → `1.3.0` |
| 8. Release gate | [RELEASE_GATE.md](file:///c:/Users/faraw/Documents/Trade_Scan/governance/RELEASE_GATE.md) | Required test suites before merge |

---

## Verification Results

```
Ran 15 tests in 1.321s — OK
```

- ✅ 6 existing tests (state machine + parser) — unchanged, still passing
- ✅ 4 new resume FSM tests — backward transitions rejected
- ✅ 2 new artifact integrity tests — summary guard logic verified
- ✅ 3 transition table validation tests — forward-only confirmed

### Invariants Confirmed

- **Run IDs:** Unchanged — no `get_canonical_hash()` or `generate_run_id()` touched
- **Directive hash:** Unchanged — `sort_keys=True` not modified
- **FSM transitions:** Still fail-fast — backward paths raise `RuntimeError`
- **No warning spam:** Logging only emits during actual fallback or resume skip
