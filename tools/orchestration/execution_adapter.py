"""Process execution helper used by pipeline orchestration."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


SUBPROCESS_TIMEOUT_S = 600  # 10-minute hard limit per stage subprocess


def run_command(cmd_list, step_name):
    print(f"\n{'='*40}")
    print(f"[{step_name}] Executing: {' '.join(cmd_list)}")
    print(f"{'='*40}")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd_list,
            cwd=PROJECT_ROOT,
            check=True,
            stderr=subprocess.PIPE,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
        duration = time.time() - start_time
        print(f"[{step_name}] COMPLETED (Time: {duration:.2f}s)")
        return True
    except subprocess.TimeoutExpired as e:
        duration = time.time() - start_time
        print(f"\n[FATAL] {step_name} TIMED OUT after {duration:.0f}s (limit: {SUBPROCESS_TIMEOUT_S}s)")
        raise RuntimeError(
            f"SUBPROCESS_TIMEOUT: {step_name} exceeded {SUBPROCESS_TIMEOUT_S}s limit. "
            f"Possible causes: MT5 hang, infinite loop, or network stall."
        ) from e
    except subprocess.CalledProcessError as e:
        # Always surface the subprocess stderr so exact tracebacks appear in logs.
        if e.stderr:
            print(f"\n[STDERR] {step_name} subprocess output:", file=sys.stderr)
            print("-" * 60, file=sys.stderr)
            print(e.stderr.strip(), file=sys.stderr)
            print("-" * 60, file=sys.stderr)

        if e.returncode == 3:
            # Exit code 3 = XLSX_LOCK_TIMEOUT: Excel held the file and didn't release.
            # Do NOT retry — mark FAILED immediately.
            raise RuntimeError(
                f"XLSX_LOCK_TIMEOUT: {step_name} could not write xlsx — "
                "Excel held the file beyond the timeout. "
                "Close Excel and reset the directive to retry."
            ) from e
        if e.returncode != 2:
            print(f"\n[FATAL] {step_name} FAILED with exit code {e.returncode}")
        raise e
    except Exception as e:
        print(f"\n[FATAL] {step_name} FAILED with error: {e}")
        raise e
