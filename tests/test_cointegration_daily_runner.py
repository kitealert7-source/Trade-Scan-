"""test_cointegration_daily_runner.py — Phase 4 unit tests.

Mocks the three phase main() functions and verifies the orchestrator's
behavior: call order, exit-code propagation, Excel-failure-is-non-fatal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import cointegration_daily_runner


class _Tracker:
    """Records the order phase mocks are called in."""
    def __init__(self):
        self.calls: list[str] = []


@pytest.fixture(autouse=True)
def _patch_log_file(monkeypatch, tmp_path):
    # Without this, every test invocation of cointegration_daily_runner.main()
    # appends to the real production log at tmp/cointegration_daily.log,
    # polluting the v1 stability-burn-in record with synthetic
    # "compute failure" / "render failure" tracebacks emitted by the mocks
    # below. autouse so every test in this module is covered, including
    # the TestArgvPropagation tests that bypass the `tracker` fixture.
    monkeypatch.setattr(cointegration_daily_runner, "LOG_FILE",
                         tmp_path / "cointegration_daily.log")


@pytest.fixture
def tracker(monkeypatch):
    t = _Tracker()

    def make_mock(name: str, rc: int):
        def _mock(argv=None):
            t.calls.append(name)
            return rc
        return _mock

    # Default: all three succeed
    monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main",
                         make_mock("p1", 0))
    monkeypatch.setattr(cointegration_daily_runner.cointegration_db, "main",
                         make_mock("p2", 0))
    monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main",
                         make_mock("p3", 0))
    return t


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:

    def test_all_three_phases_called_in_order(self, tracker):
        rc = cointegration_daily_runner.main([])
        assert rc == 0
        assert tracker.calls == ["p1", "p2", "p3"]

    def test_skip_excel(self, tracker):
        rc = cointegration_daily_runner.main(["--skip-excel"])
        assert rc == 0
        assert tracker.calls == ["p1", "p2"]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestPhase1Failures:

    def test_phase1_nonzero_aborts_with_30(self, tracker, monkeypatch):
        monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main",
                             lambda argv=None: 5)
        rc = cointegration_daily_runner.main([])
        assert rc == 30
        # P2/P3 should NOT have been called
        assert "p2" not in tracker.calls
        assert "p3" not in tracker.calls

    def test_phase1_exception_aborts_with_30(self, tracker, monkeypatch):
        def boom(argv=None):
            raise RuntimeError("compute failure")
        monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main", boom)
        rc = cointegration_daily_runner.main([])
        assert rc == 30


class TestPhase2Failures:

    def test_phase2_nonzero_aborts_with_31(self, tracker, monkeypatch):
        monkeypatch.setattr(cointegration_daily_runner.cointegration_db, "main",
                             lambda argv=None: 7)
        rc = cointegration_daily_runner.main([])
        assert rc == 31
        # P3 should NOT have been called (P2 fatal)
        assert "p3" not in tracker.calls


class TestPhase3FailuresAreNonFatal:
    """Spec §11: Excel failure must NOT block the run — parquet+SQLite stand."""

    def test_phase3_permission_error_returns_0(self, tracker, monkeypatch):
        def locked(argv=None):
            raise PermissionError("[WinError 32] file in use")
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main", locked)
        rc = cointegration_daily_runner.main([])
        assert rc == 0   # overall PASS — Excel skip is acceptable
        # All three were attempted
        assert tracker.calls == ["p1", "p2"]  # p3 raised before append

    def test_phase3_generic_exception_returns_32(self, tracker, monkeypatch):
        # Non-PermissionError exception → exit 32, but parquet+SQLite still valid
        def boom(argv=None):
            raise RuntimeError("render failure")
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main", boom)
        rc = cointegration_daily_runner.main([])
        assert rc == 32

    def test_phase3_nonzero_returns_0_warn(self, tracker, monkeypatch):
        # Non-zero from Excel is non-fatal (operator can re-run)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main",
                             lambda argv=None: 3)
        rc = cointegration_daily_runner.main([])
        assert rc == 0   # non-fatal → overall PASS


# ---------------------------------------------------------------------------
# Argv propagation
# ---------------------------------------------------------------------------


class TestArgvPropagation:

    def test_p2_receives_upsert_flag(self, monkeypatch):
        seen_argv = {}

        def capture(argv=None):
            seen_argv["p2"] = list(argv) if argv else []
            return 0

        monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main",
                             lambda argv=None: 0)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_db, "main", capture)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main",
                             lambda argv=None: 0)
        cointegration_daily_runner.main([])
        assert seen_argv["p2"] == ["--upsert"]

    def test_p3_receives_export_flag(self, monkeypatch):
        seen_argv = {}

        def capture(argv=None):
            seen_argv["p3"] = list(argv) if argv else []
            return 0

        monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main",
                             lambda argv=None: 0)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_db, "main",
                             lambda argv=None: 0)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main", capture)
        cointegration_daily_runner.main([])
        assert seen_argv["p3"] == ["--export"]
