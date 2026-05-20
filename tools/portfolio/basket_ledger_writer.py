"""basket_ledger_writer.py — append-only writer for the Baskets sheet of MPS.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.3 (SQL promotion, 2026-05-20).

The writer goes through SQLite (`ledger.db.basket_sheet` via `tools/ledger_db.py`)
and then calls `export_mps()` to regenerate `Master_Portfolio_Sheet.xlsx`
from the DB. Mirrors the per-symbol writer's flow exactly.

Both the per-symbol writer and this writer use the same FileLock on
`Master_Portfolio_Sheet.xlsx.lock` so the Excel export step is serialized
across concurrent basket dispatches and per-symbol pipelines (SQLite's
own WAL handles the DB-write serialization).

Append-only invariant (Invariant #2): existing basket_sheet rows are
never mutated. Writing the same `run_id` twice raises a FATAL error,
matching the per-symbol writer's pattern. Pre-insert SELECT-1 is the
primary check; the ON CONFLICT(run_id) DO NOTHING in `upsert_basket_row`
is the SQL-level safety net.

Verdict computation (CORE/WATCH/FAIL) was previously in
`tools/excel_format/styling.py::_compute_basket_verdict` (presentation
layer). Phase 5b.3 moved it here so it lives in the DB (mirrors how
`portfolio_status` is computed at write time, not at export time).

Schema (locked Phase 5b.2):
    run_id              str  — 12-char hex from generate_run_id()
    directive_id        str  — e.g. "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    basket_id           str  — e.g. "H2"
    execution_mode      str  — always "basket"
    rule_name           str  — e.g. "H2_recycle"
    rule_version        int  — e.g. 1
    leg_count           int  — len(legs)
    leg_specs           str  — "EURUSD:0.02:long;USDJPY:0.01:short"
    trades_total        int
    recycle_event_count int
    harvested_total_usd float
    final_realized_usd  float — sum of all realized cash (winner closures + harvest)
    exit_reason         str  — "TARGET" | "FLOOR" | "BLOWN" | "TIME" | None
    completed_at_utc    str  — ISO8601 of when this row was written
    backtests_path      str  — relative path to backtests/<id>/raw/
    vault_path          str  — relative path to DRY_RUN_VAULT/baskets/<id>/<basket_id>/
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from filelock import FileLock

from tools.basket_ledger import leg_specs_string


_BASKETS_SHEET = "Baskets"

# Locked column order for the Baskets sheet (additive only at right edge).
# 1.3.0-basket additions (right-edge append): 10 derived metrics from the
# rule's in-memory summary_stats + 1 schema_version column. NOT computed
# from re-reading the just-written parquet — operator M1 (plan §0.5).
BASKETS_SHEET_COLUMNS = [
    # ---- 1.2.0-basket (existing, untouched) ----
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
    # ---- 1.3.0-basket additions (right-edge append, in-memory derived) ----
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
    # ---- 1.4.0-basket-canonical additions (2026-05-17) ----
    # Cycle-aware metrics from tools/basket_hypothesis/canonical_metrics
    # (the parquet IS the source of truth for cycle-mechanic rules).
    # Populated when run_pipeline.py passes parquet_path + stake_usd;
    # left as pd.NA otherwise (back-compat). These columns supersede the
    # trade-level-derived peak_floating_dd_* fields above for cycle
    # mechanics (@4/@5+); the older columns stay for legacy @1/@2/@3
    # baskets and for back-compat with historical rows.
    "canonical_net_pct",
    "canonical_max_dd_pct",
    "canonical_ret_dd",
    "canonical_final_equity_usd",
    "cycle_win_rate_pct",
    "cycles_completed",
    "peak_winner_lot",
    "rule_family",
    # ---- Phase 5b.3 additions (right-edge append, 2026-05-20) ----
    # verdict_status: CORE/WATCH/FAIL computed at write time by compute_verdict().
    # Was previously injected by the formatter (tools/excel_format/styling.py);
    # promoted to a writer output as part of the SQL migration so the value
    # lives in ledger.db.basket_sheet and is consistent across readers.
    "verdict_status",
    # enrichment_status: data-completeness marker for the row. Values:
    #   complete    — canonical_metrics computed; verdict + KPIs trustworthy
    #   no_canonical — legacy row, artifact matched, but no parquet available
    #   overwritten  — legacy row whose artifact dir was clobbered by a later
    #                  same-directive_id re-run (paired with is_current=0)
    "enrichment_status",
]


class BasketLedgerError(RuntimeError):
    """Raised on append-only invariant violation."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _mps_path() -> Path:
    """Locate Master_Portfolio_Sheet.xlsx via the canonical state path."""
    from config.path_authority import TRADE_SCAN_STATE
    return TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"


