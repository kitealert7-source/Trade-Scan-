"""
refresh_freshness_index.py — Regenerate freshness_index.json from Trade_Scan.

Wraps DATA_INGRESS/engines/ops/build_freshness_index.py so an interactive session
(or any non-scheduled context) can rebuild the freshness index without waiting
for the next AntiGravity_Daily_Preflight scheduled run.

Why this exists:
  MASTER_DATA carries a DENY-enumerate ACL (post-2026-05-07 service-account
  architecture). The legacy builder used `glob('*_MASTER')` which silently
  returns 0 items under that ACL, producing a freshness_index.json with only
  NEWS_CALENDAR. The fix is symbol-universe mode: probe each
  <sym>_<broker>_MASTER subdirectory directly, which is permitted by the ACL.

Usage:
  python tools/refresh_freshness_index.py             # canonical universe
  python tools/refresh_freshness_index.py --check     # report only, don't write
  python tools/refresh_freshness_index.py --universe <path>   # override

Exit codes:
  0  index written (or --check produced a report)
  1  builder error (missing data_root, unreadable universe, etc.)
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

# Worktree-safe path resolution — never compute siblings inline.
_TOOLS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TOOLS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.path_authority import (  # noqa: E402
    ANTI_GRAVITY_DATA_ROOT,
    DATA_INGRESS,
    FRESHNESS_INDEX,
)


def _load_builder_module():
    """Import build_freshness_index.py from DATA_INGRESS without polluting sys.path.

    The builder is a sibling-repo script; we load it by file path so the
    Trade_Scan import graph stays self-contained.
    """
    builder_path = DATA_INGRESS / "engines" / "ops" / "build_freshness_index.py"
    if not builder_path.exists():
        print(f"[ERROR] build_freshness_index.py not found at {builder_path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(
        "build_freshness_index", builder_path
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe", default=None,
        help="Path to symbol_universe.json (defaults to DATA_INGRESS/config/symbol_universe.json).",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Build the index and print a summary, but do not write to disk.",
    )
    args = parser.parse_args()

    builder = _load_builder_module()

    universe_path = (
        Path(args.universe) if args.universe
        else DATA_INGRESS / "config" / "symbol_universe.json"
    )
    if not universe_path.exists():
        print(f"[ERROR] symbol_universe.json not found at {universe_path}")
        print(f"        Maintain it per the comment block inside the file, or pass --universe.")
        return 1

    symbols = builder._load_symbol_universe(universe_path)
    master_data = ANTI_GRAVITY_DATA_ROOT / "MASTER_DATA"

    print(f"[refresh] DATA_INGRESS:   {DATA_INGRESS}")
    print(f"[refresh] MASTER_DATA:    {master_data}")
    print(f"[refresh] Universe:       {universe_path.name} ({len(symbols)} symbols)")
    print(f"[refresh] Write target:   {FRESHNESS_INDEX}")

    index = builder.build_index(data_root=master_data, symbols=symbols)
    if "error" in index:
        print(f"[ERROR] {index['error']}")
        return 1

    entries = index.get("entries", {})
    errors = index.get("errors", [])
    buffer = index.get("buffer_days", 3)
    stale = [k for k, v in entries.items() if v.get("days_behind", 0) > buffer]

    print(f"[refresh] Entries: {len(entries)} | Stale (>{buffer}d): {len(stale)} | "
          f"Errors: {len(errors)}")

    if errors:
        print(f"[refresh] Errors:")
        for e in errors[:10]:
            print(f"  - {e}")

    if stale:
        print(f"[refresh] Stale entries (worst first):")
        for k in sorted(stale, key=lambda k: -entries[k]["days_behind"])[:10]:
            v = entries[k]
            print(f"  - {k:<32} last: {v['latest_date']}  {v['days_behind']}d behind")

    if args.check:
        print(f"[refresh] --check: not writing.")
        return 0

    # Write to canonical path_authority location (MASTER_DATA/freshness_index.json).
    out = builder.write_index(index, data_root=master_data)
    print(f"[refresh] Wrote index -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
