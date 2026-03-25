"""
watchdog_daemon.py — TS_Execution heartbeat monitor and self-healing watchdog.

Responsibilities:
  - Poll heartbeat.log every 60s for liveness
  - SOFT breach (180s stale): log warning only
  - HARD breach (300s stale): kill execution process + restart
  - DEGRADED: heartbeat OK but no bar processed in 7200s → log warning only
  - Storm guard: max 3 auto-restarts per 10-minute window

Operational rules:
  1. Start this daemon BEFORE starting src/main.py --phase 2
  2. Only one instance allowed — exits immediately if a live instance already exists

Usage:
  python tools/orchestration/watchdog_daemon.py

  Override ts_execution root path:
  set TS_EXEC_ROOT=C:\\path\\to\\ts_execution && python tools/orchestration/watchdog_daemon.py
"""

import os
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
POLL_INTERVAL_S       = 60
SOFT_THRESHOLD_S      = 180    # 3 polls ≈ 2 missed heartbeats → warning only
HARD_THRESHOLD_S      = 300    # 5 polls ≈ 4 missed heartbeats → kill + restart
BAR_STALL_THRESHOLD_S = 7200   # 2 × H1 interval — heartbeat OK but no bar processed
MAX_RESTARTS          = 3
COOLDOWN_WINDOW_S     = 600    # 10-minute storm guard window

# ts_execution root — defaults to sibling directory of Trade_Scan.
# Override with TS_EXEC_ROOT env var if the directory layout differs.
_TRADE_SCAN_ROOT = Path(__file__).resolve().parents[2]
TS_EXEC_ROOT = Path(os.environ.get("TS_EXEC_ROOT", str(_TRADE_SCAN_ROOT.parent / "ts_execution")))

HB_LOG       = TS_EXEC_ROOT / "outputs" / "logs" / "heartbeat.log"
EXEC_STATE   = TS_EXEC_ROOT / "outputs" / "logs" / "execution_state.json"
EXEC_PID     = TS_EXEC_ROOT / "outputs" / "logs" / "execution.pid"
GUARD_FILE   = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog_guard.json"
WATCHDOG_LOG = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog_daemon.log"
WDOG_PID     = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog.pid"

