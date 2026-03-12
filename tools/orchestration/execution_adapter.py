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
        if e.returncode != 2:
            print(f"\n[FATAL] {step_name} FAILED with exit code {e.returncode}")
        raise e
    except Exception as e:
        print(f"\n[FATAL] {step_name} FAILED with error: {e}")
        raise e
