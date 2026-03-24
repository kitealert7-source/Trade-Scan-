"""Process execution helper used by pipeline orchestration."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_command(cmd_list, step_name):
    print(f"\n{'='*40}")
    print(f"[{step_name}] Executing: {' '.join(cmd_list)}")
    print(f"{'='*40}")

    start_time = time.time()
    try:
        subprocess.run(cmd_list, cwd=PROJECT_ROOT, check=True)
        duration = time.time() - start_time
        print(f"[{step_name}] COMPLETED (Time: {duration:.2f}s)")
        return True
    except subprocess.CalledProcessError as e:
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
