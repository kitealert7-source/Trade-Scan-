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
    assert "## 2. Promotion Summary" in text
    assert "## 3. Core Metrics" in text
    assert "## 16. Deployment Verdict" in text
    # Window-mismatch guard fires because MF rows from pre-recovery runs
    # have non-standardized windows.
    assert "Cross-Window Comparability Warnings" in text


# ---------------------------------------------------------------------------
# 10. --latest-only filter (Phase B follow-up, 2026-05-12)
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_ledger(tmp_path, monkeypatch):
    """Build a tmp SQLite ledger seeded via ledger_db's own create_tables so
    the schema stays in sync with the real DB. Patches LEDGER_DB_PATH in
    BOTH `tools.family_report` (latest-only direct query) and
    `tools.ledger_db` (read_master_filter default path) so every code path
    targets the fixture.
    """
    import sqlite3
    from tools.ledger_db import create_tables

    db_path = tmp_path / "ledger.db"
    conn = sqlite3.connect(str(db_path))
    create_tables(conn)
    conn.close()

    import tools.family_report as fr_mod
    import tools.ledger_db as ledger_mod
    monkeypatch.setattr(fr_mod, "LEDGER_DB_PATH", db_path, raising=True)
    monkeypatch.setattr(ledger_mod, "LEDGER_DB_PATH", db_path, raising=True)
    return db_path


