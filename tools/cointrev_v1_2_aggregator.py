"""cointrev_v1_2_aggregator.py — roll up COINTREV v1.2 pilot results.

Strategy spec: outputs/cointegration_screener_v1/v1_2_strategy_design/DESIGN_DOC.md §6

Reads MPS Baskets sheet, filters to cointegration_meanrev_v1_2 real-mode runs,
emits per-pair + aggregate metrics. Designed for the v1.2 pilot (15 directives)
but reusable for the full 263-directive cohort once approved.

Usage:
    python tools/cointrev_v1_2_aggregator.py
    python tools/cointrev_v1_2_aggregator.py --lookback 252
    python tools/cointrev_v1_2_aggregator.py --output-csv /tmp/cointrev_pilot.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config.path_authority import TRADE_SCAN_STATE  # noqa: E402


def _load_baskets_sheet() -> pd.DataFrame:
    mps_path = TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"
    if not mps_path.is_file():
        raise FileNotFoundError(f"MPS not found at {mps_path}")
    return pd.read_excel(mps_path, sheet_name="Baskets")


def _filter_cointrev_real(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    pattern = f"COINTREV_V2_L{lookback}"
    mask = df["directive_id"].str.contains(pattern, na=False)
    sub = df[mask].copy()
    sub = sub[sub["trades_total"] > 0].copy()
    return sub.sort_values("trades_total", ascending=False).reset_index(drop=True)


def _pair_from_directive(directive_id: str) -> tuple[str, str]:
    """Parse (pair_a, pair_b) from '90_PORT_<A><B>_15M_COINTREV_V2_L252'.
    Symbols are 6-char FX pairs in alphabetical order (canonical convention).
    """
    parts = directive_id.split("_")
    syms = parts[2]
    # All FX pairs are 6 chars; basket_id is concatenation.
    a, b = syms[:6], syms[6:]
    return a, b


def _bucket_verdict(net_pct: float, max_dd_pct: float) -> str:
    if pd.isna(net_pct):
        return "MISSING_METRICS"
    if max_dd_pct > 30:
        return "BLOWUP"
    if net_pct > 1.0:
        return "WINNER"
    if net_pct < -1.0:
        return "LOSER"
    return "NEUTRAL"


def summarize(sub: pd.DataFrame) -> dict:
    """Compute aggregate stats. Skips rows with NaN canonical_net_pct."""
    n_total = len(sub)
    n_metrics = sub["canonical_net_pct"].notna().sum()
    valid = sub[sub["canonical_net_pct"].notna()].copy()
    valid["verdict_bucket"] = valid.apply(
        lambda r: _bucket_verdict(r["canonical_net_pct"], r["canonical_max_dd_pct"]),
        axis=1,
    )
    bucket_counts = valid["verdict_bucket"].value_counts().to_dict()
    return {
        "n_directives_total":   n_total,
        "n_directives_metrics": int(n_metrics),
        "n_directives_no_metrics": n_total - int(n_metrics),
        "buckets":               bucket_counts,
        "trades_total":          int(sub["trades_total"].sum()),
        "cycles_total":          int(sub["cycles_completed"].fillna(0).sum()),
        "net_pct_mean":          float(valid["canonical_net_pct"].mean()),
        "net_pct_median":        float(valid["canonical_net_pct"].median()),
        "net_pct_min":           float(valid["canonical_net_pct"].min()),
        "net_pct_max":           float(valid["canonical_net_pct"].max()),
        "max_dd_pct_mean":       float(valid["canonical_max_dd_pct"].mean()),
        "max_dd_pct_max":        float(valid["canonical_max_dd_pct"].max()),
        "ret_dd_mean":           float(valid["canonical_ret_dd"].mean()),
        "ret_dd_median":         float(valid["canonical_ret_dd"].median()),
        "cycle_wr_mean":         float(valid["cycle_win_rate_pct"].mean()),
        "cycle_wr_median":       float(valid["cycle_win_rate_pct"].median()),
        "final_realized_sum":    float(sub["final_realized_usd"].fillna(0).sum()),
    }


def format_report(sub: pd.DataFrame, stats: dict, lookback: int) -> str:
    """Markdown-ready report body."""
    lines = []
    lines.append(f"## Aggregate (n = {stats['n_directives_total']} real-mode directives @ lookback={lookback})")
    lines.append("")
    lines.append(f"- **Trades total:** {stats['trades_total']}")
    lines.append(f"- **Cycles total:** {stats['cycles_total']}")
    lines.append(f"- **Net % mean:** {stats['net_pct_mean']:.2f}  /  **median:** {stats['net_pct_median']:.2f}")
    lines.append(f"- **Net % range:** [{stats['net_pct_min']:.2f}, {stats['net_pct_max']:.2f}]")
    lines.append(f"- **Max DD % mean:** {stats['max_dd_pct_mean']:.2f}  /  **worst:** {stats['max_dd_pct_max']:.2f}")
    lines.append(f"- **Ret/DD mean:** {stats['ret_dd_mean']:.2f}  /  **median:** {stats['ret_dd_median']:.2f}")
    lines.append(f"- **Cycle WR % mean:** {stats['cycle_wr_mean']:.1f}  /  **median:** {stats['cycle_wr_median']:.1f}")
    lines.append(f"- **Realized PnL sum:** ${stats['final_realized_sum']:.2f}")
    if stats["n_directives_no_metrics"] > 0:
        lines.append(f"- *Note: {stats['n_directives_no_metrics']} run(s) missing canonical metrics — likely pre-dating the per-bar emit fix*")
    lines.append("")
    lines.append("### Verdict bucket distribution")
    lines.append("")
    for bucket in ("WINNER", "NEUTRAL", "LOSER", "BLOWUP", "MISSING_METRICS"):
        n = stats["buckets"].get(bucket, 0)
        if n:
            lines.append(f"- **{bucket}:** {n}")
    lines.append("")
    lines.append("### Per-directive detail (sorted by trades_total desc)")
    lines.append("")
    lines.append("| Directive | Pair | Trades | Cycles | Net % | MaxDD % | Ret/DD | Cycle WR % | Realized $ |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, row in sub.iterrows():
        a, b = _pair_from_directive(row["directive_id"])
        net = row["canonical_net_pct"]
        dd = row["canonical_max_dd_pct"]
        rd = row["canonical_ret_dd"]
        wr = row["cycle_win_rate_pct"]
        rl = row["final_realized_usd"]
        net_s = f"{net:.2f}" if pd.notna(net) else "n/a"
        dd_s = f"{dd:.2f}" if pd.notna(dd) else "n/a"
        rd_s = f"{rd:.2f}" if pd.notna(rd) else "n/a"
        wr_s = f"{wr:.1f}" if pd.notna(wr) else "n/a"
        rl_s = f"{rl:.2f}" if pd.notna(rl) else "n/a"
        cyc = int(row["cycles_completed"]) if pd.notna(row["cycles_completed"]) else "n/a"
        short = row["directive_id"].replace("90_PORT_", "").replace(f"_15M_COINTREV_V2_L{lookback}", "")
        lines.append(
            f"| {short} | {a}/{b} | {int(row['trades_total'])} | "
            f"{cyc} | {net_s} | {dd_s} | {rd_s} | {wr_s} | {rl_s} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--lookback", type=int, default=252)
    parser.add_argument("--output-csv", type=Path, default=None,
                        help="Optional: write per-directive table as CSV")
    parser.add_argument("--print-report", action="store_true", default=True)
    args = parser.parse_args(argv)

    df = _load_baskets_sheet()
    sub = _filter_cointrev_real(df, args.lookback)
    if sub.empty:
        print(f"[aggregator] No COINTREV_V2_L{args.lookback} real-mode runs found.",
              file=sys.stderr)
        return 1
    stats = summarize(sub)
    report = format_report(sub, stats, args.lookback)
    if args.print_report:
        print(report)
    if args.output_csv is not None:
        cols = ["directive_id", "trades_total", "cycles_completed",
                "canonical_net_pct", "canonical_max_dd_pct", "canonical_ret_dd",
                "cycle_win_rate_pct", "final_realized_usd", "run_id"]
        sub[[c for c in cols if c in sub.columns]].to_csv(args.output_csv, index=False)
        print(f"\n[aggregator] CSV written: {args.output_csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
