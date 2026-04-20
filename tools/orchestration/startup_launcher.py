"""
startup_launcher.py — TS_Execution Startup Launcher

Invoked by Windows Task Scheduler on:
  - User login (30s delay)
  - Workstation unlock  (covers sleep/resume)
  - Every 5 minutes     (periodic watchdog liveness guard)

Responsibilities (in order):
  1. Check for terminal64.exe — launch it if not running, then poll up to 120s
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
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_TRADE_SCAN_ROOT = Path(__file__).resolve().parents[2]
TS_EXEC_ROOT = Path(os.environ.get("TS_EXEC_ROOT", str(_TRADE_SCAN_ROOT.parent / "TS_Execution")))

WATCHDOG_SCRIPT = Path(__file__).parent / "watchdog_daemon.py"
WDOG_PID        = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog.pid"
EXEC_PID        = TS_EXEC_ROOT / "outputs" / "logs" / "execution.pid"
LOG_FILE        = TS_EXEC_ROOT / "outputs" / "logs" / "startup_launcher.log"
EXEC_STATE      = TS_EXEC_ROOT / "outputs" / "logs" / "execution_state.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Suppress console windows when spawning child processes from a windowless
# parent (pythonw.exe / Task Scheduler context). Without this flag every
# subprocess call that spawns a console-subsystem exe (tasklist, wmic,
# python.exe) briefly flashes a black window on the user's desktop.
_NO_WIN = subprocess.CREATE_NO_WINDOW

MT5_PROCESS      = "terminal64.exe"
MT5_POLL_S       = 10     # seconds between each probe poll
MT5_PROC_TIMEOUT = 120    # max seconds to wait for terminal64.exe to appear
MT5_API_TIMEOUT  = 60     # max seconds to wait for account_info().connected
MT5_EXE_PATH     = Path(os.environ.get(
    "MT5_EXE_PATH",
    r"C:\Program Files\OctaFX MT5\terminal64.exe",
))

_mt5_launch_attempted = False  # launch at most once per launcher run


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _rid = _current_run_id() or "NA"
    line = f"{ts} | LAUNCHER | run_id={_rid} | {msg}"
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


def _telegram(msg: str) -> None:
    """Best-effort Telegram notification. Silent on failure."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat  = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        _log("TELEGRAM_DISABLED | TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(url, data, timeout=5)
    except Exception:
        pass


def _current_run_id() -> str | None:
    """Read current TS_Execution run_id from execution_state.json if available."""
    try:
        if not EXEC_STATE.exists():
            return None
        import json

        with open(EXEC_STATE, encoding="utf-8") as f:
            data = json.load(f)
        rid = data.get("run_id")
        return str(rid) if rid else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Step 1 — MT5 process probe
