"""
ledger_db.py — SQLite backend for pipeline ledgers.

Authority: SQLite is the write target. Excel is the export format.
All tools read/write through this module. Excel files are regenerated
on demand for human review.

Tables:
  master_filter       — one row per (run_id, symbol). Written by stage3_compiler.
  portfolio_sheet     — one row per (portfolio_id, sheet). Written by portfolio_evaluator.
  portfolio_control   — one row per portfolio_id. User decision store for promote/disable.

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
    # Analysis_selection — per-row user-intent flag (0/1) picked in FSP to
    # drive the next composite_portfolio_analysis run. Auto-cleared after
    # that analysis completes. NOT a portfolio-membership signal: actual
    # deployment authority is portfolio.yaml + burn_in_registry.yaml.
    "Analysis_selection",
    "worst_5_loss_pct", "longest_loss_streak",
    "pct_time_in_market", "avg_bars_in_trade",
    "net_profit_high_vol", "net_profit_normal_vol", "net_profit_low_vol",
    "net_profit_asia", "net_profit_london", "net_profit_ny",
    "net_profit_strong_up", "net_profit_weak_up", "net_profit_neutral",
    "net_profit_weak_down", "net_profit_strong_down",
    "trades_strong_up", "trades_weak_up", "trades_neutral",
    "trades_weak_down", "trades_strong_down",
    # --- Supersession bookkeeping (added 2026-04-16) -----------------------
    # When rerun_backtest.py produces a new run for the same strategy, the
    # prior run's rows are flagged is_current=0 rather than deleted. FSP
    # readers filter on is_current=1 by default (NULL treated as 1 for pre-
    # migration rows via backfill). Quarterly cleanup moves aged is_current=0
    # rows to parquet archive. See also: TOOLS_INDEX.md § rerun_backtest.
    "is_current",        # 1 = live / 0 = superseded (default 1)
    "superseded_by",     # run_id of the replacement run, NULL for live rows
    "superseded_at",     # ISO timestamp when the supersession was recorded
    "supersede_reason",  # category string (DATA_FRESH|SIGNAL|PARAMETER|BUG_FIX|...)
    "quarantined",       # 1 = never resurrect (BUG_FIX reruns set this)
]

# MPS base columns shared by both sheets
_MPS_BASE = [
    "portfolio_id", "source_strategy",
    "reference_capital_usd", "portfolio_status", "evaluation_timeframe",
    "symbol_count",
    "trade_density_total", "trade_density_min",
    "profile_trade_density_total", "profile_trade_density_min",
    "theoretical_pnl", "realized_pnl",
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
        "sqn", "total_trades",
        "trade_density",  # Master Filter: per-symbol trades/yr (unchanged)
        "symbol_count",
        "trade_density_total", "trade_density_min",
        "profile_trade_density_total", "profile_trade_density_min",
        "total_net_profit",
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
    if col == "Analysis_selection":
        return f'"{col}" INTEGER DEFAULT 0'
    # Supersession bookkeeping: is_current defaults to 1 so rows written by
    # stage3_compiler (which doesn't know about this flag) land as live.
    # quarantined defaults to 0. superseded_* are TEXT (nullable).
    if col == "is_current":
        return f'"{col}" INTEGER DEFAULT 1'
    if col == "quarantined":
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

    # Schema migration — add any columns present in MPS_ALL_COLUMNS but missing
    # from an older existing table (e.g. symbol_count, trade_density_min/_total,
    # profile_trade_density_min/_total from the 2026-04-15 density-split refactor).
    # Legacy columns (trade_density, profile_trade_density) are dropped after
    # backfill has run; we leave them in place during the transition so readers
    # that still reference them by name do not crash.
    existing = {row[1] for row in conn.execute(
        'PRAGMA table_info("portfolio_sheet")').fetchall()}
    for col in MPS_ALL_COLUMNS:
        if col not in existing:
            conn.execute(f'ALTER TABLE portfolio_sheet ADD COLUMN {_col_def(col)}')

    # Schema migration — master_filter.
    # 2026-04-16: retire IN_PORTFOLIO (misnomer — authority is portfolio.yaml
    # and burn_in_registry.yaml, not this column) in favour of
    # Analysis_selection, a transient per-row user-intent flag that drives
    # composite_portfolio_analysis. No backfill — the previous column carried
    # no semantic signal that downstream still depends on (start-fresh per
    # user directive, 2026-04-16). Requires SQLite ≥ 3.35 for DROP COLUMN.
    mf_existing = {row[1] for row in conn.execute(
        'PRAGMA table_info("master_filter")').fetchall()}
    if "IN_PORTFOLIO" in mf_existing:
        try:
            conn.execute('ALTER TABLE master_filter DROP COLUMN "IN_PORTFOLIO"')
        except sqlite3.OperationalError as exc:
            # Older SQLite — fall back to rebuild. Preserves all other data.
            _rebuild_master_filter_without_column(conn, "IN_PORTFOLIO")
    # Add Analysis_selection if missing. ADD COLUMN is universally supported.
    mf_existing = {row[1] for row in conn.execute(
        'PRAGMA table_info("master_filter")').fetchall()}
    newly_added: list[str] = []
    for col in MASTER_FILTER_COLUMNS:
        if col not in mf_existing:
            conn.execute(f'ALTER TABLE master_filter ADD COLUMN {_col_def(col)}')
            newly_added.append(col)

    # Supersession backfill: ALTER TABLE ADD COLUMN in SQLite ignores
    # DEFAULT for existing rows (they get NULL). Backfill once so readers
    # filtering WHERE is_current=1 pick up legacy rows.
    if "is_current" in newly_added:
        conn.execute(
            'UPDATE master_filter SET "is_current" = 1 '
            'WHERE "is_current" IS NULL'
        )
    if "quarantined" in newly_added:
        conn.execute(
            'UPDATE master_filter SET "quarantined" = 0 '
            'WHERE "quarantined" IS NULL'
        )

    # Portfolio Control — user decision store for promote/disable
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_control (
            portfolio_id    TEXT PRIMARY KEY,
            selected        INTEGER DEFAULT 0,
            burn            INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'SELECTED',
            profile         TEXT DEFAULT 'CONSERVATIVE_V1',
            reason          TEXT,
            last_updated    TEXT,
            updated_by      TEXT DEFAULT 'user'
        )
    """)

    # Portfolio Control Log — append-only audit trail
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_control_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id    TEXT NOT NULL,
            action          TEXT NOT NULL,
            status_before   TEXT,
            status_after    TEXT,
            detail          TEXT,
            timestamp       TEXT NOT NULL
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


