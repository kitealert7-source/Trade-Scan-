"""producer_rate_telemetry.py — measure-only MT5 call telemetry for the live
basket producer.

Emits the SAME ``MT5_RATE_LIMIT`` line format the TS_Execution shim emits, so the
account-level aggregator parses producer and shim telemetry with one regex. The
producer is ungated (a read-only signal generator), so the gating fields
(delays/bypasses/cap_hits) are always 0 — truthful, and it makes the line
format-identical.

MEASURE-ONLY CONTRACT: record() appends a timestamp and returns. There is NO
gating, NO sleeping, NO throttling, and NO change to any MT5 call or its result.
This module cannot alter producer behaviour — it only counts.

(Self-contained by design: the bridge contract forbids importing TS_Execution
code into Trade_Scan, so the counter logic mirrors src/account_rate.RateCounter.)
"""
from __future__ import annotations

import datetime as _dt
import threading
import time
from collections import deque

_WINDOW_S = 60.0


class _Counter:
    def __init__(self, window_s: float = _WINDOW_S) -> None:
        self.window_s = window_s
        self._stamps: deque[float] = deque()
        self._by: dict[str, int] = {}
        self._total = 0
        self._peak = 0
        self._created = time.monotonic()
        self._lock = threading.Lock()

    def record(self, name: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._stamps.append(now)
            self._total += 1
            self._by[name] = self._by.get(name, 0) + 1
            cut = now - self.window_s
            while self._stamps and self._stamps[0] < cut:
                self._stamps.popleft()
            if len(self._stamps) > self._peak:
                self._peak = len(self._stamps)

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            cut = now - self.window_s
            while self._stamps and self._stamps[0] < cut:
                self._stamps.popleft()
            up = max(1e-9, now - self._created)
            win = up / self.window_s
            return {
                "active_rate": len(self._stamps),
                "peak_rate": self._peak,
                "avg_rate": self._total / win if win > 0 else 0.0,
                "total_calls": self._total,
                "by_func": dict(self._by),
            }


_COUNTER = _Counter()
_started = False
_start_lock = threading.Lock()


def record(name: str = "copy_rates_from_pos") -> None:
    """Count one MT5 call. Measure-only — never blocks, never alters flow."""
    _COUNTER.record(name)


def snapshot() -> dict:
    return _COUNTER.snapshot()


def _format_line(snap: dict, max_calls: int = 24) -> str:
    ts = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    top = sorted(snap["by_func"].items(), key=lambda kv: -int(kv[1]))[:5]
    tops = ",".join(f"{k}:{int(v)}" for k, v in top) or "none"
    return (f"{ts} | MT5_RATE_LIMIT"
            f" | active={int(snap['active_rate'])}/{max_calls}"
            f" | window=60s"
            f" | total_calls={int(snap['total_calls'])}"
            f" | delays=0 | bypasses=0 (0/0 in window) | cap_hits=0"
            f" | avg_wait_ms=0 | max_wait_ms=0"
            f" | gated=0"
            f" | top=[{tops}]")


def start_telemetry(basket: str, interval_s: float = _WINDOW_S) -> None:
    """Start the periodic (60s) telemetry emitter as a daemon thread. Idempotent.

    Prints the MT5_RATE_LIMIT line to stdout (→ producer.log via the supervisor's
    redirect). Never raises into the producer loop.
    """
    global _started
    with _start_lock:
        if _started:
            return
        _started = True

    def _writer() -> None:
        while True:
            time.sleep(interval_s)
            try:
                print(f"  {_format_line(_COUNTER.snapshot())}", flush=True)
            except Exception:
                pass

    threading.Thread(target=_writer, daemon=True,
                     name="producer_rate_telemetry").start()
    try:
        print(f"  PRODUCER_RATE_TELEMETRY_STARTED basket={basket} "
              f"interval={int(interval_s)}s (measure-only, ungated)", flush=True)
    except Exception:
        pass
