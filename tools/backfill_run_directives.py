"""backfill_run_directives.py — drop the source directive into existing run folders.

Forward-path runs now co-locate their directive (runs/<run_id>/directive.txt)
at snapshot time (run_stage1 + run_pipeline basket dispatch). This one-shot
backfills the EXISTING run folders: for each run it reads the directive_id from
run_state.json and resolves the directive via the standard 3-source recovery
(live backtest_directives/ -> TradeScan_State/quarantine/ -> git history), then
writes runs/<run_id>/directive.txt if absent.

Reports actual FILLS (by source) and FAILS (with reason). Dry-run by default.

    python tools/backfill_run_directives.py             # preview
    python tools/backfill_run_directives.py --apply     # write
    python tools/backfill_run_directives.py --apply --limit 50
"""
from __future__ import annotations

import argparse
import json
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


def _run_dirs():
    if not RUNS_DIR.is_dir():
        return []
    return [d for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "run_state.json").is_file()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="cap runs processed (0 = all)")
    args = ap.parse_args()

    runs = _run_dirs()
    if args.limit:
        runs = runs[: args.limit]

    total = len(runs)
    already = 0
    filled = Counter()        # source_type -> count
    fails = Counter()         # reason -> count
    fail_samples: list[str] = []

    print(f"[backfill] scanning {total} run folder(s) under {RUNS_DIR}  "
          f"({'APPLY' if args.apply else 'DRY-RUN'})")

    for i, run_dir in enumerate(runs, 1):
        if i % 250 == 0:
            print(f"  ... {i}/{total}")
        dest = run_dir / DIRECTIVE_SNAPSHOT_NAME
        if dest.exists():
            already += 1
            continue
        try:
            state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        except Exception:
            fails["unreadable_run_state"] += 1
            continue
        directive_id = state.get("directive_id")
        if not directive_id:
            fails["no_directive_id_in_state"] += 1
            continue

        rec = recover_directive(directive_id)
        content = rec.get("content") if rec else None
        source = rec.get("source_type") if rec else None
        if not content:                                   # 4th source: any git path
            content = recover_anypath_git(directive_id)
            source = "git_anypath" if content else None
        if not content:
            fails["directive_unrecoverable"] += 1
            if len(fail_samples) < 12:
                fail_samples.append(f"{run_dir.name[:12]}  {directive_id}")
            continue

        if args.apply:
            try:
                dest.write_bytes(content.encode("utf-8"))
            except Exception as exc:
                fails["write_failed"] += 1
                if len(fail_samples) < 12:
                    fail_samples.append(f"{run_dir.name[:12]}  write: {exc}")
                continue
        filled[source or "unknown"] += 1

    print("\n=== BACKFILL REPORT ===")
    print(f"  total run folders     : {total}")
    print(f"  already had directive : {already}")
    print(f"  FILLED                : {sum(filled.values())}"
          f"  {dict(filled)}")
    print(f"  FAILED                : {sum(fails.values())}  {dict(fails)}")
    if fail_samples:
        print("  fail samples (run / directive_id):")
        for s in fail_samples:
            print(f"    - {s}")
    if not args.apply and (sum(filled.values()) or sum(fails.values())):
        print("\n  (dry-run — re-run with --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
