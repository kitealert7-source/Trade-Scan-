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
import gc
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

# Support direct-script invocation (`python tools/ledger_db.py --export-mps`):
# put the repo root on sys.path so the `from tools...` import below resolves
# even when this file is run as a script rather than imported as tools.ledger_db.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from tools.portfolio.cointegration_schema import (
    COINTEGRATION_NUMERIC_COLUMNS,
    COINTEGRATION_SHEET_COLUMNS,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import (
    STATE_ROOT, MASTER_FILTER_PATH, POOL_DIR, STRATEGIES_DIR,
    LEDGER_DB_PATH,
)

MPS_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"


def _resolve_mps_path() -> Path:
    """Resolve the current MPS xlsx path at call time, not import time.

    Tests monkeypatch `config.path_authority.TRADE_SCAN_STATE` after this
    module is already imported, which makes the module-level MPS_PATH stale.
    Mirrors `basket_ledger_writer._mps_path()` — dynamic resolution picks
    up the patched value.
    """
    from config.path_authority import TRADE_SCAN_STATE
    return TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"

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
    # deployment authority is portfolio.yaml.
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


# Audit columns — operator-added xlsx-only columns preserved across
# export_mps() regenerations by re-reading the existing workbook and
# joining them back onto the DB-sourced DataFrame via the sheet's
# natural key. These columns live ONLY in the xlsx; the DB schema does
# not know about them, so without this carry-over they get wiped every
# time a pipeline run rewrites the file.
#
# Whitelist (not pass-through) so the carry-over is intentional and
# auditable — random columns operators might accidentally add elsewhere
# don't get silently persisted. Add new entries here when a new audit
# workflow needs to mark rows.
#
# 2026-05-24: introduced for leg_direction_flip_bug cleanup, which
# annotated superseded Baskets rows with quarantine metadata that
# survived only until the next basket pipeline run.
_MPS_AUDIT_COLUMNS: dict[str, dict[str, Any]] = {
    "Baskets": {
        "key": "run_id",
        "columns": [
            "quarantine_status",      # 'SUPERSEDED' | other operator-defined values
            "superseded_by_run_id",   # run_id of the replacement run
            "quarantine_reason",      # free-text rationale
        ],
    },
}


