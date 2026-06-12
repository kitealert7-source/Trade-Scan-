"""Fixture-based tests for tools/resolve_baseline.py.

Every test runs against a temp sqlite ledger + temp home dirs with the path
constants monkeypatched — the real ``ledger.db`` and the real
``TradeScan_State`` tree are never touched.

Coverage (RESOLVE_BASELINE_SPEC §16):
  - is_current correctness (superseded vs is_current → returns is_current)
  - multi-symbol bare directive → N references
  - OLD single-asset → seed + code from strategies/<id>/ with CSV metrics
  - basket metrics via canonical_metrics path (differs from MPS net_pct trap)
  - strategy_dir absent → code degrades without error
  - handle-not-found → resolved:false
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# master_filter columns the resolver depends on (a subset of the full schema).
_MF_COLS = [
    "rank", "run_id", "strategy", "symbol", "timeframe",
    "profit_factor", "is_current", "superseded_by",
]


def _make_ledger(db_path: Path, rows: list[dict]) -> None:
    """Create a minimal master_filter table with the given rows."""
    conn = sqlite3.connect(str(db_path))
    cols_sql = ", ".join(f'"{c}" TEXT' for c in _MF_COLS)
    conn.execute(f"CREATE TABLE master_filter ({cols_sql})")
    for r in rows:
        placeholders = ", ".join("?" for _ in _MF_COLS)
        conn.execute(
            f'INSERT INTO master_filter ({", ".join(_MF_COLS)}) VALUES ({placeholders})',
            tuple(r.get(c) for c in _MF_COLS),
        )
    conn.commit()
    conn.close()


def _write_csv(path: Path, header: str, row: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{header}\n{row}\n", encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp state root with patched path constants. Returns a helper namespace."""
    state = tmp_path / "TradeScan_State"
    backtests = state / "backtests"
    strategies = state / "strategies"
    runs = state / "runs"
    for d in (backtests, strategies, runs):
        d.mkdir(parents=True, exist_ok=True)

    # Patch the ledger's dynamic db-path resolution.
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", state, raising=False)

    # Patch state_paths constants (captured at import time) + the resolver's
    # own imported copies so capsule_path / strategy_dir / RUNS_DIR all point
    # at the temp tree.
    import config.state_paths as sp
    import tools.resolve_baseline as rb
    for mod in (sp, rb):
        monkeypatch.setattr(mod, "BACKTESTS_DIR", backtests, raising=False)
        monkeypatch.setattr(mod, "STRATEGIES_DIR", strategies, raising=False)
        # REPO_STRATEGIES_DIR is the executable-intent SOURCE home that
        # strategy_dir() resolves against; the temp `strategies` dir below
        # holds strategy.py + directive.txt, so point it here too.
        monkeypatch.setattr(mod, "REPO_STRATEGIES_DIR", strategies, raising=False)
        monkeypatch.setattr(mod, "RUNS_DIR", runs, raising=False)

    class _Env:
        pass

    e = _Env()
    e.state = state
    e.backtests = backtests
    e.strategies = strategies
    e.runs = runs
    e.db = state / "ledger.db"
    return e


