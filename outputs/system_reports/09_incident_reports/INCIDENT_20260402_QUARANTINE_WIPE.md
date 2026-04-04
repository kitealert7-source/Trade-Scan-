# Incident Report: Quarantine Wipe of All Deployed Strategies

**Date:** 2026-04-02
**Severity:** Critical (production execution halted)
**Duration:** ~30 minutes (3 restart attempts + manual restore)
**Affected Systems:** TS_Execution (all 37 live strategies), Trade_Scan, TradeScan_State

---

## 1. Timeline

| Time (UTC) | Event |
|------------|-------|
| ~11:15 | `lineage_pruner.py --execute` runs via state_lifecycle_cleanup skill |
| ~11:15 | 85 directories moved from `Trade_Scan/strategies/` to quarantine |
| ~11:15 | 84 directories moved from `TradeScan_State/strategies/` to quarantine |
| 09:36 | First TS_Execution restart attempt: FAIL — `strategy file not found` for SPKFADE S03 |
| 09:36 | Diagnosis: all strategy.py files missing from `Trade_Scan/strategies/` |
| 09:37 | Restore 37 strategy.py directories from quarantine `deployed_portfolios/` |
| 09:38 | Second restart attempt: FAIL — `not PORTFOLIO_COMPLETE` for all 37 strategies |
| 09:38 | Diagnosis: `portfolio_evaluation` artifacts missing from `TradeScan_State/strategies/` |
| 09:39 | Restore 36 portfolio_evaluation directories from quarantine `portfolios/` |
| 09:40 | Third restart attempt: FAIL — `PHASE0_SMOKE_FAIL_SCHEMA` for P05 only |
| 09:40 | Diagnosis: `_schema_sample()` used `0.0` values, fails `signal_schema.validate()` |
| 09:41 | Fix P05 schema sample to use realistic non-zero prices |
| 09:42 | Fourth restart: SUCCESS — 38 strategies loaded, 0 errors |

---

## 2. Root Cause

`lineage_pruner.py` determines what to KEEP based solely on two Excel spreadsheets:
- `Master_Portfolio_Sheet.xlsx` (column `portfolio_id`)
- `Filtered_Strategies_Passed.xlsx`

It builds an `active_portfolios` set from these sources. Any directory in `Trade_Scan/strategies/` or `TradeScan_State/strategies/` whose name is NOT in `active_portfolios` gets quarantined.

**The fundamental flaw:** The pruner has zero awareness of `TS_Execution/portfolio.yaml` — the live execution manifest. The Master sheet tracks composite portfolio bundles, not individual per-symbol deployments (e.g., `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03_AUDJPY`). Every deployed strategy that exists only as a symbol-specific directory gets classified as "abandoned" and quarantined.

**Quarantine contents:**
- `quarantine/20260402_111505_cleanup/deployed_portfolios/` — 85 directories from `Trade_Scan/strategies/`
- `quarantine/20260402_111505_cleanup/portfolios/` — 84 directories from `TradeScan_State/strategies/`

All 37 actively deployed strategies were among them.

---

## 3. Impact

- **TS_Execution halted** — no strategies could load, zero trading capability
- **3 failed restart attempts** — each revealing a different layer of missing artifacts
- **Manual recovery required** — bulk copy from quarantine back to both repos
- **No data loss** — quarantine preserved all files, nothing was deleted
- **No missed trades** — market was open but recovery completed within ~30 min

---

## 4. Gap Analysis

### Gap A: No portfolio.yaml cross-check in lineage_pruner.py (CRITICAL)

**File:** `tools/state_lifecycle/lineage_pruner.py`
**Location:** `scan_and_map()` function, lines 164-180

The scan compares directory names against `active_portfolios` (from Excel). It never reads `TS_Execution/portfolio.yaml`. Any strategy deployed to live execution but absent from the Master sheet is quarantined.

**Fix:** Add `build_execution_shield()` that reads `TS_Execution/portfolio.yaml`, extracts all enabled strategy IDs, and unconditionally protects them. Hard `[BLOCK]` + `sys.exit(1)` if any shielded strategy would be quarantined. No `--force` override.

### Gap B: No TS_Execution running check (HIGH)

