"""Regression: the FSP mirrors the backtests/ folder (source of truth).

Locks `filter_strategies._complete_backtests_strategies()` — the membership rule
introduced by the 2026-07-01 source-of-truth reconcile: a strategy is an FSP
candidate IFF its backtests/ folder holds a completed run (an AK_Trade_Report).

Guarantees:
  * complete single-asset run (has a trade report) -> included, regardless of metrics
    (a failed-but-complete run still belongs; promotion gates on candidate_status,
    not on FSP membership);
  * NO_TRADES / raw-only folder (no report) -> excluded;
  * idea-90 cointegration -> excluded (routed to cointegration_sheet -> MPS);
  * incomplete folder (no report) -> excluded;
  * missing backtests/ dir -> empty set (never raises).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.filter_strategies as fs


def _mk(bt, name, *, report=False, no_trades=False):
    d = bt / name
    d.mkdir(parents=True, exist_ok=True)
    if report:
        (d / f"AK_Trade_Report_{name}.xlsx").write_text("x", encoding="utf-8")
    if no_trades:
        raw = d / "raw"
        raw.mkdir(exist_ok=True)
        (raw / "status_no_trades.json").write_text("{}", encoding="utf-8")
    return d


def test_membership_is_completed_single_asset_only(tmp_path, monkeypatch):
    bt = tmp_path / "backtests"
    bt.mkdir()
    _mk(bt, "96_CONT_FX_1D_RSIAVG_TRENDFILT_S01_V1_P00_USDJPY", report=True)          # complete
    _mk(bt, "97_MR_IDX_1D_RSIAVG_TRENDFILT_S01_V1_P00_NAS100", no_trades=True)        # no-trades
    _mk(bt, "90_PORT_AUDJPYCADJPY_15M_COINTREV_V3_X__E1_AUDJPYCADJPY", report=True)   # cointegration
    _mk(bt, "99_X_FX_1D_Y_S01_V1_P00_EURUSD")                                         # incomplete
    monkeypatch.setattr(fs, "BACKTESTS_DIR", bt)
    assert fs._complete_backtests_strategies() == {"96_CONT_FX_1D_RSIAVG_TRENDFILT_S01_V1_P00_USDJPY"}


def test_failed_but_complete_run_is_a_member(tmp_path, monkeypatch):
    # The whole point of the reconcile: a poor-metrics run with a trade report is still
    # a member (it lists in the FSP labeled FAIL) — membership has no quality gate.
    bt = tmp_path / "backtests"
    bt.mkdir()
    _mk(bt, "22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P04_USDCHF", report=True)  # cost mirage, PF<1
    monkeypatch.setattr(fs, "BACKTESTS_DIR", bt)
    assert "22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P04_USDCHF" in fs._complete_backtests_strategies()


def test_missing_backtests_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "BACKTESTS_DIR", tmp_path / "nope")
    assert fs._complete_backtests_strategies() == set()


if __name__ == "__main__":
    import tempfile
    import traceback

    passed = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

    class _MP:  # minimal monkeypatch shim for standalone runs
        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)

        def undo(self):
            for obj, name, val in reversed(self._undo):
                setattr(obj, name, val)

    for t in tests:
        mp = _MP()
        try:
            with tempfile.TemporaryDirectory() as td:
                t(Path(td), mp)
            print(f"[PASS] {t.__name__}")
            passed += 1
        except Exception:
            print(f"[FAIL] {t.__name__}")
            traceback.print_exc()
        finally:
            mp.undo()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
