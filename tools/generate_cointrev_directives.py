"""generate_cointrev_directives.py — C4 fan-out generator.

Enumerates all pair-pairs that have >=1 qualified day in the test window
and emits 2 directives per pair (SHORT-spread + LONG-spread variants),
writing them to backtest_directives/INBOX/ and updating
governance/namespace/sweep_registry.yaml.

Per the path-C plan:
  * Universe = pair-pairs with >=1 qualified day in [start_date, end_date].
    Pairs that never qualified contribute zero info, so excluded.
  * Two variants per pair:
      SHORT-spread: legs = [long A, short B], watch z >= +entry_z
      LONG-spread:  legs = [short A, long B], watch z <= -entry_z
  * Sweep numbering: pair N (1-indexed alphabetically) gets sweeps
      S(2N-1) = short, S(2N) = long
  * idea_id = 91 (already registered)
  * recycle_rule = COINTREV_meanrev@1
  * All other params match the C3c hand-crafted directive

CLI:
    python tools/generate_cointrev_directives.py            # writes 40 directives
    python tools/generate_cointrev_directives.py --dry-run  # list only
    python tools/generate_cointrev_directives.py --start 2024-05-20 --end 2026-05-20
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from indicators.stats import cointegration_state as cs
from tools.factors.fx_correlation_matrix import _load_native_closes


INBOX = PROJECT_ROOT / "backtest_directives" / "INBOX"
SWEEP_REGISTRY = PROJECT_ROOT / "governance" / "namespace" / "sweep_registry.yaml"

IDEA_ID = "91"
FAMILY = "PORT"
TIMEFRAME = "15M"
MODEL = "COINTREV"
VARIANT = "V1"
PARENT = "P00"

# Universe filter (v1.1 cohort — drops directional / collinear pairs)
DEFAULT_MIN_BETA = 0.0      # β > 0  : positively cointegrated (true spread)
DEFAULT_MIN_CORR = 0.10     # corr > +0.10 : confirms positive co-movement
DEFAULT_MAX_CORR = 0.85     # corr < +0.85 : excludes near-collinear pairs


def enumerate_universe(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[str, str, int]]:
    """List (pair_a, pair_b, n_qualified_days) for pairs with >=1 qualified
    day in the window, sorted alphabetically by (a, b)."""
    matrix = cs.load_history_matrix()
    matrix["date"] = pd.to_datetime(matrix["date"])
    win = matrix[(matrix.date >= start) & (matrix.date <= end)]
    counts = (
        win[win.qualified]
        .groupby(["pair_a", "pair_b"])
        .size()
    )
    return [(a, b, int(n)) for ((a, b), n) in sorted(counts.items())]


def annotate_with_beta_and_corr(
    pairs: list[tuple[str, str, int]],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict]:
    """For each (pair_a, pair_b), compute:
      - mean_beta_qualified: mean β across qualified days in window
      - corr_returns: daily-return Pearson correlation in window
    Returns enriched dicts; β/corr are NaN on data failure (kept, then filtered)."""
    matrix = cs.load_history_matrix()
    matrix["date"] = pd.to_datetime(matrix["date"])
    win = matrix[(matrix.date >= start) & (matrix.date <= end)]

    out = []
    for (a, b, q_days) in pairs:
        sub = win[(win.pair_a == a) & (win.pair_b == b)]
        beta_qual = sub[sub.qualified]["beta"].dropna()
        mean_beta = float(beta_qual.mean()) if len(beta_qual) else float("nan")

        try:
            ca = _load_native_closes(a, "1d", start, end)
            cb = _load_native_closes(b, "1d", start, end)
            aligned = pd.concat([ca, cb], axis=1, join="inner").dropna()
            aligned.columns = ["A", "B"]
            ra = aligned["A"].pct_change().dropna()
            rb = aligned["B"].pct_change().dropna()
            corr = float(ra.corr(rb))
        except Exception:
            corr = float("nan")

        out.append({
            "pair_a": a, "pair_b": b, "q_days": q_days,
            "mean_beta": mean_beta, "corr": corr,
        })
    return out


def apply_universe_filter(
    annotated: list[dict],
    *,
    min_beta: float, min_corr: float, max_corr: float,
) -> tuple[list[dict], list[dict]]:
    """Split annotated pairs into (kept, dropped) by β/corr filter.
    A pair is KEPT iff:
      mean_beta > min_beta AND min_corr < corr < max_corr
    NaN β or corr → dropped (we can't confirm the relationship)."""
    kept, dropped = [], []
    for d in annotated:
        mb, c = d["mean_beta"], d["corr"]
        reason = None
        if pd.isna(mb) or pd.isna(c):
            reason = "missing_beta_or_corr"
        elif mb <= min_beta:
            reason = f"beta<=0 (={mb:+.2f}) — directional, not spread"
        elif c <= min_corr:
            reason = f"corr<={min_corr} (={c:+.3f}) — too weak / negative"
        elif c >= max_corr:
            reason = f"corr>={max_corr} (={c:+.3f}) — too collinear"
        if reason is None:
            kept.append(d)
        else:
            d_out = dict(d); d_out["drop_reason"] = reason
            dropped.append(d_out)
    return kept, dropped


def render_directive_yaml(*, pair_a: str, pair_b: str, sweep: str,
                            direction_tag: str, start: str, end: str,
                            patch: str = PARENT,
                            entry_z: float = 2.0, exit_z: float = 1.0,
                            stop_z: float = 4.0,
                            time_stop_bars: int = 192) -> tuple[str, str]:
    """Render the directive YAML for one variant.

    direction_tag ∈ {"short", "long"} determines leg order + hypothesis_variant
    + descriptive text.
    patch  — patch suffix (P00 baseline / P01 tightened / etc.)
    entry_z, exit_z, stop_z, time_stop_bars — recycle rule params
    """
    if direction_tag == "short":
        leg0 = {"symbol": pair_a, "lot": 0.1, "direction": "long"}
        leg1 = {"symbol": pair_b, "lot": 0.1, "direction": "short"}
        watch_desc = f"watch z >= +{entry_z} (spread above mean, expect fall)"
    elif direction_tag == "long":
        leg0 = {"symbol": pair_a, "lot": 0.1, "direction": "short"}
        leg1 = {"symbol": pair_b, "lot": 0.1, "direction": "long"}
        watch_desc = f"watch z <= -{entry_z} (spread below mean, expect rise)"
    else:
        raise ValueError(direction_tag)

    name = f"{IDEA_ID}_{FAMILY}_{pair_a}{pair_b}_{TIMEFRAME}_{MODEL}_{sweep}_{VARIANT}_{patch}"
    basket_id = f"{pair_a}{pair_b}"

    yaml_text = f"""test:
  name: {name}
  family: {FAMILY}
  strategy: {name}
  version: 1
  signal_version: 1
  broker: OctaFx
  timeframe: 15m
  start_date: '{start}'
  end_date: '{end}'
  research_mode: true
  tuning_allowed: false
  parameter_mutation: false
  hypothesis_ref: COINTREV_V1
  hypothesis_variant: {direction_tag}_spread_uni_p00
  description: |
    COINTREV mean-reversion v1 — C4 fan-out (auto-generated, {patch}).

    Pair: {pair_a} / {pair_b}
    Direction: {direction_tag.upper()} spread ({watch_desc}).
    Entry: 15m |intra_z| crossing entry_z (={entry_z}) from below AND qualified_daily=True.
    Exit:  first of |intra_z| <= {exit_z} (winner) | DIRECTIONAL stop at signed
           ±{stop_z} (regime break) | {time_stop_bars} bars time stop.

    Universe filter (v1.1): mean β > 0 AND 0.1 < corr < 0.85 in window —
    drops directional / collinear pairs to keep COINTREV's mean-reversion
    edge clean. Negatively-correlated pairs route to H3_spread (pyramid).

    Sizing: 0.1 lots per leg (matches 90-series convention).
    Cointegration matrix: LATEST pointer at directive load time.
    Generator: tools/generate_cointrev_directives.py
symbols:
- {pair_a}
- {pair_b}
indicators:
- indicators.volatility.atr
- indicators.stats.cointegration_state
execution_rules:
  pyramiding: false
  entry_when_flat_only: true
  reset_on_exit: false
  entry_logic:
    type: cointegration_zscore_signal
  exit_logic:
    type: basket_recycle_rule
  stop_loss:
    type: atr_multiple
    atr_multiplier: 100000.0
  trailing_stop:
    enabled: false
  take_profit:
    enabled: false
order_placement:
  type: market
  execution_timing: next_bar_open
trade_management:
  direction: basket_mixed
  reentry:
    allowed: true
  session_reset: none
position_management:
  lots: 0.1
basket:
  basket_id: {basket_id}
  legs:
  - symbol: {leg0["symbol"]}
    lot: {leg0["lot"]}
    direction: {leg0["direction"]}
  - symbol: {leg1["symbol"]}
    lot: {leg1["lot"]}
    direction: {leg1["direction"]}
  initial_stake_usd: 1000.0
  harvest_threshold_usd: 1000000.0
  recycle_rule:
    name: COINTREV_meanrev
    version: 1
    params:
      entry_z: {entry_z}
      exit_z: {exit_z}
      stop_z: {stop_z}
      time_stop_bars: {time_stop_bars}
      initial_notional_usd: 1000.0
      intra_z_column: intra_z
      qualified_column: qualified_daily
"""
    return yaml_text, name


def render_appended_sweep_slots(
    pairs: list[dict],
    *,
    start_slot: int,
    patch: str,
) -> tuple[list[str], int]:
    """Render the slot lines (no header) to APPEND to an existing 91 block.

    Returns (lines, next_sweep_after). pairs is the filtered/annotated list.
    Slot numbering: pair N gets S(start_slot+2N-2) short, S(start_slot+2N-1) long.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    lines = []
    for n, d in enumerate(pairs, start=1):
        a, b = d["pair_a"], d["pair_b"]
        for direction_tag, slot_n in (
            ("short", start_slot + 2 * (n - 1)),
            ("long",  start_slot + 2 * (n - 1) + 1),
        ):
            sweep = f"S{slot_n:02d}"
            name = (
                f"{IDEA_ID}_{FAMILY}_{a}{b}_{TIMEFRAME}_{MODEL}_{sweep}_{VARIANT}_{patch}"
            )
            lines.extend([
                f"      {sweep}:",
                f"        directive_name: {name}",
                f"        signature_hash: '0000000000000000'",
                f"        signature_hash_full: '0000000000000000000000000000000000000000000000000000000000000000'",
                f"        reserved_at_utc: '{timestamp}'",
                f"        patches: {{}}",
            ])
    next_sweep_after = start_slot + 2 * len(pairs)
    return lines, next_sweep_after


def append_sweep_slots_to_91(
    file_path: Path, lines_to_append: list[str], new_next_sweep: int,
) -> None:
    """In the existing 91 block, append new slot lines just before any
    next top-level entry, AND update the `next_sweep:` field."""
    text = file_path.read_text(encoding="utf-8")
    marker = f"  '{IDEA_ID}':"
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError(
            f"sweep_registry.yaml missing '{IDEA_ID}' block — run baseline "
            f"P00 generation first.")

    # Replace `next_sweep:` line within the 91 block
    block_end = text.find("\n  '", idx + len(marker))  # next top-level idea
    if block_end < 0:
        block_end = len(text)
    block = text[idx:block_end]
    new_block = []
    for line in block.split("\n"):
        if line.strip().startswith("next_sweep:"):
            indent = line[:len(line) - len(line.lstrip())]
            new_block.append(f"{indent}next_sweep: {new_next_sweep}")
        else:
            new_block.append(line)
    rebuilt = "\n".join(new_block)

    # Strip trailing blank lines from the existing block, then append new slots
    rebuilt = rebuilt.rstrip("\n") + "\n" + "\n".join(lines_to_append) + "\n"

    new_text = text[:idx] + rebuilt
    if block_end < len(text):
        new_text += text[block_end:]
    file_path.write_text(new_text, encoding="utf-8")


def read_next_sweep_91(file_path: Path) -> int:
    """Read the current next_sweep value from the 91 block."""
    text = file_path.read_text(encoding="utf-8")
    marker = f"  '{IDEA_ID}':"
    idx = text.find(marker)
    if idx < 0:
        return 1
    for line in text[idx:].split("\n")[:5]:
        s = line.strip()
        if s.startswith("next_sweep:"):
            return int(s.split(":", 1)[1].strip())
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default="2024-05-20")
    p.add_argument("--end", default="2026-05-20")
    p.add_argument("--patch", default="P01",
                   help="patch suffix (P00 baseline / P01 filtered+tightened)")
    p.add_argument("--entry-z", type=float, default=2.7)
    p.add_argument("--exit-z",  type=float, default=1.0)
    p.add_argument("--stop-z",  type=float, default=3.5)
    p.add_argument("--time-stop-bars", type=int, default=192)
    p.add_argument("--filter", action="store_true", default=True,
                   help="apply β>0 + 0.1<corr<0.85 universe filter (default ON)")
    p.add_argument("--no-filter", dest="filter", action="store_false")
    p.add_argument("--min-beta", type=float, default=DEFAULT_MIN_BETA)
    p.add_argument("--min-corr", type=float, default=DEFAULT_MIN_CORR)
    p.add_argument("--max-corr", type=float, default=DEFAULT_MAX_CORR)
    p.add_argument("--start-slot", type=int, default=None,
                   help="first sweep slot number (default: read next_sweep from registry)")
    p.add_argument("--dry-run", action="store_true",
                   help="list pairs + directive names; don't write files")
    args = p.parse_args(argv)

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    pairs = enumerate_universe(start, end)
    print(f"Window: {start.date()} -> {end.date()}")
    print(f"Qualifying pairs (cointegration only): {len(pairs)}")
    print(f"Patch level: {args.patch}")
    print(f"Params: entry_z={args.entry_z} exit_z={args.exit_z} "
          f"stop_z={args.stop_z} time_stop_bars={args.time_stop_bars}")
    print()

    # Annotate with β + corr → apply universe filter
    print("Computing per-pair β + correlation in window... (this may take a moment)")
    annotated = annotate_with_beta_and_corr(pairs, start, end)
    if args.filter:
        kept, dropped = apply_universe_filter(
            annotated,
            min_beta=args.min_beta,
            min_corr=args.min_corr,
            max_corr=args.max_corr,
        )
    else:
        kept, dropped = annotated, []

    print()
    print(f"=== UNIVERSE AUDIT ({len(annotated)} cointegrated -> {len(kept)} kept) ===")
    print(f"{'pair':<22}  {'q_days':>7}  {'mean B':>10}  {'corr':>8}  {'status'}")
    print("-" * 80)
    drop_reasons = {(d["pair_a"], d["pair_b"]): d["drop_reason"] for d in dropped}
    for d in annotated:
        a, b = d["pair_a"], d["pair_b"]
        mb = d["mean_beta"]; c = d["corr"]
        mb_s = f"{mb:+10.4f}" if pd.notna(mb) else "       n/a"
        c_s  = f"{c:+8.3f}"  if pd.notna(c)  else "    n/a"
        if (a, b) in drop_reasons:
            status = f"  DROP -- {drop_reasons[(a, b)]}"
        else:
            status = "  KEPT"
        print(f"{a}/{b:<14}  {d['q_days']:>7}  {mb_s}  {c_s}  {status}")
    print()

    start_slot = args.start_slot if args.start_slot is not None else read_next_sweep_91(SWEEP_REGISTRY)
    print(f"Generating {len(kept) * 2} directives starting at S{start_slot:02d}")
    print()

    rendered: list[tuple[Path, str]] = []
    for n, d in enumerate(kept, start=1):
        a, b = d["pair_a"], d["pair_b"]
        for direction_tag, slot_n in (
            ("short", start_slot + 2 * (n - 1)),
            ("long",  start_slot + 2 * (n - 1) + 1),
        ):
            sweep = f"S{slot_n:02d}"
            yaml_text, name = render_directive_yaml(
                pair_a=a, pair_b=b, sweep=sweep,
                direction_tag=direction_tag,
                start=args.start, end=args.end,
                patch=args.patch,
                entry_z=args.entry_z, exit_z=args.exit_z, stop_z=args.stop_z,
                time_stop_bars=args.time_stop_bars,
            )
            path = INBOX / f"{name}.txt"
            rendered.append((path, yaml_text))
            print(f"  {sweep:>4}  {direction_tag:5s}  {name}")

    print()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"Would write {len(rendered)} directives to {INBOX}/")
        print(f"Would append {len(rendered)} sweep slots to '91' section")
        return 0

    INBOX.mkdir(parents=True, exist_ok=True)
    n_written = 0
    n_existing = 0
    for path, content in rendered:
        if path.exists():
            n_existing += 1
        else:
            path.write_text(content, encoding="utf-8")
            n_written += 1
    print(f"Wrote {n_written} new directives ({n_existing} already existed in INBOX)")

    slot_lines, next_after = render_appended_sweep_slots(
        kept, start_slot=start_slot, patch=args.patch,
    )
    append_sweep_slots_to_91(SWEEP_REGISTRY, slot_lines, next_after)
    print(f"Appended {len(kept)*2} sweep slots to '91' section "
          f"(S{start_slot:02d}–S{next_after-1:02d}); next_sweep := {next_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
