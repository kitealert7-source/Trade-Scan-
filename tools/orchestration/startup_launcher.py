"""
startup_launcher.py — TS_Execution Startup Launcher

Invoked by Windows Task Scheduler on:
  - User login (30s delay)
  - Workstation unlock  (covers sleep/resume)
  - Every 5 minutes     (periodic watchdog liveness guard)

Responsibilities (in order):
  1. Poll for terminal64.exe (MT5 process) — abort if not found within 120s
  2. Probe MT5 API: account_info().connected == True — abort if not ready within 60s
  3. Single-instance guard: skip if watchdog already alive
  4. Start watchdog_daemon.py as detached process

Design principles:
  - Idempotent: safe to run every 5 minutes; exits in <2s if watchdog is alive
  - Does NOT hold MT5 connection: mt5.shutdown() always called after probe
  - Does NOT start watchdog unless MT5 is confirmed ready (protects storm guard quota)
  - All actions logged with UTC timestamp + phase token
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_TRADE_SCAN_ROOT = Path(__file__).resolve().parents[2]
TS_EXEC_ROOT = Path(os.environ.get("TS_EXEC_ROOT", str(_TRADE_SCAN_ROOT.parent / "ts_execution")))

WATCHDOG_SCRIPT = Path(__file__).parent / "watchdog_daemon.py"
WDOG_PID        = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog.pid"
LOG_FILE        = TS_EXEC_ROOT / "outputs" / "logs" / "startup_launcher.log"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MT5_PROCESS      = "terminal64.exe"
MT5_POLL_S       = 10     # seconds between each probe poll
MT5_PROC_TIMEOUT = 120    # max seconds to wait for terminal64.exe to appear
MT5_API_TIMEOUT  = 60     # max seconds to wait for account_info().connected


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | LAUNCHER | {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
                _lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
                LOG_FILE.write_text("\n".join(_lines[-2000:]) + "\n", encoding="utf-8")
        except Exception:
            pass  # rotation failed — append proceeds
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Step 1 — MT5 process probe
# ---------------------------------------------------------------------------
def _mt5_proc_alive() -> int | None:
    """Return MT5 PID if terminal64.exe is in tasklist, else None."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {MT5_PROCESS}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.splitlines():
            if MT5_PROCESS.lower() in line.lower():
                # CSV format: "terminal64.exe","588","Console","1","..."
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        return int(parts[1])
                    except ValueError:
                        return -1  # found but can't parse PID
    except Exception:
        pass
    return None


def wait_for_mt5_process() -> bool:
    """Poll for terminal64.exe. Returns True if found, False on timeout."""
    elapsed = 0
    while elapsed < MT5_PROC_TIMEOUT:
        pid = _mt5_proc_alive()
        if pid is not None:
            _log(f"MT5_PROC_FOUND | pid={pid}")
            return True
        time.sleep(MT5_POLL_S)
        elapsed += MT5_POLL_S
    _log(f"MT5_PROC_TIMEOUT | {MT5_PROCESS} not found in {MT5_PROC_TIMEOUT}s | aborting")
    return False


# ---------------------------------------------------------------------------
# Step 2 — MT5 API readiness probe
# ---------------------------------------------------------------------------
def wait_for_mt5_api() -> bool:
    """Probe MT5 API until account_info().connected == True. Returns True on success."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        _log("MT5_API_UNAVAILABLE | MetaTrader5 package not importable | aborting")
        return False

    try:
        mt5.initialize()
    except Exception as e:
        _log(f"MT5_API_ERROR | mt5.initialize() raised {type(e).__name__}: {e} | aborting")
        try:
            mt5.shutdown()
        except Exception:
            pass
        return False

    elapsed = 0
    result  = False
    try:
        while elapsed < MT5_API_TIMEOUT:
            try:
                info = mt5.account_info()
                if info is not None and getattr(info, "connected", False):
                    _log(f"MT5_API_OK | connected=True | account={info.login} | server={info.server}")
                    result = True
                    break
            except Exception:
                pass
            time.sleep(MT5_POLL_S)
            elapsed += MT5_POLL_S

        if not result:
            _log(f"MT5_NOT_READY | account_info().connected=False after {MT5_API_TIMEOUT}s | aborting")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Step 3 — Watchdog single-instance guard
# ---------------------------------------------------------------------------
def _pid_is_alive(pid: int) -> bool:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
        )
        return str(pid) in r.stdout
    except Exception:
        return False


def watchdog_already_running() -> bool:
    """Return True if a live watchdog process exists."""
    if not WDOG_PID.exists():
        return False
    try:
        pid = int(WDOG_PID.read_text().strip())
        if _pid_is_alive(pid):
            _log(f"WATCHDOG_ALREADY_RUNNING | pid={pid} | skipping")
            return True
    except Exception:
        pass
    return False  # stale PID file — proceed


# ---------------------------------------------------------------------------
# Step 4 — Start watchdog
# ---------------------------------------------------------------------------
def start_watchdog() -> None:
    """Launch watchdog_daemon.py as a detached process."""
    if not WATCHDOG_SCRIPT.exists():
        _log(f"WATCHDOG_SCRIPT_MISSING | {WATCHDOG_SCRIPT} | aborting")
        return

    proc = subprocess.Popen(
        [sys.executable, str(WATCHDOG_SCRIPT)],
        cwd=str(_TRADE_SCAN_ROOT),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _log(f"WATCHDOG_STARTED | pid={proc.pid}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    _log(f"LAUNCHER_START | ts_exec_root={TS_EXEC_ROOT} | watchdog={WATCHDOG_SCRIPT}")

    # Step 1 — MT5 process
    if not wait_for_mt5_process():
        _log("LAUNCHER_DONE | reason=mt5_proc_timeout")
        return

    # Step 2 — MT5 API readiness
    if not wait_for_mt5_api():
        _log("LAUNCHER_DONE | reason=mt5_not_ready")
        return

    # Step 3 — Watchdog guard
    if watchdog_already_running():
        _log("LAUNCHER_DONE | reason=watchdog_alive")
        return

    # Step 4 — Start watchdog
    start_watchdog()
    _log("LAUNCHER_DONE | reason=watchdog_started")


if __name__ == "__main__":
    main()
