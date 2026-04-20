"""
watchdog_daemon.py — TS_Execution heartbeat monitor and self-healing watchdog.

Responsibilities:
  - Poll heartbeat.log every 60s for liveness
  - SOFT breach (180s stale): log warning only
  - HARD breach (300s stale): kill execution process + restart
  - EARLY_EXIT_DETECTED: PID file exists but process dead → immediate restart
  - DEGRADED: heartbeat OK but no bar processed in 7200s → log warning only
  - Storm guard: max 3 auto-restarts per 10-minute window

Authority boundary (IMPORTANT):
  - watchdog_daemon.py  → RECOVERY ONLY (restart, kill, storm guard)
  - src/main.py          → DETECTION ONLY (alerts: THREAD_DEAD, THREAD_STALE,
                            SILENT_STRATEGY, CONFIG_INTEGRITY_FAIL, etc.)
  - No overlap: main.py never restarts itself. Watchdog never inspects strategy
    logic. Telegram alerts originate from whichever layer detects the issue.

Operational rules:
  1. Start this daemon BEFORE starting src/main.py --phase 2
  2. Only one instance allowed — exits immediately if a live instance already exists

Usage:
  python tools/orchestration/watchdog_daemon.py

  Override ts_execution root path:
  set TS_EXEC_ROOT=C:\\path\\to\\ts_execution && python tools/orchestration/watchdog_daemon.py
"""

import os
import sys
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
BAR_STALL_THRESHOLD_S = 3600   # 1 × H1 interval — heartbeat OK but no bar processed
MAX_RESTARTS          = 3
COOLDOWN_WINDOW_S     = 600    # 10-minute storm guard window

# EARLY_EXIT confirmation gate: number of consecutive polls that must observe
# "pid dead" before EARLY_EXIT_DETECTED fires. Immunizes against transient
# tasklist glitches (single-shot subprocess timeouts/errors) that would
# otherwise spawn an orphan duplicate process alongside a still-alive pid.
# Time cost: EARLY_EXIT_CONFIRMATIONS × POLL_INTERVAL_S extra before real
# crash recovery begins (≈120s at 2 polls × 60s).
EARLY_EXIT_CONFIRMATIONS = 2

# ts_execution root — defaults to sibling directory of Trade_Scan.
# Override with TS_EXEC_ROOT env var if the directory layout differs.
_TRADE_SCAN_ROOT = Path(__file__).resolve().parents[2]
TS_EXEC_ROOT = Path(os.environ.get("TS_EXEC_ROOT", str(_TRADE_SCAN_ROOT.parent / "TS_Execution")))

HB_LOG       = TS_EXEC_ROOT / "outputs" / "logs" / "heartbeat.log"
EXEC_STATE   = TS_EXEC_ROOT / "outputs" / "logs" / "execution_state.json"
EXEC_PID     = TS_EXEC_ROOT / "outputs" / "logs" / "execution.pid"
GUARD_FILE   = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog_guard.json"
WATCHDOG_LOG = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog_daemon.log"
WDOG_PID     = TS_EXEC_ROOT / "outputs" / "logs" / "watchdog.pid"

RESTART_CMD  = ["python", "src/main.py", "--phase", "2"]

# Suppress console windows when spawning child processes from a windowless
# parent (pythonw.exe / Task Scheduler "hidden" context). Without this flag
# every subprocess.run/Popen call that spawns a console-subsystem exe briefly
# flashes a black window on the user's desktop.
_NO_WIN = subprocess.CREATE_NO_WINDOW

# --- Alerts (observer-only, silent on failure) ---
sys.path.insert(0, str(TS_EXEC_ROOT / "src"))
try:
    from alerts import send_alert as _send_alert