# Basket sheet — Phase 5b.3 schema (promoted from Excel-direct to DB).
# Mirrors BASKETS_SHEET_COLUMNS in tools/portfolio/basket_ledger_writer.py
# (the 35 writer-emitted columns) plus DB-only bookkeeping:
#   - verdict_status: CORE/WATCH/FAIL, computed at write time in the writer.
#     Moved from tools/excel_format/styling.py (presentation → persistence).
#   - is_current / superseded_*: supersession tracking, mirrors master_filter.
BASKET_SHEET_COLUMNS = [
    # 1.2.0-basket — identity + base mechanics
    "run_id",
    "directive_id",
    "basket_id",
    "execution_mode",
    "rule_name",
    "rule_version",
    "leg_count",
    "leg_specs",
    "trades_total",
    "recycle_event_count",
    "harvested_total_usd",
    "final_realized_usd",
    "exit_reason",
    "completed_at_utc",
    "backtests_path",
    "vault_path",
    # 1.3.0-basket — in-memory derived (NA on pre-canonical / legacy CSV rows)
    "peak_floating_dd_usd",
    "peak_floating_dd_pct",
    "dd_freeze_count",
    "margin_freeze_count",
    "regime_freeze_count",
    "peak_margin_used_usd",
    "min_margin_level_pct",
    "worst_floating_at_freeze_usd",
    "return_on_real_capital_pct",
    "peak_lots_json",
    "schema_version",
    # 1.4.0-basket-canonical — parquet-derived (NA on legacy CSV rows)
    "canonical_net_pct",
    "canonical_max_dd_pct",
    "canonical_ret_dd",
    "canonical_final_equity_usd",
    "cycle_win_rate_pct",
    "cycles_completed",
    "peak_winner_lot",
    "rule_family",
    # Phase 5b.3 additions
    "verdict_status",       # CORE/WATCH/FAIL — computed by writer at row build
    "enrichment_status",    # complete | no_canonical | no_parquet | overwritten | archived
    "is_current",
    "superseded_by",
    "superseded_at",
    "supersede_reason",
]


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _resolve_db_path() -> Path:
    """Resolve LEDGER_DB_PATH at call time (mirrors _resolve_mps_path()).

    Same rationale as the MPS resolver: tests monkey-patch
    `config.path_authority.TRADE_SCAN_STATE` after import, so the
    module-level `LEDGER_DB_PATH` (captured at import time) is stale.
    Dynamic resolution picks up the patched value.
    """
    from config.path_authority import TRADE_SCAN_STATE
    return TRADE_SCAN_STATE / "ledger.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL mode for safe concurrent reads."""
    path = db_path or _resolve_db_path()
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
        # basket_sheet numerics (Phase 5b.3) — all REAL per existing convention
        "rule_version", "leg_count", "trades_total", "recycle_event_count",
        "harvested_total_usd", "final_realized_usd",
        "peak_floating_dd_usd", "peak_floating_dd_pct",
        "dd_freeze_count", "margin_freeze_count", "regime_freeze_count",
        "peak_margin_used_usd", "min_margin_level_pct",
        "worst_floating_at_freeze_usd", "return_on_real_capital_pct",
        "canonical_net_pct", "canonical_max_dd_pct", "canonical_ret_dd",
        "canonical_final_equity_usd", "cycle_win_rate_pct",
        "cycles_completed", "peak_winner_lot",
    }
    # Cointegration ledger numerics (single-source set; see
    # tools/portfolio/cointegration_schema.py).
    numeric |= COINTEGRATION_NUMERIC_COLUMNS
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
    # 2026-04-16: retire IN_PORTFOLIO (misnomer — authority is portfolio.yaml,
    # not this column) in favour of
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

    # Basket Sheet — Phase 5b.3 promotion of the Baskets tab from Excel-direct
    # to DB-canonical. Append-only via the writer's pre-insert SELECT-1 check
    # (mirrors per-symbol writer's invariant); ON CONFLICT(run_id) DO NOTHING
    # is the safety net.
    basket_cols = ",\n        ".join(_col_def(c) for c in BASKET_SHEET_COLUMNS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS basket_sheet (
            {basket_cols},
            PRIMARY KEY ("run_id")
        )
    """)
    b_existing = {row[1] for row in conn.execute(
        'PRAGMA table_info("basket_sheet")').fetchall()}
    newly_added_b: list[str] = []
    for col in BASKET_SHEET_COLUMNS:
        if col not in b_existing:
            conn.execute(f'ALTER TABLE basket_sheet ADD COLUMN {_col_def(col)}')
            newly_added_b.append(col)
    # Backfill is_current default on schema migration (ADD COLUMN ignores
    # DEFAULT for existing rows in SQLite — they receive NULL).
    if "is_current" in newly_added_b:
        conn.execute(
            'UPDATE basket_sheet SET "is_current" = 1 '
            'WHERE "is_current" IS NULL'
        )
    # Indexes for the common query shapes: lookup by directive+basket
    # (re-run detection) and verdict filtering (reporting).
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_basket_directive '
        'ON basket_sheet(directive_id, basket_id)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_basket_verdict '
        'ON basket_sheet(verdict_status)'
    )

    # Cointegration Sheet -- greenfield regime-conditioned research ledger.
    # Separate ontology from basket_sheet (never merged). Single-source schema:
    # tools/portfolio/cointegration_schema.py. Append-only via the writer's
    # pre-insert SELECT-1. Verdict-free in v1 (rank is a view concern); the
    # writer is a pure sink that never reads the screener DB.
    coint_cols = ",\n        ".join(_col_def(c) for c in COINTEGRATION_SHEET_COLUMNS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS cointegration_sheet (
            {coint_cols},
            PRIMARY KEY ("run_id")
        )
    """)
    c_existing = {row[1] for row in conn.execute(
        'PRAGMA table_info("cointegration_sheet")').fetchall()}
    newly_added_c: list[str] = []
    for col in COINTEGRATION_SHEET_COLUMNS:
        if col not in c_existing:
            conn.execute(f'ALTER TABLE cointegration_sheet ADD COLUMN {_col_def(col)}')
            newly_added_c.append(col)
    # Backfill is_current default on schema migration (ADD COLUMN ignores
    # DEFAULT for existing rows in SQLite -- they receive NULL).
    if "is_current" in newly_added_c:
        conn.execute(
            'UPDATE cointegration_sheet SET "is_current" = 1 '
            'WHERE "is_current" IS NULL'
        )
    # methodology_version backfill (2026-05-30, C2): tag every legacy row
    # with 'v1_raw_adf' so the corpus has explicit cohort provenance after
    # the math correction lands in C3. Idempotent: only fills NULL rows,
    # never overwrites a row that already has a methodology declared.
    if "methodology_version" in newly_added_c:
        conn.execute(
            'UPDATE cointegration_sheet SET "methodology_version" = \'v1_raw_adf\' '
            'WHERE "methodology_version" IS NULL'
        )
    # Indexes: re-run detection by (pair, lookback) and current-row filtering.
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_coint_pair '
        'ON cointegration_sheet(pair_a, pair_b, lookback_days)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_coint_current '
        'ON cointegration_sheet(is_current)'
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