def _build_row(
    *,
    basket_result: Any,
    run_id: str,
    directive_id: str,
    backtests_path: str,
    vault_path: str,
    df_trades: Any = None,
    parquet_path: Path | str | None = None,
    stake_usd: float | None = None,
) -> dict[str, Any]:
    """Project a BasketRunResult into one Baskets-sheet row.

    If df_trades is supplied (the basket_ledger.basket_result_to_tradelevel_df
    output), final_realized_usd is computed from its `pnl_usd` column —
    which the converter fills for engine-emitted force_close trades that
    don't carry pnl_usd themselves. This closes the bug surfaced by P03
    in Phase 5d.1 where MPS showed final_realized=0 while the per-window
    REPORT (built by the converter) showed -$308.34.
    """
    trades_total = sum(len(t) for t in basket_result.per_leg_trades.values())
    final_realized = 0.0
    if df_trades is not None and hasattr(df_trades, "columns") and "pnl_usd" in df_trades.columns:
        # Use the converter's pnl_usd column (it computes from prices+lot
        # for trades where the engine didn't fill pnl_usd directly).
        try:
            final_realized = float(df_trades["pnl_usd"].astype(float).fillna(0.0).sum())
        except (TypeError, ValueError):
            final_realized = 0.0
    else:
        # Fallback: sum from raw basket_result.per_leg_trades dicts.
        for trades in basket_result.per_leg_trades.values():
            for t in trades:
                v = t.get("pnl_usd")
                if v is not None:
                    try:
                        final_realized += float(v)
                    except (TypeError, ValueError):
                        pass
    base_row: dict[str, Any] = {
        "run_id":              run_id,
        "directive_id":        directive_id,
        "basket_id":           basket_result.basket_id,
        "execution_mode":      basket_result.execution_mode,
        "rule_name":           basket_result.rule_name,
        "rule_version":        int(basket_result.rule_version),
        "leg_count":           len(basket_result.legs),
        "leg_specs":           leg_specs_string(basket_result.legs),
        "trades_total":        int(trades_total),
        "recycle_event_count": int(len(basket_result.recycle_events)),
        "harvested_total_usd": float(basket_result.harvested_total_usd),
        "final_realized_usd":  float(final_realized),
        "exit_reason":         _resolve_exit_reason(basket_result),
        "completed_at_utc":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backtests_path":      backtests_path,
        "vault_path":          vault_path,
    }

    # 1.3.0-basket: derived columns from the rule's in-memory summary_stats
    # (plan §6 M1 — explicitly NOT from re-reading the parquet). Rules that
    # don't emit summary_stats (V2/V3 today) get NaN-filled rows for these
    # columns; schema_version still records 1.3.0 because the WRITER is
    # 1.3.0-aware regardless of whether the rule populated the ledger.
    stats = getattr(basket_result, "summary_stats", None) or {}
    derived: dict[str, Any] = {"schema_version": "1.3.0-basket"}
    if stats:
        peak_dd = stats.get("peak_floating_dd_usd")
        peak_dd_pct = stats.get("peak_floating_dd_pct")
        derived["peak_floating_dd_usd"] = (
            abs(float(peak_dd)) if peak_dd is not None else pd.NA
        )
        derived["peak_floating_dd_pct"] = (
            abs(float(peak_dd_pct)) if peak_dd_pct is not None else pd.NA
        )
        derived["dd_freeze_count"]     = int(stats.get("dd_freeze_count", 0))
        derived["margin_freeze_count"] = int(stats.get("margin_freeze_count", 0))
        derived["regime_freeze_count"] = int(stats.get("regime_freeze_count", 0))
        derived["peak_margin_used_usd"] = float(stats.get("peak_margin_used_usd", 0.0))
        mm = stats.get("min_margin_level_pct")
        derived["min_margin_level_pct"] = float(mm) if mm is not None else pd.NA
        derived["worst_floating_at_freeze_usd"] = float(
            stats.get("worst_floating_at_freeze_usd", 0.0)
        )
        ror = stats.get("return_on_real_capital_pct")
        derived["return_on_real_capital_pct"] = float(ror) if ror is not None else pd.NA
        peak_lots = stats.get("peak_lots") or {}
        derived["peak_lots_json"] = json.dumps(peak_lots) if peak_lots else pd.NA
    else:
        # Legacy basket run (no summary_stats — rule didn't emit ledger telemetry).
        for col in (
            "peak_floating_dd_usd", "peak_floating_dd_pct",
            "dd_freeze_count", "margin_freeze_count", "regime_freeze_count",
            "peak_margin_used_usd", "min_margin_level_pct",
            "worst_floating_at_freeze_usd", "return_on_real_capital_pct",
            "peak_lots_json",
        ):
            derived[col] = pd.NA

    # 1.4.0-basket-canonical: cycle-aware metrics from the parquet, via
    # tools.basket_hypothesis.canonical_metrics. Populated only when the
    # caller passed parquet_path + stake_usd (run_pipeline.py does this
    # post-Phase 5d.2). For cycle-mechanic rules (@4/@5), these supersede
    # the legacy trade-level fields above; for @1/@2/@3, both are correct.
    canonical_cols = (
        "canonical_net_pct", "canonical_max_dd_pct", "canonical_ret_dd",
        "canonical_final_equity_usd", "cycle_win_rate_pct",
        "cycles_completed", "peak_winner_lot", "rule_family",
    )
    if parquet_path is not None and stake_usd is not None:
        try:
            from tools.basket_hypothesis.canonical_metrics import canonical_metrics
            cm = canonical_metrics(parquet_path, float(stake_usd))
            peak_lots = cm.get("peak_lots") or {}
            derived["canonical_net_pct"]          = float(cm["net_pct"])
            derived["canonical_max_dd_pct"]       = float(cm["max_dd_pct"])
            derived["canonical_ret_dd"]           = float(cm["ret_dd"])
            derived["canonical_final_equity_usd"] = float(cm["final_equity_usd"])
            derived["cycle_win_rate_pct"]         = float(cm["cycle_win_rate_pct"])
            derived["cycles_completed"]           = int(cm["cycles_completed"])
            derived["peak_winner_lot"]            = (
                float(max(peak_lots.values())) if peak_lots else pd.NA
            )
            derived["rule_family"]                = str(cm["rule_family"])
        except Exception:
            # canonical_metrics is supplemental — do not block row write
            # on a parquet read error. Mark fields NA.
            for col in canonical_cols:
                derived[col] = pd.NA
    else:
        for col in canonical_cols:
            derived[col] = pd.NA

    return {**base_row, **derived}


