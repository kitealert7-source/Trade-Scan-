"""
ledger_db.py — SQLite backend for pipeline ledgers.

Authority: SQLite is the write target. Excel is the export format.
All tools read/write through this module. Excel files are regenerated
on demand for human review.

Tables:
  master_filter    — one row per (run_id, symbol). Written by stage3_compiler.
  portfolio_sheet  — one row per (portfolio_id, sheet). Written by portfolio_evaluator.

Usage:
  python tools/ledger_db.py --export          # regenerate both Excel files from DB
  python tools/ledger_db.py --export-mf       # Master Filter only
  python tools/ledger_db.py --export-mps      # MPS only
  python tools/ledger_db.py --stats           # row counts and schema info
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import (
    STATE_ROOT, MASTER_FILTER_PATH, POOL_DIR, STRATEGIES_DIR,
    LEDGER_DB_PATH,
)

MPS_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"

# ---------------------------------------------------------------------------
# Schema definitions — column names match Excel exactly
# ---------------------------------------------------------------------------

MASTER_FILTER_COLUMNS = [
    "rank", "run_id", "strategy", "symbol", "timeframe",
    "test_start", "test_end", "trading_period",
    "sqn", "total_trades", "trade_density",
    "total_net_profit", "gross_profit", "gross_loss",
    "profit_factor", "expectancy", "sharpe_ratio",
    "max_drawdown", "max_dd_pct", "return_dd_ratio",
    "IN_PORTFOLIO",
    "worst_5_loss_pct", "longest_loss_streak",
    "pct_time_in_market", "avg_bars_in_trade",
    "net_profit_high_vol", "net_profit_normal_vol", "net_profit_low_vol",
    "net_profit_asia", "net_profit_london", "net_profit_ny",
    "net_profit_strong_up", "net_profit_weak_up", "net_profit_neutral",
    "net_profit_weak_down", "net_profit_strong_down",
    "trades_strong_up", "trades_weak_up", "trades_neutral",
    "trades_weak_down", "trades_strong_down",
]

# MPS base columns shared by both sheets
_MPS_BASE = [
    "portfolio_id", "source_strategy",
    "reference_capital_usd", "portfolio_status", "evaluation_timeframe",
    "trade_density", "profile_trade_density", "theoretical_pnl", "realized_pnl",
    "sharpe", "max_dd_pct", "return_dd_ratio", "win_rate",
    "profit_factor", "expectancy", "total_trades", "exposure_pct",
    "equity_stability_k_ratio", "deployed_profile", "trades_accepted",
    "trades_rejected", "rejection_rate_pct", "realized_vs_theoretical_pnl",
    "peak_capital_deployed", "capital_overextension_ratio",
    "avg_concurrent", "max_concurrent", "p95_concurrent", "dd_max_concurrent",
]

# All possible MPS columns (union of both sheets + sheet discriminator)
MPS_ALL_COLUMNS = _MPS_BASE + [
    "edge_quality", "full_load_cluster",
    "avg_pairwise_corr", "max_pairwise_corr_stress",
    "sqn", "n_strategies",
    "portfolio_net_profit_low_vol", "portfolio_net_profit_normal_vol",
    "portfolio_net_profit_high_vol",
    "parsed_fields", "portfolio_engine_version", "creation_timestamp",
    "constituent_run_ids",
    "rank",
    "sheet",  # discriminator: "Portfolios" or "Single-Asset Composites"
]


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL mode for safe concurrent reads."""
    path = db_path or LEDGER_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def _col_def(col: str) -> str:
    """Map column name to SQLite type. TEXT-heavy — Excel values are mixed."""
    numeric = {
        "sqn", "total_trades", "trade_density", "total_net_profit",
        "gross_profit", "gross_loss", "profit_factor", "expectancy",
        "sharpe_ratio", "max_drawdown", "max_dd_pct", "return_dd_ratio",
        "worst_5_loss_pct", "longest_loss_streak", "pct_time_in_market",
        "avg_bars_in_trade", "reference_capital_usd", "theoretical_pnl",
        "realized_pnl", "sharpe", "win_rate", "exposure_pct",
        "equity_stability_k_ratio", "trades_accepted", "trades_rejected",
        "rejection_rate_pct", "realized_vs_theoretical_pnl",
        "peak_capital_deployed", "capital_overextension_ratio",
        "avg_concurrent", "max_concurrent", "p95_concurrent",
        "dd_max_concurrent", "edge_quality", "avg_pairwise_corr",
        "max_pairwise_corr_stress", "n_strategies",
        "portfolio_net_profit_low_vol", "portfolio_net_profit_normal_vol",
        "portfolio_net_profit_high_vol", "rank",
    }
    # Columns with numeric prefixes (net_profit_*, trades_*)
    if col.startswith(("net_profit_", "trades_")):
        return f'"{col}" REAL'
    if col in numeric:
        return f'"{col}" REAL'
    if col == "IN_PORTFOLIO":
        return f'"{col}" INTEGER DEFAULT 0'
    return f'"{col}" TEXT'


