"""
apply_portfolio_constraints.py — Post-Stage-1 Concurrency Enforcement (Research)

Usage:
    python tools/apply_portfolio_constraints.py <STRATEGY_ID>
    python tools/apply_portfolio_constraints.py <STRATEGY_ID> --cap <N>   # override

Purpose:
  Research-phase activation of the cross-symbol concurrency primitive used
  identically in burn-in (strategy_guard) and live (execution_adapter).

  Stage-1 runs symbol-isolated backtests, so portfolio-level concurrency
  cannot be enforced at signal time. This tool consumes the Stage-1 raw
  trade lists, performs a deterministic portfolio-level simulation, and
  rewrites each symbol's results to contain only accepted trades.

Behaviour:
  1. Read execution.concurrency_cap from the canonical directive (INBOX,
     active, or completed).  Missing -> None -> no filter applied.
     Must be int >= 1 when present (validated by engines.concurrency_gate).
  2. Aggregate every symbol's results_tradelevel.csv into one portfolio.
  3. Sort candidates by (entry_dt ASC, symbol ASC) — deterministic.
  4. Single chronological pass.  For each candidate:
        - Expire positions where exit_dt <= entry_dt of candidate.
        - admit(open, cap) -> ACCEPT and track; else REJECT.
     Open-position contract: entry_dt <= now < exit_dt (shared across phases).
  5. Write accepted trades back to each symbol's results_tradelevel.csv.
     Backup originals to results_tradelevel_unconstrained.csv.
     Rejected trades written to results_tradelevel_rejected.csv.
  6. Emit counters: rejected_due_to_cap, max_concurrent_seen.

Data root:
  TradeScan_State/backtests/<STRATEGY_ID>_<SYMBOL>/raw/results_tradelevel.csv
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"
BACKTESTS_ROOT = STATE_ROOT / "backtests"
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"

sys.path.insert(0, str(PROJECT_ROOT))
from engines.concurrency_gate import admit, validate_cap  # noqa: E402


def _locate_directive(strategy_id: str) -> Path | None:
    for sub in ("INBOX", "active", "completed", "active_backup"):
        candidate = DIRECTIVES_ROOT / sub / f"{strategy_id}.txt"
        if candidate.exists():
            return candidate
    return None


def _load_directive_cap(strategy_id: str, override: int | None) -> int | None:
    if override is not None:
        return validate_cap(override)

    path = _locate_directive(strategy_id)
    if path is None:
        print(f"[WARN] directive not found for {strategy_id} — treating cap as None")
        return None

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    execution = data.get("execution") or {}
    raw = execution.get("concurrency_cap", None)
    return validate_cap(raw)


def _discover_symbol_files(strategy_id: str) -> list[tuple[str, Path, Path]]:
    prefix = f"{strategy_id}_"
    rows: list[tuple[str, Path, Path]] = []
    if not BACKTESTS_ROOT.exists():
        raise FileNotFoundError(f"Backtests root not found: {BACKTESTS_ROOT}")
    for folder in sorted(BACKTESTS_ROOT.iterdir()):
        if not folder.is_dir() or not folder.name.startswith(prefix):
            continue
        symbol = folder.name[len(prefix):]
        raw_dir = folder / "raw"
        csv_path = raw_dir / "results_tradelevel.csv"
        if csv_path.exists():
            rows.append((symbol, raw_dir, csv_path))
    return rows


def _aggregate(trade_files: list[tuple[str, Path, Path]]) -> pd.DataFrame:
    frames = []
    for symbol, raw_dir, csv_path in trade_files:
        backup = raw_dir / "results_tradelevel_unconstrained.csv"
        if not backup.exists():
            shutil.copy(csv_path, backup)
        df = pd.read_csv(csv_path)
        if df.empty:
            continue
        df["symbol"] = symbol
        df["entry_dt"] = pd.to_datetime(df["entry_timestamp"])
        df["exit_dt"] = pd.to_datetime(df["exit_timestamp"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined.sort_values(by=["entry_dt", "symbol"], kind="mergesort", inplace=True)
    combined.reset_index(drop=True, inplace=True)
    return combined


def _simulate(full_df: pd.DataFrame, cap: int | None) -> tuple[list[int], list[int], int]:
    """Run portfolio-level FIFO admission simulation.

    Returns (accepted_idx, rejected_idx, max_concurrent_seen).
    Open-position contract: entry_dt <= now < exit_dt.
    """
    accepted: list[int] = []
    rejected: list[int] = []
    open_positions: list[dict] = []
    max_concurrent = 0

    for idx, row in full_df.iterrows():
        now = row["entry_dt"]
        open_positions = [p for p in open_positions if p["exit_dt"] > now]

        if admit(open_positions, cap):
            accepted.append(idx)
            open_positions.append({
                "exit_dt": row["exit_dt"],
                "symbol": row["symbol"],
            })
            if len(open_positions) > max_concurrent:
                max_concurrent = len(open_positions)
        else:
            rejected.append(idx)

    return accepted, rejected, max_concurrent


def _writeback(
    full_df: pd.DataFrame,
    accepted_idx: list[int],
    rejected_idx: list[int],
    symbol_folders: dict[str, Path],
) -> dict[str, tuple[int, int]]:
    accepted_df = full_df.loc[accepted_idx]
    rejected_df = full_df.loc[rejected_idx]
    per_symbol: dict[str, tuple[int, int]] = {}

    for symbol, raw_dir in symbol_folders.items():
        backup = raw_dir / "results_tradelevel_unconstrained.csv"
        orig_cols = pd.read_csv(backup, nrows=0).columns.tolist()

        sym_accepted = accepted_df[accepted_df["symbol"] == symbol]
        sym_rejected = rejected_df[rejected_df["symbol"] == symbol]

        target = raw_dir / "results_tradelevel.csv"
        if not sym_accepted.empty:
            sym_accepted[orig_cols].to_csv(target, index=False)
        else:
            pd.DataFrame(columns=orig_cols).to_csv(target, index=False)

        reject_path = raw_dir / "results_tradelevel_rejected.csv"
        if not sym_rejected.empty:
            sym_rejected[orig_cols].to_csv(reject_path, index=False)
        elif reject_path.exists():
            reject_path.unlink()

        per_symbol[symbol] = (len(sym_accepted), len(sym_rejected))

    return per_symbol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy_id")
    parser.add_argument(
        "--cap",
        type=int,
        default=None,
        help="Override the directive's execution.concurrency_cap (int >= 1).",
    )
    args = parser.parse_args()

    strategy_id: str = args.strategy_id
    cap = _load_directive_cap(strategy_id, args.cap)

    print(f"\n{'=' * 60}")
    print(f"PORTFOLIO CONSTRAINT ENFORCEMENT — {strategy_id}")
    print(f"Concurrency Cap: {cap if cap is not None else 'None (unlimited)'}")
    print(f"{'=' * 60}")

    trade_files = _discover_symbol_files(strategy_id)
    if not trade_files:
        print(f"[ERROR] No trade files found for {strategy_id} under {BACKTESTS_ROOT}")
        return 1

    symbol_folders = {sym: raw_dir for sym, raw_dir, _ in trade_files}
    print(f"[1/4] Loaded {len(trade_files)} symbol trade lists.")

    full_df = _aggregate(trade_files)
    total_candidates = len(full_df)
    print(f"[2/4] Aggregated {total_candidates} candidate trades.")

    if cap is None:
        print("[3/4] cap=None -> no filter applied; files unchanged.")
        summary = {
            "strategy_id": strategy_id,
            "concurrency_cap": None,
            "total_candidates": total_candidates,
            "accepted": total_candidates,
            "rejected_due_to_cap": 0,
            "max_concurrent_seen": None,
        }
        print(json.dumps(summary, indent=2))
        return 0

    accepted_idx, rejected_idx, max_concurrent = _simulate(full_df, cap)
    accepted_n = len(accepted_idx)
    rejected_n = len(rejected_idx)
    print(f"[3/4] Simulation complete.")
    print(f"      accepted           : {accepted_n}")
    print(f"      rejected_due_to_cap: {rejected_n}")
    print(f"      max_concurrent_seen: {max_concurrent}")
    if max_concurrent > cap:
        raise RuntimeError(
            f"Invariant violated: max_concurrent_seen ({max_concurrent}) > cap ({cap})"
        )

    per_symbol = _writeback(full_df, accepted_idx, rejected_idx, symbol_folders)
    print("[4/4] Writeback per-symbol (accepted / rejected):")
    for symbol in sorted(per_symbol):
        a, r = per_symbol[symbol]
        print(f"      {symbol:<8}  {a:>4}  /  {r:>4}")

    summary = {
        "strategy_id": strategy_id,
        "concurrency_cap": cap,
        "total_candidates": total_candidates,
        "accepted": accepted_n,
        "rejected_due_to_cap": rejected_n,
        "max_concurrent_seen": max_concurrent,
        "per_symbol": {s: {"accepted": a, "rejected": r} for s, (a, r) in per_symbol.items()},
    }
    summary_path = BACKTESTS_ROOT / f"_concurrency_summary__{strategy_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSummary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
