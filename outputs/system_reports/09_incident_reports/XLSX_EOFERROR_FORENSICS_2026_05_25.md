# XLSX EOFError Forensics — `Master_Portfolio_Sheet.xlsx` / `Filtered_Strategies_Passed.xlsx`

**Date:** 2026-05-25
**Status:** Root cause identified. No remediation applied — pipeline behavior preserved per the operator's "investigate first" directive.
**Surface area:** Governance readers (`tools/state_lifecycle/lineage_pruner.py`, `tools/state_lifecycle/repair_integrity.py`, ad-hoc preflight scripts).

---

## 1. Symptom

A run of `python tools/state_lifecycle/lineage_pruner.py` (default dry-run) aborts before its directive scan with an `EOFError` deep in the openpyxl reader stack:

```
File "openpyxl/worksheet/_reader.py", line 156, in parse
    for _, element in it:
File "xml/etree/ElementTree.py", line 1253, in iterator
    data = source.read(16 * 1024)
File "zipfile.py", line 965, in read
    data = self._read1(n)
File "zipfile.py", line 1068, in _read2
    raise EOFError
```

The error is **intermittent**, surfacing only when the reader runs concurrently with (or shortly after) a writer that has not yet completed its post-replace formatter step.

At the time of capture (2026-05-25 ~18:09 local):
- `Master_Portfolio_Sheet.xlsx` was mid-write (mtime advanced to 18:24 minutes later).
- `Filtered_Strategies_Passed.xlsx` was mid-write (mtime advanced to 18:17 minutes later).

A re-read at 18:30 succeeded cleanly on both files; `zipfile.ZipFile.testzip()` returned no bad members; openpyxl scanned every row of every sheet without incident. The files themselves are healthy *between* write windows.

---

## 2. Reproduction (after-the-fact characterization)

Direct re-reproduction is timing-sensitive — the race window is the duration of a formatter subprocess (~1–3 s per workbook). The signature of an active race:

```bash
python -c "
import zipfile
with zipfile.ZipFile('../TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx') as z:
    print('members=', len(z.namelist()), 'bad=', z.testzip())
"
```

Returns one of:
- `zipfile.BadZipFile: File is not a zip file` (truncated header).
- `EOFError` from deep in `_read1` (partial central directory).
- Healthy `members=N bad=None` (window has closed).

The hit rate during a `pipeline-state-cleanup` skill invocation, or shortly after a `stage3_compiler`/`portfolio_evaluator` run, is materially > 0.

---

## 3. Producer inventory

13 production code paths can write to MPS or FSP. Three use a safe atomic pattern; the rest are in-place writes without locking. Sourced from `tools/safe_append_excel.py`, `tools/portfolio/portfolio_ledger_writer.py`, and a Repo-wide grep audit.

### 3.1 Atomic writers (FileLock + temp + os.replace)

| Path | Function | Behavior |
|---|---|---|
| [tools/portfolio/portfolio_ledger_writer.py:449](tools/portfolio/portfolio_ledger_writer.py:449) | `_append_ledger_row()` | FileLock on `<path>.lock` (120 s); writes to `<path>.xlsx.tmp`; fsync; `os.replace`. **Then releases lock** and runs formatter as subprocess (see §4). |
| [tools/stage3_compiler.py:402](tools/stage3_compiler.py:402) | `compile_stage3()` | FileLock + temp + replace for Master Filter. Same post-release formatter pattern. |
| [tools/run_portfolio_analysis.py:500](tools/run_portfolio_analysis.py:500) | `run_portfolio_analysis()` | FileLock + temp + replace. Same post-release pattern. |

### 3.2 In-place writers (no lock, no temp, no atomic semantics)

| Path | Function | Risk |
|---|---|---|
| [tools/filter_strategies.py:517](tools/filter_strategies.py:517) | `build_candidate_filter()` | `pd.ExcelWriter(FSP_PATH, mode="w")` — truncates on open. Two concurrent invocations corrupt the file. |
| [tools/state_lifecycle/repair_integrity.py:179](tools/state_lifecycle/repair_integrity.py:179) | `main()` | `df.to_excel(<FSP/MPS>)` directly. |
| [tools/cleanup_mps.py:102](tools/cleanup_mps.py:102) | `main()` | Creates timestamped `.bak` first, then `ExcelWriter(mode="w")` rewrites in place. Bak file lets you reconstruct manually, but the active file passes through a truncated state. |
| [tools/profile_selector.py:375](tools/profile_selector.py:375) | (MPS writer) | `ExcelWriter(MPS_PATH, mode="w")` — same hazard as filter_strategies. |
| [tools/ledger_db.py:1023](tools/ledger_db.py:1023) | `export_mps()` | `pd.ExcelWriter(out, engine="openpyxl")` — no temp, no lock. |
| [tools/safe_append_excel.py:31](tools/safe_append_excel.py:31) | `safe_append()` | Despite the name: `openpyxl.load_workbook` then `wb.save(path)` in place. Lock-free, temp-free. |
| [tools/reconcile_portfolio_master_sheet.py](tools/reconcile_portfolio_master_sheet.py) | `reconcile()` | In-place via pandas + subprocess formatter. |

