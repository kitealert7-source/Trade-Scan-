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
from tools.window_compat import annotate_window_status, find_family_window
from tools.report.family_renderer import render


_BACKTESTS_DIR = TRADE_SCAN_STATE / "backtests"
_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "family_reports"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def generate_family_report(
    prefix: str,
    variants: list[str] | None = None,
    out_path: Path | None = None,
    window_tolerance_days: int = 5,
) -> Path:
    """Generate the family analysis report. Returns path written."""
    rows_df = _load_master_filter_rows(prefix, variants)
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
        variant_payloads.append(payload)

    # Verdicts via canonical authority
    verdicts = compute_family_verdicts(rows_df, trades_by_variant)
    for vp in variant_payloads:
        vp["verdict"] = verdicts.get(_canonical_strategy_name(vp), {})

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

def _load_master_filter_rows(prefix: str, variants: list[str] | None) -> pd.DataFrame | None:
    """Read Master Filter and filter rows by prefix + (optional) variant tags.

    Variant tags match the trailing `_S0n_Vm_Pkk` portion of the directive id.
    """
    from tools.ledger_db import read_master_filter
    mf = read_master_filter()
    if mf is None or len(mf) == 0:
        return None
    strat_col = mf["strategy"].astype(str)
    keep = strat_col.str.startswith(prefix + "_")
    rows = mf[keep].copy()
    if variants:
        # Match if any of the requested variant tags appears as a substring.
        # User can pass "P09" or "S01_V4_P09" — both work as substrings.
        variant_filters = [v.strip() for v in variants if v.strip()]
        def _match(row_name: str) -> bool:
            return any(v in row_name for v in variant_filters)
        rows = rows[rows["strategy"].astype(str).apply(_match)]
    return rows.reset_index(drop=True)


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
    args = p.parse_args(argv)

    variants = None
    if args.variants:
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    out = generate_family_report(
        prefix=args.prefix,
        variants=variants,
        out_path=args.out,
        window_tolerance_days=args.window_tolerance_days,
    )
    print(f"[FAMILY_REPORT] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