def upsert_basket_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    """Insert a basket row. Append-only: existing run_id → NO-OP at the SQL
    layer (writer raises FATAL upstream via SELECT-1 pre-check).
    """
    cols = [c for c in BASKET_SHEET_COLUMNS if c in row]
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    values = [_py_val(row[c]) for c in cols]
    conn.execute(
        f'INSERT INTO basket_sheet ({col_names}) VALUES ({placeholders}) '
        f'ON CONFLICT("run_id") DO NOTHING',
        values,
    )
    conn.commit()


def upsert_cointegration_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    """Insert a cointegration row. Append-only: existing run_id -> NO-OP at the
    SQL layer (the writer raises FATAL upstream via its SELECT-1 pre-check).
    Mirrors upsert_basket_row; restricts to the single-source schema columns.
    """
    cols = [c for c in COINTEGRATION_SHEET_COLUMNS if c in row]
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    values = [_py_val(row[c]) for c in cols]
    conn.execute(
        f'INSERT INTO cointegration_sheet ({col_names}) VALUES ({placeholders}) '
        f'ON CONFLICT("run_id") DO NOTHING',
        values,
    )
    # --- Identity-preserving refresh (cointegration pilot, 2026-06-07) ---------
    # A refresh of an existing directive arrives with a NEW run_id (the
    # FATAL-on-duplicate-run_id pre-check in append_cointegration_row guarantees
    # run_id uniqueness; the run_pipeline uniqueness guard only lets a re-run
    # through when it is an explicitly-declared refresh). Mark any PRIOR
    # is_current=1 row for the SAME directive_id as superseded, using the dormant
    # supersession columns already present in the schema. Properties:
    #   * no-op on a first run (no prior row) -> backward-compatible;
    #   * self-healing for any pre-existing duplicate-current rows;
    #   * append-only preserved (flip, never delete);
    #   * atomic with the INSERT (single commit below).
    # Scope: cointegration_sheet ONLY. Does not touch master_filter,
    # mark_superseded, quarantine, or any AGENT.md-named ledger. cointegration_
    # sheet is not an AGENT.md append-only ledger (Inv. #1 names only the two
    # Master xlsx ledgers), so this is a writer-behaviour change, not a
    # governance exception.
    _did, _rid = row.get("directive_id"), row.get("run_id")
    if _did and _rid:
        from datetime import datetime, timezone
        conn.execute(
            'UPDATE cointegration_sheet SET '
            '"is_current" = 0, "superseded_by" = ?, "superseded_at" = ?, '
            '"supersede_kind" = \'re-run\', "supersede_reason" = ? '
            'WHERE "directive_id" = ? AND "run_id" != ? AND "is_current" = 1',
            (_rid, datetime.now(timezone.utc).isoformat(),
             "superseded by cointegration refresh", _did, _rid),
        )
    conn.commit()


def upsert_basket_df(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
) -> int:
    """Bulk-insert basket rows from a DataFrame (used by backfill).

    Returns count of rows inserted (excludes ON CONFLICT no-ops).
    """
    if df.empty:
        return 0
    all_cols = [c for c in BASKET_SHEET_COLUMNS if c in df.columns]
    col_names = ", ".join(f'"{c}"' for c in all_cols)
    placeholders = ", ".join("?" for _ in all_cols)
    sql = (f'INSERT INTO basket_sheet ({col_names}) VALUES ({placeholders}) '
           f'ON CONFLICT("run_id") DO NOTHING')
    inserted = 0
    for _, row in df.iterrows():
        values = [_py_val(row.get(c)) for c in all_cols]
        cur = conn.execute(sql, values)
        inserted += cur.rowcount
    conn.commit()
    return inserted


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


