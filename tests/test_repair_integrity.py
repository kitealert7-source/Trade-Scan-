"""Regression: repair_integrity.py contract.

Two actions:
  * --action drop (default): rows whose disk artifacts are gone are dropped.
    Operator-driven cleanup is the documented exception to the append-only
    ledger invariant (CLAUDE.md #2). LINEAGE_PROTECTED_TAGS rows (SUPERSEDED
    / ARCHIVED_UNRESOLVED from H3 rehab batches) are preserved on drop.
  * --action mark: rows are tagged ARCHIVED_DEPENDENCY_LOST instead. Mark
    mode is idempotent and never overwrites an existing tag.

Both actions share the multi-sheet-safe writer (Portfolios + SAC + Baskets +
Notes all survive) and the dry-run default. The pre-2026-05-26 implementation
had a critical data-loss bug here (single-sheet write would delete SAC +
Baskets + Notes on every run); this test file guards that fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.state_lifecycle import repair_integrity as ri


def _write_fsp(path: Path, rows: list[dict]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Sheet1", index=False)
        pd.DataFrame([{"note": "preserved Notes row"}]).to_excel(
            writer, sheet_name="Notes", index=False
        )


def _write_mps(path: Path, portfolios: list[dict], sac: list[dict],
               baskets: list[dict] | None = None,
               notes: list[dict] | None = None,
               cointegration: list[dict] | None = None) -> None:
    baskets = baskets or [{"basket_id": "H2", "directive_id": "X1",
                           "verdict_status": "CORE", "quarantine_status": None}]
    notes = notes or [{"note": "preserved baskets-Notes row"}]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(portfolios).to_excel(writer, sheet_name="Portfolios", index=False)
        pd.DataFrame(sac).to_excel(writer, sheet_name="Single-Asset Composites", index=False)
        pd.DataFrame(baskets).to_excel(writer, sheet_name="Baskets", index=False)
        # Cointegration is a lossy projected view (no run_id). Written only when
        # a coint test needs the tab present; the drop path re-renders it.
        if cointegration is not None:
            pd.DataFrame(cointegration).to_excel(writer, sheet_name="Cointegration", index=False)
        pd.DataFrame(notes).to_excel(writer, sheet_name="Notes", index=False)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Stage a tmp workspace with planted valid artifacts:
       - RID_A: valid (folder + JSON planted)
       - RID_X: orphan
       - PF_LIVE: deployed folder planted
       - PF_DEAD / SAC_DEAD: no folder
    """
    fsp = tmp_path / "fsp.xlsx"
    mps = tmp_path / "mps.xlsx"
    runs = tmp_path / "runs"
    backtests = tmp_path / "backtests"
    sandbox = tmp_path / "sandbox"
    strategies = tmp_path / "strategies"
    runs.mkdir(); backtests.mkdir(); sandbox.mkdir(); strategies.mkdir()

    (runs / "RID_A").mkdir()
    (backtests / "RID_A.json").write_text("{}", encoding="utf-8")
    (strategies / "PF_LIVE").mkdir()

    monkeypatch.setattr(ri, "FILTERED_SHEET_PATH", fsp)
    monkeypatch.setattr(ri, "MASTER_SHEET_PATH", mps)
    monkeypatch.setattr(ri, "RUNS_DIR", runs)
    monkeypatch.setattr(ri, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(ri, "SANDBOX_DIR", sandbox)
    monkeypatch.setattr(ri, "STRATEGIES_DIR", strategies)
    # CRITICAL isolation: point the cointegration arm at a tmp DB. Without this
    # scan_cointegration()/apply_cointegration_drop() hit the REAL ledger.db and,
    # because the disk dirs above are empty tmp dirs, flag every real is_current=1
    # coint row as an orphan and DELETE it. (That exact gap deleted 15 production
    # rows on 2026-05-28 before this line existed.) The tmp DB has no
    # cointegration_sheet table, so the arm is a clean no-op for the legacy tests.
    monkeypatch.setattr(ri, "LEDGER_DB_PATH", tmp_path / "ledger.db")
    monkeypatch.setattr(ri, "_reformat", lambda path, profile: None)
    return fsp, mps


# ---------------------------------------------------------------------------
# Shared invariants (both actions)
# ---------------------------------------------------------------------------


def test_dry_run_does_not_mutate(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}, {"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
    )
    before_fsp = pd.read_excel(fsp)
    before_mps = pd.read_excel(mps, sheet_name="Portfolios")

    rc_drop = ri.main_via_args([])  # default drop, dry-run
    rc_mark = ri.main_via_args(["--action", "mark"])  # mark, dry-run

    assert rc_drop == 0 and rc_mark == 0
    pd.testing.assert_frame_equal(before_fsp, pd.read_excel(fsp))
    pd.testing.assert_frame_equal(before_mps, pd.read_excel(mps, sheet_name="Portfolios"))


def test_all_sheets_preserved_after_execute(staged):
    """The headline data-loss guard. Pre-rewrite to_excel() deleted SAC + Baskets + Notes."""
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
        baskets=[{"basket_id": "H2", "directive_id": "PRESERVED_DIR",
                  "verdict_status": "CORE", "quarantine_status": None}],
        notes=[{"note": "MUST_NOT_BE_LOST"}],
    )

    rc = ri.main_via_args(["--execute"])  # drop, execute
    assert rc == 0

    post_sheets = pd.ExcelFile(mps).sheet_names
    assert {"Portfolios", "Single-Asset Composites", "Baskets", "Notes"} <= set(post_sheets)
    assert "PRESERVED_DIR" in pd.read_excel(mps, sheet_name="Baskets")["directive_id"].values
    assert "MUST_NOT_BE_LOST" in pd.read_excel(mps, sheet_name="Notes")["note"].values
    assert "Notes" in pd.ExcelFile(fsp).sheet_names