### 3.3 The formatter (called by EVERY writer post-write)

[tools/excel_format/styling.py:601](tools/excel_format/styling.py:601):

```python
wb.save(path)        # in-place — writes a fresh zip over the live file
```

Invoked as a subprocess by every safe writer **after the FileLock is released and after `os.replace` has put the canonical file in place**. The formatter then opens, mutates (Notes sheet, styling), and re-saves in place. The save is a streaming write of a fresh zip; there is a window of milliseconds-to-seconds during which the file on disk is a partial zip.

---

## 4. Root cause

The intermittent EOF is **not** a workbook integrity bug, a cloud-sync collision, an Excel-lock issue, or a truncated emitter. It is a **post-replace formatter race**:

```
TIME    EVENT                                                STATE OF FILE
T0      writer acquires FileLock                             clean copy from T-N
T1      writer streams df to <path>.xlsx.tmp                 clean
T2      writer fsyncs and os.replace's tmp -> path           clean (atomic flip)
T3      writer releases FileLock                             clean
T4      writer subprocess.run([formatter, --file path])      clean
T5      formatter opens path with openpyxl.load_workbook     clean
T6      formatter mutates in memory (apply_formatting, Notes) clean
T7      formatter calls wb.save(path)                        ★ PARTIAL ZIP ★
T8      formatter completes write                            clean again
```

Between T7 and T8 — for the duration of a streaming xlsx serialization, ~100 ms to ~3 s depending on workbook size — any reader that opens the file gets a truncated zip. There is no lock protecting this window because the writer dropped the lock at T3.

Compounding the formatter race, any of the 7 in-place writers in §3.2 can extend the unsafe window to the duration of the *entire* write (~seconds), not just the formatter step. Two in-place writers running concurrently corrupt the file outright; a reader hitting either gets EOF or BadZipFile.

The absence of git tracking on `../TradeScan_State` means an interrupted write (power loss, OOM kill, sigkill) leaves the file in whatever partial state `wb.save` reached at the moment of the kill. No commit history to recover from.

---

## 5. Affected workflows

| Workflow | Reader path | Failure mode |
|---|---|---|
| `pipeline-state-cleanup` skill | `lineage_pruner.scan_and_map` reads MPS + FSP via `pd.read_excel` | Aborts whole sweep |
| Stage-1B referential integrity | `repair_integrity.py` reads MPS | Aborts repair check |
| System preflight | `tools/system_preflight.py` (best-effort openpyxl reads) | Logs warning, may misclassify |
| Strategy card generation | `tools/generate_strategy_card.py` reads MPS via pandas | Card skipped, no fatal |
| Family report | `tools/family_report.py` reads MPS | Report skipped, no fatal |
| Manual ad-hoc inspection | any operator opening the file in Excel mid-write | Excel error dialog |

No data-loss workflow has been observed. The blast radius is limited to read-side aborts and reruns.

---

## 6. Recommended invariant

**MPS, FSP, and any other governance ledger workbook must follow the "single critical section" rule:** every write path — including the formatter — happens inside one FileLock acquisition, and the only on-disk transition observable to a reader is the atomic `os.replace`. There is no in-place save on a published path.

### 6.1 Writer-side requirement

```python
with FileLock(str(path.with_suffix(".lock")), timeout=120):
    tmp = path.with_suffix(".xlsx.tmp")
    # 1. write data to tmp
    df.to_excel(tmp, ...)
    # 2. format tmp BEFORE publishing — apply_formatting + Notes sheet operate on tmp
    apply_formatting(tmp, profile)
    add_notes_sheet_to_ledger(tmp, notes_type)
    # 3. fsync tmp
    with open(tmp, "r+b") as fh:
        os.fsync(fh.fileno())
    # 4. atomic publish
    os.replace(str(tmp), str(path))
```