# ---------------------------------------------------------------------------
def _mt5_proc_alive() -> int | None:
    """Return MT5 PID if terminal64.exe is in tasklist, else None."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {MT5_PROCESS}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WIN,
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


def _try_launch_mt5() -> bool:
    """Launch terminal64.exe as a detached process. Returns True if launched."""
    if not MT5_EXE_PATH.exists():
        _log(f"MT5_EXE_NOT_FOUND | path={MT5_EXE_PATH} | cannot auto-launch")
        return False
    try:
        proc = subprocess.Popen(
            [str(MT5_EXE_PATH)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WIN,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _log(f"MT5_LAUNCHED | pid={proc.pid} | path={MT5_EXE_PATH}")
        return True
    except Exception as e:
        _log(f"MT5_LAUNCH_FAILED | {type(e).__name__}: {e}")
        return False


def wait_for_mt5_process() -> bool:
    """Poll for terminal64.exe. Returns True if found, False on timeout."""
    global _mt5_launch_attempted
    elapsed = 0
    while elapsed < MT5_PROC_TIMEOUT:
        pid = _mt5_proc_alive()
        if pid is not None:
            _log(f"MT5_PROC_FOUND | pid={pid}")
            return True
        if not _mt5_launch_attempted:
            _mt5_launch_attempted = True
            _try_launch_mt5()
        time.sleep(MT5_POLL_S)
        elapsed += MT5_POLL_S
    _log(f"MT5_PROC_TIMEOUT | {MT5_PROCESS} not found in {MT5_PROC_TIMEOUT}s | aborting")
    return False


# ---------------------------------------------------------------------------
# Step 2 — MT5 API readiness probe
# ---------------------------------------------------------------------------
def wait_for_mt5_api() -> bool:
    """Probe MT5 API: account logged in + terminal connected to server.

    Correct fields:
      mt5.account_info()  → not None  means account is logged in
      mt5.terminal_info().connected   means terminal connected to trade server
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        _log("MT5_API_UNAVAILABLE | MetaTrader5 package not importable | aborting")
        return False

    elapsed = 0
    result  = False
    try:
        while elapsed < MT5_API_TIMEOUT:
            try:
                if not mt5.initialize():
                    _log(f"MT5_INIT_FAIL | {mt5.last_error()} | retrying in {MT5_POLL_S}s")
                    mt5.shutdown()
                    time.sleep(MT5_POLL_S)
                    elapsed += MT5_POLL_S
                    continue

                acct = mt5.account_info()
                term = mt5.terminal_info()

                if acct is not None and term is not None and term.connected:
                    _log(
                        f"MT5_API_OK | connected=True"
                        f" | account={acct.login}"
                        f" | server={acct.server}"
                        f" | balance={acct.balance}"
                    )
                    result = True
                    break
                else:
                    acct_ok = acct is not None
                    term_ok = term is not None and term.connected
                    _log(f"MT5_NOT_READY_YET | account_logged_in={acct_ok} | server_connected={term_ok} | retrying")

            except Exception as e:
                _log(f"MT5_API_ERROR | {type(e).__name__}: {e} | retrying")

            mt5.shutdown()
            time.sleep(MT5_POLL_S)
            elapsed += MT5_POLL_S

        if not result:
            _log(f"MT5_NOT_READY | not ready after {MT5_API_TIMEOUT}s | aborting")
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
    """
    Liveness check with fallback. Mirrors watchdog_daemon._pid_is_alive.
    Tasklist primary, psutil fallback, fail-safe ALIVE if both error.
    The launcher *must not* treat a transient tasklist glitch as "process
    dead" — that would defeat the single-instance guard and spawn duplicates.
    """
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WIN,
        )
        if r.returncode == 0:
            return str(pid) in r.stdout
    except Exception:
        pass
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:
        pass
    return True  # fail-safe: assume alive


# Cmdline signatures to identify our processes by their command line.
# Match is substring, case-insensitive. Covers both slash styles.
_WATCHDOG_SIGS  = ("watchdog_daemon.py",)
_EXECUTION_SIGS = ("src/main.py", "src\\main.py")


def _find_python_pids_by_cmdline(signatures: tuple[str, ...]) -> list[int]:
    """
    Enumerate python.exe processes and return those whose command line
    contains any of the given signatures (case-insensitive substring).

    Uses WMIC; returns empty list on any error (conservative — caller
    should not mistake "scan failed" for "no duplicates"). Excludes
    this process's own PID.
    """
    pids: list[int] = []
    try:
        r = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get",
             "ProcessId,CommandLine", "/FORMAT:LIST"],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WIN,
        )
        current_cmdline = ""
        current_pid: int | None = None
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("CommandLine="):
                current_cmdline = line[len("CommandLine="):]
            elif line.startswith("ProcessId="):
                try:
                    current_pid = int(line[len("ProcessId="):])
                except ValueError:
                    current_pid = None
                if current_pid and current_pid != os.getpid():
                    cmdline_lower = current_cmdline.lower()
                    for sig in signatures:
                        if sig.lower() in cmdline_lower:
                            pids.append(current_pid)
                            break
                current_cmdline = ""
                current_pid = None
    except Exception as e:
        _log(f"CMDLINE_SCAN_ERROR | sigs={signatures} | {type(e).__name__}: {e}")
    return pids