except ImportError:
    def _send_alert(event_type: str, message: str) -> None:  # type: ignore[misc]
        pass  # fallback no-op if ts_execution/src not reachable


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    """Append a timestamped line to watchdog_daemon.log and print to stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _rid = _current_run_id() or "NA"
    line = f"{ts} | WATCHDOG | run_id={_rid} | {msg}"
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


def _current_run_id() -> str | None:
    """Read current TS_Execution run_id from execution_state.json if available."""
    try:
        if not EXEC_STATE.exists():
            return None
        with open(EXEC_STATE, encoding="utf-8") as f:
            d = json.load(f)
        rid = d.get("run_id")
        return str(rid) if rid else None
    except Exception:
        return None


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
        return int(EXEC_PID.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_is_alive(pid: int) -> bool:
    """
    Liveness check with fallback. Returns True iff pid is confirmed alive.

    Primary:   tasklist (fast, no extra dep).
    Fallback:  psutil.pid_exists — used when tasklist errors, times out,
               or returns non-zero.
    Unknown:   if BOTH methods fail, returns True (fail-safe ALIVE).
               Better to delay recovery by one poll than to spawn an orphan
               duplicate process on a transient subprocess glitch.
    """
    # --- Primary: tasklist ---
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WIN,
        )
        if r.returncode == 0:
            return str(pid) in r.stdout
        _log(f"PID_CHECK_TASKLIST_RC | pid={pid} | rc={r.returncode} | falling back to psutil")
    except Exception as e:
        _log(f"PID_CHECK_TASKLIST_ERROR | pid={pid} | {type(e).__name__}: {e} | falling back to psutil")

    # --- Fallback: psutil ---
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception as e:
        _log(f"PID_CHECK_PSUTIL_ERROR | pid={pid} | {type(e).__name__}: {e}")

    # --- Both methods failed — fail-safe ALIVE ---
    _log(f"PID_CHECK_UNKNOWN | pid={pid} | assuming alive (fail-safe, skipping EARLY_EXIT this poll)")
    return True


def _kill_pid(pid: int) -> bool:
    """Terminate a process by PID using taskkill /F."""
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WIN,
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
    _send_alert("RESTART_ISSUED", f"count={guard['restart_count']} log={burnin_log.name}")
    with open(burnin_log, "w", encoding="utf-8") as _f:
        subprocess.Popen(
            ["python", "-u"] + RESTART_CMD[1:],  # -u = unbuffered stdout
            cwd=str(TS_EXEC_ROOT),
            stdout=_f,
            stderr=_f,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WIN,
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
            existing = int(WDOG_PID.read_text(encoding="utf-8").strip())
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {existing}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10,
                creationflags=_NO_WIN,
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
def _is_clean_shutdown() -> bool:
    """Check if the engine exited with exit_reason=market_halt.

    When the engine shuts down for market close, it writes exit_reason to
    execution_state.json. The watchdog must respect this — no alerts, no
    restarts, no bar-stall checks after an intentional shutdown.
    """
    if not EXEC_STATE.exists():
        return False
    try:
        with open(EXEC_STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("exit_reason") == "market_halt"
    except Exception:
        return False


def _rotate_log(path: Path) -> None:
    """Rename log to .prev on startup. Never raises."""
    try:
        if path.exists() and path.stat().st_size > 0:
            prev = path.with_suffix(path.suffix + ".prev")
            shutil.move(str(path), str(prev))
    except Exception:
        pass


def run_watchdog_loop() -> None:
    if _check_single_instance():
        return

    # Rotate logs on startup — keep one .prev generation
    _rotate_log(WATCHDOG_LOG)
    _rotate_log(HB_LOG)

    # Post-reboot/startup grace period: suppress EARLY_EXIT restarts while
    # main.py may still be initializing (handles machine reboot races where
    # stale execution.pid from previous run survives on disk).
    EARLY_EXIT_GRACE_S = 90
    _watchdog_start_monotonic = time.monotonic()

    observed_run_id: str | None = None

    # Consecutive-poll counter for EARLY_EXIT confirmation gate.
    # Incremented each poll where (PID file exists AND pid reports dead).
    # Reset on any observation that contradicts that state. Only when the
    # counter reaches EARLY_EXIT_CONFIRMATIONS do we fire the restart.
    _early_exit_strike_count = 0

    _log(
        f"WATCHDOG_DAEMON_STARTED"
        f" | soft={SOFT_THRESHOLD_S}s"
        f" | hard={HARD_THRESHOLD_S}s"
        f" | bar_stall={BAR_STALL_THRESHOLD_S}s"
        f" | poll={POLL_INTERVAL_S}s"
        f" | early_exit_confirmations={EARLY_EXIT_CONFIRMATIONS}"
        f" | ts_exec_root={TS_EXEC_ROOT}"
    )

    while True:
        try:
            # Engine wrote exit_reason=market_halt — skip all checks.
            # No alerts, no restarts. Watchdog stays alive for Monday auto-start
            # but does nothing until execution_state.json is overwritten by a new run.
            if _is_clean_shutdown():
                _log("MARKET_HALT_IDLE | engine shutdown was intentional — skipping all checks")
                time.sleep(POLL_INTERVAL_S)
                continue
            current_run_id = _current_run_id()
            if current_run_id and current_run_id != observed_run_id:
                if observed_run_id:
                    _log(f"RUN_END | observed_switch_from={observed_run_id}")
                observed_run_id = current_run_id
                _log(f"RUN_START | observed_run_id={observed_run_id}")
            elif current_run_id is None and observed_run_id is not None:
                _log(f"RUN_END | observed_run_id={observed_run_id} | execution_state_missing")
                observed_run_id = None

            hb_age  = _get_heartbeat_age()
            bar_age = _get_bar_stall()

            # --- Early exit detection ---
            # If PID file exists but process is dead, this is an abnormal exit
            # (e.g. CONFIG_INTEGRITY_FAIL exit code 78). Restart quickly instead
            # of waiting for heartbeat HARD_THRESHOLD (saves up to 300s blind time).
            #
            # Two safeguards against spawning an orphan duplicate:
            #   1. N-of-M confirmation gate (EARLY_EXIT_CONFIRMATIONS consecutive
            #      polls of "pid dead") so a single tasklist glitch cannot trigger
            #      a restart while the process is actually alive.
            #   2. Belt-and-braces taskkill before restart, guarded by a fresh
            #      liveness check: if the supposedly-dead pid is actually alive
            #      when we go to restart, kill it first so we never run two.
            if EXEC_PID.exists():
                _exit_pid = _read_exec_pid()
                if _exit_pid is not None and not _pid_is_alive(_exit_pid):
                    # Post-reboot guard: during startup grace, a stale PID file
                    # with no heartbeat is almost certainly pre-reboot residue,
                    # not a crash. Main.py may be initializing right now.
                    _uptime = time.monotonic() - _watchdog_start_monotonic
                    if _uptime < EARLY_EXIT_GRACE_S and hb_age is None:
                        _log(f"STALE_PID_IGNORED | pid={_exit_pid} | watchdog_uptime={_uptime:.0f}s < grace={EARLY_EXIT_GRACE_S}s | likely pre-reboot residue — clearing PID file, no restart")
                        try:
                            EXEC_PID.unlink(missing_ok=True)
                        except Exception:
                            pass
                        _early_exit_strike_count = 0
                        time.sleep(POLL_INTERVAL_S)
                        continue

                    # N-of-M confirmation: require N consecutive polls of "dead"
                    # before declaring EARLY_EXIT. Prevents a single tasklist
                    # glitch from spawning an orphan duplicate.
                    _early_exit_strike_count += 1
                    if _early_exit_strike_count < EARLY_EXIT_CONFIRMATIONS:
                        _log(
                            f"EARLY_EXIT_PENDING | pid={_exit_pid}"
                            f" | strike={_early_exit_strike_count}/{EARLY_EXIT_CONFIRMATIONS}"
                            f" | awaiting confirmation before restart"
                        )
                        time.sleep(POLL_INTERVAL_S)
                        continue

                    _log(
                        f"EARLY_EXIT_DETECTED | pid={_exit_pid}"
                        f" | confirmed_across={_early_exit_strike_count}_polls"
                        f" | immediate restart"
                    )
                    _send_alert("EARLY_EXIT_DETECTED",
                        f"pid={_exit_pid} died abnormally "
                        f"(confirmed across {_early_exit_strike_count} polls). Restarting.")

                    # Belt-and-braces force-kill BEFORE spawning a replacement.
                    # If liveness check was a false positive and the pid is
                    # actually alive, we must kill it first or we end up with
                    # two execution processes on the same state files.
                    if _pid_is_alive(_exit_pid):
                        _log(f"EARLY_EXIT_ALIVE_AT_RESTART | pid={_exit_pid} | liveness check flipped — force-killing before spawn")
                        _send_alert("EARLY_EXIT_ALIVE_AT_RESTART",
                            f"pid={_exit_pid} liveness re-check returned ALIVE at restart time. "
                            f"Force-killing before spawning replacement.")
                        killed = _kill_pid(_exit_pid)
                        _log(f"EARLY_EXIT_FORCE_KILL | pid={_exit_pid} | success={killed}")

                    # Clean up stale PID file so restart writes a new one
                    try:
                        EXEC_PID.unlink(missing_ok=True)
                    except Exception:
                        pass
                    _early_exit_strike_count = 0
                    guard = _load_guard()
                    if _check_restart_storm(guard):
                        _log(f"STORM_GUARD_ACTIVE | restart_count={guard.get('restart_count')} | BLOCKED")
                        _send_alert("STORM_GUARD_ACTIVE",
                            f"restart_count={guard.get('restart_count')} in {COOLDOWN_WINDOW_S}s — "
                            f"HALTED. Manual intervention required.")
                    else:
                        _do_restart(guard)
                    time.sleep(POLL_INTERVAL_S)
                    continue
                else:
                    # PID file exists AND pid is alive → reset strike counter.
                    if _early_exit_strike_count > 0:
                        _log(
                            f"EARLY_EXIT_STRIKE_RESET | pid={_exit_pid}"
                            f" | was {_early_exit_strike_count}/{EARLY_EXIT_CONFIRMATIONS}"
                            f" | pid confirmed alive"
                        )
                    _early_exit_strike_count = 0
            else:
                # No PID file → no EARLY_EXIT condition to track.
                _early_exit_strike_count = 0

            # --- Liveness check ---
            if hb_age is None:
                _log("HB_LOG_MISSING | heartbeat.log not found — execution not yet started or path wrong")

            elif hb_age >= HARD_THRESHOLD_S:
                _log(f"HARD_BREACH | hb_age={hb_age:.1f}s | INITIATING RECOVERY")
                _send_alert("HARD_BREACH", f"hb_age={hb_age:.0f}s threshold={HARD_THRESHOLD_S}s")
                guard = _load_guard()
                if _check_restart_storm(guard):
                    _log(
                        f"STORM_GUARD_ACTIVE"
                        f" | restart_count={guard.get('restart_count')}"
                        f" | last_restart={guard.get('last_restart_ts')}"
                        f" | BLOCKED"
                    )
                    _send_alert("STORM_GUARD_ACTIVE",
                        f"restart_count={guard.get('restart_count')} in {COOLDOWN_WINDOW_S}s — "
                        f"HALTED. Manual intervention required.")
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
            # Escalated to HARD action: heartbeat proves process is alive but bar loop
            # is stalled (thread crash, feed hang, or MT5 disconnect not detected).
            _proc_uptime = _get_process_uptime()
            if (
                bar_age is not None
                and bar_age >= BAR_STALL_THRESHOLD_S
                and hb_age is not None
                and hb_age < SOFT_THRESHOLD_S
                and (_proc_uptime is None or _proc_uptime >= 3600)
            ):
                _log(
                    f"BAR_STALL_BREACH | heartbeat OK but no bar processed in {bar_age:.0f}s"
                    f" | threshold={BAR_STALL_THRESHOLD_S}s | INITIATING RECOVERY"
                )
                _send_alert("BAR_STALL_BREACH",
                    f"bar_age={bar_age:.0f}s threshold={BAR_STALL_THRESHOLD_S}s heartbeat_ok")
                guard = _load_guard()
                if _check_restart_storm(guard):
                    _log(
                        f"STORM_GUARD_ACTIVE"
                        f" | restart_count={guard.get('restart_count')}"
                        f" | BLOCKED — manual intervention required"
                    )
                    _send_alert("STORM_GUARD_ACTIVE",
                        f"restart_count={guard.get('restart_count')} in {COOLDOWN_WINDOW_S}s — "
                        f"HALTED. Manual intervention required.")
                else:
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

        except Exception as e:
            _log(f"WATCHDOG_LOOP_ERROR | {type(e).__name__}: {e}")

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    run_watchdog_loop()
