"""test_portfolio_stage_lock.py — Stage-4 FileLock barrier (Phase 2b).

Verifies that PortfolioStage.run() acquires the Master_Portfolio_Sheet
FileLock before invoking the underlying portfolio pipeline, and releases
it cleanly afterwards — including the case where the underlying raises.

These tests guard the contract that ONE directive at a time may enter
Stage 4. The deterministic exclusivity replaces the conceptual role of
the old 15s inter-directive cooldown.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from filelock import FileLock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.orchestration.portfolio_stage import PortfolioStage


def _make_context(directive_id="TEST_DIR_001"):
    return SimpleNamespace(
        directive_id=directive_id,
        directive_config={},
        run_ids=["a" * 24],
        symbols=["EURUSD"],
        project_root=PROJECT_ROOT,
        python_exe=sys.executable,
    )


class TestStage4Lock:

    def test_acquires_lock_before_running_underlying(self, tmp_path, monkeypatch):
        """The lock must be acquired (and the lock file present on disk)
        before run_portfolio_and_post_stages is invoked."""
        # Redirect the lock to tmp_path
        from config import state_paths
        monkeypatch.setattr(state_paths, "STRATEGIES_DIR", tmp_path, raising=True)

        observed_lock_existed = []

        def _fake_run(**kwargs):
            # By the time the underlying runs, the lock file must exist
            observed_lock_existed.append(
                (tmp_path / "Master_Portfolio_Sheet.xlsx").with_suffix(".lock").exists()
            )

        with patch(
            "tools.orchestration.stage_portfolio.run_portfolio_and_post_stages",
            side_effect=_fake_run,
        ):
            PortfolioStage().run(_make_context())

        assert observed_lock_existed == [True], (
            "Stage-4 lock file must exist on disk while run_portfolio_and_post_stages runs"
        )

    def test_lock_released_on_success(self, tmp_path, monkeypatch):
        """After a successful Stage-4 invocation, the lock must be free
        for another acquirer (no orphan hold)."""
        from config import state_paths
        monkeypatch.setattr(state_paths, "STRATEGIES_DIR", tmp_path, raising=True)
        with patch(
            "tools.orchestration.stage_portfolio.run_portfolio_and_post_stages",
            side_effect=lambda **kw: None,
        ):
            PortfolioStage().run(_make_context())

        # Another acquirer should be able to grab the lock immediately
        lock_path = (tmp_path / "Master_Portfolio_Sheet.xlsx").with_suffix(".lock")
        second = FileLock(str(lock_path))
        second.acquire(timeout=1.0)
        second.release()

    def test_lock_released_on_underlying_exception(self, tmp_path, monkeypatch):
        """If run_portfolio_and_post_stages raises, the lock must still be
        released — `acquire_with_stale_warn`'s finally block guarantees
        this. Otherwise a single Stage-4 failure would jam the entire
        pipeline forever."""
        from config import state_paths
        monkeypatch.setattr(state_paths, "STRATEGIES_DIR", tmp_path, raising=True)

        def _boom(**kw):
            raise RuntimeError("simulated stage-4 failure")

        with patch(
            "tools.orchestration.stage_portfolio.run_portfolio_and_post_stages",
            side_effect=_boom,
        ):
            with pytest.raises(RuntimeError, match="simulated stage-4 failure"):
                PortfolioStage().run(_make_context())

        # Lock must be free after the exception unwinds
        lock_path = (tmp_path / "Master_Portfolio_Sheet.xlsx").with_suffix(".lock")
        second = FileLock(str(lock_path))
        second.acquire(timeout=1.0)
        second.release()

    def test_lock_path_co_located_with_protected_resource(self, tmp_path, monkeypatch):
        """The lock file path should be `<MPS_path>.lock` (same directory
        as the protected resource, not in some unrelated scratch dir)."""
        from config import state_paths
        monkeypatch.setattr(state_paths, "STRATEGIES_DIR", tmp_path, raising=True)

        observed_lock_paths = []

        def _capture_lock_path(**kw):
            # Inspect tmp_path to find the lock file
            for p in tmp_path.iterdir():
                if p.suffix == ".lock":
                    observed_lock_paths.append(p)

        with patch(
            "tools.orchestration.stage_portfolio.run_portfolio_and_post_stages",
            side_effect=_capture_lock_path,
        ):
            PortfolioStage().run(_make_context())

        assert len(observed_lock_paths) == 1, (
            f"expected exactly one .lock file in {tmp_path}, found {observed_lock_paths}"
        )
        # Lock file name = Master_Portfolio_Sheet.lock
        assert observed_lock_paths[0].name == "Master_Portfolio_Sheet.lock"
