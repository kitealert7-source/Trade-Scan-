# Phase 0a — Bootstrap Manifest

**Status:** PASSED 2026-05-20T06:21:20Z
**Note:** SQLite path references in this document reflect the post-2026-05-20 location move (SQLite + Excel relocated from `TradeScan_State/cointegration/` to `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/` alongside the parquet — see spec §4b architectural correction). The actual probe run on 2026-05-20T06:21:20Z used the original path; behavior is identical under either path since the probe only verifies write access.
**Spec:** [COINTEGRATION_SCREENER_V1_SPEC.md §10](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)
**Gate cleared:** Phase 1 compute work may begin.

---

## Artifacts in this directory

| File | Purpose |
|---|---|
| `CointegrationScreener_Phase0aProbe.task.xml` | Windows Task Scheduler XML — UTF-16 LE BOM, registers a one-shot task as `faraw` + `InteractiveToken` + `HighestAvailable` (matches `TradeScan NAS Backup` identity pattern). |
| `register_and_run_phase0a.ps1` | Elevated bootstrap script — registers the task, triggers it, waits, prints/archives the result log, exits 0/1 based on PASS/FAIL. |
| `phase0a_run.log` | Archived copy of `tmp/cointegration_smoke.log` from the run that passed. Audit evidence. |
| `PHASE0A_MANIFEST.md` | This file. |

## Probe script under test

`tools/cointegration_screener_smoke.py` — performs the four §10 steps:

1. Read one 1d CSV per symbol from `data_root/MASTER_DATA/<SYM>_OCTAFX_MASTER/RESEARCH/` (proves MASTER_DATA read access via SeBackupPrivilege).
2. Write a 1-row dummy parquet to `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/_smoke.parquet` (proves SYSTEM_FACTORS write access — directory created on first run).
3. Open `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db`, create `_smoke` table, upsert + read back (proves SQLite write access — directory created on first run).
4. Delete the dummy parquet and drop the `_smoke` table.

## What this proves

- The faraw + InteractiveToken + HighestAvailable identity model — same as the existing `TradeScan NAS Backup` task — gives the daily run-as identity sufficient access to read MASTER_DATA, write under SYSTEM_FACTORS, and create/write DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/.
- `SeBackupPrivilege` is granted by the elevation and bypasses the DENY INTERACTIVE ACL on MASTER_DATA.
- The two output directories (`SYSTEM_FACTORS/FX_COINTEGRATION/` and `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/`) now exist on disk, ready for Phase 1's first real write.

## How to re-run (re-validation)

After any identity / OS / permission change that could affect the production execution context:

1. Right-click `register_and_run_phase0a.ps1` → **Run as Administrator**
2. Watch the console for `*** PHASE 0a PASSED ***` (or read this directory's `phase0a_run.log` for the latest run).
3. If FAILED, do NOT proceed with code changes that depend on the production identity — diagnose first.

## Lifecycle of the registered task

The task `CointegrationScreener_Phase0aProbe` remains registered for ad-hoc re-validation. It has NO trigger (one-shot only via `schtasks /Run`). To clean up:

```powershell
schtasks /Delete /TN CointegrationScreener_Phase0aProbe /F
```

The Phase 4 daily-run task (added in a later phase) is a separate registration.

## Run log summary (2026-05-20T06:21:20Z)

| Step | Outcome | ms |
|---|---|---|
| 1 — read 18 symbols' 1d files | OK | 56 |
| 2 — write SYSTEM_FACTORS parquet | OK | 23 |
| 3 — SQLite roundtrip | OK | 9 |
| 4 — cleanup | OK | 9 |
| **total** | **PASS** | **97** |