def watchdog_already_running() -> bool:
    """
    Return True if at least one live watchdog process exists AND we should
    skip spawning a new one.

    Discovery is by command-line scan, not just the PID file, so it detects
    watchdog processes whose PID file is stale or missing. If more than one
    watchdog is found, we log DUPLICATE_WATCHDOG_DETECTED and STILL return
    True — launcher's job is not to kill; stop_burnin + watchdog recovery
    handle that. We return True so no THIRD watchdog gets spawned.
    """
    live_pids = _find_python_pids_by_cmdline(_WATCHDOG_SIGS)
    if len(live_pids) >= 2:
        _log(f"DUPLICATE_WATCHDOG_DETECTED | pids={live_pids} | refusing to spawn more")
        try:
            _telegram(f"[DUPLICATE_WATCHDOG_DETECTED] pids={live_pids} — manual intervention required.")
        except Exception:
            pass
        return True
    if len(live_pids) == 1:
        _log(f"WATCHDOG_ALREADY_RUNNING | pid={live_pids[0]} | skipping")
        return True

    # Scan found nothing. Sanity-check the PID file: if it points at a live
    # pid that the scan missed (unlikely but possible if WMIC was disabled),
    # still honour it rather than spawning a duplicate.
    if WDOG_PID.exists():
        try:
            pid = int(WDOG_PID.read_text(encoding="utf-8").strip())
            if _pid_is_alive(pid):
                _log(f"WATCHDOG_PID_FILE_ALIVE | pid={pid} | scan missed it — skipping")
                return True
        except Exception:
            pass
    return False  # no live watchdog — proceed to spawn


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
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WIN,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _log(f"WATCHDOG_STARTED | pid={proc.pid}")


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------
# Windows timezone name → IANA name mapping (extend as needed)
_WIN_TO_IANA: dict[str, str] = {
    "India Standard Time":          "Asia/Kolkata",
    "UTC":                          "UTC",
    "Greenwich Standard Time":      "Atlantic/Reykjavik",
    "GMT Standard Time":            "Europe/London",
    "Romance Standard Time":        "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest",
    "W. Europe Standard Time":      "Europe/Berlin",
    "Eastern Standard Time":        "America/New_York",
    "Central Standard Time":        "America/Chicago",
    "Mountain Standard Time":       "America/Denver",
    "Pacific Standard Time":        "America/Los_Angeles",
    "AUS Eastern Standard Time":    "Australia/Sydney",
    "Singapore Standard Time":      "Asia/Singapore",
    "China Standard Time":          "Asia/Shanghai",
    "Tokyo Standard Time":          "Asia/Tokyo",
    "Arab Standard Time":           "Asia/Riyadh",
    "Arabian Standard Time":        "Asia/Dubai",
}


def _iana_tz_name() -> str:
    """
    Return the IANA timezone name for the system timezone (e.g. 'Asia/Kolkata').
    Reads the Windows registry TimeZoneKeyName, maps via _WIN_TO_IANA.
    Falls back to the Windows name if unmapped, or UTC offset string on any error.
    """
    try:
        import winreg
        key     = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        )
        win_tz  = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
        winreg.CloseKey(key)
        return _WIN_TO_IANA.get(win_tz, win_tz)   # return Windows name if unmapped
    except Exception:
        # Non-Windows or registry read failure — fall back to UTC offset
        try:
            offset = datetime.now().astimezone().strftime("%z")  # e.g. "+0530"
            return f"UTC{offset}"
        except Exception:
            return "unknown"


# ---------------------------------------------------------------------------
# FX market hours gate
# ---------------------------------------------------------------------------
def _fx_market_open() -> bool:
    """
    FX market is open Mon 00:00 UTC through Fri 22:00 UTC.
    Outside these hours (Fri 22:00 – Sun 22:00 UTC) the launcher does not start
    the watchdog, preventing execution during weekend / holiday market closures.

    OctaFX server time is UTC. Adjust TS_MARKET_TZ env var if broker differs:
      set TS_MARKET_TZ=2   # UTC+2 broker (adds 2h offset)
    """
    tz_offset_h = int(os.environ.get("TS_MARKET_TZ", "0"))
    from datetime import timedelta
    utc_now   = datetime.now(timezone.utc)
    local_now = datetime.now().astimezone()           # system local time with tzinfo
    now       = utc_now + timedelta(hours=tz_offset_h)  # broker time for gate logic

    utc_str   = utc_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    local_str = local_now.strftime("%Y-%m-%dT%H:%M:%S%z")  # e.g. 2026-03-29T15:30:00+0530
    tz_name   = _iana_tz_name()
    ts_ctx    = f"UTC_now={utc_str} | local_now={local_str} | tz={tz_name}"

    weekday   = now.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    hour      = now.hour
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    if weekday == 4 and hour >= 22:
        _log(f"MARKET_GATE | {ts_ctx} | day={day_names[weekday]} | Allowed=NO (Fri after 22:00)")
        return False
    if weekday == 5:
        _log(f"MARKET_GATE | {ts_ctx} | day={day_names[weekday]} | Allowed=NO (Saturday)")
        return False
    if weekday == 6 and hour < 22:
        _log(f"MARKET_GATE | {ts_ctx} | day={day_names[weekday]} | Allowed=NO (Sun before 22:00)")
        return False

    _log(f"MARKET_GATE | {ts_ctx} | day={day_names[weekday]} | Allowed=YES")
    return True


