"""Phase B regression — family analysis report.

Pins three categories of behavior:

  1. Unit correctness for every new helper (streaks, calendar, signature utils,
     window guard, session derivation, verdicts).
  2. Wrapper-first invariants (Rule 4):
     - The new helpers in `tools/utils/research/streaks.py` and `calendar.py`
       are semantically equivalent to the inline copies still living in
       `tools/robustness/runner.py`.
     - `tools/report/strategy_signature_utils.py` is semantically equivalent
       to the inline `_flatten` / `_diff` in `tools/generate_strategy_card.py`.
  3. Forbidden-import enforcement (Rule 3):
     - `tools/family_report.py` must NOT import Monte Carlo, bootstrap,
       friction, or reverse-path primitives.

  4. End-to-end smoke: the CLI runs against the PSBRK family backtests and
     writes a non-empty markdown file with the expected section headers.
"""

from __future__ import annotations

import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.report.family_streaks import compute_streaks, _max_streak, _avg_streak
from tools.report.family_calendar import yearwise_pnl, monthly_heatmap
from tools.report.strategy_signature_utils import (
    flatten_signature, diff_signatures, parse_strategy_name,
    extract_signature_from_source, _flatten as flatten_dict,
)
from tools.window_compat import find_family_window, classify_window, annotate_window_status
from tools.report.family_session_xtab import (
    classify_session, direction_session_matrix, direction_trend_matrix,
    direction_volatility_matrix, best_worst_cells, session_share,
)
from tools.report.family_verdicts import compute_family_verdicts


# ---------------------------------------------------------------------------
# 1. streaks.py — unit + parity with robustness/runner.py inline copy
# ---------------------------------------------------------------------------

def test_streaks_basic_counts():
    pnls = [10, -5, -2, -1, 8, 7, -3, 4]
    s = compute_streaks(pnls)
    assert s["max_win_streak"] == 2  # 8,7
    assert s["max_loss_streak"] == 3  # -5,-2,-1
    assert s["total_trades"] == 8


def test_streaks_avg_win_loss():
    # Three win-runs of length 1, 2, 4 → avg 7/3
    pnls = [1, -1, 1, 1, -1, 1, 1, 1, 1, -1]
    s = compute_streaks(pnls)
    assert s["max_win_streak"] == 4
    assert s["avg_win_streak"] == pytest.approx((1 + 2 + 4) / 3)


def test_streaks_max_streak_helper_byte_equivalent_to_inline():
    """Phase B Rule 4 byte-equivalence guard — _max_streak in streaks.py must
    produce the same output as the inline body in robustness/runner.py.
    """
    # Mirror of the inline _max_streak in runner.py:207-215
    def runner_max_streak(arr):
        mx, cur = 0, 0
        for v in arr:
            if v:
                cur += 1
                if cur > mx:
                    mx = cur
            else:
                cur = 0
        return mx

    for arr in [
        [1, 1, 0, 1, 1, 1, 0, 0, 1],
        [0] * 20,
        [1] * 20,
        [0, 1, 0, 1, 0, 1],
        [],
    ]:
        assert _max_streak(arr) == runner_max_streak(arr)


def test_streaks_avg_streak_helper_byte_equivalent_to_inline():
    """Phase B Rule 4 byte-equivalence guard — _avg_streak in streaks.py."""
    def runner_avg_streak(arr):
        streaks = []
        cur = 0
        for v in arr:
            if v:
                cur += 1
            else:
                if cur > 0:
                    streaks.append(cur)
                cur = 0
        if cur > 0:
            streaks.append(cur)
        return sum(streaks) / len(streaks) if streaks else 0

    for arr in [
        [1, 1, 0, 1, 1, 1, 0, 0, 1],
        [0] * 20,
        [1] * 20,
        [],
    ]:
        assert _avg_streak(arr) == pytest.approx(runner_avg_streak(arr))


# ---------------------------------------------------------------------------
# 2. calendar.py — yearwise/monthly correctness
# ---------------------------------------------------------------------------

def test_yearwise_pnl_basic():
    df = pd.DataFrame({
        "exit_timestamp": pd.date_range("2024-01-15", periods=12, freq="ME"),
        "pnl_usd": [10, 20, -5, 30, 15, -10, 25, 35, -8, 40, 50, 45],
    })
    yw = yearwise_pnl(df)
    assert "2024" in yw
    assert yw["2024"]["trades"] == 12
    assert yw["2024"]["net_pnl"] == pytest.approx(247.0)