def read_analysis_selection(
    conn: sqlite3.Connection | None = None,
) -> set[str]:
    """Return the set of run_ids currently flagged for the next analysis run."""
    _conn = conn or _connect()
    try:
        if not _resolve_db_path().exists():
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


def query_baskets(
    conn: sqlite3.Connection | None = None,
    current_only: bool = True,
) -> pd.DataFrame:
    """Read basket_sheet as DataFrame.

    Args:
        current_only: drop superseded rows (is_current=0). Default True
            mirrors the per-symbol writer's reader semantics.
    """
    _conn = conn or _connect()
    try:
        if not _resolve_db_path().exists():
            return pd.DataFrame(columns=BASKET_SHEET_COLUMNS)
        sql = "SELECT * FROM basket_sheet"
        if current_only:
            sql += " WHERE \"is_current\" = 1 OR \"is_current\" IS NULL"
        sql += " ORDER BY completed_at_utc DESC"
        df = pd.read_sql_query(sql, _conn)
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
    if not _resolve_db_path().exists():
        return pd.DataFrame()
    return query_master_filter()


def read_mps(sheet: str | None = None) -> pd.DataFrame:
    """Read MPS from DB. Fails hard — no Excel fallback.

    Args:
        sheet: "Portfolios" or "Single-Asset Composites". None returns all rows.

    If the DB does not exist yet (fresh install), returns empty DataFrame.
    If the DB exists but the read fails, raises — never silently falls back.
    """
    if not _resolve_db_path().exists():
        return pd.DataFrame()
    df = query_mps(sheet=sheet)
    if "sheet" in df.columns:
        df = df.drop(columns=["sheet"])
    return df


def read_baskets(current_only: bool = True) -> pd.DataFrame:
    """Read basket_sheet from DB. Fails hard — no Excel fallback."""
    if not _resolve_db_path().exists():
        return pd.DataFrame(columns=BASKET_SHEET_COLUMNS)
    return query_baskets(current_only=current_only)


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
        from tools.pipeline_utils import resilient_xlsx_write
        resilient_xlsx_write(out, lambda p: df.to_excel(p, index=False, engine="openpyxl"))
        print(f"  [EXPORT] Master Filter: {len(df)} rows -> {out}")
        return out
    finally:
        if conn is None:
            _conn.close()


def _merge_audit_columns(
    df: pd.DataFrame,
    sheet_name: str,
    xlsx_path: Path,
) -> pd.DataFrame:
    """Carry over operator-added audit columns from the existing xlsx.

    Reads the named sheet from the workbook already on disk, picks the
    columns listed in _MPS_AUDIT_COLUMNS[sheet_name]["columns"] that are
    actually present, and left-joins them onto `df` via the configured
    natural key. New rows (no match) get NaN; existing rows keep their
    operator annotations.

    Returns `df` unchanged when the workbook doesn't exist, the sheet
    isn't in it, the join key is missing on either side, or none of the
    whitelisted columns are present in the workbook.
    """
    spec = _MPS_AUDIT_COLUMNS.get(sheet_name)
    if spec is None or df.empty or not xlsx_path.exists():
        return df
    try:
        # Explicit ExcelFile context so the underlying openpyxl handle is
        # released deterministically before the caller's atomic-replace
        # writer runs. Windows os.replace() requires NO open handles on the
        # destination path; the bare pd.read_excel(path, ...) form can let
        # openpyxl hold the handle past return on some Python/openpyxl/pandas
        # combinations, producing WinError 5 during the subsequent replace.
        with pd.ExcelFile(xlsx_path, engine="openpyxl") as xl:
            existing = pd.read_excel(xl, sheet_name=sheet_name)
    except (ValueError, KeyError, FileNotFoundError):
        return df
    key = spec["key"]
    if key not in existing.columns or key not in df.columns:
        return df
    # Skip any audit column that is already in df — if it ever migrates
    # into the DB schema, the DB becomes authoritative and the merge
    # would otherwise create _x/_y suffixed duplicates.
    present = [c for c in spec["columns"]
               if c in existing.columns and c not in df.columns]
    if not present:
        return df
    audit = existing[[key] + present].drop_duplicates(subset=[key], keep="last")
    merged = df.merge(audit, on=key, how="left")
    print(f"  [PRESERVE] {sheet_name} audit columns: {present}")
    return merged