def _resolve_exit_reason(basket_result: Any) -> str:
    """The H2RecycleRule exposes exit_reason on the rule, not on the result.
    BasketRunResult doesn't currently surface it — read None gracefully."""
    return getattr(basket_result, "exit_reason", None) or ""


def compute_verdict(row: dict[str, Any]) -> str:
    """Compute CORE/WATCH/FAIL verdict from a row's canonical metrics.

    Mirrors the convention in
    `tools.portfolio.portfolio_profile_selection._compute_portfolio_status`:
    realized cash <= 0 is an instant FAIL regardless of equity-curve metrics
    (otherwise a basket carrying large floating PnL on still-open positions
    can mask negative closed-trade cash). For baskets, "real cash" is
    `final_realized_usd + harvested_total_usd`.

    Verdict ladder:
      FAIL  — canonical_net_pct < 0  OR  (realized + harvested) <= 0
      CORE  — passes FAIL AND canonical_ret_dd >= 2.0 AND canonical_max_dd_pct <= 40
      WATCH — passes FAIL but does not meet CORE thresholds
    Rows missing any required canonical metric return "" (legacy rows).
    """
    import math

    net = row.get("canonical_net_pct")
    dd = row.get("canonical_max_dd_pct")
    ret_dd = row.get("canonical_ret_dd")

    def _isna(v: Any) -> bool:
        if v is None:
            return True
        try:
            return bool(pd.isna(v))
        except (TypeError, ValueError):
            return isinstance(v, float) and math.isnan(v)

    if _isna(net) or _isna(dd) or _isna(ret_dd):
        return ""

    realized = 0.0 if _isna(row.get("final_realized_usd")) else float(row["final_realized_usd"])
    harvested = 0.0 if _isna(row.get("harvested_total_usd")) else float(row["harvested_total_usd"])
    real_cash = realized + harvested

    if float(net) < 0 or real_cash <= 0:
        return "FAIL"
    if float(ret_dd) >= 2.0 and float(dd) <= 40:
        return "CORE"
    return "WATCH"