def _seed_single_asset_capsule(env, full_strategy: str, *, with_csv=True):
    """Create a single-asset capsule with the four metric CSVs."""
    raw = env.backtests / full_strategy / "raw"
    if with_csv:
        _write_csv(
            raw / "results_standard.csv",
            "net_pnl_usd,trade_count,win_rate,profit_factor,gross_profit,gross_loss",
            "89.26,419,0.46,1.94,420.31,330.05",
        )
        _write_csv(
            raw / "results_risk.csv",
            "max_drawdown_usd,max_drawdown_pct,return_dd_ratio,sharpe_ratio",
            "12.3,0.0048,2.1,3.59",
        )
        # trade-level: 6 wins, 4 losses → top5 concentration derivable
        tl_header = "pnl_usd"
        tl_rows = "\n".join(str(v) for v in [50, 40, 30, 20, 10, 5, -8, -6, -4, -2])
        (raw / "results_tradelevel.csv").parent.mkdir(parents=True, exist_ok=True)
        (raw / "results_tradelevel.csv").write_text(
            tl_header + "\n" + tl_rows + "\n", encoding="utf-8"
        )
        _write_csv(
            raw / "results_yearwise.csv",
            "year,net_pnl_usd,trade_count,win_rate",
            "2024,89.26,419,0.46",
        )
        # one losing year appended
        with (raw / "results_yearwise.csv").open("a", encoding="utf-8") as f:
            f.write("2023,-12.0,200,0.42\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_is_current_beats_first_match(env):
    """Superseded first-match row must NOT win; is_current row is returned."""
    import tools.resolve_baseline as rb

    full = "22_CONT_FX_15M_RSIAVG_TRENDFILT_S07_V1_P02_EURUSD"
    _make_ledger(
        env.db,
        [
            # first-match (insertion order) but superseded
            {"run_id": "7bdded9f2e205d5e2cfeae8f", "strategy": full,
             "symbol": "EURUSD", "is_current": "0", "profit_factor": "1.1"},
            # canonical
            {"run_id": "80a6ef234aa03815990337c3", "strategy": full,
             "symbol": "EURUSD", "is_current": "1", "profit_factor": "1.94"},
        ],
    )
    _seed_single_asset_capsule(env, full)

    result = rb.resolve_baseline(full)
    assert result.resolved
    assert len(result.references) == 1
    ref = result.references[0]
    assert ref.run_id == "80a6ef234aa03815990337c3"
    assert ref.is_current is True
    assert ref.run_type == "single_asset"
    # metrics came from the CSVs
    assert ref.metrics["source"] == "csv_stage1"
    assert ref.metrics["profit_factor"] == pytest.approx(1.94)
    assert ref.metrics["losing_years"] == 1
    assert ref.metrics["top5_concentration"] is not None


def test_multi_symbol_returns_n(env):
    """A bare base directive handle returns one reference per symbol."""
    import tools.resolve_baseline as rb

    base = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02"
    syms = ["AUDUSD", "EURUSD", "USDJPY"]
    rows = []
    for i, s in enumerate(syms):
        full = f"{base}_{s}"
        rows.append(
            {"run_id": f"{i:024x}", "strategy": full, "symbol": s,
             "is_current": None, "profit_factor": "1.0"}
        )
        _seed_single_asset_capsule(env, full)
    _make_ledger(env.db, rows)

    result = rb.resolve_baseline(base)
    assert result.resolved
    assert len(result.references) == 3
    got_syms = sorted(r.symbol for r in result.references)
    assert got_syms == sorted(syms)
    # siblings advertised on every reference
    for ref in result.references:
        assert ref.strategy == base
        assert set(ref.siblings) == set(syms) - {ref.symbol}


def test_symbol_collapses_to_one(env):
    """--symbol narrows a multi-symbol directive to a single reference."""
    import tools.resolve_baseline as rb

    base = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02"
    syms = ["AUDUSD", "EURUSD", "USDJPY"]
    rows = []
    for i, s in enumerate(syms):
        full = f"{base}_{s}"
        rows.append(
            {"run_id": f"{i:024x}", "strategy": full, "symbol": s,
             "is_current": "1", "profit_factor": "1.0"}
        )
        _seed_single_asset_capsule(env, full)
    _make_ledger(env.db, rows)

    result = rb.resolve_baseline(base, symbol="EURUSD")
    assert len(result.references) == 1
    assert result.references[0].symbol == "EURUSD"


def test_old_single_asset_seed_and_code_from_strategies(env):
    """OLD single-asset: code + seed resolve from strategies/<id>/, metrics CSV."""
    import tools.resolve_baseline as rb

    full = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02_EURUSD"
    base = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02"
    _make_ledger(
        env.db,
        [{"run_id": "a" * 24, "strategy": full, "symbol": "EURUSD",
          "is_current": "1", "profit_factor": "1.0"}],
    )
    _seed_single_asset_capsule(env, full)

    # strategies/<base>/ holds strategy.py + the backfilled directive.txt
    sdir = env.strategies / base
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "strategy.py").write_text("# strategy code\n", encoding="utf-8")
    (sdir / "directive.txt").write_text(
        "test:\n  name: x\n  strategy: ULTC\n", encoding="utf-8"
    )

    result = rb.resolve_baseline(full)
    ref = result.references[0]
    assert ref.resolved
    # code from strategies_dir (NOT git, NOT ABSENT)
    assert ref.code["source"] == "strategies_dir"
    assert ref.code["path"].endswith("strategy.py")
    # seed: DIRECTIVE_SOURCE/run absent → falls to strategy_dir directive.txt
    assert ref.seed["source"] == "strategy_directive_txt"
    assert ref.seed["truth"] == "human_keyed_continuity"
    # metrics from CSV
    assert ref.metrics["source"] == "csv_stage1"
    assert ref.homes["strategy_dir"] is not None


