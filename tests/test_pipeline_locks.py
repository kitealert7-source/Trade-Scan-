"""test_pipeline_locks.py — file-lock helper with stale-wait warnings.

Covers the contract that pipeline_locks.acquire_with_stale_warn():
  * acquires + releases the underlying FileLock cleanly
  * yields lock_wait_ms (non-negative int)
  * emits telemetry events if a writer is passed
  * surfaces 60s stale-wait warning + telemetry without raising
  * hard-fails after the timeout (FileLockTimeout)
  * releases the lock even if the body raises

Cross-process behavior verified via subprocess fixture so the test
exercises the real OS file-lock guarantee (not just the in-process
counter).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

import pytest
from filelock import FileLock, Timeout as FileLockTimeout

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_locks import acquire_with_stale_warn


class _RecordingTelemetry:
    """Captures emitted barrier events for assertion."""
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit_barrier_wait_start(self, directive_id, stage_id, lock_name):
        self.events.append({
            "event": "barrier_wait_start",
            "directive_id": directive_id, "stage_id": stage_id, "lock_name": lock_name,
        })

    def emit_barrier_acquired(self, directive_id, stage_id, lock_name, lock_wait_ms):
        self.events.append({
            "event": "barrier_acquired",
            "directive_id": directive_id, "stage_id": stage_id, "lock_name": lock_name,
            "lock_wait_ms": lock_wait_ms,
        })

    def emit_barrier_released(self, directive_id, stage_id, lock_name):
        self.events.append({
            "event": "barrier_released",
            "directive_id": directive_id, "stage_id": stage_id, "lock_name": lock_name,
        })

    def emit_barrier_wait_stale(self, directive_id, stage_id, lock_name, elapsed_ms):
        self.events.append({
            "event": "barrier_wait_stale",
            "directive_id": directive_id, "stage_id": stage_id, "lock_name": lock_name,
            "elapsed_ms": elapsed_ms,
        })


class TestAcquireWithStaleWarn:

    def test_clean_acquire_release(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with acquire_with_stale_warn(lock_file, lock_name="test_lock") as wait_ms:
            assert isinstance(wait_ms, int)
            assert wait_ms >= 0
        # Lock file may still exist but unlocked — acquire again should succeed
        with acquire_with_stale_warn(lock_file, lock_name="test_lock"):
            pass

    def test_emits_telemetry_events(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        rec = _RecordingTelemetry()
        with acquire_with_stale_warn(
            lock_file, lock_name="my_lock",
            telemetry=rec,
            directive_id="DIR_001", stage_id="STAGE_TEST",
        ):
            pass
        events = [e["event"] for e in rec.events]
        assert events == ["barrier_wait_start", "barrier_acquired", "barrier_released"]
        # Check fields on the acquired event
        acq = next(e for e in rec.events if e["event"] == "barrier_acquired")
        assert acq["directive_id"] == "DIR_001"
        assert acq["stage_id"] == "STAGE_TEST"
        assert acq["lock_name"] == "my_lock"
        assert isinstance(acq["lock_wait_ms"], int)

    def test_releases_lock_on_exception(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with pytest.raises(RuntimeError, match="boom"):
            with acquire_with_stale_warn(lock_file, lock_name="x"):
                raise RuntimeError("boom")
        # Re-acquiring should succeed — lock was released
        with acquire_with_stale_warn(lock_file, lock_name="x"):
            pass

    def test_timeout_raises_filelocktimeout(self, tmp_path):
        """Hold the lock from one thread, second acquire must time out."""
        lock_file = tmp_path / "test.lock"
        hold = FileLock(str(lock_file))
        hold.acquire()
        try:
            with pytest.raises(FileLockTimeout, match="lock timeout"):
                with acquire_with_stale_warn(
                    lock_file, lock_name="x",
                    timeout_s=2.0,                # 2-second hard timeout
                    warn_after_s=10.0,            # warn threshold > timeout: ensure no warn fires
                    poll_interval_s=0.2,
                ):
                    pytest.fail("acquire should have timed out, not entered the body")
        finally:
            hold.release()

    def test_stale_warn_fires_without_raising(self, tmp_path, capsys):
        """Holder (subprocess) releases after ~2s; acquirer's warn threshold
        is 0.5s. Expect: stale-warn event AND telemetry, then successful
        acquire. Uses a subprocess (not a thread) for the holder — Windows
        FileLock + GIL interaction makes thread-based hold/release flaky.
        """
        lock_file = tmp_path / "test.lock"
        sentinel = tmp_path / "sentinel.txt"
        rec = _RecordingTelemetry()

        holder_code = (
            "from filelock import FileLock; from pathlib import Path; import time\n"
            f"lf = Path(r'{lock_file}')\n"
            f"sent = Path(r'{sentinel}')\n"
            "lock = FileLock(str(lf))\n"
            "lock.acquire()\n"
            "sent.write_text('held', encoding='utf-8')\n"
            "time.sleep(2.0)\n"
            "lock.release()\n"
        )
        holder = subprocess.Popen([sys.executable, "-c", holder_code])
        # Wait for subprocess to actually hold the lock before we attempt to acquire
        for _ in range(50):
            if sentinel.exists():
                break
            time.sleep(0.05)
        else:
            holder.kill()
            pytest.fail("subprocess holder never acquired the lock")

        with acquire_with_stale_warn(
            lock_file, lock_name="slow_lock",
            timeout_s=10.0,
            warn_after_s=0.5,
            poll_interval_s=0.2,
            telemetry=rec,
        ):
            pass
        holder.wait(timeout=5)

        events = [e["event"] for e in rec.events]
        assert "barrier_wait_stale" in events, f"expected stale-warn event in {events}"
        assert "barrier_acquired" in events
        # The stale-warn must come before the acquire
        stale_idx = events.index("barrier_wait_stale")
        acq_idx = events.index("barrier_acquired")
        assert stale_idx < acq_idx

        # Stdout carries the human-readable warning
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_cross_process_exclusion(self, tmp_path):
        """Real OS-level lock — second process must block while first holds."""
        lock_file = tmp_path / "cross.lock"
        sentinel = tmp_path / "sentinel.txt"

        # Subprocess holds the lock and writes a sentinel
        holder_code = (
            "import sys; from filelock import FileLock; from pathlib import Path; "
            "import time\n"
            f"lf = Path(r'{lock_file}')\n"
            f"sent = Path(r'{sentinel}')\n"
            "lock = FileLock(str(lf))\n"
            "lock.acquire()\n"
            "sent.write_text('held', encoding='utf-8')\n"
            "time.sleep(1.5)\n"
            "lock.release()\n"
        )
        holder = subprocess.Popen([sys.executable, "-c", holder_code])

        # Wait for holder to actually hold the lock
        for _ in range(50):
            if sentinel.exists():
                break
            time.sleep(0.05)
        else:
            holder.kill()
            pytest.fail("subprocess never acquired the lock")

        # Now try to acquire from this process — should wait until holder releases
        start = time.monotonic()
        with acquire_with_stale_warn(
            lock_file, lock_name="cross_lock",
            timeout_s=10.0,
            warn_after_s=5.0,
            poll_interval_s=0.2,
        ) as wait_ms:
            elapsed = time.monotonic() - start
            assert elapsed >= 0.5, f"acquire returned suspiciously fast ({elapsed:.2f}s) — was the lock honored?"
            assert wait_ms >= 500, f"reported lock_wait_ms={wait_ms} but actual wait was {elapsed*1000:.0f}ms"
        holder.wait(timeout=5)