RESTART_CMD  = ["python", "src/main.py", "--phase", "2"]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    """Append a timestamped line to watchdog_daemon.log and print to stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | WATCHDOG | {msg}"
    print(line, flush=True)
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            if WATCHDOG_LOG.exists() and WATCHDOG_LOG.stat().st_size > 5 * 1024 * 1024:
                _lines = WATCHDOG_LOG.read_text(encoding="utf-8").splitlines()
                WATCHDOG_LOG.write_text("\n".join(_lines[-2000:]) + "\n", encoding="utf-8")
        except Exception:
            pass  # rotation failed — append below still runs, mtime still updated
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Heartbeat age
# ---------------------------------------------------------------------------
def _get_heartbeat_age() -> float | None:
    """
    Returns seconds since last heartbeat, or None if heartbeat.log is absent.
    Primary: parse ISO8601 timestamp from last line of heartbeat.log.
    Fallback: file mtime if last-line parse fails.
    """
    if not HB_LOG.exists():
        return None
    mtime = HB_LOG.stat().st_mtime
    try:
        with open(HB_LOG, "rb") as f:
            try:
                f.seek(-512, 2)   # last 512 bytes — no full-file scan
            except OSError:
                f.seek(0)         # file < 512 bytes
            last_line = f.read().decode(errors="ignore").strip().splitlines()[-1]
        ts_str = last_line.split("|")[0].strip()
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        return time.time() - ts
    except Exception:
        return time.time() - mtime   # fallback to mtime


# ---------------------------------------------------------------------------
# Bar stall detection
# ---------------------------------------------------------------------------
def _get_bar_stall() -> float | None:
    """
    Returns seconds since last bar was processed, or None if state file absent.
    Reads execution_state.json written atomically by main.py per-bar callback.
    """
    if not EXEC_STATE.exists():
        return None
    try:
        with open(EXEC_STATE) as f:
            d = json.load(f)
        return time.time() - d["last_bar_time"]
    except Exception:
        return None


def _get_process_uptime() -> float | None:
    """
    Returns seconds since execution process started, or None if state file absent
    or start_time field missing (pre-patch execution_state.json).
    Reads start_time written once by main.py on startup.
    """
    if not EXEC_STATE.exists():
        return None
    try:
        with open(EXEC_STATE) as f:
            d = json.load(f)
        st = d.get("start_time")
        if st is None:
            return None
        return time.time() - st
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Process identification
# ---------------------------------------------------------------------------
def _read_exec_pid() -> int | None:
    """Read PID from execution.pid written by src/main.py on startup."""
    try:
        return int(EXEC_PID.read_text().strip())
    except Exception:
        return None


def _pid_is_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive using tasklist."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        return str(pid) in r.stdout
    except Exception:
        return False


def _kill_pid(pid: int) -> bool:
    """Terminate a process by PID using taskkill /F."""
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=15
        )
        return r.returncode == 0
    except Exception as e:
        _log(f"KILL_ERROR | pid={pid} | {e}")
        return False


# ---------------------------------------------------------------------------
# Storm guard
# ---------------------------------------------------------------------------
def _load_guard() -> dict:
    """Load restart storm guard state. Returns defaults on missing/corrupt file."""
    try:
        with open(GUARD_FILE) as f:
            return json.load(f)
    except Exception:
        return {"restart_count": 0, "last_restart_ts": 0.0}


def _save_guard(guard: dict) -> None:
    """Atomically persist guard state."""
    try:
        GUARD_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = GUARD_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(guard, f)
        shutil.move(str(tmp), str(GUARD_FILE))
    except Exception as e:
        _log(f"GUARD_SAVE_ERROR | {e}")


def _check_restart_storm(guard: dict) -> bool:
    """
    Returns True (BLOCKED) if restart_count >= MAX_RESTARTS within COOLDOWN_WINDOW_S.
    Auto-resets counter if the cooldown window has expired.
    Mutates guard in-place.
    """
    elapsed = time.time() - guard.get("last_restart_ts", 0.0)
    if elapsed > COOLDOWN_WINDOW_S:
        guard["restart_count"] = 0
    return guard.get("restart_count", 0) >= MAX_RESTARTS


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------
def _next_burnin_log() -> Path:
    """Return a datetime-stamped burnin log path in logs/ (active session).
    Format: burnin_YYYY-MM-DD_HHMM.log (UTC restart time).
    Completed sessions are moved to archive/ manually when the session ends.
    """
    logs_dir = TS_EXEC_ROOT / "outputs" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    return logs_dir / f"burnin_{ts}.log"


def _do_restart(guard: dict) -> None:
    """Increment storm counter, save guard, then launch execution as a detached process.

    Stdout is redirected to the next sequential burnin_dayN.log in archive/.
    Uses python -u (unbuffered) so output is flushed to file immediately.
    """
    guard["restart_count"] = guard.get("restart_count", 0) + 1
    guard["last_restart_ts"] = time.time()
    _save_guard(guard)
    burnin_log = _next_burnin_log()
    _log(f"RESTART_ISSUED | count={guard['restart_count']} | log={burnin_log.name} | cmd={RESTART_CMD}")
    with open(burnin_log, "w", encoding="utf-8") as _f:
        subprocess.Popen(
            ["python", "-u"] + RESTART_CMD[1:],  # -u = unbuffered stdout
            cwd=str(TS_EXEC_ROOT),
            stdout=_f,
            stderr=_f,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------
def _check_single_instance() -> bool:
    """
    Returns True if another live watchdog instance is already running.
    Writes own PID to watchdog.pid on success; registers atexit cleanup.
    """
    import atexit
    if WDOG_PID.exists():
        try:
            existing = int(WDOG_PID.read_text().strip())
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {existing}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10
            )
            if str(existing) in r.stdout:
                _log(f"WATCHDOG_ALREADY_RUNNING | pid={existing} | exiting")
                return True
        except Exception:
            pass   # stale pid file — proceed

    WDOG_PID.parent.mkdir(parents=True, exist_ok=True)
    WDOG_PID.write_text(str(os.getpid()))
    atexit.register(lambda: WDOG_PID.unlink(missing_ok=True))
    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_watchdog_loop() -> None:
    if _check_single_instance():
        return

    _log(
        f"WATCHDOG_DAEMON_STARTED"
        f" | soft={SOFT_THRESHOLD_S}s"
        f" | hard={HARD_THRESHOLD_S}s"
        f" | bar_stall={BAR_STALL_THRESHOLD_S}s"
        f" | poll={POLL_INTERVAL_S}s"
        f" | ts_exec_root={TS_EXEC_ROOT}"
    )

    while True:
        try:
            hb_age  = _get_heartbeat_age()
            bar_age = _get_bar_stall()

            # --- Liveness check ---
            if hb_age is None:
                _log("HB_LOG_MISSING | heartbeat.log not found — execution not yet started or path wrong")

            elif hb_age >= HARD_THRESHOLD_S:
                _log(f"HARD_BREACH | hb_age={hb_age:.1f}s | INITIATING RECOVERY")
                guard = _load_guard()
                if _check_restart_storm(guard):
                    _log(
                        f"STORM_GUARD_ACTIVE"
                        f" | restart_count={guard.get('restart_count')}"
                        f" | last_restart={guard.get('last_restart_ts')}"
                        f" | BLOCKED"
                    )
                else:
                    # PID file absent = clean shutdown (atexit deleted it). Do not restart.
                    if not EXEC_PID.exists():
                        _log("CLEAN_SHUTDOWN_DETECTED | execution.pid absent | no restart")
                    else:
                        pid = _read_exec_pid()
                        if pid and _pid_is_alive(pid):
                            killed = _kill_pid(pid)
                            _log(f"KILL_RESULT | pid={pid} | success={killed}")
                        else:
                            _log(f"NO_LIVE_PID | pid={pid} | process may have already exited")
                        _do_restart(guard)

            elif hb_age >= SOFT_THRESHOLD_S:
                _log(f"SOFT_BREACH | hb_age={hb_age:.1f}s | WARNING ONLY")

            else:
                _log(f"HEARTBEAT_OK | hb_age={hb_age:.1f}s")

            # --- Bar stall check (independent of liveness) ---
            _proc_uptime = _get_process_uptime()
            if (
                bar_age is not None
                and bar_age >= BAR_STALL_THRESHOLD_S
                and hb_age is not None
                and hb_age < SOFT_THRESHOLD_S
                and (_proc_uptime is None or _proc_uptime >= 3600)
            ):
                _log(
                    f"DEGRADED | heartbeat OK but no bar processed in {bar_age:.0f}s"
                    f" | expected interval ~3600s | MANUAL REVIEW REQUIRED"
                )

        except Exception as e:
            _log(f"WATCHDOG_LOOP_ERROR | {type(e).__name__}: {e}")

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    run_watchdog_loop()