**File:** `tools/state_lifecycle/lineage_pruner.py`
**Location:** Top-level, before any scan

No mechanism checks whether TS_Execution is actively running. Cleanup can proceed while live execution depends on the files being moved.

**Fix:** Check for TS_Execution PID file (`outputs/logs/execution.pid`) or recent heartbeat. If detected: `[BLOCK] TS_Execution is running. Stop execution before cleanup.`

### Gap C: No pre-execution manifest with confirmation (MEDIUM)

**File:** `tools/state_lifecycle/lineage_pruner.py`
**Location:** `execute_purge()` function

`cleanup_report.json` is written AFTER the move, not before. The dry-run prints counts to stdout, but if invoked non-interactively (e.g., by an AI agent), counts scroll by without human review.

**Fix:** Write `quarantine_manifest.json` listing every path to be moved BEFORE execution. Require `--execute --confirm-manifest <path>` to prove the operator reviewed it.

### Gap D: Skill workflow allows AI agent to bypass human gate (HIGH)

**File:** `.skills/state_lifecycle_cleanup/prompt.md`
**Location:** Between Phase 3 (dry-run) and Phase 4 (execute)

No mandatory pause or human confirmation gate between dry-run output and execute. An AI agent executing this skill can proceed from count output to `--execute` without stopping.

**Fix:** Add explicit instruction between phases: if `deployed_portfolios > 0`, automatic abort. Always require explicit operator confirmation before Phase 4.

### Gap E: system_preflight.py has no execution awareness (MEDIUM)

**File:** `tools/system_preflight.py`

Checks registry alignment and portfolio metadata but has no concept of TS_Execution deployments. Cannot detect post-cleanup breakage until TS_Execution restart fails.

**Fix:** Add `_check_execution_deployment()` that verifies every `portfolio.yaml` strategy exists in both `Trade_Scan/strategies/` and `TradeScan_State/strategies/portfolio_evaluation/`.

### Gap F: TS_Execution error message doesn't mention quarantine (LOW)

**File:** `TS_Execution/src/portfolio_loader.py`
**Location:** `validate_environment()`, line 196

Error says "Run the full Trade_Scan pipeline for this strategy first" — correct for new strategies but misleading when the real cause is quarantine cleanup. Operator wastes time investigating pipeline issues instead of checking quarantine.

**Fix:** Add "LIKELY CAUSE: Check TradeScan_State/quarantine/ for recent cleanup operations" to the error message.

---

## 5. Fix Priority

| Priority | Fix | Effort | Prevents Recurrence |
|----------|-----|--------|---------------------|
| **P0** | A — portfolio.yaml shield in lineage_pruner.py | ~30 min | Yes (direct block) |
| **P1** | D — Skill workflow hard gate | ~10 min | Yes (AI agent path) |
| **P1** | B — Running-process check | ~20 min | Yes (defense-in-depth) |
| **P2** | E — Preflight deployment check | ~20 min | Detection only |
| **P2** | C — Pre-execution manifest | ~30 min | Audit trail |
| **P3** | F — Better error messages | ~5 min | Faster diagnosis |

---

## 6. Secondary Issue: _schema_sample() Validation

During recovery, a separate issue was found: `27_MR_XAUUSD_1H_PINBAR_S01_V1_P05` had `_schema_sample()` returning `0.0` for `stop_price` and `entry_reference_price`. The TS_Execution `signal_schema.validate()` rejects zero values (`_require_finite_float` line 146-148).

**Root cause:** The scaffolding from `new_pass.py` copies the parent's schema sample, which used `0.0` placeholder values. This was never caught because Trade_Scan's pipeline doesn't run `signal_schema.validate()` — only TS_Execution does.

**Fix:** Update `new_pass.py` scaffold template OR add a schema validation step to the Trade_Scan pipeline's preflight (PROVISION stage). All `_schema_sample()` values should use realistic instrument-appropriate prices.

**Affected strategies:** Any strategy with `0.0` in `_schema_sample()` will fail Phase 0 if deployed to TS_Execution. Should audit all existing strategies.

---

## 7. Recovery Actions Taken

