"""summarize_recycle_events.py — population summaries from rule telemetry.

Consumes the governed Research Artifact — Population Evidence
(`raw/recycle_events.jsonl`; TELEMETRY_GOVERNANCE_PROPOSAL_2026_06_12.md) and
prints compact per-event-type summaries so hypothesis evaluation never requires
hand-rolled JSONL scans (the HF/HL/LM arc needed three).

Usage:
    python tools/summarize_recycle_events.py --series GP_ZCRS_CXN1_Z25_LM20
    python tools/summarize_recycle_events.py --directive 90_PORT_..._LM20__E260127
    python tools/summarize_recycle_events.py --run-dir <backtest capsule>
    ... [--event-type MOVE_BLOCK] [--by-class] [--csv out.csv]

Selection semantics:
  --series uses ANCHORED matching on capsule folder names (tag immediately
  followed by `__E`) — same discipline as resolve_baseline._series_cohort_rows;
  bare-substring matching contaminates cohorts (Z25 would catch Z25_HF55).

Output per event_type: count, runs-covered vs runs-with-events, numeric payload
fields -> p05/p25/p50/p75/p95, boolean fields -> share true, short-string
fields -> top category shares. `--by-class` splits by pair class (symbols read
from each capsule's DIRECTIVE_SOURCE.txt). `--csv` writes tidy per-event rows
(identity + flattened payload) for downstream joins, e.g. detector-overlap
recipes on (directive_id, timestamp).

Contracts: READ-ONLY; absent files = zero coverage for that run (reported,
never an error — historical runs without telemetry are valid); v0 and v1
artifacts both supported via `load_recycle_events` (v0 rows are up-converted
in memory, never on disk). Non-goals: no plotting, no DB writes, no built-in
cross-cohort joins.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np

# Repo-root bootstrap so direct invocation works (mirrors resolve_baseline.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Shared reader (schema negotiation lives HERE, once)
# ---------------------------------------------------------------------------


def load_recycle_events(path: Path | str) -> list[dict]:
    """Read one recycle_events.jsonl into a list of v1-shaped dicts.

    v1 rows (schema_version present) pass through. v0 rows (the 2026-06-12
    pre-envelope inline format) are up-converted IN MEMORY: event_type from
    `action`, timestamp from `bar_ts`, payload = remaining keys; identity
    fields left None (ambient in the capsule path for v0). The on-disk
    artifact is never modified."""
    out: list[dict] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "schema_version" in row:
                out.append(row)
                continue
            row = dict(row)
            etype = row.pop("action", "UNKNOWN")
            ts = row.pop("bar_ts", None)
            out.append({
                "schema_version": 0,
                "event_type":     str(etype),
                "timestamp":      str(ts) if ts is not None else None,
                "rule_name":      None,
                "rule_version":   None,
                "run_id":         None,
                "directive_id":   None,
                "basket_id":      None,
                "payload":        row,
            })
    return out


# ---------------------------------------------------------------------------
# Capsule selection
# ---------------------------------------------------------------------------


def _backtests_dir() -> Path:
    from config.path_authority import TRADE_SCAN_STATE
    return Path(TRADE_SCAN_STATE) / "backtests"


def _select_capsules(series: str | None, directive: str | None,
                     run_dir: str | None) -> list[Path]:
    if run_dir:
        return [Path(run_dir)]
    base = _backtests_dir()
    if directive:
        return sorted(Path(p) for p in glob.glob(str(base / (directive + "_*"))))
    # --series: ANCHORED match (tag immediately followed by __E in the folder name).
    pat = re.compile(re.escape(series) + r"__E")
    return sorted(p for p in base.iterdir()
                  if p.is_dir() and pat.search(p.name))


def _pair_class(capsule: Path) -> str:
    """Pair class from the capsule's DIRECTIVE_SOURCE.txt symbols (works for
    v0 artifacts that carry no identity). Unknown -> '?'."""
    src = capsule / "DIRECTIVE_SOURCE.txt"
    if not src.exists():
        return "?"
    try:
        import yaml
        d = yaml.safe_load(src.read_text(encoding="utf-8"))
        syms = d.get("symbols") or []
        if len(syms) != 2:
            return "?"
        from tools.portfolio.cointegration_view import _classify_pair
        return _classify_pair(str(syms[0]), str(syms[1]))
    except Exception:  # noqa: BLE001  (classification is best-effort)
        return "?"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_QUANTS = (0.05, 0.25, 0.50, 0.75, 0.95)


def _summarize_payload_field(values: list) -> str | None:
    """One-line summary for a payload field across events of one type."""
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v]
    bools = [v for v in values if isinstance(v, bool)]
    strs = [v for v in values if isinstance(v, str)]
    nulls = sum(1 for v in values if v is None)
    if nums and len(nums) >= max(len(bools), len(strs)):
        a = np.array(nums, dtype=float)
        q = "/".join(f"{np.quantile(a, x):.3g}" for x in _QUANTS)
        extra = f"  (null: {nulls})" if nulls else ""
        return f"p05/p25/p50/p75/p95 = {q}{extra}"
    if bools:
        return f"true-share = {100.0 * sum(bools) / len(bools):.1f}%  (n={len(bools)})"
    if strs:
        from collections import Counter
        top = Counter(strs).most_common(5)
        return "  ".join(f"{k}:{100.0 * n / len(strs):.0f}%" for k, n in top)
    return None


def summarize(capsules: list[Path], *, event_type: str | None = None,
              by_class: bool = False) -> str:
    groups: dict[str, list[tuple[Path, list[dict]]]] = {}
    runs_with_events = 0
    for cap in capsules:
        evs = load_recycle_events(cap / "raw" / "recycle_events.jsonl")
        if evs:
            runs_with_events += 1
        key = _pair_class(cap) if by_class else "ALL"
        groups.setdefault(key, []).append((cap, evs))

    lines = [f"capsules: {len(capsules)}   runs-with-events: {runs_with_events}"]
    for key in sorted(groups):
        evs_flat = [e for _, evs in groups[key] for e in evs
                    if event_type is None or e["event_type"] == event_type]
        if by_class:
            lines.append(f"\n=== class {key} ({len(groups[key])} runs) ===")
        by_type: dict[str, list[dict]] = {}
        for e in evs_flat:
            by_type.setdefault(e["event_type"], []).append(e)
        for etype in sorted(by_type):
            rows = by_type[etype]
            lines.append(f"{etype}: count={len(rows)}")
            fields: dict[str, list] = {}
            for r in rows:
                for k, v in (r.get("payload") or {}).items():
                    fields.setdefault(k, []).append(v)
            for k in sorted(fields):
                s = _summarize_payload_field(fields[k])
                if s:
                    lines.append(f"    {k:14} {s}")
    return "\n".join(lines)


def write_csv(capsules: list[Path], out_path: str,
              event_type: str | None = None) -> int:
    """Tidy per-event rows: identity + flattened payload (payload keys become
    columns; union across events). Returns row count."""
    rows = []
    for cap in capsules:
        for e in load_recycle_events(cap / "raw" / "recycle_events.jsonl"):
            if event_type is not None and e["event_type"] != event_type:
                continue
            flat = {k: e.get(k) for k in
                    ("schema_version", "event_type", "timestamp", "rule_name",
                     "rule_version", "run_id", "directive_id", "basket_id")}
            flat["capsule"] = cap.name
            for k, v in (e.get("payload") or {}).items():
                flat[f"payload.{k}"] = v
            rows.append(flat)
    if not rows:
        return 0
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Summarize rule telemetry (recycle_events.jsonl) for a cohort / directive / capsule.")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--series", help="cohort series tag (anchored match, e.g. GP_ZCRS_CXN1_Z25_LM20)")
    sel.add_argument("--directive", help="single directive id")
    sel.add_argument("--run-dir", help="path to one backtest capsule")
    ap.add_argument("--event-type", default=None, help="filter to one event type")
    ap.add_argument("--by-class", action="store_true", help="split by pair class")
    ap.add_argument("--csv", default=None, help="write tidy per-event rows to this path")
    args = ap.parse_args()

    capsules = _select_capsules(args.series, args.directive, args.run_dir)
    if not capsules:
        print("no capsules matched")
        return 1
    print(summarize(capsules, event_type=args.event_type, by_class=args.by_class))
    if args.csv:
        n = write_csv(capsules, args.csv, event_type=args.event_type)
        print(f"\ncsv: {n} rows -> {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
