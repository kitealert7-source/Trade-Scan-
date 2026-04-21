"""Regression harness CLI.

Usage:
    python -m tools.regression.cli                      # run all, print summary
    python -m tools.regression.cli --layer capital      # run scenarios matching name
    python -m tools.regression.cli --update-baseline    # DRY RUN: show what would change
    python -m tools.regression.cli --update-baseline --force   # actually overwrite

Exit codes: 0 = all pass, 1 = regression detected (or update dry-run complete).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.regression.runner import (
    _BASELINES_ROOT,
    _TMP_ROOT,
    print_summary,
    run_all,
)

_REBASELINE_LOG = _BASELINES_ROOT / "REBASELINE_LOG.md"


def main() -> int:
    ap = argparse.ArgumentParser(description="Regression harness")
    ap.add_argument("--layer", default=None,
                    help="Filter scenarios by substring (e.g., 'capital', 'promote')")
    ap.add_argument("--update-baseline", action="store_true",
                    help="Preview (or with --force: write) golden updates from latest outputs")
    ap.add_argument("--force", action="store_true",
                    help="Required with --update-baseline to actually overwrite goldens")
    args = ap.parse_args()

    results = run_all(layer_filter=args.layer)
    if not results:
        print("[ERROR] no scenarios ran")
        return 1

    all_passed = print_summary(results)

    if args.update_baseline:
        _handle_rebaseline(force=args.force, all_passed=all_passed)
        # After rebaseline, always exit 0 — operator reviewed diffs and
        # explicitly asked to accept the new goldens.
        return 0 if args.force else 1

    return 0 if all_passed else 1


def _handle_rebaseline(*, force: bool, all_passed: bool) -> None:
    """Stage or apply baseline overwrites from tmp/ into baselines/.

    Dry-run mode (no --force): just prints which artifacts would be replaced.
    Applied mode (--force):   actually copies + appends a line to REBASELINE_LOG.
    """
    # Only per-scenario tmp dirs with a `golden_candidate/` subtree are eligible.
    # Scenarios that want their outputs usable as goldens MUST write them to
    # `<tmp>/golden_candidate/<relative-path>` so the operator sees exactly
    # what will be written.
    candidates: list[tuple[Path, Path]] = []  # (src, dst)
    for scn_dir in sorted(p for p in _TMP_ROOT.iterdir() if p.is_dir()):
        src_root = scn_dir / "golden_candidate"
        if not src_root.exists():
            continue
        dst_root = _BASELINES_ROOT / scn_dir.name / "golden"
        for src_file in src_root.rglob("*"):
            if src_file.is_file():
                rel = src_file.relative_to(src_root)
                candidates.append((src_file, dst_root / rel))

    if not candidates:
        print("\n[REBASELINE] no candidate outputs found "
              "(scenarios must emit tmp/<name>/golden_candidate/ to opt in)")
        return

    print(f"\n[REBASELINE] {len(candidates)} artifact(s) would be updated:")
    for src, dst in candidates:
        status = "NEW" if not dst.exists() else "UPDATE"
        print(f"  [{status}] {dst.relative_to(_BASELINES_ROOT)}")

    if not force:
        print("\n[REBASELINE] DRY RUN — no files written.")
        print("             Re-run with --update-baseline --force to apply.")
        if not all_passed:
            print("             (Some scenarios failed — review DIFF files before applying.)")
        return

    for src, dst in candidates:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    _append_rebaseline_log(candidates, all_passed=all_passed)
    print(f"\n[REBASELINE] {len(candidates)} file(s) overwritten. Log appended.")


def _append_rebaseline_log(candidates, *, all_passed: bool) -> None:
    _REBASELINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    scenarios = sorted({src.parents[1].name for src, _ in candidates})
    line = (
        f"- {ts} | scenarios: {', '.join(scenarios)} | "
        f"files: {len(candidates)} | pre_state: {'GREEN' if all_passed else 'HAD_FAILURES'}\n"
    )
    header_needed = not _REBASELINE_LOG.exists()
    with _REBASELINE_LOG.open("a", encoding="utf-8") as fh:
        if header_needed:
            fh.write("# Rebaseline Log\n\n"
                     "Append-only record of `--update-baseline --force` invocations.\n\n")
        fh.write(line)


if __name__ == "__main__":
    sys.exit(main())
