"""
test_watchdog.py — Validates watchdog_daemon logic against 3 scenarios.

No MT5 required. Simulates execution state by writing heartbeat.log,
execution_state.json, and execution.pid directly.

Usage:
    python tools/orchestration/test_watchdog.py [--scenario 1|2|3]

Scenarios:
    1  Normal       — fresh heartbeat every 60s → expect HEARTBEAT_OK
    2  Kill         — stale heartbeat (>300s)   → expect HARD_BREACH + RESTART_ISSUED
    3  Degraded     — fresh heartbeat, stale bar → expect DEGRADED
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve paths (mirrors watchdog_daemon.py exactly)
# ---------------------------------------------------------------------------
_TRADE_SCAN_ROOT = Path(__file__).resolve().parents[2]
TS_EXEC_ROOT = Path(os.environ.get("TS_EXEC_ROOT", str(_TRADE_SCAN_ROOT.parent / "TS_Execution")))
LOGS_DIR     = TS_EXEC_ROOT / "outputs" / "logs"

HB_LOG     = LOGS_DIR / "heartbeat.log"
EXEC_STATE = LOGS_DIR / "execution_state.json"
EXEC_PID   = LOGS_DIR / "execution.pid"
GUARD_FILE = LOGS_DIR / "watchdog_guard.json"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    # Clear storm guard so restarts are not blocked from a previous test run
    if GUARD_FILE.exists():
        GUARD_FILE.unlink()
    print(f"[TEST] TS_EXEC_ROOT  = {TS_EXEC_ROOT}")
    print(f"[TEST] LOGS_DIR      = {LOGS_DIR}")
    print()


def _write_fresh_heartbeat():
    with open(HB_LOG, "a", encoding="utf-8") as f:
        f.write(f"{_ts()} | HEARTBEAT | uptime=00h00m00s\n")


def _write_stale_heartbeat(age_seconds: int = 400):
    """Write a heartbeat timestamped `age_seconds` ago."""
    stale_epoch = time.time() - age_seconds
    stale_ts = datetime.fromtimestamp(stale_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(HB_LOG, "a", encoding="utf-8") as f:
        f.write(f"{stale_ts} | HEARTBEAT | uptime=01h00m00s\n")


def _write_execution_state(age_seconds: int = 0):
    """Write execution_state.json with last_bar_time offset by age_seconds."""
    tmp = EXEC_STATE.with_suffix(".tmp")
    state = {"last_bar_time": time.time() - age_seconds, "bar_count": 1}
    with open(tmp, "w") as f:
        json.dump(state, f)
    import shutil
    shutil.move(str(tmp), str(EXEC_STATE))


def _write_fake_pid():
    """Write current test process PID so watchdog finds 'a live process'."""
    EXEC_PID.write_text(str(os.getpid()))


def _clear_logs():
    for f in [HB_LOG, EXEC_STATE, EXEC_PID]:
        if f.exists():
            f.unlink()


# ---------------------------------------------------------------------------
# Scenario 1 — Normal
# ---------------------------------------------------------------------------
def scenario_normal(duration_s: int = 200):
    """
    Write a fresh heartbeat every 60s for `duration_s` seconds.
    Run watchdog in parallel and expect only HEARTBEAT_OK.

    Expected watchdog output:
        HEARTBEAT_OK | hb_age=<60s
    """
    print("=" * 60)
    print("SCENARIO 1 — NORMAL (fresh heartbeat every 60s)")
    print(f"Duration: {duration_s}s  |  Watch watchdog_daemon.log for HEARTBEAT_OK")
    print("=" * 60)
    _clear_logs()
    _write_fake_pid()
    _write_execution_state(age_seconds=0)

    start = time.monotonic()
    tick  = 0
    while time.monotonic() - start < duration_s:
        _write_fresh_heartbeat()
        tick += 1
        elapsed = int(time.monotonic() - start)
        print(f"[TEST] tick={tick}  elapsed={elapsed}s  wrote fresh heartbeat → watchdog should show HEARTBEAT_OK")
        time.sleep(60)

    print("[TEST] SCENARIO 1 COMPLETE — check watchdog_daemon.log for HEARTBEAT_OK entries")


# ---------------------------------------------------------------------------
# Scenario 2 — Kill (HARD breach)
# ---------------------------------------------------------------------------
def scenario_kill():
    """
    Write a stale heartbeat (400s old) and a real PID.
    Watchdog should detect HARD_BREACH and issue RESTART_ISSUED.

    NOTE: the restart will attempt `python src/main.py --phase 2` in TS_EXEC_ROOT.
    If MT5 is not running this will fail gracefully (restart attempt still logged).

    Expected watchdog output:
        HARD_BREACH | hb_age=400.xs
        NO_LIVE_PID | pid=<pid> ...   (or KILL_RESULT if process was alive)
        RESTART_ISSUED | count=1
    """
    print("=" * 60)
    print("SCENARIO 2 — KILL (stale heartbeat → HARD_BREACH → restart)")
    print("=" * 60)
    _clear_logs()
    _write_fake_pid()
    _write_stale_heartbeat(age_seconds=400)
    _write_execution_state(age_seconds=400)
    print(f"[TEST] Wrote stale heartbeat (400s old) and execution_state")
    print(f"[TEST] Wrote PID={os.getpid()} to execution.pid")
    print(f"[TEST] Watchdog poll interval is 60s — wait up to 60s for response")
    print(f"[TEST] Expected: HARD_BREACH → KILL_RESULT or NO_LIVE_PID → RESTART_ISSUED")
    print()
    print("[TEST] SCENARIO 2 READY — start watchdog now (or wait for next poll if already running)")


# ---------------------------------------------------------------------------
# Scenario 3 — Degraded
# ---------------------------------------------------------------------------
def scenario_degraded():
    """
    Write a fresh heartbeat (system appears alive) but a stale execution_state
    (no bar processed for 8000s, > BAR_STALL_THRESHOLD_S=7200).

    Expected watchdog output:
        HEARTBEAT_OK | hb_age=<60s
        DEGRADED | heartbeat OK but no bar processed in 8000s | MANUAL REVIEW
    """
    print("=" * 60)
    print("SCENARIO 3 — DEGRADED (alive heartbeat, stale bar)")
    print("=" * 60)
    _clear_logs()
    _write_fake_pid()
    _write_fresh_heartbeat()
    _write_execution_state(age_seconds=8000)   # 8000s > BAR_STALL_THRESHOLD_S (7200s)
    print(f"[TEST] Wrote FRESH heartbeat (watchdog sees system as alive)")
    print(f"[TEST] Wrote execution_state with last_bar_time 8000s ago (> 7200s threshold)")
    print(f"[TEST] Expected: HEARTBEAT_OK + DEGRADED (no auto-restart)")
    print()
    print("[TEST] SCENARIO 3 READY — start watchdog now (or wait for next poll if already running)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Watchdog test harness")
    parser.add_argument(
        "--scenario", type=int, choices=[1, 2, 3], required=True,
        help="1=Normal, 2=Kill, 3=Degraded"
    )
    parser.add_argument(
        "--duration", type=int, default=200,
        help="Duration in seconds for scenario 1 (default: 200)"
    )
    args = parser.parse_args()

    _setup()

    if args.scenario == 1:
        scenario_normal(duration_s=args.duration)
    elif args.scenario == 2:
        scenario_kill()
    elif args.scenario == 3:
        scenario_degraded()


if __name__ == "__main__":
    main()