def test_seed_ladder_prefers_run_directive(env):
    """run_dir/directive.txt (exact_execution) beats strategy_dir copy."""
    import tools.resolve_baseline as rb

    full = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02_EURUSD"
    base = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02"
    run_id = "b" * 24
    _make_ledger(
        env.db,
        [{"run_id": run_id, "strategy": full, "symbol": "EURUSD",
          "is_current": "1", "profit_factor": "1.0"}],
    )
    _seed_single_asset_capsule(env, full)

    rdir = env.runs / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "directive.txt").write_text("test:\n  name: run\n", encoding="utf-8")
    sdir = env.strategies / base
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "directive.txt").write_text("test:\n  name: strat\n", encoding="utf-8")

    ref = rb.resolve_baseline(full).references[0]
    assert ref.seed["source"] == "run_directive_txt"
    assert ref.seed["truth"] == "exact_execution"


def test_basket_metrics_via_canonical_path(env, monkeypatch):
    """Basket metrics come from canonical_metrics(parquet, stake), not MPS."""
    import tools.resolve_baseline as rb

    base = "90_PORT_AUDJPYAUDNZD_15M_COINTREV_V3_L30"
    full = f"{base}_AUDJPYAUDNZD"
    run_id = "c" * 24
    _make_ledger(
        env.db,
        [{"run_id": run_id, "strategy": full, "symbol": "AUDJPYAUDNZD",
          "is_current": "1", "profit_factor": "1.0"}],
    )
    # basket capsule: parquet + RECYCLE_RULE_SOURCE.py + DIRECTIVE_SOURCE.txt
    cap = env.backtests / full
    raw = cap / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (cap / "RECYCLE_RULE_SOURCE.py").write_text("# rule\n", encoding="utf-8")
    (cap / "DIRECTIVE_SOURCE.txt").write_text(
        "test:\n  name: x\nbasket:\n  initial_stake_usd: 2500.0\n", encoding="utf-8"
    )
    parquet = raw / "results_basket_per_bar.parquet"
    parquet.write_bytes(b"\x00")  # presence marker; canonical_metrics is stubbed

    # Force basket detection (basket_sheet query stubbed away) + stub canonical.
    monkeypatch.setattr(rb, "_detect_run_type", lambda rid, bdir: "basket")

    captured = {}

    def fake_canonical(p, stake, **kw):
        captured["parquet"] = str(p)
        captured["stake"] = stake
        return {
            "net_pct": 33.5, "max_dd_pct": 12.0, "ret_dd": 2.8,
            "events": {"recycle_executed": 4},
            "cycles_completed": 9, "cycles_won": 6, "exit_reason": "DATA_END",
            "stake_usd": stake,
        }

    import importlib
    cm_mod = importlib.import_module("tools.basket_hypothesis.canonical_metrics")
    monkeypatch.setattr(cm_mod, "canonical_metrics", fake_canonical)

    ref = rb.resolve_baseline(full).references[0]
    assert ref.run_type == "basket"
    assert ref.metrics["source"] == "parquet_canonical"
    assert ref.metrics["net_pct"] == 33.5      # the canonical truth, not 655%
    assert ref.metrics["cycles_completed"] == 9
    # stake parsed from DIRECTIVE_SOURCE basket.initial_stake_usd
    assert captured["stake"] == pytest.approx(2500.0)
    # code from the capsule RECYCLE_RULE_SOURCE.py
    assert ref.code["source"] == "capsule"
    # seed from DIRECTIVE_SOURCE (exact execution)
    assert ref.seed["source"] == "DIRECTIVE_SOURCE"