def create_tables(conn: sqlite3.Connection) -> None:
    """Create ledger tables if they don't exist."""
    # Master Filter
    mf_cols = ",\n    ".join(_col_def(c) for c in MASTER_FILTER_COLUMNS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS master_filter (
            {mf_cols},
            PRIMARY KEY ("run_id", "symbol")
        )
    """)

    # MPS (portfolio sheet) — union schema with sheet discriminator
    mps_cols = ",\n    ".join(_col_def(c) for c in MPS_ALL_COLUMNS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS portfolio_sheet (
            {mps_cols},
            PRIMARY KEY ("portfolio_id", "sheet")
        )
    """)

    conn.commit()


# ---------------------------------------------------------------------------
# Write operations — upsert (INSERT OR REPLACE)
# ---------------------------------------------------------------------------

def upsert_master_filter(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    """Insert or update a single Master Filter row. Preserves unspecified columns."""
    cols = [c for c in MASTER_FILTER_COLUMNS if c in row]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(f'"{c}"' for c in cols)
    update_cols = [c for c in cols if c not in ("run_id", "symbol")]
    update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
    values = [row[c] for c in cols]
    if update_cols:
        conn.execute(
            f'INSERT INTO master_filter ({col_names}) VALUES ({placeholders}) '
            f'ON CONFLICT("run_id", "symbol") DO UPDATE SET {update_clause}',
            values,
        )
    else:
        conn.execute(
            f'INSERT INTO master_filter ({col_names}) VALUES ({placeholders}) '
            f'ON CONFLICT("run_id", "symbol") DO NOTHING',
            values,
        )
    conn.commit()


def upsert_master_filter_df(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
) -> None:
    """Bulk upsert a DataFrame into master_filter. Preserves unspecified columns."""
    if df.empty:
        return
    all_cols = [c for c in MASTER_FILTER_COLUMNS if c in df.columns]
    update_cols = [c for c in all_cols if c not in ("run_id", "symbol")]
    col_names = ", ".join(f'"{c}"' for c in all_cols)
    placeholders = ", ".join("?" for _ in all_cols)
    if update_cols:
        update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
        sql = (f'INSERT INTO master_filter ({col_names}) VALUES ({placeholders}) '
               f'ON CONFLICT("run_id", "symbol") DO UPDATE SET {update_clause}')
    else:
        sql = (f'INSERT INTO master_filter ({col_names}) VALUES ({placeholders}) '
               f'ON CONFLICT("run_id", "symbol") DO NOTHING')
    for _, row in df.iterrows():
        values = [_py_val(row.get(c)) for c in all_cols]
        conn.execute(sql, values)
    conn.commit()


def upsert_mps_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    sheet: str,
) -> None:
    """Insert or update a single MPS row. Preserves unspecified columns."""
    row = {**row, "sheet": sheet}
    cols = [c for c in MPS_ALL_COLUMNS if c in row]
    update_cols = [c for c in cols if c not in ("portfolio_id", "sheet")]
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
    values = [row[c] for c in cols]
    if update_cols:
        conn.execute(
            f'INSERT INTO portfolio_sheet ({col_names}) VALUES ({placeholders}) '
            f'ON CONFLICT("portfolio_id", "sheet") DO UPDATE SET {update_clause}',
            values,
        )
    else:
        conn.execute(
            f'INSERT INTO portfolio_sheet ({col_names}) VALUES ({placeholders}) '
            f'ON CONFLICT("portfolio_id", "sheet") DO NOTHING',
            values,
        )
    conn.commit()