def append_basket_row_to_mps(
    basket_result: Any,
    *,
    run_id: str,
    directive_id: str,
    backtests_path: str = "",
    vault_path: str = "",
    df_trades: Any = None,
    parquet_path: Path | str | None = None,
    stake_usd: float | None = None,
) -> Path:
    """Append a basket-run row to ledger.db.basket_sheet, then regenerate MPS xlsx.

    Returns the path of the MPS file written. Raises BasketLedgerError if
    the run_id already exists (append-only invariant — pre-insert SELECT 1).

    df_trades is the optional tradelevel DataFrame from
    `tools.basket_ledger.basket_result_to_tradelevel_df`. When supplied,
    `final_realized_usd` is computed from its pnl_usd column (which the
    converter fills for engine-force-close trades). When omitted, falls
    back to summing pnl_usd from `basket_result.per_leg_trades` directly
    (lossy for force_close trades — see _build_row docstring).
    """
    # Imported here to avoid circular import at module load (ledger_db
    # imports basket_ledger_writer for backfill helpers).
    from tools.ledger_db import (
        _connect,
        create_tables,
        export_mps,
        upsert_basket_row,
    )

    ledger_path = _mps_path()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    new_row = _build_row(
        basket_result=basket_result,
        run_id=run_id,
        directive_id=directive_id,
        backtests_path=backtests_path,
        vault_path=vault_path,
        df_trades=df_trades,
        parquet_path=parquet_path,
        stake_usd=stake_usd,
    )

    # Verdict + DB bookkeeping (Phase 5b.3 — moved out of formatter).
    new_row["verdict_status"] = compute_verdict(new_row)
    # New writes always go through the canonical_metrics path (parquet exists,
    # stake known) so enrichment_status defaults to "complete". Backfills /
    # legacy imports set their own status.
    new_row["enrichment_status"] = "complete"
    new_row["is_current"] = 1

    # FileLock coordinates the Excel export step with the per-symbol writer;
    # SQLite WAL handles concurrent DB writes on its own.
    lock_path = ledger_path.with_suffix(".lock")
    with FileLock(str(lock_path), timeout=120):
        conn = _connect()
        try:
            create_tables(conn)
            # Append-only invariant: explicit pre-check beats relying on
            # ON CONFLICT DO NOTHING (silent no-op vs. caller's FATAL).
            existing = conn.execute(
                'SELECT 1 FROM basket_sheet WHERE run_id = ? LIMIT 1',
                (run_id,),
            ).fetchone()
            if existing:
                raise BasketLedgerError(
                    f"[FATAL] basket_sheet already contains run_id={run_id!r}. "
                    f"Append-only invariant; manual deletion required if a "
                    f"re-run is intentional. (Per-symbol writer enforces the "
                    f"same rule on master_filter.)"
                )
            upsert_basket_row(conn, new_row)
        finally:
            conn.close()

        # Regenerate MPS xlsx from DB so human-readable artifact stays in sync.
        # Failure is non-fatal — DB is the source of truth; re-export catches up.
        try:
            export_mps()
        except Exception as exc:
            print(f"  [WARN] basket_sheet row written to DB; MPS xlsx export "
                  f"failed: {exc}. Re-run: python tools/ledger_db.py --export-mps")

    return ledger_path


__all__ = [
    "BASKETS_SHEET_COLUMNS",
    "BasketLedgerError",
    "append_basket_row_to_mps",
    "compute_verdict",
]
