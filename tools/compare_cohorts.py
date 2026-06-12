"""Corpus matched-pairs cohort comparator.

Compares a variant cohort against a reference-run cohort in the Master
Portfolio Sheet ('Cointegration' sheet), matched on (pair, test_start,
test_end) so each compared row is the SAME window with one variable changed.

Promoted from the ad-hoc tmp/compare_exp12.py used in the 2026-06
SL / entry-threshold null-result thread. `compare_cohorts(df, ...)` is pure
(takes a DataFrame) for testability; the CLI reads the MPS and renders.

Output is intentionally NEUTRAL: medians, per-pair deltas (variant - reference),
and "variant higher %". It does NOT label any metric "better/worse" because
direction is metric-dependent (e.g. lower maxDD is better). Interpretation is
the human's job (consistent with the hypothesis-testing orchestrator doctrine:
humans decide what to test; tooling reports rigorously, it does not judge).
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

SHEET = "Cointegration"
KEY = ["pair", "test_start", "test_end"]
METRICS = [
    ("return_dd_ratio", "Ret/DD"),
    ("realized_net%", "net%"),
    ("max drawdown %", "maxDD%"),
    ("win_rate", "win%"),
    ("cycles", "cycles"),
    ("total_trades", "trades"),
]


def compare_cohorts(df: "pd.DataFrame", reference_series: str, variant_series: str) -> dict:
    """Matched-pairs comparison of `variant_series` vs `reference_series` within `df`.

    `df` must carry a 'series' column plus the KEY + METRICS columns. Rows are
    inner-joined on KEY so every comparison is the same window. Returns neutral
    stats; an empty match returns matched_pairs=0 with no 'corpus' block.
    """
    d = df.copy()
    d["series"] = d["series"].astype(str)
    ref = d[d["series"] == reference_series]
    var = d[d["series"] == variant_series]
    m = ref.merge(var, on=KEY, suffixes=("_ref", "_var"))

    out = {
        "reference_series": reference_series,
        "variant_series": variant_series,
        "reference_rows": int(len(ref)),
        "variant_rows": int(len(var)),
        "matched_pairs": int(len(m)),
        "metrics": {},
    }
    if len(m) == 0:
        return out

    for col, lab in METRICS:
        c, x = m[f"{col}_ref"], m[f"{col}_var"]
        out["metrics"][lab] = {
            "reference_median": round(float(c.median()), 4),
            "variant_median": round(float(x.median()), 4),
            "median_pair_delta": round(float((x - c).median()), 4),  # variant - reference
            "variant_higher_pct": round(float((x > c).mean() * 100), 1),
        }

    nr, nv = m["realized_net%_ref"], m["realized_net%_var"]
    tr, tv = int(m["total_trades_ref"].sum()), int(m["total_trades_var"].sum())
    out["corpus"] = {
        "reference_net_pct_sum": round(float(nr.sum()), 1),
        "variant_net_pct_sum": round(float(nv.sum()), 1),
        "reference_worst_net_pct": round(float(nr.min()), 1),
        "variant_worst_net_pct": round(float(nv.min()), 1),
        "reference_blowups_lt_minus100": int((nr < -100).sum()),
        "variant_blowups_lt_minus100": int((nv < -100).sum()),
        "reference_total_trades": tr,
        "variant_total_trades": tv,
        "variant_trade_freq_pct": round(float(tv / max(1, tr) * 100), 1),
    }
    return out


def render(res: dict) -> str:
    lines = [
        f"{res['variant_series']}  vs  {res['reference_series']}",
        f"  reference rows={res['reference_rows']}  variant rows={res['variant_rows']}  matched pairs={res['matched_pairs']}",
    ]
    if res["matched_pairs"] == 0:
        lines.append("  (no matched windows -- check series tags / KEY columns)")
        return "\n".join(lines)
    lines.append(f"  {'metric':8} {'reference':>10} {'variant':>10} {'dMed(v-r)':>11} {'v>r%':>6}")
    for lab, mm in res["metrics"].items():
        lines.append(
            f"  {lab:8} {mm['reference_median']:>10.3f} {mm['variant_median']:>10.3f} "
            f"{mm['median_pair_delta']:>+11.3f} {mm['variant_higher_pct']:>5.0f}%"
        )
    c = res["corpus"]
    lines.append(
        f"  corpus net%: ref={c['reference_net_pct_sum']:.0f} var={c['variant_net_pct_sum']:.0f}"
        f"  | worst: ref={c['reference_worst_net_pct']:.1f} var={c['variant_worst_net_pct']:.1f}"
        f"  | blowups(<-100%): ref={c['reference_blowups_lt_minus100']} var={c['variant_blowups_lt_minus100']}"
    )
    lines.append(
        f"  total trades: ref={c['reference_total_trades']} var={c['variant_total_trades']}"
        f"  | variant trade-freq vs ref = {c['variant_trade_freq_pct']:.0f}%"
    )
    return "\n".join(lines)


def _default_mps_path() -> str:
    from config.state_paths import STRATEGIES_DIR

    return str(STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Matched-pairs cohort comparison (variant vs reference run) from the MPS Cointegration sheet."
    )
    ap.add_argument("--reference-series", required=True, help="series tag of the reference run, e.g. GP_ZCRS_CXN1_Z25")
    ap.add_argument("--variant-series", required=True, help="series tag of the variant cohort")
    ap.add_argument("--mps", default=None, help="path to Master_Portfolio_Sheet.xlsx (default: state STRATEGIES_DIR)")
    ap.add_argument("--sheet", default=SHEET)
    args = ap.parse_args()

    mps = args.mps or _default_mps_path()
    df = pd.read_excel(mps, sheet_name=args.sheet)
    print(render(compare_cohorts(df, args.reference_series, args.variant_series)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
