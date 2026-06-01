"""backfill_run_directives.py — drop the source directive into existing folders.

Forward paths now co-locate the directive at write time:
  - runs/<run_id>/directive.txt      (run_stage1 + run_pipeline basket dispatch)
  - strategies/<id>/directive.txt    (strategy_provisioner)

This one-shot backfills the EXISTING folders. For each target folder it
resolves the directive_id (run_state.json for runs; the folder name for
strategies) and recovers the directive via the standard sources
(live backtest_directives/ -> TradeScan_State/quarantine/ -> git live-paths
-> git ANY path), then writes directive.txt if absent.

Reports actual FILLS (by source) and FAILS (with reason). Dry-run by default.

    python tools/backfill_run_directives.py --target runs --apply
    python tools/backfill_run_directives.py --target strategies --apply
    python tools/backfill_run_directives.py --target strategies          # preview
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE  # noqa: E402
from tools.recover_admitted_directive import recover_directive  # noqa: E402
from tools.run_directive_snapshot import DIRECTIVE_SNAPSHOT_NAME  # noqa: E402

RUNS_DIR = TRADE_SCAN_STATE / "runs"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"


def _git(args: list[str]) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=str(PROJECT_ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def recover_anypath_git(directive_id: str) -> str | None:
    """4th source: a directive committed under a NON-live path (archive/,
    promoted/, completed_run/, …) that recover_directive's live-path git search
    misses. Returns the newest such blob's content, or None."""
    sha = _git(["log", "--all", "-n1", "--format=%H", "--",
                f":(glob)backtest_directives/**/{directive_id}.txt"]).strip().splitlines()
    if not sha:
        return None
    sha = sha[0]
    tree = _git(["ls-tree", "-r", "--name-only", sha, "--", "backtest_directives/"])
    path = next((l for l in tree.splitlines() if l.endswith(f"/{directive_id}.txt")), None)
    if not path:
        return None
    content = _git(["show", f"{sha}:{path}"])
    return content if content and content.strip() else None


def _items_for_target(target: str):
    """Yield (folder, directive_id) pairs for the chosen target."""
    if target == "runs":
        if not RUNS_DIR.is_dir():
            return
        for d in RUNS_DIR.iterdir():
            if not (d.is_dir() and (d / "run_state.json").is_file()):
                continue
            try:
                did = json.loads((d / "run_state.json").read_text(encoding="utf-8")).get("directive_id")
            except Exception:
                did = None
            yield d, did
    else:  # strategies — folder name IS the directive id (per the namespace convention)
        if not STRATEGIES_DIR.is_dir():
            return
        for d in sorted(STRATEGIES_DIR.iterdir()):
            if d.is_dir() and (d / "strategy.py").is_file():
                yield d, d.name


def _resolve_one(directive_id: str):
    rec = recover_directive(directive_id)
    if rec and rec.get("content"):
        return rec["content"], rec.get("source_type")
    content = recover_anypath_git(directive_id)
    return (content, "git_anypath") if content else (None, None)


def _resolve_directive(directive_id: str):
    """Return (content, source) for a directive_id, or (None, None).

    Multi-symbol fallback: a per-symbol strategy folder (e.g. ..._P01_GBPUSD)
    is provisioned from a BASE directive (..._P01). If the per-symbol id is
    unrecoverable, retry with the base."""
    content, source = _resolve_one(directive_id)
    if content:
        return content, source
    m = re.match(r"^(.*_P\d{2})_[A-Z0-9]{4,7}$", directive_id)
    if m:
        content, source = _resolve_one(m.group(1))
        if content:
            return content, f"{source}_base"
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", choices=["runs", "strategies"], default="runs")
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="cap folders processed (0 = all)")
    args = ap.parse_args()

    items = list(_items_for_target(args.target))
    if args.limit:
        items = items[: args.limit]

    total = len(items)
    already = 0
    filled = Counter()
    fails = Counter()
    fail_samples: list[str] = []

    print(f"[backfill] target={args.target}  scanning {total} folder(s)  "
          f"({'APPLY' if args.apply else 'DRY-RUN'})")

    for i, (folder, directive_id) in enumerate(items, 1):
        if i % 250 == 0:
            print(f"  ... {i}/{total}")
        dest = folder / DIRECTIVE_SNAPSHOT_NAME
        if dest.exists():
            already += 1
            continue
        if not directive_id:
            fails["no_directive_id"] += 1
            continue
        content, source = _resolve_directive(directive_id)
        if not content:
            fails["directive_unrecoverable"] += 1
            if len(fail_samples) < 12:
                fail_samples.append(f"{folder.name[:32]}  {directive_id}")
            continue
        if args.apply:
            try:
                dest.write_bytes(content.encode("utf-8"))
            except Exception as exc:
                fails["write_failed"] += 1
                if len(fail_samples) < 12:
                    fail_samples.append(f"{folder.name[:24]}  write: {exc}")
                continue
        filled[source or "unknown"] += 1

    print("\n=== BACKFILL REPORT ===")
    print(f"  target                : {args.target}")
    print(f"  total folders         : {total}")
    print(f"  already had directive : {already}")
    print(f"  FILLED                : {sum(filled.values())}  {dict(filled)}")
    print(f"  FAILED                : {sum(fails.values())}  {dict(fails)}")
    if fail_samples:
        print("  fail samples (folder / directive_id):")
        for s in fail_samples:
            print(f"    - {s}")
    if not args.apply and (sum(filled.values()) or sum(fails.values())):
        print("\n  (dry-run — re-run with --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