def _insert_mf_row(db_path, **fields):
    """Insert one row into master_filter. Missing columns are left NULL."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cols = ",".join(f'"{c}"' for c in fields)
    placeholders = ",".join("?" * len(fields))
    conn.execute(
        f"INSERT INTO master_filter ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    conn.commit()
    conn.close()


def test_latest_only_collapses_duplicates_by_max_rowid(isolated_ledger):
    """Two rows for the same strategy, different rowids — keep the higher.

    This is the post-2026-05-11 PSBRK shape: old run + new ENGINE-rerun
    both is_current=NULL (effectively 1), distinguishable only by rowid.
    """
    from tools.family_report import _load_master_filter_rows

    _insert_mf_row(isolated_ledger,
        run_id="old_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", test_start="2024-07-19", test_end="2026-05-04",
    )
    _insert_mf_row(isolated_ledger,
        run_id="new_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", test_start="2024-05-11", test_end="2026-05-11",
    )

    rows, dedup = _load_master_filter_rows("FAM_PFX", None, latest_only=True)

    assert len(rows) == 1
    assert rows.iloc[0]["run_id"] == "new_rid"
    assert rows.iloc[0]["test_end"] == "2026-05-11"
    assert dedup is not None
    assert dedup["enabled"] is True
    assert dedup["input_rows"] == 2
    assert dedup["kept_rows"] == 1
    # Both rows had is_current=NULL (treated as current) so this is ambiguous
    assert len(dedup["ambiguities"]) == 1
    assert dedup["ambiguities"][0]["strategy"] == "FAM_PFX_S01_V1_P01_XAUUSD"
    assert dedup["ambiguities"][0]["n_current"] == 2


def test_latest_only_excludes_is_current_zero(isolated_ledger):
    """Rows explicitly superseded (is_current=0) must be dropped before
    the max-rowid pick. The retained row is the one still marked current,
    even when the superseded row has the higher rowid.
    """
    from tools.family_report import _load_master_filter_rows

    # Live row inserted first (lower rowid)…
    _insert_mf_row(isolated_ledger,
        run_id="keep_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", is_current=1,
    )
    # …then a superseded row with a higher rowid that should NOT win.
    _insert_mf_row(isolated_ledger,
        run_id="drop_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", is_current=0,
    )

    rows, dedup = _load_master_filter_rows("FAM_PFX", None, latest_only=True)
    assert len(rows) == 1
    assert rows.iloc[0]["run_id"] == "keep_rid"
    assert dedup["ambiguities"] == []  # only one current row → no ambiguity


def test_latest_only_treats_null_is_current_as_current(isolated_ledger):
    """Per the 2026-04-16 supersession backfill convention, NULL means
    current. Legacy pre-migration rows must not be silently dropped.
    """
    from tools.family_report import _load_master_filter_rows

    _insert_mf_row(isolated_ledger,
        run_id="legacy_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD",  # is_current unset → NULL
    )
    rows, dedup = _load_master_filter_rows("FAM_PFX", None, latest_only=True)
    assert len(rows) == 1
    assert rows.iloc[0]["run_id"] == "legacy_rid"


def test_latest_only_preserves_per_symbol_resolution(isolated_ledger):
    """For multi-asset families the group key is the full `strategy`
    column (=`clean_id_<SYMBOL>`), so two symbols of the same clean_id
    must BOTH survive --latest-only (one row per symbol).
    """
    from tools.family_report import _load_master_filter_rows

    _insert_mf_row(isolated_ledger,
        run_id="aud_rid", strategy="FAM_PFX_S01_V1_P01_AUDJPY",
        symbol="AUDJPY",
    )
    _insert_mf_row(isolated_ledger,
        run_id="eur_rid", strategy="FAM_PFX_S01_V1_P01_EURUSD",
        symbol="EURUSD",
    )
    rows, dedup = _load_master_filter_rows("FAM_PFX", None, latest_only=True)
    assert len(rows) == 2
    assert set(rows["symbol"]) == {"AUDJPY", "EURUSD"}
    assert dedup["ambiguities"] == []


def test_default_path_returns_all_rows_with_rowid_for_prior_lookup(isolated_ledger):
    """When latest_only=False, every matching MF row is returned (no dedup).
    The `_rowid` column is preserved on BOTH paths so the prior-run-delta
    section can identify "the run immediately before this one" without a
    second DB round trip per variant.
    """
    from tools.family_report import _load_master_filter_rows

    _insert_mf_row(isolated_ledger,
        run_id="old_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", test_end="2026-05-04",
    )
    _insert_mf_row(isolated_ledger,
        run_id="new_rid", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", test_end="2026-05-11",
    )
    rows, dedup = _load_master_filter_rows("FAM_PFX", None, latest_only=False)
    assert len(rows) == 2
    assert dedup is None
    # `_rowid` MUST be present — downstream prior-run-delta lookup relies
    # on it. Removing it again silently breaks the same-strategy Δ section.
    assert "_rowid" in rows.columns
    assert set(rows["_rowid"]) == {1, 2}


def test_latest_only_renders_filter_line_and_ambiguity_section(isolated_ledger, tmp_path, monkeypatch):
    """End-to-end: --latest-only output includes the header filter line
    and the ambiguity table when one fires.
    """
    from tools.family_report import generate_family_report

    # Seed only a SHELL row — the report will warn about missing trade
    # logs but still render header/filter/ambiguity sections, which is
    # all we're verifying here.
    _insert_mf_row(isolated_ledger,
        run_id="r1", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD",
    )
    _insert_mf_row(isolated_ledger,
        run_id="r2", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD",
    )

    out = tmp_path / "ambig.md"
    written = generate_family_report(
        prefix="FAM_PFX", variants=None, out_path=out, latest_only=True,
    )
    text = written.read_text(encoding="utf-8")
    assert "**Filter:** `--latest-only`" in text
    assert "kept 1 / 2 MF rows" in text
    assert "## ⚠ Latest-Only Ambiguities" in text
    assert "FAM_PFX_S01_V1_P01_XAUUSD" in text


def test_cli_latest_only_flag_wires_through(isolated_ledger, tmp_path):
    """CLI parser passes --latest-only into generate_family_report."""
    from tools.family_report import main

    _insert_mf_row(isolated_ledger,
        run_id="r1", strategy="CLIFAM_S01_V1_P01_XAUUSD", symbol="XAUUSD",
    )
    out = tmp_path / "cli.md"
    rc = main(["CLIFAM", "--out", str(out), "--latest-only"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "**Filter:** `--latest-only`" in text


# ---------------------------------------------------------------------------
# 11. Prior-run delta (Phase B follow-up, 2026-05-12)
#
# Two comparison contexts in the report with DIFFERENT window-mismatch
# policies — these tests pin the same-strategy policy: window mismatch is
# SHOWN with a warning, not suppressed. (See verdict_risk.py Phase A tests
# for the cross-strategy suppress-on-mismatch policy.)
# ---------------------------------------------------------------------------

def test_prior_run_delta_picks_immediate_predecessor_by_rowid(isolated_ledger):
    """Three runs (low/mid/high rowid). The prior of the high-rowid row is
    the mid-rowid row (rowid < current, max), NOT the absolute oldest.
    """
    from tools.report.prior_run_delta import compute_prior_run_delta

    _insert_mf_row(isolated_ledger,
        run_id="rid_old", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=1.50, profit_factor=1.10, max_dd_pct=50.0, total_trades=200,
        test_start="2024-01-01", test_end="2025-01-01",
    )  # rowid 1
    _insert_mf_row(isolated_ledger,
        run_id="rid_mid", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.00, profit_factor=1.20, max_dd_pct=40.0, total_trades=400,
        test_start="2024-05-11", test_end="2026-05-11",
    )  # rowid 2 — this should be the "prior" of rowid 3
    _insert_mf_row(isolated_ledger,
        run_id="rid_new", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.30, profit_factor=1.25, max_dd_pct=38.0, total_trades=500,
        test_start="2024-05-11", test_end="2026-05-11",
    )  # rowid 3 — current

    current_row = {
        "strategy": "STR_S01_V1_P01_XAUUSD",
        "test_start": "2024-05-11", "test_end": "2026-05-11",
        "sqn": 2.30, "profit_factor": 1.25, "max_dd_pct": 38.0,
        "total_trades": 500, "total_net_profit": 1000.0, "expectancy": 2.0,
    }
    delta = compute_prior_run_delta(
        db_path=isolated_ledger,
        strategy="STR_S01_V1_P01_XAUUSD",
        current_rowid=3,
        current_row=current_row,
    )
    assert delta["found"] is True
    assert delta["prior_run_id"] == "rid_mid"
    # SQN went from 2.00 → 2.30 = +0.30
    sqn_metric = next(m for m in delta["metrics"] if m["label"] == "SQN")
    assert sqn_metric["delta"] == pytest.approx(0.30)
    assert sqn_metric["pct_change"] == pytest.approx(15.0)


def test_prior_run_delta_shows_delta_when_windows_mismatch(isolated_ledger):
    """Same-strategy policy: window mismatch DOES NOT suppress the delta;
    it surfaces a window_mismatch=True flag plus drift-days so the
    renderer can annotate. (Contrast verdict_risk._windows_compatible
    which suppresses parent-Δ on mismatch.)
    """
    from tools.report.prior_run_delta import compute_prior_run_delta

    _insert_mf_row(isolated_ledger,
        run_id="rid_old", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.10, test_start="2024-07-19", test_end="2026-05-04",
    )
    _insert_mf_row(isolated_ledger,
        run_id="rid_new", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.34, test_start="2024-05-11", test_end="2026-05-11",
    )
    current_row = {
        "strategy": "STR_S01_V1_P01_XAUUSD",
        "test_start": "2024-05-11", "test_end": "2026-05-11",
        "sqn": 2.34, "profit_factor": 1.25, "max_dd_pct": 38.0,
        "total_trades": 500,
    }
    delta = compute_prior_run_delta(
        db_path=isolated_ledger,
        strategy="STR_S01_V1_P01_XAUUSD",
        current_rowid=2,
        current_row=current_row,
        tolerance_days=5,
    )
    # Window deltas: start 2024-05-11 vs 2024-07-19 = -69 days; end +7
    assert delta["found"] is True
    assert delta["window_mismatch"] is True
    assert delta["window_drift"]["start_days"] == -69
    assert delta["window_drift"]["end_days"] == 7
    # The delta IS computed and returned despite the mismatch.
    sqn_metric = next(m for m in delta["metrics"] if m["label"] == "SQN")
    assert sqn_metric["delta"] == pytest.approx(0.24)


def test_prior_run_delta_clean_when_windows_match(isolated_ledger):
    """Within tolerance → window_mismatch=False, no warning needed."""
    from tools.report.prior_run_delta import compute_prior_run_delta

    _insert_mf_row(isolated_ledger,
        run_id="rid_old", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.10, test_start="2024-05-13", test_end="2026-05-09",
    )
    _insert_mf_row(isolated_ledger,
        run_id="rid_new", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.34, test_start="2024-05-11", test_end="2026-05-11",
    )
    current_row = {
        "test_start": "2024-05-11", "test_end": "2026-05-11", "sqn": 2.34,
    }
    delta = compute_prior_run_delta(
        db_path=isolated_ledger,
        strategy="STR_S01_V1_P01_XAUUSD",
        current_rowid=2,
        current_row=current_row,
        tolerance_days=5,
    )
    assert delta["window_mismatch"] is False


def test_prior_run_delta_absent_for_first_run(isolated_ledger):
    """Strategy with only one MF row → no prior run, returns found=False.
    The renderer skips strategies in this state.
    """
    from tools.report.prior_run_delta import compute_prior_run_delta

    _insert_mf_row(isolated_ledger,
        run_id="only_rid", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
    )
    delta = compute_prior_run_delta(
        db_path=isolated_ledger,
        strategy="STR_S01_V1_P01_XAUUSD",
        current_rowid=1,
        current_row={"sqn": 2.0},
    )
    assert delta == {"found": False}


def test_prior_run_delta_includes_superseded_with_annotation(isolated_ledger):
    """A superseded (is_current=0) prior run is still surfaced — the
    historical metric is a fact, and "this was superseded" is informative
    context. The renderer adds a visual marker for this case.
    """
    from tools.report.prior_run_delta import compute_prior_run_delta

    _insert_mf_row(isolated_ledger,
        run_id="rid_old", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.10, is_current=0,  # explicitly superseded
    )
    _insert_mf_row(isolated_ledger,
        run_id="rid_new", strategy="STR_S01_V1_P01_XAUUSD", symbol="XAUUSD",
        sqn=2.34, is_current=1,
    )
    current_row = {"sqn": 2.34}
    delta = compute_prior_run_delta(
        db_path=isolated_ledger,
        strategy="STR_S01_V1_P01_XAUUSD",
        current_rowid=2,
        current_row=current_row,
    )
    assert delta["found"] is True
    assert delta["prior_is_current"] == 0
    assert delta["prior_run_id"] == "rid_old"


# ---------------------------------------------------------------------------
# 12. Promotion Summary (Phase B follow-up, 2026-05-12)
# ---------------------------------------------------------------------------

def test_promotion_summary_uses_canonical_status_undemoted_by_soft_flags():
    """Block A authority: the `verdict.status` field (canonical) NEVER
    gets demoted by soft flags — only `effective_status` does. The
    Promotion Summary renderer must read `status`, not `effective_status`.
    Otherwise the section would silently merge with Block B's annotations.
    """
    from tools.report.family_renderer import _render_promotion_summary

    family_data = {
        "variants": [
            {
                "directive_id": "FAM_S01_V1_P01",
                "row": {"sqn": 2.6, "max_dd_pct": 25.0, "profit_factor": 1.30},
                "verdict": {
                    # Canonical = CORE; effective demoted by a soft flag.
                    "status": "CORE",
                    "effective_status": "FAIL (effective)",
                    "soft_gate_trips": ["Top-5 concentration 80.0% > 70% (soft FAIL)"],
                },
                "additional_soft_flags": [],
            },
        ],
    }
    md = "\n".join(_render_promotion_summary(family_data))
    # The variant appears in CORE (its canonical label), NOT in FAIL.
    core_section = md.split("**WATCH**")[0]
    assert "FAM_S01_V1_P01" in core_section
    assert "**FAIL** (0)" in md
    # Block B surfaces the soft flag as annotation.
    assert "Top-5 concentration 80.0%" in md


def test_promotion_summary_renders_none_for_empty_groups():
    """No hidden empties: every status group renders its count, and an
    empty group renders the literal "None" so the reader is never left
    wondering whether anything was filtered.
    """
    from tools.report.family_renderer import _render_promotion_summary

    family_data = {
        "variants": [
            {
                "directive_id": "FAM_S01_V1_P01",
                "row": {"sqn": 2.0, "max_dd_pct": 50.0, "profit_factor": 1.10},
                "verdict": {"status": "FAIL", "soft_gate_trips": []},
                "additional_soft_flags": [],
            },
        ],
    }
    md = "\n".join(_render_promotion_summary(family_data))
    assert "**CORE** (0):" in md
    assert "**WATCH** (0):" in md
    assert "**FAIL** (1):" in md
    # Each empty group has an explicit "None" bullet.
    assert md.count("- None") == 2  # CORE empty + WATCH empty


def test_promotion_summary_block_b_merges_verdict_trips_and_additional():
    """Block B sources from both `verdict.soft_gate_trips` (computed in
    family_verdicts: tail/body/flat) and `payload.additional_soft_flags`
    (Phase A helpers: loss_streak/stall_decay). The merge must
    dedupe identical strings (the two sources can both surface tail).
    """
    from tools.report.family_renderer import _render_promotion_summary

    family_data = {
        "variants": [
            {
                "directive_id": "FAM_S01_V1_P01",
                "row": {"sqn": 1.5, "max_dd_pct": 60.0, "profit_factor": 1.05},
                "verdict": {
                    "status": "FAIL",
                    "soft_gate_trips": ["Top-5 concentration 75.0% > 70% (soft FAIL)"],
                },
                "additional_soft_flags": [
                    "⚠ **Loss streak:** longest run = 18 (> 15 threshold).",
                ],
            },
        ],
    }
    md = "\n".join(_render_promotion_summary(family_data))
    assert "Top-5 concentration 75.0%" in md
    assert "Loss streak:** longest run = 18" in md


def test_promotion_summary_clean_set_listed_when_some_variants_have_no_flags():
    """When at least one soft flag fires across the family, variants
    with zero flags are surfaced under "Clean (no soft overlays)". This
    avoids the reader wondering whether a missing variant was filtered.
    """
    from tools.report.family_renderer import _render_promotion_summary

    family_data = {
        "variants": [
            {
                "directive_id": "FAM_S01_V1_P09",
                "row": {"sqn": 2.34, "max_dd_pct": 38.0, "profit_factor": 1.25},
                "verdict": {"status": "WATCH", "soft_gate_trips": []},
                "additional_soft_flags": [],
            },
            {
                "directive_id": "FAM_S01_V1_P14",
                "row": {"sqn": 2.87, "max_dd_pct": 40.03, "profit_factor": 1.35},
                "verdict": {
                    "status": "FAIL",
                    "soft_gate_trips": ["Top-5 concentration 85% > 70% (soft FAIL)"],
                },
                "additional_soft_flags": [],
            },
        ],
    }
    md = "\n".join(_render_promotion_summary(family_data))
    # P14 has a flag → not in the clean set
    # P09 has no flag → IS in the clean set
    assert "Clean (no soft overlays)" in md
    assert "FAM_S01_V1_P09" in md.split("Clean (no soft overlays)")[1]


def test_promotion_summary_all_clean_message_when_no_flags_fire():
    """When zero soft flags fire across the family, Block B renders a
    single 'no soft overlays fired' message rather than per-variant
    'clean' bullets — avoids visual noise.
    """
    from tools.report.family_renderer import _render_promotion_summary

    family_data = {
        "variants": [
            {
                "directive_id": "FAM_S01_V1_P01",
                "row": {"sqn": 2.6, "max_dd_pct": 25.0, "profit_factor": 1.30},
                "verdict": {"status": "CORE", "soft_gate_trips": []},
                "additional_soft_flags": [],
            },
            {
                "directive_id": "FAM_S01_V1_P02",
                "row": {"sqn": 2.5, "max_dd_pct": 26.0, "profit_factor": 1.28},
                "verdict": {"status": "CORE", "soft_gate_trips": []},
                "additional_soft_flags": [],
            },
        ],
    }
    md = "\n".join(_render_promotion_summary(family_data))
    assert "_No soft overlays fired across the family._" in md
    # Clean-set section is suppressed in this case.
    assert "Clean (no soft overlays):" not in md


def test_promotion_summary_renders_in_full_report(isolated_ledger, tmp_path):
    """End-to-end: the rendered report includes the Promotion Summary
    between Executive Ranking (§1) and Core Metrics (§3) with both
    blocks present.
    """
    from tools.family_report import generate_family_report

    _insert_mf_row(isolated_ledger,
        run_id="r1", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", sqn=2.34, max_dd_pct=38.0, profit_factor=1.25,
        test_start="2024-05-11", test_end="2026-05-11",
    )
    out = tmp_path / "promo.md"
    generate_family_report(
        prefix="FAM_PFX",
        variants=None,
        out_path=out,
        latest_only=True,
    )
    text = out.read_text(encoding="utf-8")
    assert "## 1. Executive Ranking" in text
    assert "## 2. Promotion Summary" in text
    assert "### Block A — Canonical Promotion Status" in text
    assert "### Block B — Soft Risk Overlays (annotation only)" in text
    assert "## 3. Core Metrics" in text


def test_prior_run_delta_section_renders_in_family_report(isolated_ledger, tmp_path):
    """End-to-end: the renderer produces a `## 4. Δ vs Prior Run` section
    when at least one variant has a prior run, with the mismatch warning
    block surfaced.
    """
    from tools.family_report import generate_family_report

    _insert_mf_row(isolated_ledger,
        run_id="rid_old", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", sqn=2.10,
        test_start="2024-07-19", test_end="2026-05-04",
    )
    _insert_mf_row(isolated_ledger,
        run_id="rid_new", strategy="FAM_PFX_S01_V1_P01_XAUUSD",
        symbol="XAUUSD", sqn=2.34,
        test_start="2024-05-11", test_end="2026-05-11",
    )

    out = tmp_path / "prior.md"
    generate_family_report(
        prefix="FAM_PFX",
        variants=None,
        out_path=out,
        latest_only=True,
    )
    text = out.read_text(encoding="utf-8")
    assert "## 5. Δ vs Prior Run (same strategy)" in text
    assert "Window mismatch" in text
    # The delta is rendered (not suppressed) — both rows visible.
    assert "**Prior:** 2024-07-19 → 2026-05-04" in text
    assert "**Current:** 2024-05-11 → 2026-05-11" in text
