"""replay_shadow_journal_reference.py — generate the strategy_guard.py reference classifications for the 33-day shadow journal.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 7a (revised battery), Stage 1
(shadow journal replay).

Phase 7a's acceptance gate compares the *ported* validator (in
TS_SignalValidator) against the proven `execution_engine.strategy_guard`
implementation on the same input distribution. This script generates
the "gold-standard reference" half of that comparison: it walks every
SIGNAL event in `VALIDATION_DATASET/shadow_journal_2026_04_to_05/`,
loads the appropriate per-symbol vault (from the latest DRY_RUN_*
snapshot containing it), and runs `StrategyGuard.validate_signal()`
on each event.

Output is byte-stable JSONL — one line per SIGNAL event — for later
byte-diff against the TS_SignalValidator port's output on the same
journal events.

Caveats (intentionally documented, not deflected):

* The production journal's stored `signal_hash` field uses a DIFFERENT
  hash function than `strategy_guard._compute_signal_hash`. Specifically,
  the production hash (TS_Execution/src/signal_journal.py::signal_hash):
    - Includes `strategy_id` in the inputs (strategy_guard does not)
    - Returns full SHA-256 (strategy_guard returns the 16-char prefix)
    - Uses direction string "LONG"/"SHORT" (strategy_guard uses int)
  Consequence: this script's `result_hash` does NOT equal the journal's
  `signal_hash` field. That is expected. The reference set is what
  `strategy_guard.py` classifies TODAY, not what production classified
  historically. The port's goal is to reproduce strategy_guard's
  current behavior, not the historical production hashes.

* Schema migration in the journal: pre-migration events have a 16-char
  `signal_hash` (from before strategy_id was added to the hash); post-
  migration have the full 64-char SHA-256. We don't depend on either —
  we recompute against strategy_guard.

* `risk_distance` is derived as `abs(entry_price - stop_price)` per the
  same formula the production system used at signal time.

Usage:
  python tools/replay_shadow_journal_reference.py
  python tools/replay_shadow_journal_reference.py --limit 100  (for dev)
  python tools/replay_shadow_journal_reference.py --out <path>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Trade_Scan import shim — file lives under tools/ but imports execution_engine/
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Suppress per-event "[GUARD] HARD_FAIL" log lines from strategy_guard. The
# replay's role is to capture classifications into JSONL, not to surface every
# decision. (HARD_FAIL is the *correct* outcome for every event in the journal
# — they're live signals beyond the backtest window, the case the
# `validate_signal` docstring explicitly calls out. See the reference set's
# stats for the post-run summary.)
logging.getLogger("execution_engine.strategy_guard").setLevel(logging.ERROR)

from config.path_authority import DRY_RUN_VAULT, VALIDATION_DATASET  # noqa: E402
from execution_engine.strategy_guard import StrategyGuard, GuardConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Vault discovery
# ---------------------------------------------------------------------------


DRY_RUN_VAULT_ROOT = DRY_RUN_VAULT
SHADOW_CORPUS_ROOT = VALIDATION_DATASET / "shadow_journal_2026_04_to_05"
SHADOW_JOURNAL_FILE = SHADOW_CORPUS_ROOT / "bars" / "journal" / "shadow_trades.jsonl"
DEFAULT_PROFILE = "RAW_MIN_LOT_V1"
DEFAULT_OUT = REPO_ROOT / "outputs" / "shadow_journal_strategy_guard_reference.jsonl"


def _base_strategy_id(strategy_id: str, symbol: str) -> str:
    """Strip a trailing `_<symbol>` suffix when present.

    The journal records ids like `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05_GBPJPY`
    where the trailing `_GBPJPY` is the multi-symbol leaf. The vault lives
    under the *base* directive id `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05`.
    Two journal events used the bare base id without the suffix — those are
    handled by the `as-is` branch.

    NOTE: identical to `TS_SignalValidator/vault_lookup.py::base_strategy_id`
    (TSSV commit 066cae3 extracted that as a shared module within TSSV).
    Cannot share across repos by H2 plan §1l repo-separation discipline; if
    you change one, change both. Future option: vendor the helper into a
    shared `engine_abi`-style module if more cross-repo helpers accrue.
    """
    suffix = f"_{symbol}"
    if strategy_id.endswith(suffix):
        return strategy_id[: -len(suffix)]
    return strategy_id


def _find_latest_vault(base_strategy_id: str) -> Path | None:
    """Return the most recent DRY_RUN_* snapshot that contains the strategy."""
    found = sorted(
        DRY_RUN_VAULT_ROOT.glob(f"DRY_RUN_*/{base_strategy_id}"),
        reverse=True,  # newest snapshot first by name ordering (YYYY_MM_DD__hash)
    )
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Guard cache (one StrategyGuard per base strategy_id)
# ---------------------------------------------------------------------------


def _build_guard_cache(strategies: list[str], profile: str) -> dict[str, StrategyGuard | None]:
    cache: dict[str, StrategyGuard | None] = {}
    for sid in strategies:
        vault = _find_latest_vault(sid)
        if vault is None:
            print(f"[reference]  NO VAULT  {sid}", file=sys.stderr)
            cache[sid] = None
            continue
        try:
            guard = StrategyGuard.from_vault(vault, profile=profile, config=GuardConfig())
            cache[sid] = guard
            print(
                f"[reference]  LOADED    {sid}  vault={vault.parent.name}  "
                f"trades={guard.baseline.total_trades}  WR={guard.baseline.expected_win_rate:.3f}  "
                f"max_streak={guard.baseline.max_loss_streak}  DD=${guard.baseline.max_drawdown_usd:.2f}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"[reference]  ERROR     {sid}  {exc!r}", file=sys.stderr)
            cache[sid] = None
    return cache


# ---------------------------------------------------------------------------
# Replay loop
# ---------------------------------------------------------------------------


def _classify_event(guard: StrategyGuard, event: dict) -> dict:
    """Run validate_signal on one event. Return the row dict for JSONL."""
    symbol = event["symbol"]
    bar_time = event["bar_time"]
    direction_int = 1 if event["direction"] == "LONG" else -1
    entry_price = float(event["entry_price"])
    stop_price_raw = event.get("stop_price")
    if stop_price_raw is None:
        return {
            "event_id":          event.get("event_id"),
            "strategy_id":       event.get("strategy_id"),
            "symbol":            symbol,
            "bar_time":          bar_time,
            "direction":         event["direction"],
            "entry_price":       entry_price,
            "stop_price":        None,
            "risk_distance":     None,
            "result_status":     "SKIPPED_NO_STOP_PRICE",
            "result_hash":       None,
            "result_matched_ref": None,
            "result_price_delta": None,
            "result_time_delta":  None,
        }
    stop_price = float(stop_price_raw)
    risk_distance = abs(entry_price - stop_price)
    result = guard.validate_signal(
        symbol=symbol,
        entry_timestamp=bar_time,
        direction=direction_int,
        entry_price=entry_price,
        risk_distance=risk_distance,
    )
    return {
        "event_id":          event.get("event_id"),
        "strategy_id":       event.get("strategy_id"),
        "symbol":            symbol,
        "bar_time":          bar_time,
        "direction":         event["direction"],
        "entry_price":       entry_price,
        "stop_price":        stop_price,
        "risk_distance":     risk_distance,
        "result_status":     result.status,
        "result_hash":       result.hash,
        "result_matched_ref": result.matched_ref or None,
        "result_price_delta": result.price_delta if result.status == "SOFT_MATCH" else None,
        "result_time_delta":  result.time_delta  if result.status == "SOFT_MATCH" else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", default=DEFAULT_PROFILE,
                   help="capital profile to load from each vault (default: RAW_MIN_LOT_V1)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="output JSONL path (default: outputs/shadow_journal_strategy_guard_reference.jsonl)")
    p.add_argument("--limit", type=int, default=None,
                   help="cap events for dev runs (default: all)")
    args = p.parse_args(argv)

    if not SHADOW_JOURNAL_FILE.is_file():
        print(f"[reference]  FATAL  journal missing at {SHADOW_JOURNAL_FILE}", file=sys.stderr)
        return 2

    # Pass 1: collect unique base strategy_ids in the journal.
    unique_base: dict[str, str] = {}  # base_sid -> example raw_sid for logging
    with SHADOW_JOURNAL_FILE.open(encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "SIGNAL":
                continue
            sid = ev.get("strategy_id", "")
            sym = ev.get("symbol", "")
            base = _base_strategy_id(sid, sym)
            unique_base.setdefault(base, sid)

    print(f"[reference]  found {len(unique_base)} distinct base strategies in journal", file=sys.stderr)

    # Pass 2: load StrategyGuard per base strategy (cached).
    cache = _build_guard_cache(sorted(unique_base.keys()), profile=args.profile)

    # Pass 3: classify every SIGNAL event, stream to output JSONL.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    stats: dict[str, int] = {}
    n_in = n_out = n_skipped_no_guard = 0
    with SHADOW_JOURNAL_FILE.open(encoding="utf-8") as f_in, args.out.open("w", encoding="utf-8") as f_out:
        for line in f_in:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "SIGNAL":
                continue
            n_in += 1
            sid = ev.get("strategy_id", "")
            sym = ev.get("symbol", "")
            base = _base_strategy_id(sid, sym)
            guard = cache.get(base)
            if guard is None:
                n_skipped_no_guard += 1
                row = {
                    "event_id":      ev.get("event_id"),
                    "strategy_id":   sid,
                    "symbol":        sym,
                    "bar_time":      ev.get("bar_time"),
                    "direction":     ev.get("direction"),
                    "result_status": "SKIPPED_NO_VAULT",
                    "result_hash":   None,
                }
            else:
                row = _classify_event(guard, ev)
            stats[row["result_status"]] = stats.get(row["result_status"], 0) + 1
            f_out.write(json.dumps(row, sort_keys=True) + "\n")
            n_out += 1
            if args.limit is not None and n_out >= args.limit:
                break

    print(f"\n[reference]  events read:   {n_in}", file=sys.stderr)
    print(f"[reference]  events written: {n_out}", file=sys.stderr)
    print(f"[reference]  skipped (no vault): {n_skipped_no_guard}", file=sys.stderr)
    print(f"[reference]  classification distribution:", file=sys.stderr)
    for status, count in sorted(stats.items(), key=lambda kv: -kv[1]):
        pct = (count / n_out * 100.0) if n_out else 0.0
        print(f"             {status:<24} {count:>6}  ({pct:5.1f}%)", file=sys.stderr)
    print(f"[reference]  wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
