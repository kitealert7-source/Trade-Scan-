"""Regression test for the 2026-05-30 BC3 first-attempt failure.

The bug: a Python harness imported tools.cointegration_backfill_screener
and called bf.main() WITHOUT an `if __name__ == "__main__":` guard. On
Windows, ProcessPoolExecutor uses spawn-based worker bootstrap; each
worker re-imports the harness as __main__. With the guard missing, the
unguarded body ran in every worker — each tried to re-execute the full
backfill (backup → truncate → compute), racing on CREATE TABLE backup_
<suffix> until 5 workers failed and BrokenProcessPool aborted the parent.

This test confirms:
  (a) A properly-guarded harness completes cleanly under real ProcessPool
      parallelism (max-parallel=2 exercises the spawn-bootstrap path).
  (b) The unguarded variant fails with a diagnostic signature — so the
      regression-target failure mode is still real and detectable.

Skipped on non-Windows (spawn-bootstrap re-import is Windows-specific;
POSIX fork doesn't re-execute the harness).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Module-level mocks persist across spawn-bootstrap because workers run the
# harness's imports + module-level statements before reaching the guarded
# block. The tmp-DB redirect uses the same mechanism. Compute is mocked so
# the test doesn't touch MASTER_DATA or the production cointegration.db.
_HARNESS_BODY = r"""
import os, sys
from pathlib import Path
sys.path.insert(0, r"__ROOT__")

import pandas as pd
from tools import cointegration_backfill_screener as bf
from tools import cointegration_db as cdb
from tools.cointegration_screen import (
    PARQUET_COLUMNS, SINGLES_PARQUET_COLUMNS,
    PAIR_METHODOLOGY_VERSION, SINGLES_METHODOLOGY_VERSION,
)

TMP_DB = r"__TMP_DB__"


def _fake_run(as_of=None, tf="1d", **kw):
    a = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp("2024-01-15")
    return pd.DataFrame([dict(
        pair_a="EURUSD", pair_b="USDJPY",
        tf=tf, lookback_days=252,
        window_start=a - pd.Timedelta(days=251),
        window_end=a, sample_size=252,
        adf_pvalue=0.05, pvalue_rolling_median_5d=float("nan"),
        adf_statistic=-3.0, half_life_days=10.0,
        hedge_ratio=1.0, beta_method="ols_static",
        test_method="eg_mackinnon", current_zscore=0.0,
        regime="broken", data_version="x",
        generated_at=pd.Timestamp("2026-05-30T00:00:00", tz="UTC"),
        methodology_version=PAIR_METHODOLOGY_VERSION,
    )], columns=PARQUET_COLUMNS)


def _fake_run_singles(as_of=None, tf="1d", **kw):
    a = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp("2024-01-15")
    return pd.DataFrame([dict(
        symbol="EURUSD", tf=tf, lookback_days=252,
        window_start=a - pd.Timedelta(days=251),
        window_end=a, sample_size=252,
        adf_pvalue=0.05, pvalue_rolling_median_5d=float("nan"),
        adf_statistic=-3.0, half_life_days=10.0,
        current_zscore=0.0, regime="broken", data_version="x",
        generated_at=pd.Timestamp("2026-05-30T00:00:00", tz="UTC"),
        methodology_version=SINGLES_METHODOLOGY_VERSION,
    )], columns=SINGLES_PARQUET_COLUMNS)


# Module-level patches: applied in parent AND on every worker re-import.
bf.run = _fake_run
bf.run_singles = _fake_run_singles
bf._check_scheduler_paused = lambda: None

# Re-point connect() to the tmp DB so the harness never touches production.
_orig_connect = cdb.connect


def _tmp_connect(*a, **kw):
    if not a and not kw:
        return _orig_connect(TMP_DB)
    return _orig_connect(*a, **kw)


cdb.connect = _tmp_connect
bf.connect = _tmp_connect

# Initialize the tmp DB so create_tables() inside backfill is idempotent.
_c0 = _orig_connect(TMP_DB)
from tools.cointegration_db import create_tables as _ct
_ct(_c0)
_c0.close()
"""

_MAIN_CALL_LINES = [
    'rc = bf.main(["--start", "2024-01-15", "--end", "2024-01-16",',
    '              "--tfs", "1d", "--max-parallel", "2"])',
    'sys.exit(rc)',
]


def _build_harness(*, guarded: bool, tmp_db: str) -> str:
    body = (_HARNESS_BODY
            .replace("__ROOT__", str(PROJECT_ROOT))
            .replace("__TMP_DB__", tmp_db))
    if guarded:
        indented = "\n".join("    " + line for line in _MAIN_CALL_LINES)
        return body + '\nif __name__ == "__main__":\n' + indented + "\n"
    return body + "\n" + "\n".join(_MAIN_CALL_LINES) + "\n"


@pytest.mark.skipif(sys.platform != "win32",
                    reason="Spawn-bootstrap race is Windows-specific")
def test_guarded_harness_succeeds_under_real_process_pool(tmp_path):
    """The blessed pattern — `if __name__ == '__main__':` around bf.main —
    must run cleanly with --max-parallel 2 (real ProcessPoolExecutor)."""
    harness = tmp_path / "good.py"
    harness.write_text(
        _build_harness(guarded=True, tmp_db=str(tmp_path / "test.db")),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(harness)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"Guarded harness should succeed cleanly.\n"
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "BrokenProcessPool" not in result.stderr, result.stderr
    assert "RuntimeError" not in result.stderr, result.stderr


@pytest.mark.skipif(sys.platform != "win32",
                    reason="Spawn-bootstrap race is Windows-specific")
def test_unguarded_harness_fails_with_diagnostic(tmp_path):
    """Sanity check: the failure mode is still real. Removing the guard
    must NOT silently succeed — Python's multiprocessing main-import
    guard, the BrokenProcessPool fallout, or the backup-table CREATE race
    must surface."""
    harness = tmp_path / "bad.py"
    harness.write_text(
        _build_harness(guarded=False, tmp_db=str(tmp_path / "test.db")),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(harness)],
        capture_output=True, text=True, timeout=120,
    )
    diagnostic_signatures = (
        "BrokenProcessPool",
        "freeze_support",
        "_check_not_importing_main",
        "already exists",
    )
    fingerprint_present = any(s in result.stderr for s in diagnostic_signatures)
    assert result.returncode != 0 or fingerprint_present, (
        f"Unguarded harness unexpectedly succeeded — the spawn-bootstrap "
        f"race should NOT be silent.\nreturncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