def upsert_mps_df(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    sheet: str,
) -> None:
    """Bulk upsert a DataFrame into portfolio_sheet. Preserves unspecified columns."""
    if df.empty:
        return
    all_cols = [c for c in MPS_ALL_COLUMNS if c in df.columns]
    if "sheet" not in all_cols:
        all_cols.append("sheet")
    update_cols = [c for c in all_cols if c not in ("portfolio_id", "sheet")]
    col_names = ", ".join(f'"{c}"' for c in all_cols)
    placeholders = ", ".join("?" for _ in all_cols)
    if update_cols:
        update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
        sql = (f'INSERT INTO portfolio_sheet ({col_names}) VALUES ({placeholders}) '
               f'ON CONFLICT("portfolio_id", "sheet") DO UPDATE SET {update_clause}')
    else:
        sql = (f'INSERT INTO portfolio_sheet ({col_names}) VALUES ({placeholders}) '
               f'ON CONFLICT("portfolio_id", "sheet") DO NOTHING')
    for _, row in df.iterrows():
        values = [_py_val(row.get(c)) if c != "sheet" else sheet for c in all_cols]
        conn.execute(sql, values)
    conn.commit()


def update_column(
    conn: sqlite3.Connection,
    table: str,
    key_col: str,
    key_val: str,
    col: str,
    val: Any,
    key_col2: str | None = None,
    key_val2: str | None = None,
) -> None:
    """Update a single column value. Use key_col2/key_val2 for composite PK tables."""
    if key_col2 is None and table == "master_filter":
        raise ValueError("master_filter has composite PK (run_id, symbol) — key_col2 required")
    sql = f'UPDATE "{table}" SET "{col}" = ? WHERE "{key_col}" = ?'
    params: list[Any] = [_py_val(val), key_val]
    if key_col2 is not None:
        sql += f' AND "{key_col2}" = ?'
        params.append(key_val2)
    conn.execute(sql, params)
    conn.commit()


