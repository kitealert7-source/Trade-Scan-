"""Family Analysis Report CLI — orchestrates per-variant analytics and renders
a single markdown comparison document.

Usage:
    python tools/family_report.py <family_prefix> [options]

Examples:
    python tools/family_report.py 65_BRK_XAUUSD_5M_PSBRK
    python tools/family_report.py 65_BRK_XAUUSD_5M_PSBRK --variants P09,P14,P15
    python tools/family_report.py 65_BRK_XAUUSD_5M_PSBRK --out /tmp/family.md

Wrapper-first per FAMILY_REPORT_IMPLEMENTATION_PLAN.md Rule 4:
  - Reuses `tail_contribution`, `directional_removal`, `early_late_split`,
    `rolling_window`, `classify_stability`, `identify_dd_clusters` directly.
  - Uses duplicated inline helpers in `tools/utils/research/streaks.py` and
    `tools/utils/research/calendar.py` (no edits to `robustness/runner.py`).
  - Uses duplicated `_flatten`/`_diff` in `tools/report/strategy_signature_utils.py`
    (no edits to `generate_strategy_card.py`).

Forbidden imports (Rule 3 — these primitives are too heavy for the family
iteration cadence; they remain in the per-strategy robustness report):
  - tools.utils.research.simulators
  - tools.utils.research.block_bootstrap
  - tools.robustness.monte_carlo
  - tools.robustness.bootstrap
  - tools.robustness.friction
  - tools.utils.research.friction

Output: a single markdown file under
``outputs/family_reports/<prefix>_<YYYYMMDD>_<HHMMSS>.md``.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Path bootstrap so the module runs as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE
from config.state_paths import LEDGER_DB_PATH

# Allowed primitives (Rule 1)
from tools.utils.research.robustness import (
    tail_contribution,
    directional_removal,
    early_late_split,
)
from tools.utils.research.rolling import rolling_window, classify_stability
from tools.utils.research.drawdown import identify_dd_clusters

# Wrapper-first duplicates (Rule 4) — see family_streaks.py / family_calendar.py
# docstrings. Files live under tools/report/ because tools/utils/research/ is
# gitignored at the repo level (pre-existing rule, unrelated to Phase B).
from tools.report.family_streaks import compute_streaks
from tools.report.family_calendar import yearwise_pnl

# Only-new analytics (Rule 2)
from tools.report.family_session_xtab import (
    direction_session_matrix,
    direction_trend_matrix,
    direction_volatility_matrix,
    best_worst_cells,
    session_share,
)
from tools.report.family_verdicts import compute_family_verdicts
from tools.report.strategy_signature_utils import (
    flatten_signature, diff_signatures, parse_strategy_name,
)
from tools.report.prior_run_delta import compute_prior_run_delta
# Wrapper-first (Rule 4): reuse the Phase A loss-streak + stall-decay flag
# helpers verbatim — duplicating their logic into family_report would drift.
# These two complement the tail/body/flat trips that family_verdicts already
# computes; together they form the Block B soft-overlay set for the
# Promotion Summary section.
from tools.report.report_sections.verdict_risk import (
    _loss_streak_flag,
    _stall_decay_flag,
)
from tools.window_compat import annotate_window_status, find_family_window
from tools.report.family_renderer import render


_BACKTESTS_DIR = TRADE_SCAN_STATE / "backtests"
# Family reports are generated artifacts (rebuildable per invocation) and
# belong on the State side of the Trade_Scan/TradeScan_State boundary.
# See outputs/REPORT_OWNERSHIP_AUDIT.md (2026-05-11).
_OUTPUT_DIR = TRADE_SCAN_STATE / "reports" / "families"
# Consulted by the missing-MF-rows diagnostic (Patch D3) so the error can
# point at the canonical successor family when the prefix has been
# superseded by a rename (e.g. 53_MR_EURUSD_* -> 53_MR_FX_*).
_SUPERSESSION_MAP_PATH = PROJECT_ROOT / "governance" / "supersession_map.yaml"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def generate_family_report(
    prefix: str,
    variants: list[str] | None = None,
    out_path: Path | None = None,
    window_tolerance_days: int = 5,
    latest_only: bool = False,
) -> Path:
    """Generate the family analysis report. Returns path written.

    When ``latest_only`` is True, the per-strategy MF row with the highest
    SQLite rowid (== insertion order proxy for "most recent run") is kept.
    Rows flagged ``is_current = 0`` are dropped. If a strategy still has
    multiple current rows after the explicit-supersession filter, an
    ambiguity warning is surfaced in the rendered report — this is a
    pre-existing supersession-bookkeeping gap, not a ``--latest-only`` bug.
    """
    rows_df, dedup_info = _load_master_filter_rows(
        prefix, variants, latest_only=latest_only,
    )
    if rows_df is None or len(rows_df) == 0:
        raise SystemExit(
            f"No Master Filter rows match prefix {prefix!r} "
            f"(filters: variants={variants}). Run the pipeline for those "
            f"variants first or correct the prefix."
        )

    # Annotate cross-window status per row
    annotated = annotate_window_status(rows_df.to_dict("records"), tolerance_days=window_tolerance_days)
    family_start, family_end = find_family_window(rows_df)

    # Build per-variant payload
    variant_payloads: list[dict[str, Any]] = []
    trades_by_variant: dict[str, pd.DataFrame] = {}
    for row in annotated:
        directive_id = _strip_symbol_suffix(str(row.get("strategy", "")))
        symbol = str(row.get("symbol", ""))
        trades = _load_trade_log(directive_id, symbol)
        if trades is not None and len(trades) > 0:
            trades_by_variant[str(row.get("strategy"))] = trades
        payload = _build_variant_payload(directive_id, symbol, row, trades)
        # Same-strategy prior-run Δ. Window mismatch is informative here
        # (unlike parent-Δ which suppresses) — see prior_run_delta module
        # docstring for the comparison-policy rationale.
        current_rowid = row.get("_rowid")
        payload["prior_run_delta"] = compute_prior_run_delta(
            db_path=LEDGER_DB_PATH,
            strategy=str(row.get("strategy", "")),
            current_rowid=int(current_rowid) if current_rowid is not None else None,
            current_row=row,
            tolerance_days=window_tolerance_days,
        )
        variant_payloads.append(payload)

    # Verdicts via canonical authority
    verdicts = compute_family_verdicts(rows_df, trades_by_variant)
    for vp in variant_payloads:
        vp["verdict"] = verdicts.get(_canonical_strategy_name(vp), {})

    # Promotion Summary Block B — extra soft overlays beyond the tail/body/
    # flat trips already computed by `compute_family_verdicts`. These are
    # purely informational (per the 2026-05-12 spec: "Do not change status
    # labels. Only annotate.") so we keep them on a separate payload key
    # and the renderer reads both.
    for vp in variant_payloads:
        key = _canonical_strategy_name(vp)
        tdf = trades_by_variant.get(key)
        extra: list[str] = []
        if tdf is not None and len(tdf) > 0:
            extra.extend(_loss_streak_flag(tdf))
            extra.extend(_stall_decay_flag(tdf))
        vp["additional_soft_flags"] = extra

    # Lineage (parent inference + signature diffs)
    parents = _infer_lineage_parents(variant_payloads)
    diffs = _compute_lineage_diffs(variant_payloads, parents)

    # Window warnings (anything not in-window)
    warnings_list = [
        f"{_short_name(p['directive_id'])}: {p.get('reason', 'window mismatch')}"
        for p in variant_payloads if not p.get("in_window", True)
    ]

    family_data: dict[str, Any] = {
        "prefix": prefix,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {
            "start": str(family_start.date()) if family_start is not None else "?",
            "end": str(family_end.date()) if family_end is not None else "?",
        },
        "window_warnings": warnings_list,
        "variants": variant_payloads,
        "lineage_parents": parents,
        "lineage_diffs": diffs,
        "dedup": dedup_info,
    }

    md = render(family_data)

    if out_path is None:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = _OUTPUT_DIR / f"{prefix}_{ts}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _count_backtest_folders(prefix: str) -> int:
    """Count `TradeScan_State/backtests/<prefix>_*<SYMBOL>/` directories.

    Used by the missing-MF-rows diagnostic to distinguish "artifacts
    exist but ledger doesn't have them" from "nothing exists at all".
    """
    if not _BACKTESTS_DIR.exists():
        return 0
    needle = prefix + "_"
    return sum(
        1 for p in _BACKTESTS_DIR.iterdir()
        if p.is_dir() and p.name.startswith(needle)
    )


def _supersession_successors(prefix: str) -> list[str]:
    """Return sorted successor family prefixes for any directive id whose
    full id starts with ``prefix + '_'`` in
    ``governance/supersession_map.yaml``. Empty list when the map is
    missing/empty or no keys match.

    Used by the missing-MF-rows diagnostic to point the operator at the
    canonical successor when the prefix has been renamed (e.g.
    ``53_MR_EURUSD_*`` -> ``53_MR_FX_*``).
    """
    if not _SUPERSESSION_MAP_PATH.exists():
        return []
    try:
        import yaml
        data = yaml.safe_load(
            _SUPERSESSION_MAP_PATH.read_text(encoding="utf-8")
        ) or {}
    except Exception:
        return []
    entries = data.get("supersessions") or {}
    if not isinstance(entries, dict):
        return []

    successors: set[str] = set()
    needle = prefix + "_"
    for old_id, entry in entries.items():
        if not isinstance(old_id, str) or not old_id.startswith(needle):
            continue
        if not isinstance(entry, dict):
            continue
        new_id = entry.get("superseded_by")
        if not isinstance(new_id, str) or not new_id:
            continue
        # Strip trailing _S<n>_V<n>_P<n> to recover the family prefix.
        m = re.match(r"^(.+?)_S\d+_V\d+_P\d+$", new_id)
        successors.add(m.group(1) if m else new_id)
    return sorted(successors)


def _raise_mf_missing(prefix: str, variants: list[str] | None) -> None:
    """Build the enriched FAMILY_REPORT_MF_MISSING diagnostic and raise
    ``SystemExit``. Fail-closed.

    Single-line parseable header at the top for greppable automation
    (session-close audits, batch runs):

        FAMILY_REPORT_MF_MISSING: prefix=<P> backtests=<N> superseded_by=<S|none>

    Human-readable body below explains disk evidence + likely causes.
    Never returns.
    """
    n_backtests = _count_backtest_folders(prefix)
    successors = _supersession_successors(prefix)
    successor_tok = ",".join(successors) if successors else "none"

    header = (
        f"FAMILY_REPORT_MF_MISSING: "
        f"prefix={prefix} backtests={n_backtests} "
        f"superseded_by={successor_tok}"
    )

    lines: list[str] = [header, ""]
    variants_clause = (
        f" (filter variants={variants})." if variants else "."
    )
    lines.append(
        f"No usable Master Filter rows for prefix {prefix!r}{variants_clause}"
    )
    lines.append("")
    lines.append("Disk evidence:")
    if n_backtests > 0:
        lines.append(
            f"  - {n_backtests} backtest folder(s) found at "
            f"TradeScan_State/backtests/{prefix}_*"
        )
        lines.append(
            "  - 0 usable MF rows for this family "
            "(ledger row either absent or marked is_current=0)"
        )
    else:
        lines.append(
            f"  - 0 backtest folders under "
            f"TradeScan_State/backtests/{prefix}_*"
        )
        lines.append("  - 0 usable MF rows for this family prefix")
    lines.append("")
    lines.append("Likely causes:")
    if successors:
        suffix = (
            f" (and {len(successors) - 1} more)"
            if len(successors) > 1 else ""
        )
        lines.append(
            f"  - Family superseded / renamed -> see successor "
            f"`{successors[0]}`{suffix} in "
            f"governance/supersession_map.yaml"
        )
    if n_backtests > 0:
        lines.append("  - Stage-3 aggregation never ran for these backtests")
        lines.append("  - Runs FAILED before ledger write")
        if not successors:
            lines.append(
                "  - Family superseded / renamed "
                "(no entry in supersession_map.yaml)"
            )
    elif not successors:
        lines.append(
            "  - Prefix typo (no artifacts or ledger rows match this prefix)"
        )
        lines.append("  - Pipeline never ran for this family")
    raise SystemExit("\n".join(lines))


def _load_master_filter_rows(
    prefix: str,
    variants: list[str] | None,
    latest_only: bool = False,
) -> tuple[pd.DataFrame, dict | None]:
    """Read Master Filter and filter rows by prefix + (optional) variant tags.

    Variant tags match the trailing `_S0n_Vm_Pkk` portion of the directive id.

    Always includes a `_rowid` column in the returned DataFrame — needed by
    the prior-run-delta section to look up the immediately preceding run of
    the same strategy. The MF schema has no ingestion timestamp, so rowid
    (monotonic on INSERT) is the only reliable run-recency signal.

    When ``latest_only`` is True, per-strategy dedup is applied: rows with
    ``is_current = 0`` are dropped, and within each remaining (strategy)
    group the row with the highest rowid is kept. Returns a ``dedup_info``
    dict alongside the rows when ``latest_only`` is engaged, ``None``
    otherwise.

    Group key is the MF ``strategy`` column (= ``clean_id + _<SYMBOL>``).
    This collapses re-runs of the same clean_id within a single asset, and
    preserves per-symbol resolution for multi-asset families.

    Raises ``SystemExit`` via ``_raise_mf_missing`` when no MF rows
    match the prefix (with disk evidence, supersession hint, and likely
    causes; single-line parseable header for automation). Patch D3,
    2026-05-12.
    """
    # Direct SQL for both paths so we always have rowid available. Bypassing
    # `read_master_filter()` is safe — it just does `SELECT * FROM
    # master_filter ORDER BY run_id` with no normalization (verified via
    # tools/ledger_db.py:query_master_filter).
    conn = sqlite3.connect(str(LEDGER_DB_PATH))
    try:
        rows = pd.read_sql_query(
            "SELECT rowid AS _rowid, * FROM master_filter "
            "WHERE strategy LIKE ?",
            conn,
            params=(prefix + "_%",),
        )
    finally:
        conn.close()

    if rows is None or len(rows) == 0:
        _raise_mf_missing(prefix, variants)

    if variants:
        # Match if any of the requested variant tags appears as a substring.
        # User can pass "P09" or "S01_V4_P09" — both work as substrings.
        variant_filters = [v.strip() for v in variants if v.strip()]
        def _match(row_name: str) -> bool:
            return any(v in row_name for v in variant_filters)
        rows = rows[rows["strategy"].astype(str).apply(_match)]

    if not latest_only:
        return rows.reset_index(drop=True), None

    # --- Latest-only path: drop superseded, then collapse on max(rowid). --
    input_rows = len(rows)

    if "is_current" in rows.columns:
        # NULL is treated as 1 per the 2026-04-16 supersession backfill
        # convention (see tools/ledger_db.py ~ line 226).
        current_mask = rows["is_current"].isna() | (rows["is_current"] == 1)
        rows = rows[current_mask].copy()

    # Post-filter empty: rows existed for the prefix but ALL were
    # explicitly superseded (is_current=0). Same operator-visible class
    # as the pre-filter empty case (no usable rows for the family) —
    # surface the same parseable diagnostic so stress-test grep
    # automation catches both cases uniformly. The supersession-map hint
    # is especially likely to be relevant here (every row was marked
    # superseded; the successor family is probably what the operator
    # actually wants). Patch D3, 2026-05-12.
    if len(rows) == 0:
        _raise_mf_missing(prefix, variants)

    # Ambiguity detection BEFORE the drop_duplicates collapse — these are
    # strategies with >1 current row, a pre-existing supersession gap that
    # --latest-only papers over by picking max(rowid) but surfaces in the
    # report so the operator can decide whether to formally supersede.
    if len(rows) > 0:
        current_counts = rows.groupby("strategy").size()
        ambiguous = current_counts[current_counts > 1]
    else:
        ambiguous = pd.Series(dtype=int)

    rows = rows.sort_values("_rowid", ascending=False).drop_duplicates(
        subset=["strategy"], keep="first",
    )
    # Keep _rowid for downstream prior-run-delta lookup.
    rows = rows.reset_index(drop=True)

    dedup_info = {
        "enabled": True,
        "input_rows": int(input_rows),
        "kept_rows": int(len(rows)),
        "ambiguities": [
            {"strategy": str(s), "n_current": int(n)}
            for s, n in ambiguous.items()
        ],
    }
    return rows, dedup_info


def _load_trade_log(directive_id: str, symbol: str) -> pd.DataFrame | None:
    """Load `results_tradelevel.csv` for the variant. Returns None if missing."""
    path = _BACKTESTS_DIR / f"{directive_id}_{symbol}" / "raw" / "results_tradelevel.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        for col in ("entry_timestamp", "exit_timestamp"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df
    except Exception:
        return None


def _load_equity_curve(directive_id: str, symbol: str) -> pd.DataFrame | None:
    """Load `equity_curve.csv` for the variant. Returns None if missing."""
    path = _BACKTESTS_DIR / f"{directive_id}_{symbol}" / "raw" / "equity_curve.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        return df
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-variant analytics
# ---------------------------------------------------------------------------

def _build_variant_payload(
    directive_id: str,
    symbol: str,
    annotated_row: dict,
    trades: pd.DataFrame | None,
) -> dict[str, Any]:
    """Compute every per-variant analytic the renderer expects."""
    payload: dict[str, Any] = {
        "directive_id": directive_id,
        "symbol": symbol,
        "row": annotated_row,
        "in_window": annotated_row.get("in_window", True),
        "reason": annotated_row.get("reason", ""),
    }

    if trades is None or len(trades) == 0:
        payload["missing_data"] = True
        return payload

    # Cheap primitives (Rule 3 — all O(N) over trade log)
    payload["tail_contribution"] = tail_contribution(trades)
    payload["body_after_top_20"] = _body_after_top_20(trades)
    payload["directional"] = directional_removal(trades)
    payload["streaks"] = compute_streaks(trades["pnl_usd"].values)
    payload["yearwise"] = yearwise_pnl(trades)
    payload["session_share"] = session_share(trades)
    payload["direction_share"] = _direction_share_positive(trades)
    payload["regime_cells"] = {
        "session":    best_worst_cells(direction_session_matrix(trades), "session"),
        "trend":      best_worst_cells(direction_trend_matrix(trades), "trend_label"),
        "volatility": best_worst_cells(direction_volatility_matrix(trades), "volatility_regime"),
    }
    # Early/late split — needs start_cap; pull from MF if available
    try:
        sc = float(annotated_row.get("starting_capital") or 10000.0)
    except Exception:
        sc = 10000.0
    payload["early_late"] = early_late_split(trades, start_cap=sc)

    # Rolling stability — needs equity curve
    eq = _load_equity_curve(directive_id, symbol)
    if eq is not None and len(eq) > 0:
        try:
            win_df = rolling_window(eq, trades, window_days=365, step_days=30)
            payload["rolling_stability"] = classify_stability(win_df)
        except Exception:
            payload["rolling_stability"] = {}
        try:
            payload["dd_clusters"] = identify_dd_clusters(eq, top_n=1)
        except Exception:
            payload["dd_clusters"] = []
    else:
        payload["rolling_stability"] = {}
        payload["dd_clusters"] = []

    return payload


def _body_after_top_20(trades: pd.DataFrame) -> float:
    sorted_pnl = trades["pnl_usd"].astype(float).sort_values(ascending=False)
    if len(sorted_pnl) < 20:
        return float(sorted_pnl.sum())
    return float(sorted_pnl.iloc[20:].sum())


def _direction_share_positive(trades: pd.DataFrame) -> dict[str, float]:
    if "direction" not in trades.columns or "pnl_usd" not in trades.columns:
        return {"long": 0.0, "short": 0.0}
    pos = trades[trades["pnl_usd"].astype(float) > 0]
    total = float(pos["pnl_usd"].sum())
    if total <= 0:
        return {"long": 0.0, "short": 0.0}
    return {
        "long":  float(pos.loc[pos["direction"] == 1, "pnl_usd"].sum()) / total * 100.0,
        "short": float(pos.loc[pos["direction"] == -1, "pnl_usd"].sum()) / total * 100.0,
    }


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------

def _infer_lineage_parents(variants: list[dict]) -> dict[str, str]:
    """Naive parent inference: P(N) → P(N-1) ... → P00 within same prefix/sweep.

    Looks for the parent within the current family set first. Falls back to
    None when no in-family parent exists (e.g., first pass of a new sweep).
    """
    by_id = {v["directive_id"]: v for v in variants}
    parents: dict[str, str] = {}
    for vid in by_id:
        parsed = parse_strategy_name(vid)
        if not parsed:
            continue
        prefix, sweep, version, pass_n = parsed
        if pass_n == 0:
            continue
        for pn in range(pass_n - 1, -1, -1):
            candidate = f"{prefix}_S{sweep:02d}_V{version}_P{pn:02d}"
            if candidate in by_id:
                parents[vid] = candidate
                break
    return parents


def _compute_lineage_diffs(
    variants: list[dict],
    parents: dict[str, str],
) -> dict[str, list[tuple[str, str, str]]]:
    """For each variant with a parent, compute signature-diff against parent."""
    by_id = {v["directive_id"]: v for v in variants}
    diffs: dict[str, list[tuple[str, str, str]]] = {}
    for vid, parent_id in parents.items():
        cur_path  = _strategy_py_path(vid)
        prev_path = _strategy_py_path(parent_id)
        if cur_path is None or prev_path is None:
            continue
        cur_sig  = flatten_signature(cur_path)
        prev_sig = flatten_signature(prev_path)
        d = diff_signatures(prev_sig, cur_sig)
        if d:
            diffs[vid] = d
    return diffs


def _strategy_py_path(directive_id: str) -> Path | None:
    """Locate the strategy.py for a directive — prefer the run-snapshot."""
    # Primary: Trade_Scan/strategies/<id>/strategy.py (current authority)
    p = PROJECT_ROOT / "strategies" / directive_id / "strategy.py"
    if p.exists():
        return p
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_symbol_suffix(strategy_col_value: str) -> str:
    """Master Filter `strategy` column carries `_<SYMBOL>` suffix; strip it
    to recover the bare directive id used elsewhere.
    """
    m = re.match(r"^(.+?)(?:_[A-Z]{3,8})$", strategy_col_value)
    return m.group(1) if m else strategy_col_value


def _canonical_strategy_name(payload: dict) -> str:
    """The key used by `compute_family_verdicts` — that's the MF `strategy` column."""
    return str((payload.get("row") or {}).get("strategy", payload["directive_id"]))