Single atomic flip. No post-replace in-place save. No subprocess call required for formatting (the formatter is callable as a library — `from excel_format import apply_formatting, add_notes_sheet_to_ledger`).

### 6.2 Reader-side defense in depth

Even with §6.1 in place, a reader running against a workbook whose writer is mid-`os.replace` on Windows can briefly see a zero-byte or non-existent file. Governance readers should wrap their first read in a short retry loop:

```python
def read_governance_ledger(path: Path, attempts: int = 5, backoff: float = 0.2):
    last_exc = None
    for i in range(attempts):
        try:
            return pd.read_excel(path)
        except (zipfile.BadZipFile, EOFError, FileNotFoundError) as exc:
            last_exc = exc
            time.sleep(backoff * (2 ** i))
    raise last_exc
```

Five attempts with exponential backoff covers a worst-case formatter window plus a slow os.replace.

### 6.3 In-place writers in §3.2 must be retired

Every writer in §3.2 violates §6.1. Each should either:
- Migrate to the §6.1 pattern (preferred), or
- Be deprecated if its function is superseded by an atomic writer.

### 6.4 Lock & corruption detection with structured logging

Wrap the §6.1 critical section with explicit telemetry:

```python
log.info("ledger_write_begin", extra={"path": str(path), "writer": __name__,
                                       "lock_acquired_at": iso_now()})
... critical section ...
log.info("ledger_write_commit", extra={"path": str(path), "size_bytes": path.stat().st_size,
                                        "sha256": sha256(path), "duration_ms": ...})
```

On any `BadZipFile`/`EOFError`/`OSError` inside the critical section, the writer must NOT swallow — log + raise, leaving the prior committed file untouched (the temp is dropped on context exit).

---

## 7. Remediation plan (not yet applied)

Phase 1 — readers (cheap, low risk):
1. Add `read_governance_ledger()` helper to `tools/pipeline_utils.py` (the obvious home — it's already imported widely).
2. Switch `lineage_pruner.py`, `repair_integrity.py`, and any other governance reader to use it.
3. Regression test that simulates a BadZipFile on first read and verifies retry succeeds on second.

Phase 2 — writer consolidation (medium):
4. Refactor `format_excel_artifact.py` so `apply_formatting()` and `add_notes_sheet_to_ledger()` accept a path that is *not yet* the canonical file. Today they do — the subprocess shim is what couples them to the canonical path. Removing the subprocess call from writers and calling the library directly inside the lock eliminates the §4 race entirely.
5. Migrate `portfolio_ledger_writer.py`, `stage3_compiler.py`, `run_portfolio_analysis.py` to format-before-replace.
6. Add a single regression test: spawn two writer subprocesses concurrently; assert no reader sees a partial state.

Phase 3 — retire in-place writers (high effort, structural):
7. Audit each §3.2 writer. For each one:
   - If it can be replaced by an atomic writer (e.g., `cleanup_mps.py` likely should delegate to `portfolio_ledger_writer.py` with a delete-rows operation), do that.
   - Otherwise, port it to the §6.1 pattern.

Phase 4 — observability:
8. Emit telemetry per §6.4 to a `TradeScan_State/logs/ledger_writes.jsonl` append-only file. Use it to confirm no writer takes longer than the lock timeout, and to investigate any future incidents.

---

## 8. What this report does NOT do

- It does not change any code. The pipeline behavior is preserved exactly as it stood at commit `176b149`. Per the operator's directive, remediation requires explicit approval and an atomic-phase implementation plan.
- It does not address `TradeScan_State` lacking git tracking. That's a separate decision (cost: ~100 MB committed history; benefit: bisectability across ledger states).
- It does not retroactively recover any historical EOF-aborted run. Those runs simply need to be re-invoked when the writer is quiescent.

---

## 9. References

- Commit `0933560`: sidecar pairing in `lineage_pruner` (Step 1 of the admitted-marker rehab); incidentally surfaced this EOF when the dry-run exercised MPS/FSP reads.
- Commit `081dbbc`: the 433-marker orphan sweep that triggered the run where this was first observed.
- [outputs/system_reports/10_State Lifecycle Management/Workflow_Design.md](outputs/system_reports/10_State%20Lifecycle%20Management/Workflow_Design.md) — adjacent lifecycle documentation; §4 covers the directive sidecar invariant that motivated the original investigation.
- `tools/portfolio/portfolio_ledger_writer.py:449-508` — the reference safe-writer pattern this report's §6.1 generalizes.
- `tools/excel_format/styling.py:601` — the formatter's in-place save call; the proximate cause of the post-replace race window.