def test_strategy_dir_absent_code_degrades(env, monkeypatch):
    """strategies/<id>/ missing → code ABSENT, no crash (git stubbed to miss)."""
    import tools.resolve_baseline as rb

    full = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02_EURUSD"
    _make_ledger(
        env.db,
        [{"run_id": "d" * 24, "strategy": full, "symbol": "EURUSD",
          "is_current": "1", "profit_factor": "1.0"}],
    )
    _seed_single_asset_capsule(env, full)
    # No strategies/<base>/ dir created; stub git so it deterministically misses.
    monkeypatch.setattr(rb, "_code_in_git", lambda fs: None)

    ref = rb.resolve_baseline(full).references[0]
    assert ref.resolved is True          # still resolves (best-available)
    assert ref.code["source"] == "ABSENT"
    assert ref.homes["strategy_dir"] is None
    assert any("provenance_gap: code" in w for w in ref.warnings)
    # metrics still resolved from CSV — degradation is localized to code
    assert ref.metrics["source"] == "csv_stage1"


def test_handle_not_found(env):
    """A handle with no ledger row resolves false (exit 1)."""
    import tools.resolve_baseline as rb

    _make_ledger(env.db, [])
    result = rb.resolve_baseline("99_ZZZ_FX_1H_NOPE_S00_V1_P00_EURUSD")
    assert result.resolved is False
    assert len(result.references) == 1
    assert result.references[0].resolved is False


def test_require_seed_unmet_marks_unresolved(env, monkeypatch):
    """--require seed downgrades a reference whose seed is ABSENT."""
    import tools.resolve_baseline as rb

    full = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02_EURUSD"
    _make_ledger(
        env.db,
        [{"run_id": "e" * 24, "strategy": full, "symbol": "EURUSD",
          "is_current": "1", "profit_factor": "1.0"}],
    )
    _seed_single_asset_capsule(env, full)
    # No directive anywhere + git stubbed to miss → seed ABSENT.
    monkeypatch.setattr(rb, "_recover_seed_via_git", lambda fs, b: (None, "git"))

    result = rb.resolve_baseline(full, require="seed")
    assert result.references[0].resolved is False


def test_superseded_followed_to_successor(env):
    """No is_current row but superseded_by points to a live successor."""
    import tools.resolve_baseline as rb

    full = "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02_EURUSD"
    succ = "f" * 24
    old = "1" * 24
    _make_ledger(
        env.db,
        [
            {"run_id": old, "strategy": full, "symbol": "EURUSD",
             "is_current": "0", "superseded_by": succ, "profit_factor": "1.0"},
            {"run_id": succ, "strategy": full, "symbol": "EURUSD",
             "is_current": "1", "profit_factor": "1.5"},
        ],
    )
    _seed_single_asset_capsule(env, full)

    # Resolve by the superseded run_id → should follow to the successor.
    ref = rb.resolve_baseline(old).references[0]
    assert ref.resolved
    assert ref.run_id == succ


# ---------------------------------------------------------------------------
# Series-tag (cohort) resolution — cointegration_sheet + anchored matching
# (frictions #1/#2 from the 2026-06-12 HF55 hypothesis session)
# ---------------------------------------------------------------------------

_COINT_COLS = [
    "run_id", "directive_id", "pair_a", "pair_b", "is_current",
    "canonical_net_pct", "canonical_ret_dd", "canonical_max_dd_pct",
    "cycle_win_rate_pct", "cycles_completed", "trades_total",
]


def _make_coint_sheet(db_path: Path, rows: list[dict]) -> None:
    """Add a minimal cointegration_sheet to the temp ledger."""
    conn = sqlite3.connect(str(db_path))
    cols_sql = ", ".join(f'"{c}" TEXT' for c in _COINT_COLS)
    conn.execute(f"CREATE TABLE cointegration_sheet ({cols_sql})")
    for r in rows:
        placeholders = ", ".join("?" for _ in _COINT_COLS)
        conn.execute(
            f'INSERT INTO cointegration_sheet ({", ".join(_COINT_COLS)}) '
            f"VALUES ({placeholders})",
            tuple(r.get(c) for c in _COINT_COLS),
        )
    conn.commit()
    conn.close()


