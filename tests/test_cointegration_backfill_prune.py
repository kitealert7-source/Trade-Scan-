"""The cointegration backfill screener prunes its own old tmp/backfill_* workdirs
(housekeeping at the source) — addresses the parquet accumulation in tmp/ that the
boot+4h screener cadence left uncleaned (500+ dirs / 3000+ parquet by 2026-06-30).

Contract locked here: only the `backfill_*` glob is touched, only when older than the
retention window; recent/in-flight runs and non-backfill tmp/ contents are preserved.
"""
import os
import time
from pathlib import Path

from tools.cointegration_backfill_screener import _prune_old_backfill_workdirs


def _aged_dir(parent: Path, name: str, age_days: float) -> Path:
    d = parent / name
    d.mkdir()
    (d / "coint_1d.parquet").write_text("x", encoding="utf-8")
    t = time.time() - age_days * 86400
    os.utime(d, (t, t))
    return d


def test_prunes_old_keeps_recent_and_non_backfill(tmp_path):
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    old = _aged_dir(tmp_root, "backfill_20260101T000000Z", age_days=30)
    recent = _aged_dir(tmp_root, "backfill_20260630T000000Z", age_days=1)
    non_backfill = _aged_dir(tmp_root, "test_guardrails", age_days=30)  # different prefix
    stray_log = tmp_root / "cointegration_daily.log"
    stray_log.write_text("log", encoding="utf-8")
    os.utime(stray_log, (time.time() - 30 * 86400, time.time() - 30 * 86400))

    removed = _prune_old_backfill_workdirs(tmp_root, retention_days=7)

    assert removed == 1
    assert not old.exists(), "old backfill_* must be pruned"
    assert recent.exists(), "recent backfill_* must be kept"
    assert non_backfill.exists(), "non-backfill dirs must NOT be touched"
    assert stray_log.exists(), "stray non-backfill files must NOT be touched"


def test_missing_tmp_root_is_noop(tmp_path):
    assert _prune_old_backfill_workdirs(tmp_path / "does_not_exist") == 0


def test_negative_retention_is_noop(tmp_path):
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    _aged_dir(tmp_root, "backfill_20250101T000000Z", age_days=999)
    assert _prune_old_backfill_workdirs(tmp_root, retention_days=-1) == 0
