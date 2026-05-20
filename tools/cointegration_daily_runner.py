"""cointegration_daily_runner.py — Phase 4: supervised daily pipeline.

Orchestrates the full daily cointegration cycle in a single process:

    Phase 1 (compute)   tools.cointegration_screen.main()      → parquet
    Phase 2 (upsert)    tools.cointegration_db.main(--upsert)  → SQLite
    Phase 3 (render)    tools.cointegration_excel.main(--export) → Excel

Each phase is invoked as a function call (not subprocess) so:
  * single OS process, single result log
  * exceptions bubble with intact tracebacks
  * exit code reflects the FIRST failing phase

Per COINTEGRATION_SCREENER_V1_SPEC.md §12 Phase 4 + §11 failure handling.

Excel failure semantics (spec §11):
    Excel render failures (file lock, openpyxl error) are WARNINGS not
    fatal — the parquet + SQLite remain valid for the next run to use,
    and the operator can manually regenerate via:
        python tools/cointegration_excel.py --export

Exit codes:
     0   PASS  — all phases succeeded
    30   FAIL  — Phase 1 (compute) failed
    31   FAIL  — Phase 2 (SQLite upsert) failed
    32   WARN  — Phase 3 (Excel) failed; parquet + SQLite are still valid
    40   FAIL  — unexpected uncaught exception

Result log: tmp/cointegration_daily.log (UTF-8, append-only).

Usage:
    python tools/cointegration_daily_runner.py             # full daily run
    python tools/cointegration_daily_runner.py --skip-excel  # debug
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cointegration screener — Phase 4 daily supervised runner.")
    parser.add_argument("--skip-excel", action="store_true",
                        help="Skip the Excel-export phase (parquet + SQLite still run).")
    args = parser.parse_args(argv)

    _log("=" * 60)
    _log(f"START daily run  pid={os.getpid()} user={os.environ.get('USERNAME', '?')}")

    # Phase 1: compute → parquet. FATAL on failure (downstream phases need parquet).
    rc = _run_phase("Phase 1 (compute → parquet)",
                     cointegration_screen.main, [], fail_exit_code=30)
    if rc != 0:
        _log(f"ABORT after Phase 1 failure")
        return rc

    # Phase 2: parquet → SQLite. FATAL on failure (Phase 3 reads from SQLite).
    rc = _run_phase("Phase 2 (parquet → SQLite)",
                     cointegration_db.main, ["--upsert"], fail_exit_code=31)
    if rc != 0:
        _log(f"ABORT after Phase 2 failure")
        return rc

    # Phase 3: SQLite → Excel. NON-FATAL — locked Excel is expected and the
    # parquet/SQLite stand on their own. Operator can manually regenerate.
    if args.skip_excel:
        _log("SKIP  Phase 3 (--skip-excel)")
        _log("PASS  all phases (excel skipped)")
        return 0

    rc = _run_phase("Phase 3 (SQLite → Excel)",
                     cointegration_excel.main, ["--export"],
                     fail_exit_code=32, fatal=False)
    if rc is None:
        # Non-fatal Excel skip — overall run is still PASS.
        _log("PASS  Phases 1 + 2 (Phase 3 deferred — locked/error)")
        return 0
    if rc != 0:
        return rc

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