def set_in_portfolio(
    run_ids: set[str],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Authoritative IN_PORTFOLIO writer. Sets given run_ids to True, all others to False.

    This is the ONLY function that should flip IN_PORTFOLIO. Called by promote_to_burnin.py.
    Returns count of rows set to True.
    Raises ValueError if run_ids is empty (prevents catastrophic wipe).
    """
    if not run_ids:
        raise ValueError(
            "set_in_portfolio() called with empty run_ids — "
            "this would wipe all IN_PORTFOLIO flags. Aborting."
        )
    _conn = conn or _connect()
    try:
        create_tables(_conn)
        _conn.execute('UPDATE master_filter SET "IN_PORTFOLIO" = 0 WHERE "IN_PORTFOLIO" = 1')
        placeholders = ", ".join("?" for _ in run_ids)
        _conn.execute(
            f'UPDATE master_filter SET "IN_PORTFOLIO" = 1 WHERE "run_id" IN ({placeholders})',
            list(run_ids),
        )
        synced = _conn.execute(
            'SELECT COUNT(*) FROM master_filter WHERE "IN_PORTFOLIO" = 1'
        ).fetchone()[0]
        if synced != len(run_ids):
            matched = {r[0] for r in _conn.execute(
                'SELECT run_id FROM master_filter WHERE "IN_PORTFOLIO" = 1'
            ).fetchall()}
            missing = run_ids - matched
            import warnings
            warnings.warn(
                f"set_in_portfolio: {len(missing)} run_id(s) not found in DB: {sorted(missing)}"
            )
        _conn.commit()
        return synced
    except Exception:
        _conn.rollback()
        raise
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Read operations — return DataFrames
# ---------------------------------------------------------------------------

def query_master_filter(
    conn: sqlite3.Connection | None = None,
) -> pd.DataFrame:
    """Read entire Master Filter as DataFrame. Drop-in for pd.read_excel()."""
    _conn = conn or _connect()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM master_filter ORDER BY run_id",
            _conn,
        )
        return df
    finally:
        if conn is None:
            _conn.close()


def query_mps(
    conn: sqlite3.Connection | None = None,
    sheet: str | None = None,
) -> pd.DataFrame:
    """Read MPS as DataFrame. If sheet is None, returns all rows."""
    _conn = conn or _connect()
    try:
        if sheet:
            df = pd.read_sql_query(
                "SELECT * FROM portfolio_sheet WHERE sheet = ? ORDER BY portfolio_id",
                _conn, params=(sheet,),
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM portfolio_sheet ORDER BY sheet, portfolio_id",
                _conn,
            )
        return df
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Convenience readers — DB only, fail hard
# ---------------------------------------------------------------------------

def read_master_filter() -> pd.DataFrame:
    """Read Master Filter from DB. Fails hard — no Excel fallback.

    If the DB does not exist yet (fresh install), returns empty DataFrame.
    If the DB exists but the read fails, raises — never silently falls back.
    """
    if not LEDGER_DB_PATH.exists():
        return pd.DataFrame()
    return query_master_filter()


def read_mps(sheet: str | None = None) -> pd.DataFrame:
    """Read MPS from DB. Fails hard — no Excel fallback.

    Args:
        sheet: "Portfolios" or "Single-Asset Composites". None returns all rows.

    If the DB does not exist yet (fresh install), returns empty DataFrame.
    If the DB exists but the read fails, raises — never silently falls back.
    """
    if not LEDGER_DB_PATH.exists():
        return pd.DataFrame()
    df = query_mps(sheet=sheet)
    if "sheet" in df.columns:
        df = df.drop(columns=["sheet"])
    return df


# ---------------------------------------------------------------------------
# Export — regenerate Excel from DB
# ---------------------------------------------------------------------------

def export_master_filter(
    conn: sqlite3.Connection | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write Master Filter Excel from DB. Returns output path."""
    _conn = conn or _connect()
    try:
        df = query_master_filter(_conn)
        out = output_path or MASTER_FILTER_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(str(out), index=False, engine="openpyxl")
        print(f"  [EXPORT] Master Filter: {len(df)} rows -> {out}")
        return out
    finally:
        if conn is None:
            _conn.close()


def export_mps(
    conn: sqlite3.Connection | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write MPS Excel from DB with Portfolios + Single-Asset sheets."""
    _conn = conn or _connect()
    try:
        df_port = query_mps(_conn, sheet="Portfolios")
        df_single = query_mps(_conn, sheet="Single-Asset Composites")

        # Drop the 'sheet' discriminator and all-null columns from export
        for df in (df_port, df_single):
            if "sheet" in df.columns:
                df.drop(columns=["sheet"], inplace=True)
            # Remove columns that are entirely NULL (union schema artifacts)
            all_null = [c for c in df.columns if df[c].isna().all()]
            if all_null:
                df.drop(columns=all_null, inplace=True)

        out = output_path or MPS_PATH
        out.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(str(out), engine="openpyxl") as writer:
            df_port.to_excel(writer, sheet_name="Portfolios", index=False)
            df_single.to_excel(writer, sheet_name="Single-Asset Composites", index=False)

        print(f"  [EXPORT] MPS: Portfolios={len(df_port)}, "
              f"Single-Asset Composites={len(df_single)} -> {out}")
        return out
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _py_val(val: Any) -> Any:
    """Convert pandas/numpy scalars to native Python for SQLite."""
    if val is None:
        return None
    try:
        import numpy as np
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            v = float(val)
            return None if np.isnan(v) else v
        if isinstance(val, (np.bool_,)):
            return int(val)
    except ImportError:
        pass
    if isinstance(val, float):
        import math
        return None if math.isnan(val) else val
    return val


def print_stats(conn: sqlite3.Connection | None = None) -> None:
    """Print DB stats."""
    _conn = conn or _connect()
    try:
        mf_count = _conn.execute("SELECT COUNT(*) FROM master_filter").fetchone()[0]
        mps_count = _conn.execute("SELECT COUNT(*) FROM portfolio_sheet").fetchone()[0]
        mps_port = _conn.execute(
            "SELECT COUNT(*) FROM portfolio_sheet WHERE sheet='Portfolios'"
        ).fetchone()[0]
        mps_single = _conn.execute(
            "SELECT COUNT(*) FROM portfolio_sheet WHERE sheet='Single-Asset Composites'"
        ).fetchone()[0]

        print(f"\n  Ledger DB: {LEDGER_DB_PATH}")
        print(f"  master_filter:    {mf_count} rows")
        print(f"  portfolio_sheet:  {mps_count} rows "
              f"(Portfolios={mps_port}, Single-Asset Composites={mps_single})")
        print()
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Ledger DB — SQLite backend")
    parser.add_argument("--export", action="store_true",
                        help="Export both ledgers to Excel")
    parser.add_argument("--export-mf", action="store_true",
                        help="Export Master Filter to Excel")
    parser.add_argument("--export-mps", action="store_true",
                        help="Export MPS to Excel")
    parser.add_argument("--stats", action="store_true",
                        help="Print DB stats")
    args = parser.parse_args()

    conn = _connect()
    create_tables(conn)

    if args.stats:
        print_stats(conn)
    if args.export or args.export_mf:
        export_master_filter(conn)
    if args.export or args.export_mps:
        export_mps(conn)
    if not any([args.export, args.export_mf, args.export_mps, args.stats]):
        print_stats(conn)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
