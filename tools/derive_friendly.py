"""derive_friendly.py — rule-derive the FX-FX "friendly" cointegration universe.

Reads the MPS backtest workbook and writes governance/fx_fx_friendly.yaml, which
cointegration_excel.py consumes to stamp a `tier` flag (elite|friendly) on
screener rows. Rule-based (NOT a fixed N) — re-run monthly or after new backtests.

Rule:
    friendly = pair is FX-FX (both legs spot FX) AND Evaluable >= 5
               AND Median Ret/DD >= 0.50
    elite    = friendly AND Median Ret/DD >= 0.75

The generator joins this list to its rows by a canonical, order-independent
pair key: '/'.join(sorted([pair_a, pair_b])).

Usage:
    python tools/derive_friendly.py             # write governance/fx_fx_friendly.yaml
    python tools/derive_friendly.py --dry-run   # print to stdout, don't write
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import yaml

from config.path_authority import TRADE_SCAN_STATE

MPS_PATH = TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"
SHEET = "COINT TRADE CANDIDATES"
OUTPUT_YAML = PROJECT_ROOT / "governance" / "fx_fx_friendly.yaml"

# Spot-FX currency pairs: both legs must be in this set for FX-FX classification
# (excludes XAU/BTC/ETH/indices). This is the cointegration-friendly *eligible*
# asset universe — the rule then selects within it on backtest robustness.
FX_CURRENCIES = frozenset({
    "AUDJPY", "AUDNZD", "AUDUSD", "CADJPY", "CHFJPY", "EURAUD", "EURGBP",
    "EURJPY", "EURUSD", "GBPAUD", "GBPJPY", "GBPNZD", "GBPUSD", "NZDJPY",
    "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
})

MIN_EVALUABLE = 5
FRIENDLY_MIN_RET_DD = 0.50
ELITE_MIN_RET_DD = 0.75


def canonical_key(leg_a: str, leg_b: str) -> str:
    """Order-independent pair key shared across MPS / screener-DB / this yaml."""
    return "/".join(sorted([leg_a.strip(), leg_b.strip()]))


def _legs(pair_cell) -> tuple[str, str] | None:
    """Parse 'A / B' (tolerating a leading medal emoji) into (A, B)."""
    clean = re.sub(r"[^\x00-\x7F]", "", str(pair_cell)).strip()
    if "/" not in clean:
        return None
    a, b = [x.strip() for x in clean.split("/", 1)]
    return (a, b) if a and b else None


def derive(mps_path: Path = MPS_PATH) -> list[dict]:
    """Apply the friendly rule to the MPS COINT TRADE CANDIDATES sheet."""
    df = pd.read_excel(mps_path, sheet_name=SHEET, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    best: dict[str, dict] = {}
    for _, row in df.iterrows():
        legs = _legs(row.get("Pair"))
        if not legs:
            continue
        a, b = legs
        if a not in FX_CURRENCIES or b not in FX_CURRENCIES:
            continue
        ev = pd.to_numeric(row.get("Evaluable"), errors="coerce")
        rd = pd.to_numeric(row.get("Median Ret/DD"), errors="coerce")
        if pd.isna(ev) or pd.isna(rd) or ev < MIN_EVALUABLE or rd < FRIENDLY_MIN_RET_DD:
            continue
        rec = {
            "pair": canonical_key(a, b),
            "tier": "elite" if rd >= ELITE_MIN_RET_DD else "friendly",
            "median_ret_dd": round(float(rd), 3),
            "evaluable": int(ev),
        }
        # canonical de-dup: keep the strongest orientation if a pair recurs
        k = rec["pair"]
        if k not in best or rec["median_ret_dd"] > best[k]["median_ret_dd"]:
            best[k] = rec
    return sorted(best.values(), key=lambda r: (r["tier"] != "elite", -r["median_ret_dd"]))


def build_doc(rows: list[dict]) -> dict:
    elite = [r for r in rows if r["tier"] == "elite"]
    friendly = [r for r in rows if r["tier"] == "friendly"]
    return {
        "meta": {
            "description": "Rule-derived FX-FX 'friendly' cointegration universe "
                           "(consumed by tools/cointegration_excel.py).",
            "rule": f"FX-FX (both legs spot FX) AND Evaluable>={MIN_EVALUABLE} "
                    f"AND Median Ret/DD>={FRIENDLY_MIN_RET_DD}; "
                    f"elite = Median Ret/DD>={ELITE_MIN_RET_DD}",
            "source": "Master_Portfolio_Sheet.xlsx :: COINT TRADE CANDIDATES",
            "refresh": "Re-run monthly or after new backtests: python tools/derive_friendly.py",
            "canonical_key": "'/'.join(sorted([pair_a, pair_b]))  # order-independent",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(rows),
            "n_elite": len(elite),
            "n_friendly": len(friendly),
        },
        "pairs": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print to stdout, don't write")
    args = ap.parse_args(argv)

    rows = derive()
    text = yaml.safe_dump(build_doc(rows), sort_keys=False, default_flow_style=False,
                          allow_unicode=False)
    if args.dry_run:
        sys.stdout.write(text)
        return 0
    OUTPUT_YAML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_YAML.write_text(text, encoding="utf-8")
    n_elite = sum(1 for r in rows if r["tier"] == "elite")
    print(f"wrote {OUTPUT_YAML}  ({len(rows)} pairs: {n_elite} elite, "
          f"{len(rows) - n_elite} friendly)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