def _rebuild_master_filter_without_column(
    conn: sqlite3.Connection, drop_col: str,
) -> None:
    """Fallback rebuild for SQLite < 3.35 (no native DROP COLUMN).

    Copies master_filter into a new table that omits ``drop_col``, then
    swaps. Runs inside a transaction — rolls back on failure, so a crash
    mid-rebuild leaves the original table intact.
    """
    cols = [row[1] for row in conn.execute(
        'PRAGMA table_info("master_filter")').fetchall()
        if row[1] != drop_col]
    keep = ", ".join(f'"{c}"' for c in cols)
    mf_cols = ",\n    ".join(_col_def(c) for c in MASTER_FILTER_COLUMNS
                              if c != drop_col and c in cols)
    try:
        conn.execute("BEGIN")
        conn.execute(f"""
            CREATE TABLE master_filter__new (
                {mf_cols},
                PRIMARY KEY ("run_id", "symbol")
            )
        """)
        conn.execute(
            f'INSERT INTO master_filter__new ({keep}) '
            f'SELECT {keep} FROM master_filter'
        )
        conn.execute('DROP TABLE master_filter')
        conn.execute('ALTER TABLE master_filter__new RENAME TO master_filter')
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def set_analysis_selection(
    run_ids: set[str] | list[str],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Authoritative Analysis_selection writer.

    REPLACE semantics: clears every row's flag, then sets rows whose
    ``run_id`` is in ``run_ids`` to 1. Pass an empty set/list to clear all
    selections (see ``clear_analysis_selection`` for the named alias).

    Unlike the retired ``set_in_portfolio``, empty input is legitimate here
    because this flag is transient user intent, not portfolio membership —
    the post-analysis reset is a normal lifecycle step, not a catastrophic
    wipe. Callers who want the "replace with at least one selection" guard
    should check ``len(run_ids)`` themselves before calling.

    Returns the count of rows now flagged = 1.
    """
    run_ids = set(run_ids)
    _conn = conn or _connect()
    try:
        create_tables(_conn)
        _conn.execute(
            'UPDATE master_filter SET "Analysis_selection" = 0 '
            'WHERE "Analysis_selection" = 1'
        )
        if run_ids:
            placeholders = ", ".join("?" for _ in run_ids)
            _conn.execute(
                f'UPDATE master_filter SET "Analysis_selection" = 1 '
                f'WHERE "run_id" IN ({placeholders})',
                list(run_ids),
            )
        synced = _conn.execute(
            'SELECT COUNT(*) FROM master_filter WHERE "Analysis_selection" = 1'
        ).fetchone()[0]
        if run_ids and synced != len(run_ids):
            matched = {r[0] for r in _conn.execute(
                'SELECT run_id FROM master_filter WHERE "Analysis_selection" = 1'
            ).fetchall()}
            missing = run_ids - matched
            import warnings
            warnings.warn(
                f"set_analysis_selection: {len(missing)} run_id(s) not found "
                f"in DB: {sorted(missing)}"
            )
        _conn.commit()
        return synced
    except Exception:
        _conn.rollback()
        raise
    finally:
        if conn is None:
            _conn.close()


def clear_analysis_selection(
    conn: sqlite3.Connection | None = None,
) -> int:
    """Wipe all Analysis_selection flags. Invoked post-analysis so the next
    FSP regeneration starts with a blank slate. Returns the number of rows
    that were flipped from 1 → 0.
    """
    _conn = conn or _connect()
    try:
        create_tables(_conn)
        cur = _conn.execute(
            'UPDATE master_filter SET "Analysis_selection" = 0 '
            'WHERE "Analysis_selection" = 1'
        )
        cleared = cur.rowcount
        _conn.commit()
        return cleared
    except Exception:
        _conn.rollback()
        raise
    finally:
        if conn is None:
            _conn.close()


def mark_superseded(
    old_run_id: str,
    new_run_id: str,
    reason: str,
    *,
    quarantine: bool = False,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Flag all master_filter rows belonging to old_run_id as superseded.

    Called by rerun_backtest.py after the replacement pipeline run writes
    its own rows. Does NOT delete the old rows — append-only invariant is
    preserved. FSP readers default to is_current=1, so superseded rows
    vanish from the decision view but remain available for diff/forensics
    and quarterly archive.

    Args:
        old_run_id: run_id of the prior run being retired.
        new_run_id: run_id of the replacement run (must already exist in DB).
        reason: short category/reason string. Persisted to supersede_reason.
        quarantine: if True, also set quarantined=1 (BUG_FIX reruns — the
            prior result is semantically wrong, never resurrect it).
        conn: optional connection (for transactional composition).

    Returns the count of rows flipped. Zero means either old_run_id wasn't
    found or it was already superseded.
    """
    from datetime import datetime, timezone
    _conn = conn or _connect()
    try:
        create_tables(_conn)
        # Validate new_run_id exists — fail loud rather than pointing to
        # a phantom run in superseded_by.
        new_exists = _conn.execute(
            'SELECT 1 FROM master_filter WHERE "run_id" = ? LIMIT 1',
            (new_run_id,),
        ).fetchone()
        if not new_exists:
            raise ValueError(
                f"mark_superseded: new_run_id {new_run_id!r} not present "
                f"in master_filter. Run the pipeline first, then supersede."
            )
        ts = datetime.now(timezone.utc).isoformat()
        if quarantine:
            cur = _conn.execute(
                'UPDATE master_filter SET '
                '"is_current" = 0, "superseded_by" = ?, '
                '"superseded_at" = ?, "supersede_reason" = ?, '
                '"quarantined" = 1 '
                'WHERE "run_id" = ? AND ("is_current" = 1 OR "is_current" IS NULL)',
                (new_run_id, ts, reason, old_run_id),
            )
        else:
            cur = _conn.execute(
                'UPDATE master_filter SET '
                '"is_current" = 0, "superseded_by" = ?, '
                '"superseded_at" = ?, "supersede_reason" = ? '
                'WHERE "run_id" = ? AND ("is_current" = 1 OR "is_current" IS NULL)',
                (new_run_id, ts, reason, old_run_id),
            )
        flipped = cur.rowcount
        _conn.commit()
        return flipped
    except Exception:
        _conn.rollback()
        raise
    finally:
        if conn is None:
            _conn.close()


def mark_superseded_pre_run(
    run_ids: list[str],
    reason: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Retire prior run rows before a replacement pipeline run starts.

    Companion to mark_superseded() for the pre-rerun case: we do not yet
    have a replacement run_id to point to, so we flip is_current only and
    leave the forward pointer blank. The forward pointer is filled in by
    rerun_backtest.py (or mark_superseded) after the replacement run lands.

    Called by reset_directive.py --supersede. Preserves the append-only
    invariant (rows stay; flag flips). Only touches rows currently live —
    already-superseded rows are left untouched, so repeated calls are safe.

    Pre-run (this function):
        is_current    = 0
        superseded_at = <now>
        supersede_reason = <reason>
        superseded_by = NULL        (unknown until replacement run lands)

    Post-run (handled elsewhere, e.g. mark_superseded after rerun):
        superseded_by = <new_run_id>

    Args:
        run_ids: list of run_id strings to retire.
        reason: short category/reason string persisted to supersede_reason.
        conn: optional connection (for transactional composition).

    Returns the count of rows flipped from is_current=1 to is_current=0.
    Rows already superseded are skipped and not counted.
    """
    from datetime import datetime, timezone
    if not run_ids:
        return 0
    _conn = conn or _connect()
    try:
        create_tables(_conn)
        ts = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" * len(run_ids))
        cur = _conn.execute(
            'UPDATE master_filter SET '
            '"is_current" = 0, '
            '"superseded_at" = ?, '
            '"supersede_reason" = ? '
            f'WHERE "run_id" IN ({placeholders}) '
            'AND ("is_current" = 1 OR "is_current" IS NULL)',
            (ts, reason, *run_ids),
        )
        flipped = cur.rowcount
        _conn.commit()
        return flipped
    except Exception:
        _conn.rollback()
        raise
    finally:
        if conn is None:
            _conn.close()


def find_runs_for_stem(
    strategy_stem: str,
    timeframe: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    """Return run_ids of live master_filter rows matching a strategy stem.

    Scope predicate (precision-first): strategy LIKE '<stem>%' AND,
    when supplied, timeframe = '<tf>'. Matches both bare stem rows and
    per-symbol forms (e.g. STEM and STEM_EURUSD). Never returns rows for
    other stems or other timeframes.

    Already-superseded rows (is_current=0) are excluded — reruns only
    retire live baselines.
    """
    _conn = conn or _connect()
    try:
        create_tables(_conn)
        if timeframe:
            cur = _conn.execute(
                'SELECT run_id FROM master_filter '
                'WHERE strategy LIKE ? '
                'AND timeframe = ? '
                'AND ("is_current" = 1 OR "is_current" IS NULL)',
                (f"{strategy_stem}%", timeframe),
            )
        else:
            cur = _conn.execute(
                'SELECT run_id FROM master_filter '
                'WHERE strategy LIKE ? '
                'AND ("is_current" = 1 OR "is_current" IS NULL)',
                (f"{strategy_stem}%",),
            )
        return [str(r[0]) for r in cur.fetchall()]
    finally:
        if conn is None:
            _conn.close()


def read_analysis_selection(
    conn: sqlite3.Connection | None = None,
) -> set[str]:
    """Return the set of run_ids currently flagged for the next analysis run."""
    _conn = conn or _connect()
    try:
        if not LEDGER_DB_PATH.exists():
            return set()
        rows = _conn.execute(
            'SELECT "run_id" FROM master_filter WHERE "Analysis_selection" = 1'
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Read operations — return DataFrames
# ---------------------------------------------------------------------------

def query_master_filter(
    conn: sqlite3.Connection | None = None,
    *,
    include_superseded: bool = False,
) -> pd.DataFrame:
    """Read Master Filter as DataFrame. Drop-in for pd.read_excel().

    Args:
        include_superseded: If False (default), returns only live rows
            (is_current = 1, NULL treated as live for pre-migration rows).
            If True, returns full history including retired rows. Use True
            only for diagnostics, backfill, and forensic tooling.
    """
    _conn = conn or _connect()
    try:
        if include_superseded:
            df = pd.read_sql_query(
                "SELECT * FROM master_filter ORDER BY run_id",
                _conn,
            )
        else:
            df = pd.read_sql_query(
                'SELECT * FROM master_filter '
                'WHERE ("is_current" = 1 OR "is_current" IS NULL) '
                'ORDER BY run_id',
                _conn,
            )
        return df
    finally:
        if conn is None:
            _conn.close()


def query_mps(
    conn: sqlite3.Connection | None = None,
    sheet: str | None = None,
    *,
    include_superseded: bool = False,
) -> pd.DataFrame:
    """Read MPS as DataFrame. If sheet is None, returns all rows.

    Args:
        include_superseded: Parameter accepted for API symmetry with
            query_master_filter. The portfolio_sheet table does not currently
            track supersedence (no is_current column); MPS rows are upserted
            by (portfolio_id, sheet) primary key so reruns overwrite in place.
            This flag is a no-op today; callers should still pass it
            explicitly for forward compatibility if future supersedence is
            added to portfolio_sheet.
    """
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

def read_master_filter(*, include_superseded: bool = False) -> pd.DataFrame:
    """Read Master Filter from DB. Fails hard — no Excel fallback.

    By default returns only live rows (is_current=1 or NULL). Pass
    include_superseded=True for diagnostics/backfill tools that need full
    history.

    If the DB does not exist yet (fresh install), returns empty DataFrame.
    If the DB exists but the read fails, raises — never silently falls back.
    """
    if not LEDGER_DB_PATH.exists():
        return pd.DataFrame()
    return query_master_filter(include_superseded=include_superseded)


def read_mps(
    sheet: str | None = None,
    *,
    include_superseded: bool = False,
) -> pd.DataFrame:
    """Read MPS from DB. Fails hard — no Excel fallback.

    Args:
        sheet: "Portfolios" or "Single-Asset Composites". None returns all rows.
        include_superseded: Accepted for API symmetry. The portfolio_sheet
            table does not currently track supersedence; this flag is a no-op
            today. See query_mps() docstring for details.

    If the DB does not exist yet (fresh install), returns empty DataFrame.
    If the DB exists but the read fails, raises — never silently falls back.
    """
    if not LEDGER_DB_PATH.exists():
        return pd.DataFrame()
    df = query_mps(sheet=sheet, include_superseded=include_superseded)
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

        # Join burn_in_status from portfolio_control (read-only view column)
        ctrl = read_portfolio_control(conn=_conn)
        if not ctrl.empty:
            status_map = dict(zip(ctrl["portfolio_id"], ctrl["status"]))
        else:
            status_map = {}
        for df in (df_port, df_single):
            df.insert(1, "burn_in_status",
                      df["portfolio_id"].map(status_map).fillna(""))

        out = output_path or MPS_PATH
        out.parent.mkdir(parents=True, exist_ok=True)

        # Preserve non-data sheets (e.g. Notes) on regeneration. Without this,
        # callers that use --supersede or a plain export would silently strip
        # human audit context attached to the workbook. Mirrors the pattern
        # in profile_selector.py / portfolio_evaluator.py.
        data_sheet_names = {"Portfolios", "Single-Asset Composites"}
        preserved: dict[str, pd.DataFrame] = {}
        if out.exists():
            try:
                with pd.ExcelFile(out) as _xls:
                    for _sn in _xls.sheet_names:
                        if _sn not in data_sheet_names:
                            try:
                                preserved[_sn] = pd.read_excel(_xls, sheet_name=_sn)
                            except Exception:
                                # Unreadable sheet (formulas-only etc.) — skip
                                # rather than crash. Worst case Notes lost on
                                # this run; not a data-integrity regression.
                                pass
            except Exception:
                pass  # Corrupt file — regenerate from scratch.

        with pd.ExcelWriter(str(out), engine="openpyxl", mode="w") as writer:
            df_port.to_excel(writer, sheet_name="Portfolios", index=False)
            df_single.to_excel(writer, sheet_name="Single-Asset Composites", index=False)
            for _sn, _sdf in preserved.items():
                _sdf.to_excel(writer, sheet_name=_sn, index=False)

        preserved_note = f", preserved={sorted(preserved)}" if preserved else ""
        print(f"  [EXPORT] MPS: Portfolios={len(df_port)}, "
              f"Single-Asset Composites={len(df_single)}{preserved_note} -> {out}")
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
# Portfolio Control — CRUD
# ---------------------------------------------------------------------------

PORTFOLIO_CONTROL_VALID_STATUSES = {"SELECTED", "BURN_IN", "RBIN"}


def log_control_action(
    conn: sqlite3.Connection,
    portfolio_id: str,
    action: str,
    status_before: str | None = None,
    status_after: str | None = None,
    detail: str | None = None,
) -> None:
    """Append an entry to portfolio_control_log. Never fails the caller."""
    from datetime import datetime, timezone
    try:
        conn.execute(
            'INSERT INTO portfolio_control_log '
            '(portfolio_id, action, status_before, status_after, detail, timestamp) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (portfolio_id, action, status_before, status_after, detail,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception:
        pass  # audit log must never break the caller


def read_control_log(
    conn: sqlite3.Connection | None = None,
    portfolio_id: str | None = None,
    limit: int = 50,
) -> pd.DataFrame:
    """Read recent audit log entries."""
    _conn = conn or _connect()
    try:
        if portfolio_id:
            return pd.read_sql_query(
                "SELECT * FROM portfolio_control_log WHERE portfolio_id = ? "
                "ORDER BY id DESC LIMIT ?",
                _conn, params=(portfolio_id, limit),
            )
        return pd.read_sql_query(
            "SELECT * FROM portfolio_control_log ORDER BY id DESC LIMIT ?",
            _conn, params=(limit,),
        )
    finally:
        if conn is None:
            _conn.close()


def upsert_portfolio_control(
    conn: sqlite3.Connection,
    portfolio_id: str,
    **fields: Any,
) -> None:
    """Insert or update a portfolio_control row. Only updates provided fields."""
    from datetime import datetime, timezone

    fields["last_updated"] = datetime.now(timezone.utc).isoformat()
    all_fields = {"portfolio_id": portfolio_id, **fields}
    cols = list(all_fields.keys())
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    update_cols = [c for c in cols if c != "portfolio_id"]
    update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
    values = [all_fields[c] for c in cols]

    conn.execute(
        f'INSERT INTO portfolio_control ({col_names}) VALUES ({placeholders}) '
        f'ON CONFLICT("portfolio_id") DO UPDATE SET {update_clause}',
        values,
    )
    conn.commit()


def read_portfolio_control(
    conn: sqlite3.Connection | None = None,
    status: str | None = None,
) -> pd.DataFrame:
    """Read portfolio_control as DataFrame. Optionally filter by status."""
    _conn = conn or _connect()
    try:
        if status:
            df = pd.read_sql_query(
                "SELECT * FROM portfolio_control WHERE status = ? ORDER BY portfolio_id",
                _conn, params=(status,),
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM portfolio_control ORDER BY portfolio_id",
                _conn,
            )
        return df
    finally:
        if conn is None:
            _conn.close()


def update_control_status(
    conn: sqlite3.Connection,
    portfolio_id: str,
    status: str,
    updated_by: str = "system",
    **extra: Any,
) -> None:
    """Atomic status transition. Validates status is legal."""
    if status not in PORTFOLIO_CONTROL_VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}. Valid: {PORTFOLIO_CONTROL_VALID_STATUSES}")
    from datetime import datetime, timezone
    fields = {"status": status, "updated_by": updated_by,
              "last_updated": datetime.now(timezone.utc).isoformat()}
    fields.update(extra)
    set_clause = ", ".join(f'"{k}" = ?' for k in fields)
    conn.execute(
        f'UPDATE portfolio_control SET {set_clause} WHERE portfolio_id = ?',
        list(fields.values()) + [portfolio_id],
    )
    conn.commit()


def delete_portfolio_control(
    conn: sqlite3.Connection,
    portfolio_id: str,
) -> bool:
    """Delete a control row. Returns True if a row was deleted."""
    cursor = conn.execute(
        'DELETE FROM portfolio_control WHERE portfolio_id = ?',
        (portfolio_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


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
