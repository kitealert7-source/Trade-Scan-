"""generate_cointrev_v1_2_directives.py — emit COINTREV v1.2 basket directives.

Strategy spec: outputs/cointegration_screener_v1/v1_2_strategy_design/DESIGN_DOC.md §5

Reads the cointegration_triggers SQLite ledger and emits one basket directive
per distinct (pair_a, pair_b) at a given lookback (default 252). Each
directive references rule cointegration_meanrev_v1_2@1 and sets
`basket.cointegration_join.lookback_days` so basket_data_loader joins the
per-date cointegration state + trigger flags onto each leg's DataFrame at
runtime.

Naming convention (per DESIGN_DOC §5):
    90_PORT_{PAIR_A}{PAIR_B}_15M_COINTREV_V2_L{LOOKBACK}

Date range: full trigger-history extent (earliest as_of → latest as_of)
auto-derived from the ledger at run time, so each directive covers every
trigger event the screener has recorded for its pair.

Default output: backtest_directives/cointrev_v1_2_staging/ — a STAGING
location, not INBOX. The pilot workflow promotes 10-20 representative
directives to INBOX first; full 263 only after operator review of pilot
results (per DESIGN_DOC §11 step 10).

Usage:
    python tools/generate_cointrev_v1_2_directives.py --dry-run
    python tools/generate_cointrev_v1_2_directives.py --limit 5
    python tools/generate_cointrev_v1_2_directives.py
    python tools/generate_cointrev_v1_2_directives.py --lookback-days 504
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config.path_authority import REAL_REPO_ROOT  # noqa: E402
from tools.basket_data_loader import _COINT_DB_PATH  # noqa: E402


_DEFAULT_TARGET_DIR = REAL_REPO_ROOT / "backtest_directives" / "cointrev_v1_2_staging"
_DEFAULT_LOOKBACK = 252
_DEFAULT_TIMEFRAME = "15m"
_DEFAULT_BROKER = "OctaFx"


def _query_pairs(db_path: Path, lookback: int) -> list[tuple[str, str]]:
    """Distinct (pair_a, pair_b) at the given lookback, alphabetically ordered."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT pair_a, pair_b "
            "  FROM cointegration_triggers "
            " WHERE lookback_days = ? "
            " ORDER BY pair_a, pair_b",
            (lookback,),
        ).fetchall()
    finally:
        conn.close()
    return [(a, b) for a, b in rows]


