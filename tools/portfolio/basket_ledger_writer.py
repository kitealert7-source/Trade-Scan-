"""basket_ledger_writer.py — append-only writer for the Baskets sheet of MPS.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.2 (Path B).

The per-symbol writer in `tools/portfolio/portfolio_ledger_writer.py`
goes through SQLite (ledger_db) → Excel. Basket runs don't fit the
per-symbol metrics shape that `_compute_ledger_row` expects, so this
writer maintains a SEPARATE sheet (`Baskets`) within
`Master_Portfolio_Sheet.xlsx` via openpyxl directly. SQLite integration
of the basket schema is deferred to Phase 5b.3 cleanup; until then the
Excel sheet IS the source of truth for basket runs.

Both the per-symbol writer and this writer use the same FileLock on
`Master_Portfolio_Sheet.xlsx.lock`, so concurrent writes from a basket
dispatch and a per-symbol pipeline are serialized correctly.

Append-only invariant (Invariant #2): existing Baskets rows are never
mutated. Writing the same (run_id) twice raises a FATAL error matching
the per-symbol writer's pattern.

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

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from filelock import FileLock

from tools.basket_ledger import leg_specs_string


_BASKETS_SHEET = "Baskets"

# Locked column order for the Baskets sheet (additive only at right edge).
BASKETS_SHEET_COLUMNS = [
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
    return {
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


def _resolve_exit_reason(basket_result: Any) -> str:
    """The H2RecycleRule exposes exit_reason on the rule, not on the result.
    BasketRunResult doesn't currently surface it — read None gracefully."""
    return getattr(basket_result, "exit_reason", None) or ""


def append_basket_row_to_mps(
    basket_result: Any,
    *,
    run_id: str,
    directive_id: str,
    backtests_path: str = "",
    vault_path: str = "",
    df_trades: Any = None,
) -> Path:
    """Append a basket-run row to the Baskets sheet of MPS.

    Returns the path of the MPS file written. Raises BasketLedgerError if
    the run_id already exists (append-only invariant).

    df_trades is the optional tradelevel DataFrame from
    `tools.basket_ledger.basket_result_to_tradelevel_df`. When supplied,
    `final_realized_usd` is computed from its pnl_usd column (which the
    converter fills for engine-force-close trades). When omitted, falls
    back to summing pnl_usd from `basket_result.per_leg_trades` directly
    (lossy for force_close trades — see _build_row docstring).
    """
    ledger_path = _mps_path()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    new_row = _build_row(
        basket_result=basket_result,
        run_id=run_id,
        directive_id=directive_id,
        backtests_path=backtests_path,
        vault_path=vault_path,
        df_trades=df_trades,
    )

    # Use the same lock the per-symbol writer uses so basket + per-symbol
    # writes serialize correctly.
    lock_path = ledger_path.with_suffix(".lock")
    with FileLock(str(lock_path), timeout=120):
        # Read existing sheets (preserve all other tabs verbatim).
        existing_sheets: dict[str, pd.DataFrame] = {}
        if ledger_path.exists():
            with pd.ExcelFile(ledger_path) as xls:
                for sn in xls.sheet_names:
                    try:
                        existing_sheets[sn] = pd.read_excel(xls, sheet_name=sn)
                    except Exception:
                        pass

        # Build / extend the Baskets sheet
        if _BASKETS_SHEET in existing_sheets:
            df_baskets = existing_sheets[_BASKETS_SHEET]
        else:
            df_baskets = pd.DataFrame(columns=BASKETS_SHEET_COLUMNS)

        # Append-only invariant: refuse to add the same run_id twice.
        if "run_id" in df_baskets.columns and run_id in set(df_baskets["run_id"].astype(str)):
            raise BasketLedgerError(
                f"[FATAL] Baskets sheet already contains run_id={run_id!r}. "
                f"Append-only invariant; manual deletion required if a re-run "
                f"is intentional. (Per-symbol writer enforces the same rule.)"
            )

        # Add any newly introduced columns at the right edge of the existing
        # frame so column order stays append-only across versions.
        for col in BASKETS_SHEET_COLUMNS:
            if col not in df_baskets.columns:
                df_baskets[col] = pd.NA
        # Reorder to canonical order (any extra columns from older writers
        # remain trailing).
        ordered = BASKETS_SHEET_COLUMNS + [c for c in df_baskets.columns if c not in BASKETS_SHEET_COLUMNS]
        df_baskets = df_baskets[ordered]

        df_baskets = pd.concat([df_baskets, pd.DataFrame([new_row])], ignore_index=True)
        existing_sheets[_BASKETS_SHEET] = df_baskets

        # Atomic write: tmp + fsync + replace
        tmp_path = ledger_path.with_suffix(".xlsx.tmp")
        with pd.ExcelWriter(tmp_path, engine="openpyxl", mode="w") as writer:
            for sn, sdf in existing_sheets.items():
                sdf.to_excel(writer, sheet_name=sn, index=False)
        with open(tmp_path, "r+b") as fh:
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(ledger_path))

    # NOTE: deliberately NOT calling tools/format_excel_artifact.py here.
    # That formatter is per-symbol-portfolio-schema-aware and DESTROYS our
    # Baskets sheet by reshaping it to match Portfolios columns. Phase 5b.3
    # cleanup may add a basket-aware formatter profile; until then the
    # Baskets sheet is readable as-is in Excel + via pandas.

    return ledger_path


__all__ = [
    "BASKETS_SHEET_COLUMNS",
    "BasketLedgerError",
    "append_basket_row_to_mps",
]