# ---------------------------------------------------------------------------
# Step 5 — Execution process guard + initial start
# ---------------------------------------------------------------------------
def _execution_running() -> bool:
    """
    Return True if at least one execution process is alive AND launcher
    should skip spawning a new one.

    Discovery is by command-line scan (src/main.py) so orphan processes
    whose PID file is stale are still detected. If more than one is found,
    logs DUPLICATE_EXECUTION_DETECTED and still returns True — the launcher
    will not spawn a third; the watchdog's new EARLY_EXIT_ALIVE_AT_RESTART
    path + stop_burnin are the only sanctioned killers.
    """
    live_pids = _find_python_pids_by_cmdline(_EXECUTION_SIGS)
    if len(live_pids) >= 2:
        _log(f"DUPLICATE_EXECUTION_DETECTED | pids={live_pids} | refusing to spawn more")
        try:
            _telegram(f"[DUPLICATE_EXECUTION_DETECTED] pids={live_pids} — manual intervention required.")
        except Exception:
            pass
        return True
    if len(live_pids) == 1:
        return True

    # Scan found nothing. Honour PID file as fallback in case WMIC is disabled.
    if EXEC_PID.exists():
        try:
            pid = int(EXEC_PID.read_text(encoding="utf-8").strip())
            if _pid_is_alive(pid):
                _log(f"EXECUTION_PID_FILE_ALIVE | pid={pid} | scan missed it — skipping")
                return True
        except Exception:
            pass
    return False  # no live execution — proceed to spawn


def _archive_stale_burnin_logs() -> None:
    """Move all existing burnin_*.log files to logs/archive/ before starting a new session.

    Keeps logs/ clean: only the current session's log remains in the active folder.
    Silent on any error — archiving must never block execution start.
    """
    logs_dir   = TS_EXEC_ROOT / "outputs" / "logs"
    archive    = logs_dir / "archive"
    try:
        archive.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in sorted(logs_dir.glob("burnin_*.log")):
            try:
                f.rename(archive / f.name)
                moved += 1
            except Exception:
                pass  # file in use or already moved — skip
        if moved:
            _log(f"BURNIN_LOGS_ARCHIVED | count={moved} | dest=logs/archive/")
    except Exception as e:
        _log(f"ARCHIVE_ERROR | {type(e).__name__}: {e} | continuing")


def start_execution() -> None:
    """Archive stale burnin logs, then launch src/main.py --phase 2 as a detached process."""
    logs_dir = TS_EXEC_ROOT / "outputs" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    _archive_stale_burnin_logs()
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    log_file = logs_dir / f"burnin_{ts}.log"
    _log(f"EXECUTION_START | log={log_file.name}")
    with open(log_file, "w", encoding="utf-8") as f:
        subprocess.Popen(
            [sys.executable, "-u", "src/main.py", "--phase", "2"],
            cwd=str(TS_EXEC_ROOT),
            stdout=f,
            stderr=f,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WIN,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    _log(f"LAUNCHER_START | ts_exec_root={TS_EXEC_ROOT} | watchdog={WATCHDOG_SCRIPT}")

    # Step 0 — Market hours gate (FX: Mon 00:00 – Fri 22:00 UTC)
    if not _fx_market_open():
        _log("LAUNCHER_DONE | reason=market_closed (weekend/holiday)")
        return

    # Step 1 — MT5 process
    if not wait_for_mt5_process():
        _log("LAUNCHER_DONE | reason=mt5_proc_timeout")
        return

    # Step 2 — MT5 API readiness
    if not wait_for_mt5_api():
        _log("LAUNCHER_DONE | reason=mt5_not_ready")
        return

    # Step 3 — Watchdog guard + start
    if watchdog_already_running():
        _log("WATCHDOG_SKIP | already running")
    else:
        # Step 4 — Start watchdog
        start_watchdog()

    # Step 5 — Execution guard + initial start
    # Watchdog handles crash-restarts; launcher handles the initial start each session.
    if _execution_running():
        _log("LAUNCHER_DONE | reason=all_running")
        return

    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()  # 0=Mon … 6=Sun
    if wd == 6 and now_utc.hour >= 22 or wd == 0 and now_utc.hour < 6:
        _log("WEEKEND_RESTART | FX market reopened Sun 22:00 UTC — resuming execution after weekend shutdown")
        _telegram("[WEEKEND_RESTART] FX market reopened — execution resuming.")
    start_execution()
    _log("LAUNCHER_DONE | reason=execution_started")


if __name__ == "__main__":
    main()
