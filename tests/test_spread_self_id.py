"""R9 cost-regime self-identification (2026-06-17): a basket run self-reports
its cost basis on two queryable ledger columns, closing the gap that the old
`execution_model_version` left -- it lived in the RESEARCH preamble (CSV
comment="#") with 0 code readers, so a run never recorded which cost regime
applied.

  spread_coverage_pct  -- MEASURED min-across-legs % of consumed bars with
                          spread>0 (catches the XAU spread=0 acquisition gap
                          that silently zero-charged a leg -- the failure that
                          motivated R9). Data axis.
  execution_cost_model -- DERIVED from the imported compute ABI via the
                          basket_runner SSOT (override-inert, as honest as
                          engine_abi -- never an independently-set stamp).
                          Engine axis.

Together: WHERE execution_cost_model LIKE '%charged%' AND spread_coverage_pct >=
99  ==  the "genuinely charged, decision-grade" filter the v1.5.10 canonical
flip must certify rows against. Both nullable (pre-2026-06-17 rows = NULL).
This change is INERT: it adds observability only -- no compute changes, no
canonical flip. See memory engine_identity_is_compute_not_stamp.
"""
import inspect
import sqlite3

import pandas as pd

from tools.basket_provenance import (
    basket_input_provenance,
    execution_cost_model,
    leg_spread_coverage_pct,
    min_spread_coverage_pct,
    single_asset_cost_model,
)
from tools.ledger_db import create_tables, upsert_cointegration_row
from tools.portfolio.cointegration_provenance import build_cointegration_row
from tools.portfolio.cointegration_schema import (
    COINTEGRATION_NUMERIC_COLUMNS,
    COINTEGRATION_SHEET_COLUMNS,
)


def _df(spreads):
    """A minimal consumed-leg frame: OHLCV + the `spread` column the engine
    charges off."""
    n = len(spreads)
    return pd.DataFrame({
        "open": [1.0] * n, "high": [1.0] * n, "low": [1.0] * n,
        "close": [1.0] * n, "volume": [1] * n, "spread": spreads,
    })


# --- leg_spread_coverage_pct (MEASURED, data axis) -------------------------

def test_full_coverage_is_100():
    assert leg_spread_coverage_pct(_df([2.0, 1.5, 3.0, 2.2])) == 100.0


def test_half_zero_spread_is_50():
    # The XAU-gap signature: half the bars carry a 0 spread the engine cannot
    # charge -> the leg self-reports 50% coverage.
    assert leg_spread_coverage_pct(_df([2.0, 0.0, 3.0, 0.0])) == 50.0


def test_all_zero_spread_is_0():
    assert leg_spread_coverage_pct(_df([0.0, 0.0, 0.0])) == 0.0


def test_missing_spread_column_is_null():
    df = pd.DataFrame({"open": [1.0], "close": [1.0]})
    assert leg_spread_coverage_pct(df) is None


def test_empty_or_none_frame_is_null():
    assert leg_spread_coverage_pct(_df([])) is None
    assert leg_spread_coverage_pct(None) is None


# --- min_spread_coverage_pct (binding-leg fold) ----------------------------

def test_min_picks_the_binding_worst_leg():
    # A basket is only as spread-faithful as its least-covered leg.
    assert min_spread_coverage_pct({"EURUSD": 100.0, "XAUUSD": 23.0}) == 23.0


def test_min_ignores_none_legs():
    assert min_spread_coverage_pct({"EURUSD": 100.0, "BTCUSD": None}) == 100.0


def test_min_all_none_or_empty_is_null():
    assert min_spread_coverage_pct({"A": None, "B": None}) is None
    assert min_spread_coverage_pct({}) is None
    assert min_spread_coverage_pct(None) is None


# --- execution_cost_model (DERIVED from compute ABI, engine axis) ----------

def test_v1_5_9_maps_to_uncharged():
    assert execution_cost_model("engine_abi.v1_5_9") == "spread_uncosted_roundtrip_v1_5_9"


def test_v1_5_10_maps_to_charged():
    assert execution_cost_model("engine_abi.v1_5_10") == "spread_charged_diraware_v1_5_10"


def test_uncharged_label_does_not_collide_with_charged_filter():
    """The decision-grade filter is `LIKE 'spread_charged%'`; the uncharged
    label must NOT trip it (the substring "charged" lives inside "uncharged",
    which is exactly the bug this label scheme is designed to dodge)."""
    uncharged = execution_cost_model("engine_abi.v1_5_9")
    assert "charged" not in uncharged
    assert not uncharged.startswith("spread_charged")


def test_unknown_abi_is_visibly_unspecified_not_silently_mislabeled():
    assert execution_cost_model("engine_abi.v9_9_9") == "unspecified:engine_abi.v9_9_9"


def test_none_abi_is_null():
    assert execution_cost_model(None) is None
    assert execution_cost_model("") is None


# --- single_asset_cost_model (DERIVED from engine_version, single-asset axis) -

def test_single_asset_v1_5_10_maps_to_charged():
    # The single-asset execution_loop charges direction-aware spread at v1.5.10.
    assert single_asset_cost_model("1.5.10") == "spread_charged_diraware_v1_5_10"


def test_single_asset_charged_label_matches_basket():
    # A charged single-asset run must read identically to a charged basket leg
    # so one `LIKE 'spread_charged%'` filter spans both paths.
    assert single_asset_cost_model("1.5.10") == execution_cost_model("engine_abi.v1_5_10")


