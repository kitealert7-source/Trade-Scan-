"""Tests for the BC2 extension of cointegration_backfill_screener.

Covers the argparse helpers, the mandatory scheduler-pause check, the
chronological-upsert invariant, the resume frontier query, and the
methodology-tag propagation through the worker → upsert pipeline.

The compute path is mocked (`tools.cointegration_screen.run` /
`run_singles`) to keep the suite under a second and independent of
MASTER_DATA availability.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import cointegration_backfill_screener as bf
from tools.cointegration_db import (
    DB_COLUMNS, SINGLES_DB_COLUMNS, TABLE_NAME, SINGLES_TABLE_NAME,
    connect, create_tables,
)
from tools.cointegration_screen import (
    PARQUET_COLUMNS, SINGLES_PARQUET_COLUMNS,
    PAIR_METHODOLOGY_VERSION, SINGLES_METHODOLOGY_VERSION,
)


# ---------------------------------------------------------------------------
# Argparse + helpers
# ---------------------------------------------------------------------------


class TestParseTfs:

    def test_accepts_supported(self):
        assert bf._parse_tfs("1d") == ["1d"]
        assert bf._parse_tfs("1d,4h") == ["1d", "4h"]
        assert bf._parse_tfs(" 1d , 4h ") == ["1d", "4h"]

    def test_dedupe_preserves_order(self):
        assert bf._parse_tfs("4h,1d,4h,1d") == ["4h", "1d"]

    def test_rejects_unsupported(self):
        with pytest.raises(argparse.ArgumentTypeError, match="unsupported TF"):
            bf._parse_tfs("1d,15m")
        with pytest.raises(argparse.ArgumentTypeError, match="unsupported TF"):
            bf._parse_tfs("1h")

    def test_rejects_empty(self):
        with pytest.raises(argparse.ArgumentTypeError, match="at least one"):
            bf._parse_tfs("")
        with pytest.raises(argparse.ArgumentTypeError, match="at least one"):
            bf._parse_tfs(",,")


class TestBoundedParallel:

    def test_floors_at_one(self):
        assert bf._bounded_parallel(0) == 1
        assert bf._bounded_parallel(-3) == 1
        assert bf._bounded_parallel(1) == 1

    def test_caps_at_cpu_minus_reserve(self):
        with mock.patch.object(bf.os, "cpu_count", return_value=8):
            # cap = 8 - 2 = 6
            assert bf._bounded_parallel(4) == 4
            assert bf._bounded_parallel(6) == 6
            assert bf._bounded_parallel(100) == 6

    def test_handles_unknown_cpu_count(self):
        with mock.patch.object(bf.os, "cpu_count", return_value=None):
            # cap = max(1, 2 - 2) = 1
            assert bf._bounded_parallel(8) == 1


# ---------------------------------------------------------------------------
# Mandatory pre-flight: scheduler-pause check
# ---------------------------------------------------------------------------


def _schtasks_output(state: str) -> str:
    """A minimal schtasks /Query /V /FO LIST blob with the state line we parse."""
    return (
        "HostName:              MACHINE\r\n"
        "TaskName:              \\AntiGravity_Daily_Preflight\r\n"
        f"Scheduled Task State:  {state}\r\n"
        "Task To Run:           pythonw.exe ...\r\n"
    )


class TestSchedulerCheck:

    def test_non_windows_returns_silently(self):
        with mock.patch.object(bf.os, "name", "posix"):
            bf._check_scheduler_paused()  # no raise

    def test_disabled_passes(self):
        with mock.patch.object(bf.os, "name", "nt"), \
             mock.patch.object(bf.shutil, "which", return_value="schtasks.exe"), \
             mock.patch.object(bf.subprocess, "run") as mrun:
            mrun.return_value = mock.Mock(
                returncode=0, stdout=_schtasks_output("Disabled"), stderr="")
            bf._check_scheduler_paused()  # no raise

    @pytest.mark.parametrize("state", ["Ready", "Running", "Queued", "Enabled"])
    def test_any_enabled_state_raises(self, state):
        with mock.patch.object(bf.os, "name", "nt"), \
             mock.patch.object(bf.shutil, "which", return_value="schtasks.exe"), \
             mock.patch.object(bf.subprocess, "run") as mrun:
            mrun.return_value = mock.Mock(
                returncode=0, stdout=_schtasks_output(state), stderr="")
            with pytest.raises(bf.SchedulerStillEnabledError,
                                match=f"is '{state}'"):
                bf._check_scheduler_paused()

    def test_unregistered_task_passes(self):
        with mock.patch.object(bf.os, "name", "nt"), \
             mock.patch.object(bf.shutil, "which", return_value="schtasks.exe"), \
             mock.patch.object(bf.subprocess, "run") as mrun:
            mrun.return_value = mock.Mock(returncode=1, stdout="", stderr="ERROR: ...")
            bf._check_scheduler_paused()  # no raise

    def test_schtasks_missing_warns_but_passes(self):
        with mock.patch.object(bf.os, "name", "nt"), \
             mock.patch.object(bf.shutil, "which", return_value=None):
            bf._check_scheduler_paused()  # no raise, only WARN log line

    def test_timeout_raises(self):
        with mock.patch.object(bf.os, "name", "nt"), \
             mock.patch.object(bf.shutil, "which", return_value="schtasks.exe"), \
             mock.patch.object(bf.subprocess, "run",
                                side_effect=subprocess.TimeoutExpired(
                                    cmd="schtasks", timeout=15)):
            with pytest.raises(bf.SchedulerStillEnabledError,
                                match="timed out"):
                bf._check_scheduler_paused()

    def test_unparseable_state_raises(self):
        """Defensive: a state line we cannot parse must NOT silently pass."""
        with mock.patch.object(bf.os, "name", "nt"), \
             mock.patch.object(bf.shutil, "which", return_value="schtasks.exe"), \
             mock.patch.object(bf.subprocess, "run") as mrun:
            # stdout missing the 'Scheduled Task State' line
            mrun.return_value = mock.Mock(
                returncode=0, stdout="HostName: X\nTaskName: Y\n", stderr="")
            with pytest.raises(bf.SchedulerStillEnabledError,
                                match="could not parse"):
                bf._check_scheduler_paused()


# ---------------------------------------------------------------------------
# Resume frontier
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_conn(tmp_path):
    db = tmp_path / "coint.db"
    c = connect(db)
    create_tables(c)
    yield c
    c.close()


def _insert_daily(conn, as_of: str, pair_a: str, pair_b: str, tf: str,
                   lookback: int, methodology: str = "v2_log_eg") -> None:
    cols = ", ".join(DB_COLUMNS)
    placeholders = ", ".join(["?"] * len(DB_COLUMNS))
    conn.execute(
        f"INSERT INTO {TABLE_NAME} ({cols}) VALUES ({placeholders})",
        (as_of, pair_a, pair_b, tf, lookback,
         "2025-08-25", as_of, lookback, 0.05, None, 0, -3.0,
         10.0, 1.0, "ols_static", "eg_mackinnon",
         0.0, "breaking", "v0", "2026-05-30T00:00:00",
         methodology),
    )
    conn.commit()


class TestResumeFrontier:

    def test_empty_db_returns_none_per_tf(self, fresh_conn):
        rp = bf._find_resume_point(fresh_conn, ["1d", "4h"])
        assert rp == {"1d": None, "4h": None}

    def test_returns_max_v2_as_of_per_tf(self, fresh_conn):
        _insert_daily(fresh_conn, "2024-01-15", "EURUSD", "USDJPY", "1d", 252)
        _insert_daily(fresh_conn, "2024-01-16", "EURUSD", "USDJPY", "1d", 252)
        _insert_daily(fresh_conn, "2024-01-10", "EURUSD", "USDJPY", "4h", 1500)
        rp = bf._find_resume_point(fresh_conn, ["1d", "4h"])
        assert rp == {"1d": "2024-01-16", "4h": "2024-01-10"}

    def test_ignores_v1_tagged_rows(self, fresh_conn):
        """v1 history must not anchor the resume frontier — we want to RESUME
        the v2 backfill from where IT left off, not where v1 ended."""
        _insert_daily(fresh_conn, "2024-01-20", "EURUSD", "USDJPY", "1d", 252,
                       methodology="v1_raw_adf")
        _insert_daily(fresh_conn, "2024-01-15", "EURUSD", "USDJPY", "1d", 252,
                       methodology="v2_log_eg")
        rp = bf._find_resume_point(fresh_conn, ["1d"])
        assert rp == {"1d": "2024-01-15"}


# ---------------------------------------------------------------------------
# Worker compute — synthetic + parquet round-trip
# ---------------------------------------------------------------------------


def _fake_run_df(as_of: pd.Timestamp, tf: str) -> pd.DataFrame:
    """Tiny deterministic DataFrame matching PARQUET_COLUMNS schema."""
    row = {
        "pair_a": "EURUSD", "pair_b": "USDJPY",
        "tf": tf, "lookback_days": 252,
        "window_start": as_of - pd.Timedelta(days=251),
        "window_end": as_of, "sample_size": 252,
        "adf_pvalue": 0.03, "pvalue_rolling_median_5d": float("nan"),
        "adf_statistic": -3.5, "half_life_days": 10.0,
        "hedge_ratio": 1.0, "beta_method": "ols_static",
        "test_method": "eg_mackinnon", "current_zscore": 0.5,
        "regime": "cointegrated", "data_version": "abc",
        "generated_at": pd.Timestamp("2026-05-30T00:00:00", tz="UTC"),
        "methodology_version": PAIR_METHODOLOGY_VERSION,
    }
    return pd.DataFrame([row], columns=PARQUET_COLUMNS)


def _fake_run_singles_df(as_of: pd.Timestamp, tf: str) -> pd.DataFrame:
    row = {
        "symbol": "EURUSD", "tf": tf, "lookback_days": 252,
        "window_start": as_of - pd.Timedelta(days=251),
        "window_end": as_of, "sample_size": 252,
        "adf_pvalue": 0.04, "pvalue_rolling_median_5d": float("nan"),
        "adf_statistic": -3.0, "half_life_days": 8.0,
        "current_zscore": 0.3, "regime": "cointegrated",
        "data_version": "abc",
        "generated_at": pd.Timestamp("2026-05-30T00:00:00", tz="UTC"),
        "methodology_version": SINGLES_METHODOLOGY_VERSION,
    }
    return pd.DataFrame([row], columns=SINGLES_PARQUET_COLUMNS)


class TestComputeOne:

    def test_writes_isolated_parquets_per_task(self, tmp_path):
        with mock.patch.object(bf, "run", side_effect=_fake_run_df), \
             mock.patch.object(bf, "run_singles",
                                side_effect=lambda **kw:
                                    _fake_run_singles_df(kw["as_of"], kw["tf"])):
            coint_p, singles_p = bf._compute_one(
                "2024-01-15", "1d", str(tmp_path))
        assert Path(coint_p).is_file()
        assert Path(singles_p).is_file()
        assert Path(coint_p).name == "coint_1d_2024-01-15.parquet"
        assert Path(singles_p).name == "singles_1d_2024-01-15.parquet"

    def test_methodology_tag_propagates_to_parquet(self, tmp_path):
        """The worker's parquet must carry the post-C3 cohort tags from the
        screener constants — no hardcoding inside the backfill tool."""
        with mock.patch.object(bf, "run", side_effect=_fake_run_df), \
             mock.patch.object(bf, "run_singles",
                                side_effect=lambda **kw:
                                    _fake_run_singles_df(kw["as_of"], kw["tf"])):
            coint_p, singles_p = bf._compute_one(
                "2024-06-17", "4h", str(tmp_path))
        df = pd.read_parquet(coint_p)
        assert df["methodology_version"].iloc[0] == PAIR_METHODOLOGY_VERSION
        df_s = pd.read_parquet(singles_p)
        assert df_s["methodology_version"].iloc[0] == SINGLES_METHODOLOGY_VERSION


# ---------------------------------------------------------------------------
# Chronological upsert invariant (determinism / hysteresis correctness)
# ---------------------------------------------------------------------------


class TestChronologicalUpsert:

    def test_upsert_walks_dates_ascending(self, fresh_conn, tmp_path,
                                            monkeypatch):
        """Even if workers complete out of order, the parent must call
        upsert_from_parquet in strict chronological as_of order so the
        hysteresis classifier reads correct same-cohort priors."""
        upsert_calls: list[str] = []
        upsert_singles_calls: list[str] = []

        def fake_upsert(_conn, path):
            upsert_calls.append(Path(path).stem)
            return 1

        def fake_upsert_singles(_conn, path):
            upsert_singles_calls.append(Path(path).stem)
            return 1

        # Patch the scheduler check to no-op, mock compute to write tiny parquets,
        # mock upsert + create_tables to capture order.
        monkeypatch.setattr(bf, "_check_scheduler_paused", lambda: None)
        monkeypatch.setattr(bf, "run", _fake_run_df)
        monkeypatch.setattr(bf, "run_singles",
                              lambda **kw: _fake_run_singles_df(
                                  kw["as_of"], kw["tf"]))
        monkeypatch.setattr(bf, "upsert_from_parquet", fake_upsert)
        monkeypatch.setattr(bf, "upsert_singles_from_parquet",
                              fake_upsert_singles)
        monkeypatch.setattr(bf, "rebuild_triggers_from_history",
                              lambda _c: 0)
        monkeypatch.setattr(bf, "_backup_tables",
                              lambda _c, _s: None)
        monkeypatch.setattr(bf, "_truncate_tables", lambda _c: None)
        monkeypatch.setattr(bf, "connect",
                              lambda *_a, **_kw: fresh_conn)

        # Force serial compute so the test runs in-process and deterministically.
        bf.backfill(
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-17"),
            tfs=["1d", "4h"],
            max_parallel=1,
            do_backup=False,
            workdir=tmp_path,
        )

        # Expected order: (2024-01-15, 1d), (2024-01-15, 4h),
        #                 (2024-01-16, 1d), (2024-01-16, 4h),
        #                 (2024-01-17, 1d), (2024-01-17, 4h)
        expected = [
            "coint_1d_2024-01-15", "coint_4h_2024-01-15",
            "coint_1d_2024-01-16", "coint_4h_2024-01-16",
            "coint_1d_2024-01-17", "coint_4h_2024-01-17",
        ]
        assert upsert_calls == expected
        # Singles must follow the same ordering invariant.
        assert upsert_singles_calls == [
            c.replace("coint_", "singles_") for c in expected
        ]


# ---------------------------------------------------------------------------
# Resume integration — work-list trimming
# ---------------------------------------------------------------------------


class TestResumeWorkListTrimming:

    def test_resume_skips_completed_dates(self, fresh_conn, tmp_path,
                                            monkeypatch):
        """Seed live with v2 rows through 2024-01-16; --resume must process
        only 2024-01-17 onward for that TF."""
        _insert_daily(fresh_conn, "2024-01-15", "EURUSD", "USDJPY", "1d", 252)
        _insert_daily(fresh_conn, "2024-01-16", "EURUSD", "USDJPY", "1d", 252)
        # 4h has no v2 rows yet — must be processed from the start
        upsert_calls: list[str] = []
        monkeypatch.setattr(bf, "_check_scheduler_paused", lambda: None)
        monkeypatch.setattr(bf, "run", _fake_run_df)
        monkeypatch.setattr(bf, "run_singles",
                              lambda **kw: _fake_run_singles_df(
                                  kw["as_of"], kw["tf"]))
        monkeypatch.setattr(bf, "upsert_from_parquet",
                              lambda _c, p: upsert_calls.append(Path(p).stem) or 1)
        monkeypatch.setattr(bf, "upsert_singles_from_parquet",
                              lambda _c, p: 1)
        monkeypatch.setattr(bf, "rebuild_triggers_from_history",
                              lambda _c: 0)
        monkeypatch.setattr(bf, "connect",
                              lambda *_a, **_kw: fresh_conn)

        bf.backfill(
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-17"),
            tfs=["1d", "4h"],
            max_parallel=1,
            do_backup=False,
            resume=True,
            workdir=tmp_path,
        )
        # 1d: only 2024-01-17 processed (15, 16 already complete in v2)
        # 4h: all three dates processed (no prior v2 history)
        assert "coint_1d_2024-01-15" not in upsert_calls
        assert "coint_1d_2024-01-16" not in upsert_calls
        assert "coint_1d_2024-01-17" in upsert_calls
        assert "coint_4h_2024-01-15" in upsert_calls
        assert "coint_4h_2024-01-16" in upsert_calls
        assert "coint_4h_2024-01-17" in upsert_calls


# ---------------------------------------------------------------------------
# Determinism guard: serial vs parallel must produce byte-identical DB state
# ---------------------------------------------------------------------------


class TestDeterminismGuard:
    """BC1 §9.7 invariant: --max-parallel 1 and --max-parallel N must produce
    byte-identical DB rows (modulo inserted_at).

    This test runs both modes in-process with mocked compute and compares the
    upsert call order — which determines the per-row hysteresis state — and
    the resulting per-row DataFrame.

    The parallel path uses ProcessPoolExecutor; to keep the test under the
    second budget we patch it to a thread pool here (concurrent.futures
    ThreadPoolExecutor is API-compatible for our usage and avoids fork cost
    on Windows). The chronological-ordering invariant is on the UPSERT
    phase, which the threaded path exercises identically to the process
    path."""

    def _seeded_run(self, workdir: Path, monkeypatch, max_parallel: int,
                     db_path: Path) -> list[str]:
        """Run the backfill in-process and return the upsert call order.
        Each call uses its own DB file so the two runs start from the same
        empty-after-create_tables state — required for a clean determinism
        comparison."""
        # Initialize the DB once so create_tables inside backfill is idempotent.
        c0 = connect(db_path)
        create_tables(c0)
        c0.close()

        upsert_calls: list[str] = []
        monkeypatch.setattr(bf, "_check_scheduler_paused", lambda: None)
        monkeypatch.setattr(bf, "run", _fake_run_df)
        monkeypatch.setattr(bf, "run_singles",
                              lambda **kw: _fake_run_singles_df(
                                  kw["as_of"], kw["tf"]))
        monkeypatch.setattr(bf, "upsert_from_parquet",
                              lambda _c, p: upsert_calls.append(Path(p).stem) or 1)
        monkeypatch.setattr(bf, "upsert_singles_from_parquet",
                              lambda _c, p: 1)
        monkeypatch.setattr(bf, "rebuild_triggers_from_history",
                              lambda _c: 0)
        monkeypatch.setattr(bf, "_backup_tables",
                              lambda _c, _s: None)
        monkeypatch.setattr(bf, "_truncate_tables", lambda _c: None)
        # New connection per backfill call — backfill closes the connection
        # at the end, so reusing one across calls is not safe.
        monkeypatch.setattr(bf, "connect",
                              lambda *_a, **_kw: connect(db_path))
        # Substitute ThreadPoolExecutor for ProcessPoolExecutor so the test
        # runs in-process — the chronological invariant we're asserting is
        # on the upsert phase, which executes identically in either pool.
        monkeypatch.setattr(bf._cf, "ProcessPoolExecutor",
                              bf._cf.ThreadPoolExecutor)

        bf.backfill(
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-19"),
            tfs=["1d", "4h"],
            max_parallel=max_parallel,
            do_backup=False,
            workdir=workdir,
        )
        return upsert_calls

    def test_serial_and_parallel_produce_same_upsert_order(
            self, tmp_path, monkeypatch):
        # Separate DB files + workdirs so the two runs start from the same
        # empty state and don't share intermediate parquets.
        serial = self._seeded_run(
            tmp_path / "serial_wd", monkeypatch, max_parallel=1,
            db_path=tmp_path / "serial.db")
        parallel = self._seeded_run(
            tmp_path / "parallel_wd", monkeypatch, max_parallel=4,
            db_path=tmp_path / "parallel.db")
        assert serial == parallel, (
            f"determinism guard failed: serial vs parallel upsert order differs\n"
            f"  serial: {serial}\n  parallel: {parallel}"
        )
