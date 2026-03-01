# Pipeline Robustness Improvements

**Source:** IDX22 live run post-mortem — 2026-02-28  
**Status:** Proposal — awaiting prioritization

---

## 🔴 Critical

### 1. Stage-0.75 Must Verify Authoritative Indicators

**Problem:** Dry-run passes even when `prepare_indicators()` doesn't produce the columns the engine requires.  
`AUTHORITATIVE_INDICATORS = ['volatility_regime', 'trend_regime', 'trend_label', 'trend_score', 'atr']`  
This surfaces only at Stage-1 runtime — after all run states are initialized — causing a hard crash and requiring a full reset.

**Fix:** After `prepare_indicators()` completes in Stage-0.75, explicitly check:

```python
missing = [col for col in AUTHORITATIVE_INDICATORS if col not in df.columns]
if missing:
    raise RuntimeError(f"DRYRUN_FAIL: Missing authoritative indicators: {missing}")
```

**Impact:** Catches engine contract violations at dryrun, before any state commits.

---

### 2. `initialize()` Must Be Idempotent Across Provision-Only + Full Run

**Problem:** `--provision-only` leaves run states at `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`. When the full pipeline then runs, the orchestrator calls `state_mgr.initialize()` for each symbol, resetting them to `IDLE`. Stage-1 then finds `IDLE` and hard-fails with state mismatch.

**Fix:** `PipelineStateManager.initialize()` should skip initialization if state already exists beyond `IDLE`:

```python
def initialize(self):
    if self.get_state() not in [None, "IDLE"]:
        return  # Already initialized — do not reset
    # ... existing init logic
```

**Impact:** Makes `--provision-only` + separate full run a safe and supported workflow.

---

## 🟡 Moderate

### 3. Audit Pipeline Print Statements for Non-ASCII Characters

**Problem:** Characters like `✓` and `→` in `run_pipeline.py` print statements crash on Windows cp1252 encoding. Required post-hoc fixes and multiple manifest regens.

**Fix:** Audit all `print()` calls in pipeline tools. Replace Unicode symbols with ASCII equivalents: `[OK]`, `->`, `[PASS]`, `[FAIL]`, `[DONE]`.

**Files to audit:** `run_pipeline.py`, `exec_preflight.py`, `canonicalizer.py`

---

### 4. Guard Manifest Regeneration Timing Warning

**Problem:** If `run_pipeline.py` is modified twice before manifest is regenerated, an intermediate stale hash gets committed. User had to regenerate three times in one session.

**Fix:** `generate_guard_manifest.py` should print timestamps alongside each hash. Optionally: detect if any listed file's mtime is newer than the manifest's write time on next verification and warn explicitly:

```
[WARN] run_pipeline.py modified AFTER last manifest generation. Re-run generate_guard_manifest.py.
```

---

### 5. Flat-Text → YAML Directive Scaffold Utility

**Problem:** Legacy directives in flat natural-language format are rejected by both `parse_directive` and the canonicalization gate. No conversion path exists — manual YAML authoring required.

**Fix:** `tools/convert_directive.py` — reads a flat-text directive and emits a YAML skeleton with correct block structure. Does NOT fill values — human fills parameters. Outputs to `/tmp/<ID>_scaffold.yaml` for review.

---

## 🟢 Minor

### 6. Pandas FutureWarning Noise from `fillna(False)`

**Problem:** `.fillna(False)` on boolean Series emits a FutureWarning in newer pandas versions. On Windows/PowerShell this gets written to stderr, causing the shell to flag the command as errored despite `[SUCCESS]` output.

**Fix:** Use `.fillna(False).infer_objects(copy=False)` in strategy code. Optionally suppress known pandas deprecation warnings in `run_stage1.py`.

---

## Priority Order

| # | Fix | Effort | Impact |
|---|-----|--------|--------|
| 1 | Dryrun authoritative indicator check | Low | Prevents Stage-1 crash after dryrun PASS |
| 2 | `initialize()` idempotency | Low | Makes provision-only workflow reliable |
| 3 | ASCII-only print statements | Low | Prevents Windows encoding crashes |
| 4 | Manifest regen timing warning | Medium | Reduces guard manifest confusion |
| 5 | Flat-text scaffold utility | Medium | Eases onboarding of legacy directives |
| 6 | FutureWarning suppression | Trivial | Cleaner pipeline output |