def _short_name(name: str) -> str:
    parts = name.split("_")
    if len(parts) >= 8:
        return "_".join(parts[5:])
    return name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Family Analysis Report — on-demand markdown across N variants.",
    )
    p.add_argument("prefix",
                   help="Family prefix, e.g. 65_BRK_XAUUSD_5M_PSBRK")
    p.add_argument("--variants",
                   help="Comma-separated variant tags to include (e.g. P09,P14,S03)")
    p.add_argument("--out", type=Path,
                   help="Override output path (default: outputs/family_reports/<prefix>_<ts>.md)")
    p.add_argument("--window-tolerance-days", type=int, default=5,
                   help="Cross-window comparability tolerance in days (default: 5)")
    p.add_argument("--latest-only", action="store_true",
                   help="Per strategy, keep only the most recently inserted MF "
                        "row (max rowid) and drop superseded (is_current=0) "
                        "rows. Ambiguities — strategies with >1 current row "
                        "after the supersession filter — are surfaced in the "
                        "rendered report rather than silently collapsed.")
    args = p.parse_args(argv)

    variants = None
    if args.variants:
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    out = generate_family_report(
        prefix=args.prefix,
        variants=variants,
        out_path=args.out,
        window_tolerance_days=args.window_tolerance_days,
        latest_only=args.latest_only,
    )
    print(f"[FAMILY_REPORT] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