def _read_cointegration_current(conn: sqlite3.Connection) -> pd.DataFrame:
    """Read current (is_current=1) cointegration_sheet rows. Empty DataFrame if
    the table doesn't exist yet (fresh DB) -- mirrors the Baskets guard."""
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cointegration_sheet'"
    ).fetchone()
    if not exists:
        return pd.DataFrame()
    return pd.read_sql_query(
        "SELECT * FROM cointegration_sheet WHERE is_current = 1", conn
    )


def _latest_coint_regime_map() -> dict:
    """Current 252d cointegration regime per pair for the COINT TRADE
    CANDIDATES "Coint Status (252d)" column.

    Reads the screener DB (cointegration_daily) -- the same source behind the
    "All Pairs (Diagnostic)" sheet -- via tools.cointegration_db. Best-effort
    enrichment: any failure (missing/locked DB, schema drift) returns an empty
    map so MPS regeneration is never blocked by a source that lives in a sibling
    data store with its own refresh lifecycle. The status reflects the standard
    252d screen as of its latest run, NOT the per-pair window each candidate was
    backtested on.
    """
    try:
        from tools import cointegration_db as _cdb
        if not _cdb.SQLITE_DB.exists():
            return {}
        _c = _cdb.connect(_cdb.SQLITE_DB)
        try:
            return _cdb.latest_regime_map(_c, tf="1d", lookback_days=252)
        finally:
            _c.close()
    except Exception as exc:  # best-effort: never block the MPS export
        print(f"  [EXPORT] WARN: cointegration regime lookup failed "
              f"({type(exc).__name__}: {exc}); 'Coint Status (252d)' left blank")
        return {}


