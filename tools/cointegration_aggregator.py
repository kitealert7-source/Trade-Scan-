"""cointegration_aggregator.py -- roll up cointegration_sheet (V3 episode) results.

The V3 analog of cointrev_v1_2_aggregator (which read the V2-era MPS Baskets
sheet). Reads the canonical `cointegration_sheet` table (is_current=1) directly
and emits per-episode + aggregate metrics, reporting verdict buckets, and a
pair-class breakdown. Run it after each batch of the episode-corpus rebuild to
sanity-check before promoting the next batch.

Verdict buckets are REPORTING ONLY (WINNER / NEUTRAL / LOSER / BLOWUP) -- the
ledger deliberately stores no verdict column (operator directive; ranking is by
Ret/DD). They mirror the V2 aggregator's buckets for continuity.

Usage:
    python tools/cointegration_aggregator.py
    python tools/cointegration_aggregator.py --output-csv /tmp/coint_corpus.csv
    python tools/cointegration_aggregator.py --min-trades 1
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from config.path_authority import TRADE_SCAN_STATE  # noqa: E402
from tools.leverage_liquidation_adjust import liquidation_adjusted_from_dd  # noqa: E402

_IDX = {"FRA40", "UK100", "US30", "AUS200", "EUSTX50", "JPN225",
        "GER40", "ESP35", "NAS100", "SPX500", "US500"}
_CRYPTO = {"BTCUSD", "ETHUSD"}
_METAL = {"XAUUSD"}


def _kind(s: str) -> str:
    if s in _IDX:
        return "IDX"
    if s in _CRYPTO:
        return "CRY"
    if s in _METAL:
        return "MET"
    return "FX"


def _pair_class(a: str, b: str) -> str:
    ks = tuple(sorted([_kind(a), _kind(b)]))
    if ks == ("FX", "FX"):
        return "FX-FX"
    if ks == ("IDX", "IDX"):
        return "IDX-IDX"
    if ks == ("FX", "IDX"):
        return "FX-IDX"
    if "CRY" in ks or "MET" in ks:
        return "CRYPTO/METAL"
    return "other"


def _verdict(net: float, dd: float) -> str:
    if pd.isna(net):
        return "MISSING"
    if dd is not None and not pd.isna(dd) and dd > 30:
        return "BLOWUP"
    if net > 1.0:
        return "WINNER"
    if net < -1.0:
        return "LOSER"
    return "NEUTRAL"


def apply_liquidation_floor(df: pd.DataFrame) -> pd.DataFrame:
    """Floor would-have-been-liquidated rows (canonical_max_dd_pct > 100% =>
    trough equity went below zero intra-run) to net=-100 / dd=100 / ret_dd=-1,
    adding a `liquidated` bool column. The frozen engine models NO margin call,
    so a leveraged-sizing (granular_parity / vol_parity) basket can report >100%
    DD or a fictitious recovery; this is the analysis-layer floor
    (SZVP_LEVERAGE_FORENSIC, 2026-06-04). Pure ledger metrics — the per-bar
    equity artifact is not retained for cointegration runs, so max-DD is the
    discriminant (leverage_liquidation_adjust.liquidation_adjusted_from_dd)."""
    df = df.copy()
    if df.empty:
        df["liquidated"] = pd.Series([], dtype=bool)
        return df
    adj = [liquidation_adjusted_from_dd(net_pct=n, max_dd_pct=d, ret_dd=r)
           for n, d, r in zip(df["net"], df["dd"], df["rdd"])]
    df["net"] = [a["net_pct"] for a in adj]
    df["dd"] = [a["max_dd_pct"] for a in adj]
    df["rdd"] = [a["ret_dd"] for a in adj]
    df["liquidated"] = [a["liquidated"] for a in adj]
    return df


def load(min_trades: int = 0, apply_floor: bool = True) -> pd.DataFrame:
    db = Path(TRADE_SCAN_STATE) / "ledger.db"
    if not db.is_file():
        raise FileNotFoundError(f"ledger.db not found at {db}")
    conn = sqlite3.connect(str(db))
    try:
        df = pd.read_sql_query(
            "SELECT pair_a, pair_b, test_start, test_end, "
            "canonical_net_pct AS net, canonical_ret_dd AS rdd, "
            "canonical_max_dd_pct AS dd, cycle_win_rate_pct AS win, "
            "cycles_completed AS cycles, trades_total AS trades "
            "FROM cointegration_sheet WHERE is_current = 1", conn)
    finally:
        conn.close()
    if min_trades:
        df = df[df["trades"] >= min_trades].copy()
    df["pair"] = df["pair_a"] + "/" + df["pair_b"]
    df["pair_class"] = [_pair_class(a, b) for a, b in zip(df["pair_a"], df["pair_b"])]
    if apply_floor:
        df = apply_liquidation_floor(df)
    else:
        df["liquidated"] = False
    df["verdict"] = [_verdict(n, d) for n, d in zip(df["net"], df["dd"])]
    return df


def summarize(df: pd.DataFrame, label: str) -> None:
    n = len(df)
    if n == 0:
        print(f"{label}: 0 rows")
        return
    pos = int((df["net"] > 0).sum())
    print(f"{label}: n={n} | positive={pos} ({pos / n * 100:.0f}%) | "
          f"net% mean={df['net'].mean():.1f} med={df['net'].median():.1f} | "
          f"ret/dd mean={df['rdd'].mean():.2f} | win% mean={df['win'].mean():.1f}")
    vc = df["verdict"].value_counts().to_dict()
    print("    verdicts:", {k: vc.get(k, 0)
                            for k in ["WINNER", "NEUTRAL", "LOSER", "BLOWUP", "MISSING"]})
    if "liquidated" in df.columns:
        liq = int(df["liquidated"].sum())
        if liq:
            print(f"    liquidation-floored (maxDD>100% -> net-100/dd100/ret_dd-1): {liq}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-csv", default=None)
    ap.add_argument("--min-trades", type=int, default=0)
    ap.add_argument("--no-liquidation-floor", action="store_true",
                    help="disable the analysis-layer liquidation floor (show raw engine metrics)")
    args = ap.parse_args()

    df = load(args.min_trades, apply_floor=not args.no_liquidation_floor)
    print("=== Cointegration corpus (cointegration_sheet, is_current=1) ===")
    summarize(df, "ALL")
    print("--- by pair-class ---")
    for cls in ["FX-FX", "IDX-IDX", "FX-IDX", "CRYPTO/METAL", "other"]:
        sub = df[df["pair_class"] == cls]
        if len(sub):
            summarize(sub, f"  {cls}")
    if len(df):
        print("--- top 5 by ret/dd ---")
        for _, r in df.nlargest(5, "rdd").iterrows():
            print(f"  {r['pair']:16} net={r['net']:+6.1f}% rdd={r['rdd']:+5.2f} "
                  f"win={r['win']:4.0f}% {r['test_start']}->{r['test_end']}")
        print("--- bottom 5 by ret/dd ---")
        for _, r in df.nsmallest(5, "rdd").iterrows():
            print(f"  {r['pair']:16} net={r['net']:+6.1f}% rdd={r['rdd']:+5.2f} "
                  f"win={r['win']:4.0f}% {r['test_start']}->{r['test_end']}")
    if args.output_csv:
        df.to_csv(args.output_csv, index=False)
        print(f"[CSV] wrote {len(df)} rows -> {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