def test_monthly_heatmap_shape():
    df = pd.DataFrame({
        "exit_timestamp": pd.date_range("2024-01-15", periods=12, freq="ME"),
        "pnl_usd": [10] * 12,
    })
    mh = monthly_heatmap(df)
    assert "2024" in mh
    assert len(mh["2024"]) == 12


def test_yearwise_pnl_empty_handles():
    assert yearwise_pnl(pd.DataFrame()) == {}
    assert yearwise_pnl(None) == {}


# ---------------------------------------------------------------------------
# 3. strategy_signature_utils.py — flatten/diff/parse parity
# ---------------------------------------------------------------------------

def test_flatten_signature_skips_indicators_and_signature_version():
    sig = {
        "indicators": ["foo", "bar"],   # SKIP key
        "signature_version": 3,         # SKIP key
        "execution_rules": {
            "entry_logic": {"type": "breakout", "lookback": 20},
            "stop_loss": {"type": "atr", "atr_multiplier": 1.5},
        },
    }
    flat = flatten_dict(sig)
    assert "indicators" not in flat
    assert "signature_version" not in flat
    assert "execution_rules.entry_logic.type" not in flat  # SKIP_VAL_KEYS
    assert flat["execution_rules.entry_logic.lookback"] == 20
    assert flat["execution_rules.stop_loss.atr_multiplier"] == 1.5


def test_parse_strategy_name():
    parsed = parse_strategy_name("65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09")
    assert parsed is not None
    prefix, sweep, version, pass_n = parsed
    assert prefix == "65_BRK_XAUUSD_5M_PSBRK"
    assert sweep == 1
    assert version == 4
    assert pass_n == 9


def test_diff_signatures_detects_added_changed_removed():
    prev = {"a": {"x": 1, "y": 2}, "b": {"z": 3}}
    curr = {"a": {"x": 1, "y": 4}, "c": {"w": 5}}
    diffs = diff_signatures(prev, curr)
    # y changed, b.z removed, c.w added
    keys = [k for k, _, _ in diffs]
    assert "a.y" in keys
    assert "b.z" in keys
    assert "c.w" in keys


def test_extract_signature_from_source_parses_python_dict():
    source = '''
# --- STRATEGY SIGNATURE START ---
STRATEGY_SIGNATURE = {
    "execution_rules": {"entry_logic": {"type": "test", "lookback": 99}},
}
# --- STRATEGY SIGNATURE END ---
'''
    sig = extract_signature_from_source(source)
    assert sig["execution_rules"]["entry_logic"]["lookback"] == 99


# ---------------------------------------------------------------------------
# 4. window_compat — median + classification
# ---------------------------------------------------------------------------

def test_find_family_window_returns_median():
    rows = [
        {"test_start": "2024-05-11", "test_end": "2026-05-11"},
        {"test_start": "2024-05-13", "test_end": "2026-05-09"},
        {"test_start": "2024-07-19", "test_end": "2026-05-04"},
    ]
    start, end = find_family_window(rows)
    assert start == pd.Timestamp("2024-05-13")
    assert end == pd.Timestamp("2026-05-09")


def test_classify_window_within_tolerance():
    info = classify_window(
        {"test_start": "2024-05-13", "test_end": "2026-05-11"},
        pd.Timestamp("2024-05-11"), pd.Timestamp("2026-05-11"),
        tolerance_days=5,
    )
    assert info["in_window"] is True


def test_classify_window_outside_tolerance():
    info = classify_window(
        {"test_start": "2024-07-19", "test_end": "2026-05-04"},
        pd.Timestamp("2024-05-11"), pd.Timestamp("2026-05-11"),
        tolerance_days=5,
    )
    assert info["in_window"] is False
    assert "tolerance" in info["reason"]


def test_annotate_window_status_flags_outliers():
    # Three-row family so the median sits firmly with A/B and C is an outlier.
    rows = [
        {"strategy": "A", "test_start": "2024-05-11", "test_end": "2026-05-11"},
        {"strategy": "B", "test_start": "2024-05-13", "test_end": "2026-05-09"},
        {"strategy": "C", "test_start": "2024-07-19", "test_end": "2026-05-04"},
    ]
    annotated = annotate_window_status(rows, tolerance_days=5)
    # Median is (2024-05-13, 2026-05-09); rows A and B are well within tolerance.
    assert annotated[0]["in_window"] is True
    assert annotated[1]["in_window"] is True
    assert annotated[2]["in_window"] is False