# ---------------------------------------------------------------------------
# Drop mode (default)
# ---------------------------------------------------------------------------


def test_drop_removes_orphan_rows(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}, {"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"},
        ],
        sac=[{"portfolio_id": "SAC_DEAD", "constituent_run_ids": "RID_X"}],
    )

    rc = ri.main_via_args(["--execute"])  # default drop
    assert rc == 0

    fsp_after = pd.read_excel(fsp)
    assert list(fsp_after["run_id"]) == ["RID_A"]
    assert list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"]) == ["PF_LIVE"]
    assert pd.read_excel(mps, sheet_name="Single-Asset Composites").empty


def test_drop_preserves_lineage_protected_tags(staged):
    """SUPERSEDED / ARCHIVED_UNRESOLVED rows survive drop — those are explicit
    audit decisions from the H3 rehab pattern."""
    fsp, mps = staged
    _write_fsp(fsp, [])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_SUPERSEDED", "constituent_run_ids": "RID_X",
             "quarantine_status": "SUPERSEDED"},
            {"portfolio_id": "PF_UNRESOLVED", "constituent_run_ids": "RID_X",
             "quarantine_status": "ARCHIVED_UNRESOLVED"},
            {"portfolio_id": "PF_TOMBSTONE", "constituent_run_ids": "RID_X",
             "quarantine_status": "ARCHIVED_DEPENDENCY_LOST"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X",
             "quarantine_status": None},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    survivors = list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"])
    assert "PF_SUPERSEDED" in survivors
    assert "PF_UNRESOLVED" in survivors
    assert "PF_TOMBSTONE" not in survivors  # soft tombstone — drop removes
    assert "PF_DEAD" not in survivors


def test_drop_handles_missing_folder_orphans(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_NO_FOLDER", "constituent_run_ids": "RID_A"},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    survivors = list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"])
    assert survivors == ["PF_LIVE"]


# ---------------------------------------------------------------------------
# Mark mode
# ---------------------------------------------------------------------------


def test_mark_tags_orphan_rows_without_dropping(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}, {"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"},
        ],
        sac=[{"portfolio_id": "SAC_DEAD", "constituent_run_ids": "RID_X"}],
    )

    rc = ri.main_via_args(["--action", "mark", "--execute"])
    assert rc == 0

    fsp_after = pd.read_excel(fsp)
    assert set(fsp_after["run_id"]) == {"RID_A", "RID_X"}
    x_row = fsp_after[fsp_after.run_id == "RID_X"].iloc[0]
    assert bool(x_row["quarantined"]) is True

    mps_p = pd.read_excel(mps, sheet_name="Portfolios")
    dead = mps_p[mps_p.portfolio_id == "PF_DEAD"].iloc[0]
    assert dead["quarantine_status"] == "ARCHIVED_DEPENDENCY_LOST"
    assert "RID_X" in str(dead["quarantine_reason"])
    live = mps_p[mps_p.portfolio_id == "PF_LIVE"].iloc[0]
    qstat_live = live.get("quarantine_status")
    assert pd.isna(qstat_live) or qstat_live in (None, "")