def test_series_tag_resolves_from_cointegration_sheet(env):
    """A COINTREV cohort tag (rows only in cointegration_sheet, not
    basket_sheet) resolves to the top-ret_dd member with the row's canonical
    metrics — previously returned 'matched no cohort member'."""
    from tools.resolve_baseline import resolve_baseline

    _make_ledger(env.db, [])  # master_filter exists but is empty
    _make_coint_sheet(env.db, [
        {"run_id": "a" * 24,
         "directive_id": "90_PORT_AAABBB_15M_X_V3_L30_GP_ZCRS_CXN1_Z25__E240101",
         "pair_a": "AAA", "pair_b": "BBB", "is_current": 1,
         "canonical_net_pct": "5.0", "canonical_ret_dd": "0.5",
         "canonical_max_dd_pct": "4.0", "cycle_win_rate_pct": "60",
         "cycles_completed": "10", "trades_total": "20"},
        {"run_id": "b" * 24,
         "directive_id": "90_PORT_CCCDDD_15M_X_V3_L30_GP_ZCRS_CXN1_Z25__E240202",
         "pair_a": "CCC", "pair_b": "DDD", "is_current": 1,
         "canonical_net_pct": "9.0", "canonical_ret_dd": "2.5",
         "canonical_max_dd_pct": "3.0", "cycle_win_rate_pct": "70",
         "cycles_completed": "12", "trades_total": "24"},
    ])

    res = resolve_baseline("GP_ZCRS_CXN1_Z25")
    assert res.resolved, res.to_dict()
    ref = res.references[0]
    assert ref.is_cohort is True
    assert "cointegration_sheet" in (ref.note or "")
    assert "of 2 cohort members" in (ref.note or "")
    # top ret_dd member wins (2.5 > 0.5)
    assert ref.run_id == "b" * 24
    assert float(ref.metrics["canonical_ret_dd"]) == 2.5


def test_series_tag_anchored_excludes_sibling_cohorts(env):
    """A tag that is a prefix of a sibling cohort's tag (Z25 vs Z25_HF55)
    must match ONLY the anchored rows — bare substring matching previously
    pulled 944 rows into a 475-row cohort lock."""
    from tools.resolve_baseline import resolve_baseline

    _make_ledger(env.db, [])
    base = "90_PORT_AAABBB_15M_X_V3_L30_GP_ZCRS_CXN1_Z25"
    _make_coint_sheet(env.db, [
        {"run_id": "a" * 24, "directive_id": base + "__E240101",
         "pair_a": "AAA", "pair_b": "BBB", "is_current": 1,
         "canonical_net_pct": "1.0", "canonical_ret_dd": "0.5",
         "canonical_max_dd_pct": "4.0", "cycle_win_rate_pct": "60",
         "cycles_completed": "10", "trades_total": "20"},
        {"run_id": "c" * 24, "directive_id": base + "_HF55__E240101",
         "pair_a": "AAA", "pair_b": "BBB", "is_current": 1,
         "canonical_net_pct": "2.0", "canonical_ret_dd": "9.9",
         "canonical_max_dd_pct": "2.0", "cycle_win_rate_pct": "65",
         "cycles_completed": "8", "trades_total": "16"},
    ])

    res = resolve_baseline("GP_ZCRS_CXN1_Z25")
    ref = res.references[0]
    # The sibling (higher ret_dd) must NOT be selected: anchored match only.
    assert "of 1 cohort members" in (ref.note or ""), ref.note
    assert ref.run_id == "a" * 24

    # And the sibling tag itself resolves to its own single row.
    res2 = resolve_baseline("GP_ZCRS_CXN1_Z25_HF55")
    ref2 = res2.references[0]
    assert "of 1 cohort members" in (ref2.note or "")
    assert ref2.run_id == "c" * 24