def _query_date_range(db_path: Path, lookback: int) -> tuple[str, str]:
    """Earliest + latest as_of date for triggers at the given lookback."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT MIN(as_of), MAX(as_of) "
            "  FROM cointegration_triggers "
            " WHERE lookback_days = ?",
            (lookback,),
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None:
        raise RuntimeError(
            f"cointegration_triggers has no rows at lookback={lookback}. "
            f"Run cointegration screener first."
        )
    earliest, latest = row
    return str(earliest)[:10], str(latest)[:10]


def _tf_slug(timeframe: str) -> str:
    """Filename slug for a TF: '15m' -> '15M', '1d' -> '1D', '1h' -> '1H'."""
    return timeframe.upper()


def _directive_name(pair_a: str, pair_b: str, lookback: int,
                    timeframe: str = _DEFAULT_TIMEFRAME) -> str:
    """Per DESIGN_DOC §5: 90_PORT_{PAIR_A}{PAIR_B}_{TF}_COINTREV_V2_L{LOOKBACK}."""
    return f"90_PORT_{pair_a}{pair_b}_{_tf_slug(timeframe)}_COINTREV_V2_L{lookback}"


def _basket_id(pair_a: str, pair_b: str) -> str:
    """basket_id = PAIR_A+PAIR_B concatenated (must match SYMBOL slot in name)."""
    return f"{pair_a}{pair_b}"


def _build_directive(pair_a: str, pair_b: str, *, lookback: int,
                     start_date: str, end_date: str,
                     timeframe: str = _DEFAULT_TIMEFRAME) -> dict[str, Any]:
    """Build one COINTREV v1.2 directive payload.

    Both legs declared `direction: long` is a placeholder. The
    CointTriggerLegStrategy's signal is position_direction * coint_direction
    (LONG_SPREAD = +1; SHORT_SPREAD = -1) — the rule sets actual basket
    direction per cycle from the trigger row. Legs use position_direction
    +1/-1 set by run_pipeline._load_basket_leg_data via leg["direction"];
    we use long/short here so leg_a is +1 (long) and leg_b is -1 (short),
    consistent with the alphabetical canonical β-pair convention.
    """
    name = _directive_name(pair_a, pair_b, lookback, timeframe)
    return {
        "test": {
            "name": name,
            "family": "PORT",
            "strategy": name,
            "version": 1,
            "signal_version": 1,
            "broker": _DEFAULT_BROKER,
            "timeframe": timeframe,
            "start_date": start_date,
            "end_date": end_date,
            "research_mode": True,
            "tuning_allowed": False,
            "parameter_mutation": False,
            "hypothesis_ref": "COINTREV_V1_2_BASE",
            "hypothesis_variant": f"COINTREV_V1_2_L{lookback}_{pair_a}_{pair_b}",
            "description": (
                f"COINTREV v1.2 base run: beta-weighted spread on "
                f"({pair_a}, {pair_b}) at lookback={lookback}. "
                f"Reads cointegration_triggers ledger via auto-join "
                f"(basket.cointegration_join.lookback_days = {lookback}). "
                f"Base run: no hard z-stop, no pyramid; exits = "
                f"mean-reversion (|z| <= exit_z) > regime-degradation "
                f"(coint_regime in ['breaking', 'broken']) > time-stop "
                f"(elapsed >= time_stop_bars). Locked per "
                f"DESIGN_DOC.md section 4. Date range = full trigger-history "
                f"extent: {start_date} -> {end_date}."
            ),
        },
        "symbols": [pair_a, pair_b],
        "indicators": [
            "indicators.volatility.atr",
        ],
        "execution_rules": {
            "pyramiding": False,
            "entry_when_flat_only": True,
            "reset_on_exit": False,
            "entry_logic": {"type": "coint_trigger_proposal"},
            "exit_logic": {"type": "basket_recycle_rule"},
            "stop_loss": {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "trailing_stop": {"enabled": False},
            "take_profit": {"enabled": False},
        },
        "order_placement": {
            "type": "market",
            "execution_timing": "next_bar_open",
        },
        "trade_management": {
            "direction": "basket_mixed",
            "reentry": {"allowed": True},
            "session_reset": "none",
        },
        "position_management": {"lots": 0.01},
        "basket": {
            "basket_id": _basket_id(pair_a, pair_b),
            "legs": [
                {"symbol": pair_a, "lot": 0.01, "direction": "long"},
                {"symbol": pair_b, "lot": 0.01, "direction": "short"},
            ],
            "initial_stake_usd": 1000.0,
            "harvest_threshold_usd": 1000000.0,
            "cointegration_join": {"lookback_days": lookback},
            "recycle_rule": {
                "name": "cointegration_meanrev_v1_2",
                "version": 1,
                "params": {
                    "min_gap_days_between_triggers": 5,
                    "exit_z": 1.0,
                    "time_stop_bars": 60,
                    "regime_exit_states": ["breaking", "broken"],
                    "initial_notional_usd": 1000.0,
                    "default_initial_lot": 0.01,
                },
            },
        },
    }


def _write_directive(directive: dict[str, Any], target_dir: Path) -> Path:
    """Write directive to <target_dir>/<test.name>.txt using YAML default flow."""
    target_dir.mkdir(parents=True, exist_ok=True)
    name = directive["test"]["name"]
    path = target_dir / f"{name}.txt"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(directive, f, sort_keys=False, default_flow_style=False,
                       allow_unicode=False, width=80)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--db-path", type=Path, default=_COINT_DB_PATH,
                        help=f"SQLite cointegration.db path (default: {_COINT_DB_PATH})")
    parser.add_argument("--lookback-days", type=int, default=_DEFAULT_LOOKBACK,
                        help=f"Cointegration lookback window (default: {_DEFAULT_LOOKBACK})")
    parser.add_argument("--target-dir", type=Path, default=_DEFAULT_TARGET_DIR,
                        help=f"Output directory (default: {_DEFAULT_TARGET_DIR.relative_to(REAL_REPO_ROOT)})")
    parser.add_argument("--timeframe", type=str, default=_DEFAULT_TIMEFRAME,
                        help=f"Execution TF for directives (default: {_DEFAULT_TIMEFRAME}). "
                             f"Valid: 5m, 15m, 30m, 1h, 4h, 1d (must match run_pipeline._BAR_SECONDS_MAP).")
    parser.add_argument("--pair-filter", type=str, default=None,
                        help="Comma-separated list of pair concatenations (e.g. 'EUSTX50UK100,JPN225SPX500'). "
                             "When set, generator emits only these pairs.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Write only the first N directives (alphabetical order). "
                             "Use for pilot subset selection.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — do not write files. Reports count + first 5 names.")
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"[gen-cointrev] ERROR: db_path {args.db_path} does not exist.",
              file=sys.stderr)
        return 1

    print(f"[gen-cointrev] Reading {args.db_path}")
    print(f"[gen-cointrev] Lookback days: {args.lookback_days}")

    pairs = _query_pairs(args.db_path, args.lookback_days)
    if not pairs:
        print(f"[gen-cointrev] ERROR: no pair-pairs at lookback={args.lookback_days}.",
              file=sys.stderr)
        return 1

    earliest, latest = _query_date_range(args.db_path, args.lookback_days)
    print(f"[gen-cointrev] {len(pairs)} pair-pairs in ledger; "
          f"date range {earliest} -> {latest}")
    print(f"[gen-cointrev] Timeframe: {args.timeframe}")

    if args.pair_filter:
        allowed = set(p.strip().upper() for p in args.pair_filter.split(","))
        before = len(pairs)
        pairs = [(a, b) for a, b in pairs if (a + b) in allowed]
        print(f"[gen-cointrev] Filtered {before} -> {len(pairs)} pair-pairs via --pair-filter.")

    if args.limit is not None:
        pairs = pairs[: args.limit]
        print(f"[gen-cointrev] Limited to first {len(pairs)} (alphabetical).")

    if args.dry_run:
        print(f"[gen-cointrev] DRY RUN — no files written.")
        print(f"[gen-cointrev] Target dir would be: {args.target_dir}")
        print(f"[gen-cointrev] First 5 directive names:")
        for pa, pb in pairs[:5]:
            print(f"    {_directive_name(pa, pb, args.lookback_days, args.timeframe)}")
        if len(pairs) > 5:
            print(f"    ... and {len(pairs) - 5} more.")
        return 0

    written = 0
    for pa, pb in pairs:
        directive = _build_directive(
            pa, pb,
            lookback=args.lookback_days,
            start_date=earliest,
            end_date=latest,
            timeframe=args.timeframe,
        )
        path = _write_directive(directive, args.target_dir)
        written += 1
    print(f"[gen-cointrev] Wrote {written} directives to {args.target_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
