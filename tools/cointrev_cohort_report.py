"""cointrev_cohort_report.py — C5 aggregation + calendar-overlap analysis.

Reads the completed COINTREV directives from /execute-directives and produces:

  1. COHORT_REPORT.md   — directive-level metrics rolled up to the universe
                            (total PnL, per-pair breakdown, distribution of
                            win-rates, exit-reason counts, etc.)

  2. CONCURRENCY_REPORT.md — calendar-overlap analysis (operator-added
                              C5 requirement 2026-05-20):
                                * histogram of concurrent-open count per bar
                                * peak concurrent count + when it occurred
                                * peak-concurrency cluster composition
                                * daily concurrency time-series
                                * cohort time-in-position summary

  Plus supporting CSVs (cohort_metrics.csv, concurrency_per_bar.csv).

Outputs land under:
  outputs/cointegration_screener_v1/backtest_v1/

CLI:
  python tools/cointrev_cohort_report.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from config.path_authority import TRADE_SCAN_STATE


BACKTESTS_DIR = TRADE_SCAN_STATE / "backtests"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "cointegration_screener_v1" / "backtest_v1"


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}", flush=True)


# ---------------------------------------------------------------------------
# Discovery: find all COINTREV backtest directories
# ---------------------------------------------------------------------------


def find_cointrev_runs() -> list[dict]:
    """Locate every 91_PORT_*_COINTREV_* backtest directory + extract IDs."""
    runs = []
    for d in sorted(BACKTESTS_DIR.glob("91_PORT_*_15M_COINTREV_*")):
        if not d.is_dir():
            continue
        # Directive ID = directory name minus trailing _<basket_id>
        dirname = d.name
        # e.g. 91_PORT_EURGBPGBPUSD_15M_COINTREV_S23_V1_P00_EURGBPGBPUSD
        # split off the last _<basket_id> token
        parts = dirname.rsplit("_", 1)
        directive_id = parts[0]
        basket_id = parts[1] if len(parts) > 1 else ""
        # Parse pair + direction from name
        # 91_PORT_<symbol>_15M_COINTREV_S<NN>_V1_P00
        tokens = directive_id.split("_")
        symbol = tokens[2]
        sweep = tokens[5]   # S23 / S24 / etc.
        # SWEEP odd = short-spread, even = long-spread (per generator convention)
        sweep_n = int(sweep[1:])
        direction = "short" if sweep_n % 2 == 1 else "long"
        # Recover the two pair legs from the symbol (split at 6 chars)
        pair_a = symbol[:6]
        pair_b = symbol[6:]
        runs.append({
            "directive_id":    directive_id,
            "basket_id":       basket_id,
            "sweep":           sweep,
            "pair_a":          pair_a,
            "pair_b":          pair_b,
            "direction":       direction,
            "backtest_dir":    d,
            "basket_csv":      d / "raw" / "results_basket.csv",
            "tradelevel_csv":  d / "raw" / "results_tradelevel.csv",
            "per_bar_parquet": d / "raw" / "results_basket_per_bar.parquet",
        })
    return runs


# ---------------------------------------------------------------------------
# Per-directive metric load
# ---------------------------------------------------------------------------


def load_directive_metrics(runs: list[dict]) -> pd.DataFrame:
    """Pull top-line metrics (Net PnL, DD, etc.) from each run's basket csv +
    per-bar parquet."""
    rows = []
    for r in runs:
        row = {
            "directive_id": r["directive_id"],
            "pair_a":       r["pair_a"],
            "pair_b":       r["pair_b"],
            "direction":    r["direction"],
            "sweep":        r["sweep"],
        }
        # Basket-level metrics (from results_basket.csv)
        if r["basket_csv"].exists():
            try:
                bdf = pd.read_csv(r["basket_csv"])
                # The CSV is typically single-row; pull as series
                if len(bdf) >= 1:
                    bser = bdf.iloc[0]
                    row["recycle_event_count"] = int(bser.get("recycle_event_count", 0))
                    row["final_realized_usd"]  = float(bser.get("final_realized_usd", 0.0))
                    row["days_to_exit"]        = int(bser.get("days_to_exit", 0))
            except Exception as exc:
                row["basket_load_error"] = f"{type(exc).__name__}: {exc}"

        # Per-bar parquet — equity stats, time-in-position
        if r["per_bar_parquet"].exists():
            try:
                pdf = pd.read_parquet(r["per_bar_parquet"])
                if len(pdf) > 0:
                    row["bars_total"]      = int(len(pdf))
                    row["bars_in_pos"]     = int((pdf["active_legs"] > 0).sum())
                    row["time_in_pos_pct"] = 100.0 * row["bars_in_pos"] / row["bars_total"]
                    row["peak_equity_usd"] = float(pdf["peak_equity_usd"].max())
                    row["final_equity"]    = float(pdf["equity_total_usd"].iloc[-1])
                    row["max_dd_usd"]      = float(pdf["dd_from_peak_usd"].min())
                    row["max_dd_pct"]      = float(pdf["dd_from_peak_pct"].min())
                    row["net_pnl_usd"]     = row["final_equity"] - 1000.0
                    row["net_pct"]         = 100.0 * row["net_pnl_usd"] / 1000.0
            except Exception as exc:
                row["per_bar_load_error"] = f"{type(exc).__name__}: {exc}"

        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Concurrency analysis (the operator-added C5 requirement)
# ---------------------------------------------------------------------------


def build_concurrency_matrix(runs: list[dict]) -> pd.DataFrame:
    """Build a (timestamp × directive) boolean matrix of in-position state.

    Returns DataFrame indexed by timestamp; one column per directive_id with
    True/False. Forward-filled to NaT where the directive had no bar emitted.
    """
    per_run_open: dict[str, pd.Series] = {}
    union_index: set[pd.Timestamp] = set()
    for r in runs:
        pq = r["per_bar_parquet"]
        if not pq.exists():
            continue
        try:
            df = pd.read_parquet(pq)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            ser = (
                df.set_index("timestamp")["active_legs"]
                .gt(0)
                .rename(r["directive_id"])
            )
            per_run_open[r["directive_id"]] = ser
            union_index.update(ser.index)
        except Exception as exc:
            _log(f"WARN: concurrency load failed for {r['directive_id']}: {exc}")
    if not per_run_open:
        return pd.DataFrame()
    idx = pd.DatetimeIndex(sorted(union_index))
    matrix = pd.DataFrame(index=idx)
    for did, ser in per_run_open.items():
        matrix[did] = ser.reindex(idx, fill_value=False)
    return matrix.astype(bool)


def concurrency_stats(matrix: pd.DataFrame) -> dict:
    """Compute concurrency statistics from the boolean matrix."""
    if matrix.empty:
        return {"empty": True}
    counts_per_bar = matrix.sum(axis=1)
    peak_count = int(counts_per_bar.max())
    # Peak day(s) — bars where concurrency hit the max
    peak_bars = counts_per_bar[counts_per_bar == peak_count]
    peak_first_ts = peak_bars.index[0] if len(peak_bars) else None
    # Cluster composition at peak (which directives were open)
    peak_cluster = []
    if peak_first_ts is not None:
        for col in matrix.columns:
            if bool(matrix.loc[peak_first_ts, col]):
                peak_cluster.append(col)
    # Histogram: bars per concurrency level
    hist = counts_per_bar.value_counts().sort_index().to_dict()
    # Daily concurrency (max per day)
    daily_max = counts_per_bar.resample("1D").max()
    daily_mean = counts_per_bar.resample("1D").mean()
    # Time-in-position cohort-wide (any-of-N open)
    bars_with_any_open = int((counts_per_bar > 0).sum())
    cohort_time_in_pos_pct = 100.0 * bars_with_any_open / len(counts_per_bar)
    return {
        "peak_concurrency":            peak_count,
        "peak_first_ts":               peak_first_ts,
        "peak_cluster_directives":     peak_cluster,
        "peak_bars_count":             int(len(peak_bars)),
        "histogram":                   hist,
        "daily_max":                   daily_max,
        "daily_mean":                  daily_mean,
        "bars_with_any_open":          bars_with_any_open,
        "cohort_time_in_pos_pct":      cohort_time_in_pos_pct,
        "total_bars":                  int(len(counts_per_bar)),
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------


def write_cohort_report(metrics_df: pd.DataFrame, conc: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "COHORT_REPORT.md"

    n_dir = len(metrics_df)
    valid = metrics_df.dropna(subset=["net_pnl_usd"])
    n_valid = len(valid)
    n_short = (metrics_df["direction"] == "short").sum()
    n_long = (metrics_df["direction"] == "long").sum()

    total_pnl = float(valid["net_pnl_usd"].sum()) if n_valid else 0.0
    winners = valid[valid["net_pnl_usd"] > 0]
    losers = valid[valid["net_pnl_usd"] < 0]
    n_zero_trade = int((valid["bars_in_pos"] == 0).sum()) if n_valid else 0

    lines = []
    lines.append("# COINTREV Cohort Report — Path C C5 fan-out")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**Universe:** {n_dir} directives ({n_short} short-spread, {n_long} long-spread)")
    lines.append(f"**Window:** 2024-05-20 → 2026-05-20 (15m TF)")
    lines.append(f"**Per-directive stake:** $1,000 (independent backtests)")
    lines.append("")
    lines.append("## Cohort top-line")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Directives completed | {n_valid}/{n_dir} |")
    lines.append(f"| **Cumulative Net PnL (sum across cohort)** | **${total_pnl:,.2f}** |")
    lines.append(f"| Average Net PnL per directive | ${total_pnl/max(n_valid,1):,.2f} |")
    lines.append(f"| Winners (Net PnL > 0) | {len(winners)} ({100*len(winners)/max(n_valid,1):.1f}%) |")
    lines.append(f"| Losers (Net PnL < 0) | {len(losers)} ({100*len(losers)/max(n_valid,1):.1f}%) |")
    lines.append(f"| No-trade directives (0 bars in pos) | {n_zero_trade} ({100*n_zero_trade/max(n_valid,1):.1f}%) |")
    if len(winners):
        lines.append(f"| Mean winner | ${winners['net_pnl_usd'].mean():,.2f} |")
    if len(losers):
        lines.append(f"| Mean loser | ${losers['net_pnl_usd'].mean():,.2f} |")
    lines.append("")

    # Per-direction breakdown
    lines.append("## By direction")
    lines.append("")
    lines.append("| direction | n | net pnl | mean pnl | winners | losers |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for d in ("short", "long"):
        sub = valid[valid["direction"] == d]
        ws = (sub["net_pnl_usd"] > 0).sum()
        ls = (sub["net_pnl_usd"] < 0).sum()
        lines.append(
            f"| {d} | {len(sub)} | ${sub['net_pnl_usd'].sum():,.2f} | "
            f"${sub['net_pnl_usd'].mean() if len(sub) else 0:,.2f} | {ws} | {ls} |"
        )
    lines.append("")

    # Per-directive table (sorted by Net PnL desc)
    lines.append("## Per-directive (sorted by Net PnL descending)")
    lines.append("")
    lines.append("| directive | dir | pair | net pnl | net % | max dd % | events | bars in pos |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for _, r in valid.sort_values("net_pnl_usd", ascending=False).iterrows():
        lines.append(
            f"| {r['directive_id']} | {r['direction']} | {r['pair_a']}/{r['pair_b']} | "
            f"${r['net_pnl_usd']:,.2f} | {r.get('net_pct', 0):.1f}% | "
            f"{r.get('max_dd_pct', 0):.1f}% | {int(r.get('recycle_event_count', 0))} | "
            f"{int(r.get('bars_in_pos', 0))} |"
        )
    lines.append("")

    # Concurrency reference
    if not conc.get("empty"):
        lines.append("## Concurrency reference (see CONCURRENCY_REPORT.md for full detail)")
        lines.append("")
        lines.append(f"- Peak concurrent open directives: **{conc['peak_concurrency']}**")
        lines.append(f"- First hit at: {conc['peak_first_ts']}")
        lines.append(f"- Cohort time-in-position (any of {n_valid} open): **{conc['cohort_time_in_pos_pct']:.1f}%**")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_concurrency_report(matrix: pd.DataFrame, conc: dict,
                              metrics_df: pd.DataFrame) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "CONCURRENCY_REPORT.md"

    lines = []
    lines.append("# COINTREV Calendar-Overlap Analysis — C5 addition")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**Purpose:** Even without a true portfolio engine, this tells us whether")
    lines.append(f"opportunities are naturally diversified across pairs OR concentrated in the")
    lines.append(f"same macro windows. Critical for any future real-capital portfolio modeling.")
    lines.append("")

    if conc.get("empty"):
        lines.append("(no concurrency data — no completed runs found)")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    lines.append("## Cohort time-in-position summary")
    lines.append("")
    lines.append(f"- Total bars in window: **{conc['total_bars']:,}**")
    lines.append(f"- Bars with ≥1 directive open: **{conc['bars_with_any_open']:,}** ({conc['cohort_time_in_pos_pct']:.1f}%)")
    lines.append("")

    lines.append("## Peak concurrency")
    lines.append("")
    lines.append(f"- **Peak count: {conc['peak_concurrency']} directives open simultaneously**")
    lines.append(f"- First hit at: {conc['peak_first_ts']}")
    lines.append(f"- Bars at peak level: {conc['peak_bars_count']:,}")
    lines.append("")
    lines.append("### Cluster composition at first peak")
    lines.append("")
    lines.append("| directive_id | direction | pair |")
    lines.append("|---|---|---|")
    for did in conc["peak_cluster_directives"]:
        r = metrics_df[metrics_df["directive_id"] == did]
        if len(r):
            row = r.iloc[0]
            lines.append(f"| {did} | {row['direction']} | {row['pair_a']}/{row['pair_b']} |")
        else:
            lines.append(f"| {did} | ? | ? |")
    lines.append("")

    lines.append("## Concurrency histogram (bars per concurrency level)")
    lines.append("")
    lines.append("| concurrent count | bars | % of all bars | wall-clock |")
    lines.append("|---:|---:|---:|---|")
    for cnt, n in sorted(conc["histogram"].items()):
        pct = 100.0 * n / conc["total_bars"]
        wall_min = n * 15      # 15m per bar
        wall_h = wall_min / 60
        lines.append(f"| {cnt} | {n:,} | {pct:.2f}% | {wall_h:.1f}h |")
    lines.append("")

    # Daily concurrency time-series (top 20 daily-max days)
    lines.append("## Top 20 days by max concurrency")
    lines.append("")
    daily_max = conc["daily_max"]
    top20 = daily_max.dropna().sort_values(ascending=False).head(20)
    lines.append("| date | max concurrent that day |")
    lines.append("|---|---:|")
    for d, v in top20.items():
        lines.append(f"| {d.date()} | {int(v)} |")
    lines.append("")

    lines.append("## Interpretation hints")
    lines.append("")
    lines.append("- **If peak concurrency ≈ N (cohort size)** → all opportunities cluster in same macro windows; real-capital deployment hits hard concurrency wall.")
    lines.append("- **If peak concurrency is small (e.g. 2-5 of 40)** → opportunities naturally diversified across time; real-capital strategy more viable with modest position-count cap.")
    lines.append("- **If 1-concurrency dominates the histogram** → most of the time only one pair is active; portfolio benefits are mostly statistical (smoothing) rather than parallel-deployment.")
    lines.append("- **Long-tail cluster composition** (many distinct combinations at peak) → no single 'overlap regime'; concentration is sporadic.")
    lines.append("- **Repeat cluster composition** (same N pairs at peak each time) → a small structural group drives most of the cohort's activity.")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default=str(OUTPUT_DIR), help="Output directory")
    args = p.parse_args(argv)

    _log(f"backtests dir: {BACKTESTS_DIR}")
    runs = find_cointrev_runs()
    _log(f"discovered {len(runs)} COINTREV runs on disk")
    if not runs:
        _log("no runs found — has /execute-directives completed yet?")
        return 1

    _log("loading per-directive metrics...")
    metrics_df = load_directive_metrics(runs)
    _log(f"  {len(metrics_df)} metric rows assembled")

    # Save the metrics CSV for any follow-up slicing
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "cohort_metrics.csv"
    metrics_df.to_csv(csv_path, index=False)
    _log(f"  wrote {csv_path}")

    _log("building concurrency matrix...")
    matrix = build_concurrency_matrix(runs)
    _log(f"  matrix shape: {matrix.shape}")
    conc = concurrency_stats(matrix)

    # Save concurrency per-bar series (counts only — full matrix would be huge)
    if not matrix.empty:
        cper = matrix.sum(axis=1).rename("concurrent_open_count").to_frame()
        cper.to_csv(OUTPUT_DIR / "concurrency_per_bar.csv")
        _log(f"  wrote {OUTPUT_DIR / 'concurrency_per_bar.csv'}")

    cohort_path = write_cohort_report(metrics_df, conc)
    _log(f"wrote {cohort_path}")

    conc_path = write_concurrency_report(matrix, conc, metrics_df)
    _log(f"wrote {conc_path}")

    # Console summary
    print()
    print("=" * 70)
    print("COHORT SUMMARY")
    print("=" * 70)
    valid = metrics_df.dropna(subset=["net_pnl_usd"])
    total = valid["net_pnl_usd"].sum() if len(valid) else 0
    wins = (valid["net_pnl_usd"] > 0).sum() if len(valid) else 0
    print(f"  directives:        {len(valid)}/{len(metrics_df)}")
    print(f"  cumulative PnL:    ${total:,.2f}")
    print(f"  winner directives: {wins}/{len(valid)}")
    if not conc.get("empty"):
        print(f"  peak concurrent:   {conc['peak_concurrency']} directives @ {conc['peak_first_ts']}")
        print(f"  cohort time-in-pos: {conc['cohort_time_in_pos_pct']:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