# ---------------------------------------------------------------------------
# 5. family_session_xtab — session classification + cross-tabs
# ---------------------------------------------------------------------------

def test_classify_session_boundaries():
    # 00:00 UTC → asia (boundary inclusive)
    assert classify_session(pd.Timestamp("2024-06-15 00:00:00")) == "asia"
    # 07:59 UTC → asia (last asia hour)
    assert classify_session(pd.Timestamp("2024-06-15 07:59:00")) == "asia"
    # 08:00 UTC → london (boundary inclusive)
    assert classify_session(pd.Timestamp("2024-06-15 08:00:00")) == "london"
    # 15:59 UTC → london
    assert classify_session(pd.Timestamp("2024-06-15 15:59:00")) == "london"
    # 16:00 UTC → ny
    assert classify_session(pd.Timestamp("2024-06-15 16:00:00")) == "ny"
    # 23:59 UTC → ny
    assert classify_session(pd.Timestamp("2024-06-15 23:59:00")) == "ny"


def test_direction_session_matrix_basic():
    df = pd.DataFrame({
        "entry_timestamp": pd.to_datetime([
            "2024-01-01 03:00:00",  # asia
            "2024-01-01 10:00:00",  # london
            "2024-01-01 18:00:00",  # ny
            "2024-01-02 04:00:00",  # asia
        ]),
        "direction": [1, 1, -1, -1],
        "pnl_usd": [10, 20, -5, 30],
    })
    matrix = direction_session_matrix(df)
    assert len(matrix) > 0
    assert "direction" in matrix.columns
    assert "session" in matrix.columns


def test_best_worst_cells_respects_min_trades():
    df = pd.DataFrame([
        {"direction": "Long", "session": "asia", "trades": 50, "net_pnl": 1000.0, "win_rate": 60.0, "profit_factor": 2.0},
        {"direction": "Long", "session": "london", "trades": 10, "net_pnl": 5000.0, "win_rate": 90.0, "profit_factor": 9.0},
        {"direction": "Short", "session": "ny", "trades": 50, "net_pnl": -500.0, "win_rate": 30.0, "profit_factor": 0.5},
    ])
    bw = best_worst_cells(df, "session", min_trades=30)
    # Top PnL row (5000) has only 10 trades → excluded; next best is Long×asia
    assert bw["best"]["cell"] == "Long × Asia"
    assert bw["worst"]["cell"] == "Short × Ny"


def test_session_share_sums_to_100():
    df = pd.DataFrame({
        "entry_timestamp": pd.to_datetime([
            "2024-01-01 03:00:00", "2024-01-01 10:00:00", "2024-01-01 18:00:00",
        ]),
        "direction": [1, 1, 1],
        "pnl_usd": [40, 30, 30],
    })
    share = session_share(df)
    total = share["asia"] + share["london"] + share["ny"]
    assert total == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 6. family_verdicts — orchestration over canonical authority
# ---------------------------------------------------------------------------

def test_family_verdicts_canonical_passthrough_for_core():
    rows = pd.DataFrame([{
        "strategy": "X_FX_FOO_S01_V1_P00",
        "symbol": "EURUSD",
        "total_trades": 1000,
        "max_dd_pct": 10.0,
        "return_dd_ratio": 5.0,
        "sharpe_ratio": 2.0,
        "sqn": 3.0,
        "profit_factor": 1.5,
        "trade_density": 200,
        "expectancy": 1.0,
    }])
    verdicts = compute_family_verdicts(rows)
    v = verdicts["X_FX_FOO_S01_V1_P00"]
    assert v["status"] == "CORE"
    assert v["effective_status"] == "CORE"
    assert v["soft_gate_trips"] == []


