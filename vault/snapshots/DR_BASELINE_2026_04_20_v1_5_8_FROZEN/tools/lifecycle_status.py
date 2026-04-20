"""
lifecycle_status.py -- Report lifecycle state counts from portfolio.yaml.

Usage:
    python tools/lifecycle_status.py
"""

import sys
from collections import Counter
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"


def main() -> None:
    if not PORTFOLIO_YAML.exists():
        print(f"[ABORT] portfolio.yaml not found: {PORTFOLIO_YAML}")
        sys.exit(1)

    with open(PORTFOLIO_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    strategies = (data.get("portfolio") or {}).get("strategies") or []
    counts: Counter = Counter()
    entries_by_state: dict[str, list[str]] = {}

    for s in strategies:
        lc = s.get("lifecycle", "UNTAGGED")
        counts[lc] += 1
        entries_by_state.setdefault(lc, []).append(s.get("id", "?"))

    # Fixed display order
    order = ["LEGACY", "BURN_IN", "WAITING", "LIVE", "DISABLED", "UNTAGGED"]
    # Add any states not in the fixed order
    for state in sorted(counts.keys()):
        if state not in order:
            order.append(state)

    total = sum(counts.values())
    print(f"\nLifecycle Status  ({total} entries in portfolio.yaml)")
    print("=" * 50)
    for state in order:
        n = counts.get(state, 0)
        if n > 0:
            print(f"  {state:<12} {n:>3}")
    print("=" * 50)

    # Detail view: show IDs grouped by state
    print()
    for state in order:
        ids = entries_by_state.get(state, [])
        if not ids:
            continue
        # Collapse multi-symbol entries to base ID
        bases = []
        seen = set()
        for sid in ids:
            # Heuristic: strip trailing _SYMBOL for multi-symbol entries
            # A base ID matches if multiple IDs share the same prefix
            bases.append(sid)
        # Deduplicate: group by base strategy
        base_groups: dict[str, int] = {}
        for sid in ids:
            # Find shortest prefix that's shared
            base_groups[sid] = 1
        # Simple: just list unique base strategies
        base_ids = set()
        for sid in ids:
            # Check if this is a per-symbol entry by seeing if removing last _TOKEN
            # yields another entry's prefix
            parts = sid.rsplit("_", 1)
            if len(parts) == 2 and any(
                other_id.startswith(parts[0] + "_") and other_id != sid
                for other_id in ids
            ):
                base_ids.add(parts[0])
            else:
                base_ids.add(sid)

        print(f"  {state} ({len(ids)} entries, {len(base_ids)} strategies):")
        for bid in sorted(base_ids):
            sym_count = sum(1 for sid in ids if sid == bid or sid.startswith(bid + "_"))
            if sym_count > 1:
                print(f"    {bid}  ({sym_count} symbols)")
            else:
                print(f"    {bid}")
        print()


if __name__ == "__main__":
    main()
