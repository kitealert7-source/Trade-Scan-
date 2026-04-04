"""
stop_execution.py — Orchestration wrapper for TS_Execution shutdown.

Delegates the actual stop to TS_Execution/tools/stop_execution.py (canonical),
then adds orchestration concerns: structured logging, weekend detection, Telegram.

Usage:
    python tools/orchestration/stop_execution.py            # stop + log
    python tools/orchestration/stop_execution.py --status   # check running state only

Invoked by Task Scheduler every Friday at market close.
Safe to run multiple times — idempotent.
"""

import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_TRADE_SCAN_ROOT = Path(__file__).resolve().parents[2]
TS_EXEC_ROOT = Path(os.environ.get(
    "TS_EXEC_ROOT",
    str(_TRADE_SCAN_ROOT.parent / "TS_Execution"),
))

# Canonical stop script lives in TS_Execution
_CANONICAL_STOP = TS_EXEC_ROOT / "tools" / "stop_execution.py"

LOGS_DIR = TS_EXEC_ROOT / "outputs" / "logs"
STOP_LOG = LOGS_DIR / "stop_execution.log"


def _log(msg: str) -> None:
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | STOP | {msg}"
    print(line, flush=True)
    try:
        STOP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(STOP_LOG, "a", encoding="utf-8") as f:
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


def main() -> int:
    if "--status" in sys.argv:
        # Delegate --status to canonical tool
        r = subprocess.run([sys.executable, str(_CANONICAL_STOP)], timeout=30)
        return r.returncode

    _log(f"STOP_REQUESTED | ts_exec_root={TS_EXEC_ROOT}")

    # Delegate to canonical TS_Execution stop tool (kills processes, cleans
    # PID files, orphaned .tmp, __pycache__, archives burnin logs)
    exit_code = 0
    try:
        r = subprocess.run(
            [sys.executable, str(_CANONICAL_STOP), "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        exit_code = r.returncode
        _log(f"CANONICAL_STOP | exit_code={exit_code}")
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                _log(f"  {line}")
    except Exception as e:
        _log(f"CANONICAL_STOP_ERROR | {type(e).__name__}: {e}")
        exit_code = 1

    _log("STOP_COMPLETE | delegated to TS_Execution/tools/stop_execution.py")
    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    if wd == 4 and now_utc.hour >= 21 or wd in (5, 6):
        _log("WEEKEND_SHUTDOWN | FX market closed Fri 22:00 UTC — execution stopped until Mon 00:00 UTC (market gate in startup_launcher will auto-restart)")
        _telegram("[WEEKEND_SHUTDOWN] Execution stopped — FX market closed. Auto-restart Mon 00:00 UTC.")
    _log("WATCHDOG will see CLEAN_SHUTDOWN_DETECTED on next poll — no auto-restart")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
