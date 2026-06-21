"""Lock the anti-masking behavior of the governed Stage-1 worker.

Regression guard for the 2026-06-21 governed worker NO_TRADES false-negative: a worker
that exits 0 but produces no Stage-1 data dir must be surfaced as a real FAILED, never
masked as a genuine NO_TRADES (0-trades) outcome.

This locks the decision point (`missing_tradelog_is_silent_failure`) that the Stage-1
registry worker uses when `results_tradelevel.csv` is absent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.orchestration.stage_symbol_execution import missing_tradelog_is_silent_failure


def test_no_data_dir_is_silent_failure_not_no_trades(tmp_path):
    # Fake worker exited 0 but produced nothing: the run dir has no data/ subdir at all.
    run_data_dir = tmp_path / "8930d9ad" / "data"  # never created
    assert missing_tradelog_is_silent_failure(run_data_dir) is True, (
        "exit-0-but-empty worker (no data dir) must classify as SILENT FAILURE -> FAILED, "
        "never a masked NO_TRADES"
    )


def test_data_dir_present_is_genuine_no_trades(tmp_path):
    # Backtest completed (data dir present) but produced no trades -> legitimate NO_TRADES.
    run_data_dir = tmp_path / "abc12345" / "data"
    run_data_dir.mkdir(parents=True)
    assert missing_tradelog_is_silent_failure(run_data_dir) is False, (
        "a completed backtest with a data dir but 0 trades is a genuine NO_TRADES, not FAILED"
    )


def test_accepts_str_path(tmp_path):
    # Callers pass a Path, but lock str acceptance too (defensive).
    missing = str(tmp_path / "nope" / "data")
    assert missing_tradelog_is_silent_failure(missing) is True


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        assert missing_tradelog_is_silent_failure(base / "x" / "data") is True
        (base / "y" / "data").mkdir(parents=True)
        assert missing_tradelog_is_silent_failure(base / "y" / "data") is False
        assert missing_tradelog_is_silent_failure(str(base / "z" / "data")) is True
    print("OK — silent-failure classification locked (FAILED on no-data-dir, NO_TRADES on present-data-dir).")