1. Restored 37 strategy.py directories from `quarantine/deployed_portfolios/` to `Trade_Scan/strategies/`
2. Restored 36 portfolio_evaluation directories from `quarantine/portfolios/` to `TradeScan_State/strategies/`
3. Fixed P05 `_schema_sample()` to use realistic prices (2900/2930/2960)
4. Verified all 38 portfolio.yaml entries resolve correctly
5. TS_Execution restarted successfully with 0 errors

---

## 8. Lessons Learned

1. **Any cleanup tool that moves/deletes files MUST cross-reference the live execution manifest.** Excel spreadsheets are not the source of truth for what is deployed.
2. **The quarantine pattern saved us.** Files were moved, not deleted. Recovery was a bulk copy, not a rebuild. This design decision is validated.
3. **AI agent skill execution needs hard gates.** The skill workflow allowed seamless progression from dry-run to execute without human review of what would be quarantined.
4. **Defense in depth matters.** A single shield (portfolio.yaml check) would have prevented this, but multiple layers (running check, manifest confirmation, preflight awareness) ensure coverage against variations of this failure mode.

---

## 9. Post-Incident Fixes Applied

Fixes implemented in `tools/state_lifecycle/lineage_pruner.py` on 2026-04-02:

### Fix A: Execution Shield (VERIFIED)
- `build_execution_shield()` reads `TS_Execution/portfolio.yaml`, extracts all enabled strategy IDs (38 strategies).
- `scan_and_map()` checks both `portfolios` and `deployed_portfolios` targets against the shield set.
- Any conflict triggers `[BLOCK] Attempted to quarantine deployed strategies:` + `sys.exit(1)`.
- **Audit result:** Simulated run confirmed all 38 deployed strategies would be blocked from quarantine.

### Fix B: Running-Process Check (VERIFIED)
- `execution_pid_exists()` uses two-layer detection:
  - Layer 1: PID file (`execution.pid`) — cross-platform alive check (ctypes on Windows, signal 0 on Unix).
  - Layer 2: Heartbeat freshness (`heartbeat.log` modified within 5 minutes).
- Catches stale PID files (process re-launched with new PID without updating old file).
- **Audit result:** With TS_Execution running but PID file stale (PID 29544 dead, heartbeat 77s fresh), the check correctly blocked: `[BLOCK] TS_Execution is running`.
- **Bug found and fixed:** Original `os.kill(pid, 0)` crashed on Windows with `SystemError`. Replaced with `ctypes.windll.kernel32.OpenProcess()` for Windows, kept `os.kill` for Unix.

### Fix E: Preflight Execution Contract (VERIFIED — 2026-04-02)
- `_check_execution_contract()` added to `tools/system_preflight.py`.
- For each enabled strategy in `TS_Execution/portfolio.yaml`:
  1. `strategy.py` exists in `Trade_Scan/strategies/{id}/`
  2. `portfolio_evaluation/` exists in `TradeScan_State/strategies/{id}/`
  3. `_schema_sample()` passes `signal_schema.validate()`
- Reports RED per failing strategy. Would have caught the quarantine wipe before TS_Execution restart.
- **Audit result:** All 38 deployed strategies pass.

### Fix G: Tier-Aware Run Resolution + Registry Sync (VERIFIED — 2026-04-02)
- `resolve_run_location(run_id)` added to `system_preflight.py` — resolves runs across `runs/`, `sandbox/`, and `quarantine/` with cached quarantine index.
- `_check_registry()` uses tier-aware resolution: sandbox runs are found correctly, quarantined-but-missing triggers YELLOW (not silent skip).
- `_check_portfolios()` distinguishes quarantined deps (YELLOW) from truly missing deps (RED).
- `batch_update_registry_status()` added to `lineage_pruner.py` — single atomic write (tmp + `os.replace`) after all moves complete. Registry entries for quarantined runs marked `status: "quarantined"`.
- **Audit result:** Eliminated 120 false-positive REDs (sandbox routing bug) and 91 false-positive portfolio dependency REDs.

### Fixes C, D, F: Not Yet Implemented
- C (pre-execution manifest) — documented, not yet coded
- D (skill workflow hard gate) — documented, not yet coded
- F (better TS_Execution error messages) — documented, not yet coded