def test_single_asset_pre_v1_5_10_is_none_applied():
    # Every uncharged single-asset engine (the FROZEN v1.5.8 default + older)
    # keeps the backward-compatible 'none_applied' it always carried.
    assert single_asset_cost_model("1.5.8") == "none_applied"
    assert single_asset_cost_model("1.5.6") == "none_applied"


def test_single_asset_blank_version_is_none_applied():
    assert single_asset_cost_model(None) == "none_applied"
    assert single_asset_cost_model("") == "none_applied"


def test_current_basket_compute_self_reports_a_recognized_regime():
    """The field earns its keep immediately: the LIVE basket ABI (basket_runner
    SSOT) maps to a recognized cost regime, never `unspecified`. Today that is
    the UNCHARGED v1_5_9 -- the canonical flip will move ENGINE_ABI to v1_5_10
    and this assertion will then read the charged regime, with no code change
    here (the mapping covers both)."""
    from tools.basket_runner import ENGINE_ABI

    model = execution_cost_model(ENGINE_ABI)
    assert model is not None
    assert not model.startswith("unspecified:"), (
        f"live basket ABI {ENGINE_ABI!r} is not in the cost-model map -- add it "
        f"so runs keep self-identifying across the engine bump"
    )


# --- schema + DDL + wiring locks -------------------------------------------

def test_columns_in_authoritative_schema_with_correct_types():
    assert "spread_coverage_pct" in COINTEGRATION_SHEET_COLUMNS
    assert "execution_cost_model" in COINTEGRATION_SHEET_COLUMNS
    # measured pct is REAL; the derived label is TEXT.
    assert "spread_coverage_pct" in COINTEGRATION_NUMERIC_COLUMNS
    assert "execution_cost_model" not in COINTEGRATION_NUMERIC_COLUMNS


def test_columns_materialize_in_the_ddl(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        create_tables(conn)
        cols = {r[1] for r in conn.execute(
            'PRAGMA table_info("cointegration_sheet")').fetchall()}
        assert {"spread_coverage_pct", "execution_cost_model"} <= cols
    finally:
        conn.close()


def test_input_provenance_emits_per_leg_coverage():
    prov = basket_input_provenance(
        {"EURUSD": _df([2.0, 2.0]), "XAUUSD": _df([0.0, 0.0])}, "1.5.9",
    )
    assert prov["spread_coverage_pct"] == {"EURUSD": 100.0, "XAUUSD": 0.0}


def test_assembler_exposes_and_carries_both_fields():
    params = inspect.signature(build_cointegration_row).parameters
    assert "spread_coverage_pct" in params
    assert "execution_cost_model" in params


def test_assembler_floats_coverage_and_passes_cost_model(tmp_path, monkeypatch):
    import tools.window_validity_gate as gate

    db = tmp_path / "cointegration.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE cointegration_daily (as_of TEXT, pair_a TEXT, "
              "pair_b TEXT, tf TEXT, lookback_days INTEGER, regime TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(gate, "DB_PATH", db)

    import yaml
    doc = {
        "test": {"start_date": "2024-03-01", "end_date": "2024-10-01", "timeframe": "1d"},
        "basket": {"legs": [{"symbol": "EURUSD", "lot": 0.1, "direction": "long"},
                            {"symbol": "GER40", "lot": 0.1, "direction": "long"}],
                   "cointegration_join": {"lookback_days": 252}},
    }
    p = tmp_path / "d.txt"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")

    row = build_cointegration_row(
        parsed=doc, directive_path=p, run_id="R_SELFID", directive_id="DIR_SELFID",
        directive_hash="h", backtests_path="backtests/x", vault_path="",
        canonical={"net_pct": 1.0, "max_dd_pct": 1.0, "ret_dd": 1.0,
                   "final_equity_usd": 1010.0},
        trades_total=3, completed_at_utc="2026-06-17T00:00:00Z", stake_usd=1000.0,
        engine_version="1.5.9", spread_coverage_pct=42,
        execution_cost_model="spread_uncosted_roundtrip_v1_5_9",
    )
    assert row["spread_coverage_pct"] == 42.0
    assert isinstance(row["spread_coverage_pct"], float)
    assert row["execution_cost_model"] == "spread_uncosted_roundtrip_v1_5_9"


def test_ledger_query_isolates_charged_decision_grade_rows(tmp_path):
    """End-to-end success criterion: one ledger query isolates the genuinely
    charged, full-coverage rows from uncharged or thin-spread ones."""
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        create_tables(conn)
        upsert_cointegration_row(conn, {  # charged + full coverage -> decision-grade
            "run_id": "charged_full", "execution_cost_model": "spread_charged_diraware_v1_5_10",
            "spread_coverage_pct": 100.0})
        upsert_cointegration_row(conn, {  # charged but XAU-gap thin coverage -> excluded
            "run_id": "charged_thin", "execution_cost_model": "spread_charged_diraware_v1_5_10",
            "spread_coverage_pct": 23.0})
        upsert_cointegration_row(conn, {  # uncharged engine -> excluded (and must
                                          # not trip the 'charged' filter)
            "run_id": "uncharged", "execution_cost_model": "spread_uncosted_roundtrip_v1_5_9",
            "spread_coverage_pct": 100.0})
        conn.commit()
        decision_grade = {r[0] for r in conn.execute(
            "SELECT run_id FROM cointegration_sheet WHERE execution_cost_model "
            "LIKE 'spread_charged%' AND spread_coverage_pct >= 99").fetchall()}
        assert decision_grade == {"charged_full"}
    finally:
        conn.close()