def test_mark_does_not_overwrite_existing_tag(staged):
    fsp, mps = staged
    _write_fsp(fsp, [])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_SUPER", "constituent_run_ids": "RID_X",
             "quarantine_status": "SUPERSEDED", "quarantine_reason": "from H3 rehab"},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--action", "mark", "--execute"])
    assert rc == 0
    row = pd.read_excel(mps, sheet_name="Portfolios").iloc[0]
    assert row["quarantine_status"] == "SUPERSEDED"
    assert row["quarantine_reason"] == "from H3 rehab"


def test_idempotent_second_run_is_noop(staged):
    """Both modes should produce identical state on a second --execute pass."""
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
    )

    rc1 = ri.main_via_args(["--action", "mark", "--execute"])
    state_1 = pd.read_excel(mps, sheet_name="Portfolios")

    rc2 = ri.main_via_args(["--action", "mark", "--execute"])
    state_2 = pd.read_excel(mps, sheet_name="Portfolios")

    assert rc1 == 0 and rc2 == 0
    pd.testing.assert_frame_equal(state_1, state_2)


# ---------------------------------------------------------------------------
# Cointegration arm (DB-canonical; the tab is a lossy projected view)
# ---------------------------------------------------------------------------


@pytest.fixture
def staged_coint(tmp_path, monkeypatch):
    """Stage a fully DB-isolated workspace for the cointegration drop arm.

    Unlike `staged`, this also patches config.path_authority.TRADE_SCAN_STATE so
    the writer (append_cointegration_row) and the tool resolve the SAME tmp
    ledger.db — never the real one. (The real DB was wiped once by a test that
    lacked exactly this isolation.)
    """
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path)

    fsp = tmp_path / "fsp.xlsx"
    mps = tmp_path / "mps.xlsx"
    for sub in ("runs", "backtests", "sandbox", "strategies"):
        (tmp_path / sub).mkdir()

    monkeypatch.setattr(ri, "FILTERED_SHEET_PATH", fsp)
    monkeypatch.setattr(ri, "MASTER_SHEET_PATH", mps)
    monkeypatch.setattr(ri, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(ri, "BACKTESTS_DIR", tmp_path / "backtests")
    monkeypatch.setattr(ri, "SANDBOX_DIR", tmp_path / "sandbox")
    monkeypatch.setattr(ri, "STRATEGIES_DIR", tmp_path / "strategies")
    monkeypatch.setattr(ri, "LEDGER_DB_PATH", tmp_path / "ledger.db")
    monkeypatch.setattr(ri, "_reformat", lambda path, profile: None)

    _write_fsp(fsp, [])
    _write_mps(mps, portfolios=[], sac=[],
               cointegration=[{"rank": 1, "pair": "seed/seed"}])
    return tmp_path, fsp, mps


def _seed_coint_row(tmp_path, run_id, directive_id, basket_id, *,
                    make_valid, pair_a="EURUSD", pair_b="GER40"):
    """Append one cointegration_sheet row to the tmp DB, then arrange disk to
    make it valid (backtest parquet present) or orphan (substrate rm -rf'd).

    The writer requires backtests_path to exist at write time, so the dir is
    created first; for an orphan we delete it afterwards (the operator rm -rf).
    """
    from tools.portfolio.cointegration_ledger_writer import append_cointegration_row
    bt_folder = f"{directive_id}_{basket_id}"
    btdir = tmp_path / "backtests" / bt_folder
    (btdir / "raw").mkdir(parents=True, exist_ok=True)
    append_cointegration_row({
        "run_id": run_id,
        "directive_id": directive_id,
        "pair_a": pair_a,
        "pair_b": pair_b,
        "timeframe": "1d",
        "lookback_days": 252,
        "test_start": "2025-01-01",
        "test_end": "2025-06-01",
        "completed_at_utc": "2026-05-28T12:00:00Z",
        "backtests_path": f"backtests/{bt_folder}",
        "canonical_net_pct": 12.5,
        "canonical_max_dd_pct": 8.0,
        "canonical_ret_dd": 1.56,
        "canonical_final_equity_usd": 1125.0,
        "trades_total": 42,
        "methodology_version": "v1_raw_adf",
        "engine_version": "1.5.9",
    })
    if make_valid:
        # backtests-aware validity: parquet present even though runs/<id>/ is not.
        (btdir / "raw" / "results_basket_per_bar.parquet").write_bytes(b"PAR1")
    else:
        import shutil
        shutil.rmtree(btdir)  # operator rm -rf -> orphan


def _coint_current_run_ids(tmp_path) -> set[str]:
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        return {r[0] for r in conn.execute(
            "SELECT run_id FROM cointegration_sheet WHERE is_current = 1"
        )}
    finally:
        conn.close()


def test_coint_drop_removes_orphan_keeps_valid(staged_coint):
    """Drop deletes the orphan coint row from the DB and keeps the one whose
    backtest substrate survives (basket-aware validity)."""
    tmp, fsp, mps = staged_coint
    _seed_coint_row(tmp, "RIDCOINTVALID", "90_PORT_VALID_1D", "EURUSDGER40",
                    make_valid=True, pair_a="EURUSD", pair_b="GER40")
    _seed_coint_row(tmp, "RIDCOINTORPH", "90_PORT_ORPH_1D", "CADJPYUK100",
                    make_valid=False, pair_a="CADJPY", pair_b="UK100")
    assert _coint_current_run_ids(tmp) == {"RIDCOINTVALID", "RIDCOINTORPH"}

    rc = ri.main_via_args(["--execute"])  # default drop
    assert rc == 0

    assert _coint_current_run_ids(tmp) == {"RIDCOINTVALID"}
    # xlsx tab re-rendered from the post-drop DB: only the valid row remains.
    tab = pd.read_excel(mps, sheet_name="Cointegration")
    assert len(tab) == 1
    assert tab.iloc[0]["pair"] == "EURUSD / GER40"


def test_coint_dry_run_does_not_delete(staged_coint):
    tmp, fsp, mps = staged_coint
    _seed_coint_row(tmp, "RIDCOINTORPH", "90_PORT_ORPH_1D", "CADJPYUK100",
                    make_valid=False)
    rc = ri.main_via_args([])  # dry-run, drop
    assert rc == 0
    assert _coint_current_run_ids(tmp) == {"RIDCOINTORPH"}  # untouched


def test_coint_mark_is_noop(staged_coint):
    """Mark mode must not touch cointegration rows (no quarantine_status column;
    DB-native lineage). The orphan survives a mark --execute pass."""
    tmp, fsp, mps = staged_coint
    _seed_coint_row(tmp, "RIDCOINTORPH", "90_PORT_ORPH_1D", "CADJPYUK100",
                    make_valid=False)
    rc = ri.main_via_args(["--action", "mark", "--execute"])
    assert rc == 0
    assert _coint_current_run_ids(tmp) == {"RIDCOINTORPH"}  # mark left it alone


def test_coint_drop_preserves_all_sheets(staged_coint):
    """A coint drop re-renders the Cointegration tab without losing the other
    MPS data sheets."""
    tmp, fsp, mps = staged_coint
    _seed_coint_row(tmp, "RIDCOINTORPH", "90_PORT_ORPH_1D", "CADJPYUK100",
                    make_valid=False)
    rc = ri.main_via_args(["--execute"])
    assert rc == 0
    post = set(pd.ExcelFile(mps).sheet_names)
    assert {"Portfolios", "Single-Asset Composites", "Baskets",
            "Cointegration", "Notes"} <= post
    assert _coint_current_run_ids(tmp) == set()  # the only coint row was dropped


# ---------------------------------------------------------------------------
# Baskets DB-drop arm (durability of operator-driven cleanup across --export)
# ---------------------------------------------------------------------------


def _seed_basket_row(tmp_path: Path, run_id: str, directive_id: str,
                     basket_id: str, *, make_valid: bool) -> None:
    """Seed one basket_sheet DB row + (optionally) plant the disk artifacts
    that make it valid under is_valid_basket_run.

    Valid: backtests/<directive_id>_<basket_id>/raw/results_basket_per_bar.parquet
    is planted. Orphan: nothing is planted.
    """
    from tools.ledger_db import _connect, create_tables, upsert_basket_row
    conn = _connect()
    try:
        create_tables(conn)
        upsert_basket_row(conn, {
            "run_id": run_id,
            "directive_id": directive_id,
            "basket_id": basket_id,
            "execution_mode": "live",
            "rule_name": "test_rule",
            "rule_version": 1.0,
            "leg_count": 2,
            "leg_specs": "{}",
            "trades_total": 0,
            "completed_at_utc": "2026-05-31T00:00:00Z",
            "backtests_path": f"backtests/{directive_id}_{basket_id}",
        })
    finally:
        conn.close()
    if make_valid:
        btdir = tmp_path / "backtests" / f"{directive_id}_{basket_id}"
        (btdir / "raw").mkdir(parents=True, exist_ok=True)
        (btdir / "raw" / "results_basket_per_bar.parquet").write_bytes(b"PAR1")


def _basket_db_run_ids(tmp_path: Path) -> set[str]:
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        return {r[0] for r in conn.execute("SELECT run_id FROM basket_sheet")}
    finally:
        conn.close()


def test_drop_orphan_basket_row_survives_re_export(staged_coint):
    """Regression for the 2026-05-31 durability gap.

    Pre-fix, apply_baskets_drop only mutated the xlsx. The basket_sheet table
    still held the dropped row, so the next `ledger_db.py --export` rebuilt
    df_baskets from query_baskets() and silently re-emitted the orphan into
    the xlsx — making the operator-driven cleanup invisible at the next
    export trigger. The fix adds apply_baskets_db_drop, called from main()
    alongside the xlsx rewrite.

    This test seeds one valid + one orphan basket_sheet row, mirrors them in
    the xlsx Baskets tab, runs repair_integrity --execute, then RE-EXPORTS
    via ledger_db.export_mps() and asserts the orphan stays gone. The
    re-export step is the critical assertion: pre-fix it would have undone
    the cleanup.
    """
    tmp, fsp, mps = staged_coint

    _seed_basket_row(tmp, "RID_BSKVALID", "dir_valid", "H2", make_valid=True)
    _seed_basket_row(tmp, "RID_BSKORPH", "dir_orph", "H3", make_valid=False)

    # Mirror the DB state in the xlsx Baskets tab so scan_baskets (which
    # reads the xlsx, not the DB) flags the orphan.
    _write_mps(
        mps, portfolios=[], sac=[],
        baskets=[
            {"run_id": "RID_BSKVALID", "directive_id": "dir_valid",
             "basket_id": "H2", "verdict_status": "CORE",
             "quarantine_status": None},
            {"run_id": "RID_BSKORPH", "directive_id": "dir_orph",
             "basket_id": "H3", "verdict_status": "CORE",
             "quarantine_status": None},
        ],
        cointegration=[{"rank": 1, "pair": "seed/seed"}],
    )
    assert _basket_db_run_ids(tmp) == {"RID_BSKVALID", "RID_BSKORPH"}

    rc = ri.main_via_args(["--execute"])  # default drop
    assert rc == 0

    # DB: orphan deleted, valid preserved.
    assert _basket_db_run_ids(tmp) == {"RID_BSKVALID"}, \
        "Orphan basket_sheet row was not deleted from DB"

    # Xlsx: orphan removed by repair_integrity's own write.
    post_xlsx = pd.read_excel(mps, sheet_name="Baskets")
    assert "RID_BSKORPH" not in set(post_xlsx["run_id"])
    assert "RID_BSKVALID" in set(post_xlsx["run_id"])

    # THE REGRESSION CHECK: re-export from DB. Pre-fix, basket_sheet still
    # held the orphan, so this would re-emit it and overwrite the cleaned
    # xlsx. Post-fix, the DB no longer has the row → export keeps it gone.
    from tools.ledger_db import export_mps
    export_mps(output_path=mps)

    final_xlsx = pd.read_excel(mps, sheet_name="Baskets")
    assert "RID_BSKORPH" not in set(final_xlsx["run_id"]), \
        "Orphan reappeared after re-export — DB DELETE did not happen"
    assert "RID_BSKVALID" in set(final_xlsx["run_id"]), \
        "Valid basket row went missing after re-export"


def test_drop_basket_lineage_protected_not_db_deleted(staged_coint):
    """SUPERSEDED basket rows survive both the xlsx drop and the DB delete.

    apply_baskets_drop filters LINEAGE_PROTECTED_TAGS out of its drop set
    AND out of the run_ids it hands to apply_baskets_db_drop. A SUPERSEDED
    row whose disk is gone must remain in both the xlsx and basket_sheet —
    the tag is the explicit audit decision.
    """
    tmp, fsp, mps = staged_coint

    _seed_basket_row(tmp, "RID_BSKSUPER", "dir_super", "H4", make_valid=False)
    _write_mps(
        mps, portfolios=[], sac=[],
        baskets=[
            {"run_id": "RID_BSKSUPER", "directive_id": "dir_super",
             "basket_id": "H4", "verdict_status": "CORE",
             "quarantine_status": "SUPERSEDED"},
        ],
        cointegration=[{"rank": 1, "pair": "seed/seed"}],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    # SUPERSEDED row preserved in DB AND xlsx, even though disk is missing.
    assert _basket_db_run_ids(tmp) == {"RID_BSKSUPER"}
    post_xlsx = pd.read_excel(mps, sheet_name="Baskets")
    assert "RID_BSKSUPER" in set(post_xlsx["run_id"])


# ---------------------------------------------------------------------------
# portfolio_sheet DB-side drop (mirror of the basket arm, 2026-06-25)
# ---------------------------------------------------------------------------


def _seed_portfolio_sheet(rows: list[tuple[str, str]]) -> None:
    """Create portfolio_sheet in the (monkeypatched) tmp ledger.db + insert
    (portfolio_id, sheet) rows. Isolation: ri.LEDGER_DB_PATH is the tmp DB."""
    import sqlite3
    from tools.ledger_db import create_tables
    conn = sqlite3.connect(str(ri.LEDGER_DB_PATH))
    try:
        create_tables(conn)
        conn.executemany(
            'INSERT INTO portfolio_sheet (portfolio_id, sheet) VALUES (?, ?)', rows
        )
        conn.commit()
    finally:
        conn.close()


def _portfolio_sheet_ids(sheet: str = "Portfolios") -> set[str]:
    import sqlite3
    conn = sqlite3.connect(str(ri.LEDGER_DB_PATH))
    try:
        return {r[0] for r in conn.execute(
            "SELECT portfolio_id FROM portfolio_sheet WHERE sheet = ?", (sheet,))}
    finally:
        conn.close()


def test_apply_mps_db_drop_is_scoped_to_portfolio_id_and_sheet(staged):
    """apply_mps_db_drop hard-DELETEs by (portfolio_id, sheet). A same portfolio_id
    on the OTHER tab must survive — portfolio_sheet PK is (portfolio_id, sheet)."""
    staged  # side effect: ri.LEDGER_DB_PATH -> tmp ledger.db
    _seed_portfolio_sheet([
        ("PF_ORPH", "Portfolios"),
        ("PF_KEEP", "Portfolios"),
        ("PF_ORPH", "Single-Asset Composites"),  # same id, other tab — must survive
    ])

    n = ri.apply_mps_db_drop(["PF_ORPH"], "Portfolios")
    assert n == 1

    assert _portfolio_sheet_ids("Portfolios") == {"PF_KEEP"}
    assert _portfolio_sheet_ids("Single-Asset Composites") == {"PF_ORPH"}


def test_apply_mps_db_drop_noop_when_table_absent(staged):
    """Defensive: a fresh DB with no portfolio_sheet table is a clean no-op
    (so the existing portfolio drop tests, which never seed the table, pass)."""
    staged
    assert ri.apply_mps_db_drop(["PF_DEAD"], "Portfolios") == 0


def test_drop_deletes_orphan_from_portfolio_sheet_db(staged):
    """End-to-end: --execute drops an orphan portfolio from BOTH the xlsx and the
    portfolio_sheet DB. Pre-fix the DB row survived, so export_mps re-emitted it
    into the cleaned xlsx at the next export — the gap caught on 2026-06-25."""
    fsp, mps = staged
    _seed_portfolio_sheet([("PF_LIVE", "Portfolios"), ("PF_DEAD", "Portfolios")])

    _write_fsp(fsp, [{"run_id": "RID_A"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},  # valid (folder planted)
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"},  # orphan
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    # xlsx: orphan gone (pre-existing behavior)
    assert list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"]) == ["PF_LIVE"]
    # DB: orphan gone too (THE FIX — pre-fix PF_DEAD survived and re-emitted)
    assert _portfolio_sheet_ids("Portfolios") == {"PF_LIVE"}, \
        "orphan PF_DEAD not deleted from portfolio_sheet DB — would re-emit on export"


# ---------------------------------------------------------------------------
# argparse wrapper for tests
# ---------------------------------------------------------------------------


def _install_main_via_args():
    real_main = ri.main

    def main_via_args(argv):
        old = sys.argv
        sys.argv = ["repair_integrity.py", *argv]
        try:
            return real_main()
        finally:
            sys.argv = old

    ri.main_via_args = main_via_args


_install_main_via_args()
