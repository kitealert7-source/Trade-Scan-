"""reenrich_cointegration.py -- recompute a cointegration row's derived metrics
from its RETAINED parquet substrate.

This is the future-proofing path: a new decision metric is a RECOMPUTE over the
immutable substrate, not a re-run and not a schema migration. It updates ONLY
the derived metric columns + metrics_fn_version. Identity, provenance (window,
regime, reproducibility hashes), and lineage are IMMUTABLE and never touched.

Integrity: verifies parquet_sha256 first. If the substrate changed, that is a
DATA change and must be a re-run (new run_id), not a recompute -- the tool
refuses rather than silently re-deriving against different bytes.

Usage:
    python tools/reenrich_cointegration.py <run_id>
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from tools.portfolio.cointegration_schema import METRICS_FN_VERSION


class ReenrichError(RuntimeError):
    """Raised on a missing row, missing substrate, or sha256 mismatch."""


def _f(v) -> float | None:
    return None if v is None else float(v)


def _parquet_path(backtests_path: str) -> Path:
    from config.path_authority import TRADE_SCAN_STATE
    return TRADE_SCAN_STATE / backtests_path / "raw" / "results_basket_per_bar.parquet"


def reenrich_cointegration_row(run_id: str) -> dict:
    """Recompute derived metrics for `run_id` from its retained parquet and
    UPDATE them in place. Returns the recomputed metric dict.

    Raises ReenrichError on a missing current row, a missing parquet (substrate
    lost -- the retention guard should prevent this), or a sha256 mismatch.
    """
    from tools.ledger_db import _connect
    from tools.basket_hypothesis.canonical_metrics import canonical_metrics

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT backtests_path, parquet_sha256, stake_usd FROM cointegration_sheet "
            "WHERE run_id = ? AND is_current = 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ReenrichError(f"no current cointegration row for run_id={run_id!r}")
        backtests_path, stored_sha, stake_usd = row

        pq = _parquet_path(str(backtests_path))
        if not pq.is_file():
            raise ReenrichError(
                f"retained parquet missing: {pq}. Substrate lost -- cannot "
                f"recompute. (The retention guard should prevent this.)"
            )
        current_sha = hashlib.sha256(pq.read_bytes()).hexdigest()
        if stored_sha and current_sha != str(stored_sha):
            raise ReenrichError(
                f"parquet_sha256 mismatch for {run_id}: the substrate changed "
                f"since write. A data change must be a re-run (new run_id), not a "
                f"recompute."
            )

        cm = canonical_metrics(pq, float(stake_usd or 1000.0))
        values = {
            "canonical_net_pct": _f(cm.get("net_pct")),
            "canonical_max_dd_pct": _f(cm.get("max_dd_pct")),
            "canonical_max_dd_pct_vs_stake": _f(cm.get("max_dd_pct_vs_stake")),
            "canonical_ret_dd": _f(cm.get("ret_dd")),
            "canonical_final_equity_usd": _f(cm.get("final_equity_usd")),
            "cycle_win_rate_pct": _f(cm.get("cycle_win_rate_pct")),
            "realized_net_pct": _f(cm.get("realized_net_pct")),
            "cycles_completed": (
                None if cm.get("cycles_completed") is None
                else int(cm["cycles_completed"])
            ),
        }
        set_clause = ", ".join(f'"{c}" = ?' for c in values)
        params = list(values.values()) + [METRICS_FN_VERSION, run_id]
        conn.execute(
            f'UPDATE cointegration_sheet SET {set_clause}, "metrics_fn_version" = ? '
            f"WHERE run_id = ?",
            params,
        )
        conn.commit()
        return values
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id", help="cointegration_sheet run_id to recompute")
    args = ap.parse_args(argv)
    try:
        vals = reenrich_cointegration_row(args.run_id)
    except ReenrichError as exc:
        print(f"[FATAL] {exc}")
        return 1
    print(f"[OK] reenriched {args.run_id}: {vals} (metrics_fn_version={METRICS_FN_VERSION})")
    print("  Note: run `python tools/ledger_db.py --export-mps` to refresh the tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