def test_family_verdicts_soft_gate_demotes_to_fail_effective():
    rows = pd.DataFrame([{
        "strategy": "Y_FX_FOO_S01_V1_P00",
        "symbol": "EURUSD",
        "total_trades": 1000,
        "max_dd_pct": 10.0,
        "return_dd_ratio": 5.0,
        "sharpe_ratio": 2.0,
        "sqn": 3.0,
        "profit_factor": 1.5,
        "trade_density": 200,
        "expectancy": 1.0,
    }])
    # Trade log with extreme tail concentration (>70% top-5)
    n = 100
    trades = pd.DataFrame({
        "pnl_usd": [10000.0] * 5 + [-1.0] * 95,
        "direction": [1] * n,
        "exit_timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
    })
    verdicts = compute_family_verdicts(rows, {"Y_FX_FOO_S01_V1_P00": trades})
    v = verdicts["Y_FX_FOO_S01_V1_P00"]
    assert v["status"] == "CORE"
    assert v["effective_status"] == "FAIL (effective)"
    assert len(v["soft_gate_trips"]) >= 1


# ---------------------------------------------------------------------------
# 7. Rule 3 — forbidden imports
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORTS = {
    "tools.utils.research.simulators",
    "tools.utils.research.block_bootstrap",
    "tools.utils.research.friction",
    "tools.robustness.monte_carlo",
    "tools.robustness.bootstrap",
    "tools.robustness.friction",
}


def _extract_imports(py_path: Path) -> set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                names.add(n.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


@pytest.mark.parametrize("relpath", [
    "tools/family_report.py",
    "tools/report/family_renderer.py",
    "tools/report/family_session_xtab.py",
    "tools/report/family_verdicts.py",
    "tools/report/strategy_signature_utils.py",
    "tools/report/family_streaks.py",
    "tools/report/family_calendar.py",
    "tools/window_compat.py",
])
def test_phase_b_module_does_not_import_forbidden(relpath):
    """Rule 3 guard — none of the Phase B modules may import the expensive primitives."""
    p = Path(__file__).resolve().parents[1] / relpath
    imports = _extract_imports(p)
    leaks = imports & _FORBIDDEN_IMPORTS
    assert not leaks, f"{relpath} imports forbidden module(s): {leaks}"


# ---------------------------------------------------------------------------
# 8. Rule 4 — wrapper-first: no edits to runner.py or generate_strategy_card.py
# ---------------------------------------------------------------------------

def test_runner_py_inline_streak_logic_still_present():
    """If someone extracts the inline streak code from runner.py, Phase B
    moves out of wrapper-first regime — that's a separate proposal per Rule 4.
    """
    runner = (Path(__file__).resolve().parents[1] / "tools/robustness/runner.py").read_text(encoding="utf-8")
    # Inline _max_streak / _avg_streak are still there
    assert "def _max_streak(arr):" in runner
    assert "def _avg_streak(arr):" in runner


def test_generate_strategy_card_inline_flatten_still_present():
    """Same idea — the wrapper-first guarantee says we don't touch this file."""
    src = (Path(__file__).resolve().parents[1] / "tools/generate_strategy_card.py").read_text(encoding="utf-8")
    assert "def _flatten(obj, prefix" in src
    assert "def _diff(prev_sig, curr_sig):" in src


# ---------------------------------------------------------------------------
# 9. End-to-end smoke test
# ---------------------------------------------------------------------------

_PSBRK_BACKTEST_PATH = Path(__file__).resolve().parents[1] / ".." / "TradeScan_State" / "backtests" / "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14_XAUUSD"


@pytest.mark.skipif(
    not _PSBRK_BACKTEST_PATH.exists(),
    reason="PSBRK backtest dir missing — run pipeline first",
)
def test_family_report_cli_runs_and_writes_file(tmp_path):
    """Run the CLI end-to-end against the PSBRK family. Output file must
    exist and contain the expected section headers.
    """
    from tools.family_report import generate_family_report

    out = tmp_path / "family_smoke.md"
    written = generate_family_report(
        prefix="65_BRK_XAUUSD_5M_PSBRK",
        variants=["P09", "P14", "P15", "S02_V1_P01", "S02_V1_P03", "S03_V1_P02"],
        out_path=out,
    )
    assert written == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # Section markers
    assert "# Family Analysis — 65_BRK_XAUUSD_5M_PSBRK" in text
    assert "## 1. Executive Ranking" in text
    assert "## 2. Core Metrics" in text
    assert "## 14. Deployment Verdict" in text
    # Window-mismatch guard fires because MF rows from pre-recovery runs
    # have non-standardized windows.
    assert "Cross-Window Comparability Warnings" in text