def export_mps(
    conn: sqlite3.Connection | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write MPS Excel from DB with Portfolios + Single-Asset + Baskets sheets.

    The Baskets sheet is only included if basket_sheet has rows (so a fresh
    install with no basket runs still produces a valid 2-sheet xlsx).
    """
    _conn = conn or _connect()
    try:
        df_port = query_mps(_conn, sheet="Portfolios")
        df_single = query_mps(_conn, sheet="Single-Asset Composites")
        df_baskets = query_baskets(_conn, current_only=True)
        df_coint = _read_cointegration_current(_conn)

        # Drop the 'sheet' discriminator and all-null columns from export.
        # NOTE: on an empty DataFrame, df[c].isna().all() is True for every
        # column — guard the all-null drop with len>0 to avoid wiping the
        # schema (regression surfaced by Phase 5b.3 basket-only test runs
        # where portfolio_sheet is empty but basket_sheet has rows).
        for df in (df_port, df_single):
            if "sheet" in df.columns:
                df.drop(columns=["sheet"], inplace=True)
            if len(df) > 0:
                all_null = [c for c in df.columns if df[c].isna().all()]
                if all_null:
                    df.drop(columns=all_null, inplace=True)

        # Join burn_in_status from portfolio_control (read-only view column).
        # Skip if portfolio_id was wiped (empty Portfolios table).
        ctrl = read_portfolio_control(conn=_conn)
        if not ctrl.empty:
            status_map = dict(zip(ctrl["portfolio_id"], ctrl["status"]))
        else:
            status_map = {}
        for df in (df_port, df_single):
            if "portfolio_id" in df.columns:
                df.insert(1, "burn_in_status",
                          df["portfolio_id"].map(status_map).fillna(""))

        # Strip DB-bookkeeping columns from the Baskets export — they belong
        # in the DB, not the user-facing sheet (mirrors how master_filter's
        # is_current/superseded_* are absent from FSP export).
        if not df_baskets.empty:
            for c in ("is_current", "superseded_by", "superseded_at",
                      "supersede_reason"):
                if c in df_baskets.columns:
                    df_baskets = df_baskets.drop(columns=[c])

        out = output_path or _resolve_mps_path()
        out.parent.mkdir(parents=True, exist_ok=True)

        # Carry over operator-added audit columns from the existing xlsx
        # before the ExcelWriter(mode='w') below truncates it. Whitelisted
        # in _MPS_AUDIT_COLUMNS; joined by the sheet's natural key.
        df_baskets = _merge_audit_columns(df_baskets, "Baskets", out)

        # Cointegration research ledger -> its own tab as the lean human view
        # (separate ontology). The DB keeps every column; the view projects to
        # the ~16 a human scans (sorted, ranked, friendly-named).
        df_coint_view = None
        df_candidates = None
        if not df_coint.empty:
            from tools.portfolio.cointegration_view import build_cointegration_view_df
            df_coint_view = build_cointegration_view_df(df_coint)
            # Pair-level decision-support shortlist (one row per pair). Separate
            # grain from the run-level Cointegration tab; same is_current rows.
            from tools.portfolio.trade_candidates_view import build_trade_candidates_df
            # Current 252d cointegration regime per pair, read from the screener
            # DB (cointegration_daily -- the source behind "All Pairs
            # (Diagnostic)"). Best-effort: a missing/locked screener DB leaves
            # the status column blank rather than aborting MPS regeneration.
            regime_map = _latest_coint_regime_map()
            df_candidates = build_trade_candidates_df(df_coint, regime_map=regime_map)

        # Atomic, lock-resilient write via the shared SSOT writer: per-PID temp
        # render -> kill-Excel-if-locked -> os.replace with backoff -> loud-fail.
        # The xlsx is a derived view of the canonical DB; concurrent
        # --max-parallel exporters use per-PID temps and never observe a
        # half-written workbook ("last writer wins"; DB stays authoritative).
        from tools.pipeline_utils import resilient_xlsx_write

        def _render_mps(_p):
            with pd.ExcelWriter(str(_p), engine="openpyxl") as writer:
                df_port.to_excel(writer, sheet_name="Portfolios", index=False)
                df_single.to_excel(writer, sheet_name="Single-Asset Composites", index=False)
                if not df_baskets.empty:
                    df_baskets.to_excel(writer, sheet_name="Baskets", index=False)
                # Shortlist before the detailed tab: summary then drill-down.
                if df_candidates is not None and not df_candidates.empty:
                    df_candidates.to_excel(writer, sheet_name="COINT TRADE CANDIDATES", index=False)
                if df_coint_view is not None and not df_coint_view.empty:
                    df_coint_view.to_excel(writer, sheet_name="Cointegration", index=False)

        resilient_xlsx_write(out, _render_mps)

        suffix = f", Baskets={len(df_baskets)}" if not df_baskets.empty else ""
        if df_candidates is not None and not df_candidates.empty:
            suffix += f", TradeCandidates={len(df_candidates)}"
        if df_coint_view is not None and not df_coint_view.empty:
            suffix += f", Cointegration={len(df_coint_view)}"
        print(f"  [EXPORT] MPS: Portfolios={len(df_port)}, "
              f"Single-Asset Composites={len(df_single)}{suffix} -> {out}")
        return out
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _py_val(val: Any) -> Any:
    """Convert pandas/numpy scalars to native Python for SQLite.

    Handles None, pd.NA, np.nan, np.integer/np.floating/np.bool_. pd.NA is
    coerced to None so sqlite3's parameter binding works (it does not
    natively understand pandas.NAType).
    """
    if val is None:
        return None
    # pd.NA propagates through `==` so the usual check fails; use isna.
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        # pd.isna raises on non-scalar inputs (lists, dicts); fall through
        pass
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
        # basket_sheet may not exist on first run before create_tables
        try:
            basket_count = _conn.execute(
                "SELECT COUNT(*) FROM basket_sheet"
            ).fetchone()[0]
            basket_current = _conn.execute(
                "SELECT COUNT(*) FROM basket_sheet "
                "WHERE \"is_current\" = 1 OR \"is_current\" IS NULL"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            basket_count = basket_current = 0

        print(f"\n  Ledger DB: {LEDGER_DB_PATH}")
        print(f"  master_filter:    {mf_count} rows")
        print(f"  portfolio_sheet:  {mps_count} rows "
              f"(Portfolios={mps_port}, Single-Asset Composites={mps_single})")
        print(f"  basket_sheet:     {basket_count} rows "
              f"(current={basket_current})")
        print()
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Portfolio Control — CRUD
# ---------------------------------------------------------------------------

PORTFOLIO_CONTROL_VALID_STATUSES = {"SELECTED", "LIVE", "REMOVE"}


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
