"""Tests for build_cointegration_row (P3 orchestration-side assembler).

Synthetic screener DB (patched into the gate) + a directive dict + a synthetic
canonical-metrics dict -> assert the assembled row. No parquet is read (the
assembler takes canonical metrics as a parameter).
"""
import datetime as dt
import sqlite3

import yaml

import tools.window_validity_gate as gate
from tools.portfolio.cointegration_provenance import build_cointegration_row


def _daily(start, regimes):
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=i)).isoformat(), r) for i, r in enumerate(regimes)]


def _setup_screener(tmp_path, monkeypatch, pair_a, pair_b, lookback, rows, tf="1d"):
    db = tmp_path / "cointegration.db"
    c = sqlite3.connect(str(db))
    c.execute(
        "CREATE TABLE cointegration_daily ("
        " as_of TEXT, pair_a TEXT, pair_b TEXT, tf TEXT,"
        " lookback_days INTEGER, regime TEXT)"
    )
    c.executemany(
        "INSERT INTO cointegration_daily VALUES (?,?,?,?,?,?)",
        [(d, pair_a, pair_b, tf, lookback, r) for d, r in rows],
    )
    c.commit()
    c.close()
    monkeypatch.setattr(gate, "DB_PATH", db)


def _directive_doc(symbols, lookback, start, end, tf="1d", override=None):
    cj = {"lookback_days": lookback}
    if override is not None:
        cj["methodology_override"] = override
    return {
        "test": {"start_date": start, "end_date": end, "timeframe": tf},
        "basket": {
            "legs": [{"symbol": s, "lot": 0.1, "direction": "long"} for s in symbols],
            "cointegration_join": cj,
        },
    }


_CANON = {
    "net_pct": 12.5, "max_dd_pct": 8.0, "max_dd_pct_vs_stake": 6.4,
    "ret_dd": 1.56, "final_equity_usd": 1125.0,
    "cycle_win_rate_pct": 55.0, "cycles_completed": 11,
}


def _write(tmp_path, doc):
    p = tmp_path / "d.txt"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def test_build_row_pass_window(tmp_path, monkeypatch):
    _setup_screener(tmp_path, monkeypatch, "EURUSD", "GER40", 252,
                    _daily("2024-01-01", ["cointegrated"] * 400))
    # legs reversed in the directive -> assembler must canonical-order them
    doc = _directive_doc(["GER40", "EURUSD"], 252, "2024-03-01", "2024-10-01")
    d = _write(tmp_path, doc)

    row = build_cointegration_row(
        parsed=doc, directive_path=d, run_id="R1", directive_id="DIR1",
        directive_hash="abc123", backtests_path="backtests/x", vault_path="vault/x",
        canonical=_CANON, trades_total=42,
        completed_at_utc="2026-05-28T00:00:00Z", stake_usd=1000.0,
        n_obs=400, parquet_sha256="deadbeef", engine_version="1.5.8",
    )

    assert row["pair_a"] == "EURUSD" and row["pair_b"] == "GER40"
    assert row["timeframe"] == "1d"
    assert row["lookback_days"] == 252
    assert row["test_start"] == "2024-03-01" and row["test_end"] == "2024-10-01"
    assert "EURUSD" in row["leg_specs"] and "GER40" in row["leg_specs"]
    assert row["window_validation_status"] == "PASS"
    assert row["span_start"] == "2024-01-01"
    assert row["continuous_span_obs"] == 400
    assert row["fragment_count"] == 1
    assert row["pct_cointegrated"] == 1.0
    assert row["regime_state"] == "cointegrated"
    assert row["canonical_ret_dd"] == 1.56
    assert row["canonical_max_dd_pct_vs_stake"] == 6.4
    assert row["cycles_completed"] == 11
    assert row["trades_total"] == 42
    assert row["directive_sha256"] == "abc123"
    assert row["engine_version"] == "1.5.8"
    assert row["parquet_sha256"] == "deadbeef"
    assert row["strategy_code_sha256"] is None  # baskets have no strategy.py


def test_default_methodology_is_v2_log_eg(tmp_path, monkeypatch):
    """Default methodology_version is the screener's active cohort (v2_log_eg).

    Frozen by this test against accidental drift; flipped from v1_raw_adf on
    2026-05-30 once the pair screener migrated to log-price Engle-Granger.
    Callers may still override; this only pins the default."""
    _setup_screener(tmp_path, monkeypatch, "EURUSD", "GER40", 252,
                    _daily("2024-01-01", ["cointegrated"] * 400))
    doc = _directive_doc(["EURUSD", "GER40"], 252, "2024-03-01", "2024-10-01")
    d = _write(tmp_path, doc)

    row = build_cointegration_row(
        parsed=doc, directive_path=d, run_id="R_DEF", directive_id="DIR_DEF",
        directive_hash="h", backtests_path="backtests/z", vault_path="",
        canonical=_CANON, trades_total=1,
        completed_at_utc="2026-05-30T00:00:00Z", stake_usd=1000.0,
        engine_version="1.5.9",
    )

    assert row["methodology_version"] == "v2_log_eg"


def test_build_row_override_window(tmp_path, monkeypatch):
    _setup_screener(tmp_path, monkeypatch, "EURUSD", "GER40", 252,
                    _daily("2024-01-01", ["broken"] * 200))  # never aligned
    doc = _directive_doc(["EURUSD", "GER40"], 252, "2024-03-01", "2024-09-01",
                         override="deliberate out-of-regime probe")
    d = _write(tmp_path, doc)

    row = build_cointegration_row(
        parsed=doc, directive_path=d, run_id="R2", directive_id="DIR2",
        directive_hash="h", backtests_path="backtests/y", vault_path="",
        canonical=_CANON, trades_total=5,
        completed_at_utc="2026-05-28T00:00:00Z", stake_usd=1000.0,
        engine_version="1.5.9",
    )

    assert row["window_validation_status"] == "OVERRIDE"
    assert row["fragment_count"] == 0          # never aligned -> no spans
    assert row["span_start"] is None
    assert row["regime_state"] == "broken"
