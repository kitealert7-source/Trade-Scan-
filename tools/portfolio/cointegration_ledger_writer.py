"""cointegration_ledger_writer.py -- append-only, sink-only writer for the
cointegration_sheet ledger table.

INTENTIONALLY DUMB. This writer does NOT compute metrics, does NOT read parquet
contents, and NEVER reads the screener DB. The caller (the pipeline
orchestrator, P3) provides ALL business data -- canonical metrics, regime
provenance, reproducibility fields -- in the `row` dict. The writer only:
  1. validates the row against the contract (fail-fast),
  2. enforces the append-only invariant (existing run_id -> FATAL),
  3. persists to ledger.db.cointegration_sheet.

PROVENANCE IS IMMUTABLE: a run_id's row is written once and never updated here.
Re-runs are NEW run_ids (new rows); supersession is a separate lineage op.

SINK-ONLY: the only filesystem touch is an EXISTENCE check on the recorded
backtests_path (do not store a pointer to nothing) -- never a content read.

The xlsx render (the Cointegration tab) is a downstream concern (P4); this
writer's job is to persist to the source of truth (the DB).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.portfolio.cointegration_schema import (
    COINTEGRATION_SHEET_COLUMNS,
    SCHEMA_VERSION,
)
from tools.portfolio.research_metrics import validate_metrics_json


class CointegrationLedgerError(RuntimeError):
    """Raised on append-only violation or a row-contract failure."""


# Fields the caller MUST provide for a row to be meaningful. Everything else in
# the schema is optional/nullable (candidate_key, supersede_*, metrics_json,
# span_*, n_obs, stake_usd, the reproducibility quartet when unavailable, ...).
REQUIRED_FIELDS = (
    "run_id",
    "directive_id",
    "pair_a",
    "pair_b",
    "timeframe",
    "lookback_days",
    "test_start",
    "test_end",
    "completed_at_utc",
    "backtests_path",
    "canonical_net_pct",
    "canonical_max_dd_pct",
    "canonical_ret_dd",
    "canonical_final_equity_usd",
    "trades_total",
    # methodology_version added 2026-05-30 (C2). Mandatory so no row can
    # silently enter the corpus without a methodology cohort tag — every
    # row must declare 'v1_raw_adf' (legacy), 'v2_log_eg' (post-C3), etc.
    "methodology_version",
    # engine_version added 2026-06-16 (engine-identity convergence). Mandatory
    # so a row can never enter the corpus without recording the COMPUTE engine.
    # A None/blank stamp is now a FATAL write rejection rather than a silent
    # NULL. The orchestrator sources it from the basket compute single-source
    # (run_pipeline._basket_compute_engine_version). See memory
    # engine_identity_is_compute_not_stamp.
    "engine_version",
)


def _validate_row(row: dict[str, Any]) -> None:
    unknown = set(row) - set(COINTEGRATION_SHEET_COLUMNS)
    if unknown:
        raise CointegrationLedgerError(
            f"[FATAL] unknown column(s) for cointegration_sheet: {sorted(unknown)}"
        )
    missing = [f for f in REQUIRED_FIELDS if row.get(f) in (None, "")]
    if missing:
        raise CointegrationLedgerError(
            f"[FATAL] missing required field(s): {missing}. The writer is a pure "
            f"sink -- the caller must supply all provenance and metrics."
        )
    # metrics_json governed: scalar / typed / namespaced / registered.
    validate_metrics_json(row.get("metrics_json"))


def _resolve_backtests_dir(backtests_path: str) -> Path:
    """backtests_path is stored relative to TradeScan_State; resolve it for the
    EXISTENCE check only. The writer records the relative string verbatim and
    never reads the directory's contents."""
    from config.path_authority import TRADE_SCAN_STATE
    p = Path(backtests_path)
    return p if p.is_absolute() else (TRADE_SCAN_STATE / p)


def append_cointegration_row(row: dict[str, Any]) -> None:
    """Append one row to ledger.db.cointegration_sheet. Sink-only + append-only.

    Raises CointegrationLedgerError on a contract violation, a missing backtest
    folder, or a duplicate run_id (append-only invariant; provenance immutable).
    """
    row = dict(row)  # defensive copy; never mutate the caller's provenance
    _validate_row(row)

    bt_dir = _resolve_backtests_dir(str(row["backtests_path"]))
    if not bt_dir.exists():
        raise CointegrationLedgerError(
            f"[FATAL] backtests_path does not exist: {bt_dir}. Refusing to record "
            f"a row that points at a missing artifact."
        )

    # Writer-owned bookkeeping (the only fields the writer sets itself).
    row.setdefault("schema_version", SCHEMA_VERSION)
    row.setdefault("enrichment_status", "complete")
    row["is_current"] = 1

    # Lazy import mirrors the basket writer (managed cycle with ledger_db).
    from tools.ledger_db import _connect, create_tables, upsert_cointegration_row

    conn = _connect()
    try:
        create_tables(conn)
        existing = conn.execute(
            "SELECT 1 FROM cointegration_sheet WHERE run_id = ? LIMIT 1",
            (row["run_id"],),
        ).fetchone()
        if existing:
            raise CointegrationLedgerError(
                f"[FATAL] cointegration_sheet already contains run_id="
                f"{row['run_id']!r}. Append-only invariant; provenance is "
                f"immutable. A re-run must use a new run_id."
            )
        upsert_cointegration_row(conn, row)
    finally:
        conn.close()


__all__ = [
    "CointegrationLedgerError",
    "REQUIRED_FIELDS",
    "append_cointegration_row",
]
