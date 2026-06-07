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
    # Safety: Phase 4 (MPS refresh) writes the REAL Master_Portfolio_Sheet.xlsx
    # via ledger_db.export_mps() + the portfolio formatter. Default EVERY test
    # to a no-op so none ever touches the production MPS; the `tracker` fixture
    # overrides this to record call order, and Phase-4 tests override per-case.
    monkeypatch.setattr(cointegration_daily_runner, "_run_phase4_mps",
                         lambda argv=None: 0)
    # Safety: the post-Phase-2 freshness assertion opens the REAL production
    # cointegration.db. Default EVERY test to a no-op so none reads prod state;
    # the dedicated tests/test_cointegration_freshness_check.py exercises the
    # check directly against a tmp DB. (emit_to_log is non-tracked, so this
    # never perturbs the call-order assertions either.)
    monkeypatch.setattr(
        cointegration_daily_runner.cointegration_freshness_check,
        "emit_to_log", lambda *a, **k: None)


@pytest.fixture
def tracker(monkeypatch):
    t = _Tracker()

    def make_mock(name: str, rc: int):
        def _mock(argv=None):
            t.calls.append(name)
            return rc
        return _mock

    # Default: all four succeed
    monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main",
                         make_mock("p1", 0))
    monkeypatch.setattr(cointegration_daily_runner.cointegration_db, "main",
                         make_mock("p2", 0))
    monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main",
                         make_mock("p3", 0))
    # Phase 4 is a runner-local function (not a module .main), so patch it
    # directly. Records "p4" and succeeds; overrides the autouse no-op.
    monkeypatch.setattr(cointegration_daily_runner, "_run_phase4_mps",
                         make_mock("p4", 0))
    return t


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:

    # Phase 1 fires TWICE per run (1a=1d, 1b=4h) — both invoke
    # cointegration_screen.main, which the tracker records as "p1".
    # Wired 2026-06-06 when 4h was added to the automated cadence.

    def test_all_four_phases_called_in_order(self, tracker):
        rc = cointegration_daily_runner.main([])
        assert rc == 0
        assert tracker.calls == ["p1", "p1", "p2", "p3", "p4"]

    def test_skip_excel_still_runs_mps(self, tracker):
        # --skip-excel skips ONLY the screener render; Phase 4 (MPS) is
        # independent (reads the SQLite from Phase 2) and still runs.
        rc = cointegration_daily_runner.main(["--skip-excel"])
        assert rc == 0
        assert tracker.calls == ["p1", "p1", "p2", "p4"]

    def test_skip_mps_still_runs_excel(self, tracker):
        rc = cointegration_daily_runner.main(["--skip-mps"])
        assert rc == 0
        assert tracker.calls == ["p1", "p1", "p2", "p3"]

    def test_skip_both_renders(self, tracker):
        rc = cointegration_daily_runner.main(["--skip-excel", "--skip-mps"])
        assert rc == 0
        assert tracker.calls == ["p1", "p1", "p2"]


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
        # p3 raised before append; Phase 4 (MPS) is independent and still ran.
        # p1 appears twice — Phase 1a (1d) + Phase 1b (4h).
        assert tracker.calls == ["p1", "p1", "p2", "p4"]

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


class TestPhase4MpsRefreshIsNonFatal:
    """Phase 4 (MPS refresh) mirrors Phase 3 semantics: a locked/failed MPS
    write must not abort the run, and must stay decoupled from Phase 3."""

    def test_phase4_permission_error_returns_0(self, tracker, monkeypatch):
        def locked(argv=None):
            raise PermissionError("[WinError 32] MPS in use")
        monkeypatch.setattr(cointegration_daily_runner, "_run_phase4_mps", locked)
        rc = cointegration_daily_runner.main([])
        assert rc == 0   # MPS lock is a non-fatal deferral
        # p4 raised before append; p1 appears twice (Phase 1a + 1b).
        assert tracker.calls == ["p1", "p1", "p2", "p3"]

    def test_phase4_generic_exception_returns_33(self, tracker, monkeypatch):
        def boom(argv=None):
            raise RuntimeError("export failure")
        monkeypatch.setattr(cointegration_daily_runner, "_run_phase4_mps", boom)
        rc = cointegration_daily_runner.main([])
        assert rc == 33

    def test_phase4_nonzero_returns_0_warn(self, tracker, monkeypatch):
        monkeypatch.setattr(cointegration_daily_runner, "_run_phase4_mps",
                             lambda argv=None: 4)
        rc = cointegration_daily_runner.main([])
        assert rc == 0   # non-fatal → overall PASS

    def test_phase4_runs_even_when_phase3_hard_fails(self, tracker, monkeypatch):
        # Phase 3 hard error must NOT prevent the independent Phase 4 refresh.
        def boom(argv=None):
            raise RuntimeError("render failure")
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main", boom)
        rc = cointegration_daily_runner.main([])
        assert rc == 32                # worst hard exit code surfaces
        assert "p4" in tracker.calls   # but Phase 4 still ran


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

    def test_phase1_invoked_per_tf_in_1d_then_4h_order(self, monkeypatch):
        """Phase 1a fires with --tf 1d, then Phase 1b with --tf 4h.

        Locks in the post-2026-06-06 dual-TF cadence so a future refactor
        that drops 4h (or reverts to a single bare call) trips a test
        rather than silently re-introducing the 10-day 4h staleness gap
        observed 2026-05-29 → 2026-06-06.
        """
        seen_argv: list[list[str]] = []

        def capture(argv=None):
            seen_argv.append(list(argv) if argv else [])
            return 0

        monkeypatch.setattr(cointegration_daily_runner.cointegration_screen, "main", capture)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_db, "main",
                             lambda argv=None: 0)
        monkeypatch.setattr(cointegration_daily_runner.cointegration_excel, "main",
                             lambda argv=None: 0)
        cointegration_daily_runner.main([])
        assert seen_argv == [["--tf", "1d"], ["--tf", "4h"]]
