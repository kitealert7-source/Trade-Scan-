"""cointegration_daily_runner.py — supervised daily pipeline (spec Phase 4).

Orchestrates the full daily cointegration cycle in a single process:

    Phase 1 (compute)   tools.cointegration_screen.main()        → parquet
    Phase 2 (upsert)    tools.cointegration_db.main(--upsert)    → SQLite
    Phase 3 (render)    tools.cointegration_excel.main(--export) → screener.xlsx
    Phase 4 (mps)       ledger_db.export_mps() + portfolio format → MPS.xlsx

Phases 1-2 are FATAL (downstream needs their output). Phases 3 and 4 are
independent NON-FATAL render phases that read only the SQLite refreshed by
Phase 2: Phase 3 renders the screener workbook; Phase 4 re-exports the MPS so
its COINT TRADE CANDIDATES "Coint Status (252d)" column tracks the screener DB
(that column is compute-at-regen — it only refreshes when the MPS is
re-exported). A lock-skip in one render phase never blocks the other.

Each phase is invoked as a function call (not subprocess) so:
  * single OS process, single result log
  * exceptions bubble with intact tracebacks
  * exit code reflects the FIRST failing fatal phase / worst render failure

Per COINTEGRATION_SCREENER_V1_SPEC.md §12 Phase 4 + §11 failure handling.

Render failure semantics (spec §11):
    Excel render failures (file lock, openpyxl error) are WARNINGS not fatal —
    the parquet + SQLite + ledger DB remain valid for the next run, and the
    operator can manually regenerate via:
        python tools/cointegration_excel.py --export                 # screener
        python tools/ledger_db.py --export-mps  +  format_excel_artifact
            --file <MPS> --profile portfolio                         # MPS

Exit codes:
     0   PASS  — all phases succeeded (or a render phase deferred on a lock)
    30   FAIL  — Phase 1 (compute) failed
    31   FAIL  — Phase 2 (SQLite upsert) failed
    32   WARN  — Phase 3 (screener Excel) hard-failed; parquet + SQLite valid
    33   WARN  — Phase 4 (MPS refresh) hard-failed; ledger DB + screener valid
    40   FAIL  — unexpected uncaught exception

Result log: tmp/cointegration_daily.log (UTF-8, append-only).

Usage:
    python tools/cointegration_daily_runner.py                 # full daily run
    python tools/cointegration_daily_runner.py --skip-excel    # skip screener xlsx
    python tools/cointegration_daily_runner.py --skip-mps      # skip MPS refresh
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on stdout/stderr BEFORE any code that might print unicode.
# Windows defaults to cp1252 which cannot encode the "→" used in phase
# names — Task Scheduler hides this (stdout discarded), but PowerShell
# Start-Process -RedirectStandardOutput captures stdout to a file whose
# write would otherwise crash. Has to happen before the imports below
# because their module-level code may emit unicode at import time.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import cointegration_screen, cointegration_db, cointegration_excel


LOG_FILE = PROJECT_ROOT / "tmp" / "cointegration_daily.log"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} | {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run_phase(name: str, fn, argv: list[str], fail_exit_code: int,
                fatal: bool = True) -> int | None:
    """Run one phase. Return exit code on PASS; None if non-fatal Excel skipped."""
    t0 = time.time()
    try:
        rc = fn(argv)
    except PermissionError as exc:
        # Excel-locked is the canonical non-fatal case (spec §11).
        if not fatal:
            _log(f"WARN  {name} permission denied (file locked? user has it open?): {exc}")
            _log(f"      parquet + SQLite are still valid; next run will catch up")
            return None
        _log(f"FAIL  {name} permission denied: {exc}")
        return fail_exit_code
    except Exception as exc:
        _log(f"FAIL  {name} uncaught {type(exc).__name__}: {exc}")
        _log(traceback.format_exc())
        return fail_exit_code
    elapsed = time.time() - t0
    if rc != 0:
        if not fatal:
            _log(f"WARN  {name} exit_code={rc} (elapsed {elapsed:.1f}s) — non-fatal, next run will retry")
            return None
        _log(f"FAIL  {name} exit_code={rc} (elapsed {elapsed:.1f}s)")
        return fail_exit_code
    _log(f"OK    {name} in {elapsed:.1f}s")
    return 0


def _run_phase4_mps(_argv: list[str] | None = None) -> int:
    """Phase 4 body: re-export the MPS so its COINT TRADE CANDIDATES
    "Coint Status (252d)" column tracks the screener DB that Phase 2 just
    upserted. Mirrors the post-backtest MPS procedure exactly:

      1. ledger_db.export_mps()              -> MPS xlsx; the Coint Status
         column recomputes from cointegration_daily (compute-at-regen).
      2. apply_formatting(mps, "portfolio")  +  add_notes_sheet_to_ledger(mps,
         "portfolio")                        -> portfolio styling + restore the
         Notes glossary that export's ExcelWriter(mode='w') strips (the
         candidates tab is a preserved sheet — its data is not reformatted).

    Both writers route through the shared resilient_xlsx_write primitive, so a
    workbook the operator left open is force-closed and rewritten rather than
    silently skipped; a genuinely un-writable file raises (PermissionError ->
    non-fatal deferral; any other error -> exit 33) via the _run_phase caller.

    Returns 0 on success. Lazy imports keep module import light (ledger_db pulls
    in the full ledger stack) and avoid an import cycle.
    """
    from tools import ledger_db
    from tools.excel_format import add_notes_sheet_to_ledger, apply_formatting

    mps_path = ledger_db.export_mps()
    apply_formatting(str(mps_path), "portfolio")
    add_notes_sheet_to_ledger(str(mps_path), "portfolio")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cointegration screener — daily supervised runner (spec Phase 4).")
    parser.add_argument("--skip-excel", action="store_true",
                        help="Skip Phase 3 (screener Excel render); Phases 1-2 + 4 still run.")
    parser.add_argument("--skip-mps", action="store_true",
                        help="Skip Phase 4 (MPS refresh); Phases 1-3 still run.")
    args = parser.parse_args(argv)

    _log("=" * 60)
    _log(f"START daily run  pid={os.getpid()} user={os.environ.get('USERNAME', '?')}")

    # Phase 1: compute → parquet for each supported timeframe.
    #   1d — FATAL: canonical screener view; Phases 2/3/4 + research consumers
    #        (basket_data_loader, indicators.stats.cointegration_state,
    #        cointegration_excel) read 1d artifacts.
    #   4h — NON-FATAL: research-side dataset surfaced in the Excel Summary's
    #        dual-TF intersection section and the History sheet's tf filter.
    #        A 4h compute failure must not block the 1d-dependent downstream
    #        phases, because consumers fall back gracefully to the prior 4h
    #        SQLite rows.
    # Wired 2026-06-06: previously the runner called cointegration_screen.main([])
    # once (defaulting to tf=1d), so 4h had no automated cadence — the last 4h
    # rows in SQLite were from 2026-05-29 via manual backfill.
    rc = _run_phase("Phase 1a (compute 1d → parquet)",
                     cointegration_screen.main, ["--tf", "1d"], fail_exit_code=30)
    if rc != 0:
        _log("ABORT after Phase 1a (1d compute) failure")
        return rc

    rc = _run_phase("Phase 1b (compute 4h → parquet)",
                     cointegration_screen.main, ["--tf", "4h"],
                     fail_exit_code=30, fatal=False)
    # rc is 0 on success or None when _run_phase swallowed a non-fatal failure;
    # either way we continue — 4h freshness is best-effort.

    # Phase 2: parquet → SQLite. FATAL on failure (Phases 3 + 4 read from SQLite).
    # cointegration_db.main auto-discovers every coint_<tf>_latest.parquet
    # alongside the default 1d path, so this single call upserts both TFs.
    rc = _run_phase("Phase 2 (parquet → SQLite)",
                     cointegration_db.main, ["--upsert"], fail_exit_code=31)
    if rc != 0:
        _log("ABORT after Phase 2 failure")
        return rc

    # Phases 3 + 4: independent NON-FATAL render phases. Both read only the
    # SQLite that Phase 2 just refreshed (NOT each other), so a lock-skip in one
    # must never block the other — neither early-returns. We collect the worst
    # hard exit code and report any lock-deferrals; a deferral alone is PASS.
    worst_rc = 0
    deferred: list[str] = []

    # Phase 3: SQLite → screener.xlsx.
    if args.skip_excel:
        _log("SKIP  Phase 3 (--skip-excel)")
    else:
        rc = _run_phase("Phase 3 (SQLite → Excel)",
                         cointegration_excel.main, ["--export"],
                         fail_exit_code=32, fatal=False)
        if rc is None:
            deferred.append("Phase 3")
        elif rc != 0:
            worst_rc = worst_rc or rc

    # Phase 4: ledger DB + screener DB → MPS.xlsx (refreshes the COINT TRADE
    # CANDIDATES "Coint Status (252d)" column — compute-at-regen).
    if args.skip_mps:
        _log("SKIP  Phase 4 (--skip-mps)")
    else:
        rc = _run_phase("Phase 4 (MPS refresh)",
                         _run_phase4_mps, [],
                         fail_exit_code=33, fatal=False)
        if rc is None:
            deferred.append("Phase 4")
        elif rc != 0:
            worst_rc = worst_rc or rc

    if worst_rc:
        return worst_rc
    if deferred:
        _log(f"PASS  Phases 1 + 2 ({' + '.join(deferred)} deferred — locked/error)")
    else:
        _log("PASS  all phases")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        _log(f"FAIL UNCAUGHT_AT_TOP: {type(exc).__name__}: {exc}")
        _log(traceback.format_exc())
        exit_code = 40
    raise SystemExit(exit_code)
