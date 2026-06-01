"""basket_reproducibility_check.py — is a basket directive's re-run reproducible?

Reads the reproducibility identity recorded in each basket run's manifest.json
(directive hash + engine_version + per-leg input-data hash + leg/rule code
hashes) and reports whether two runs would reproduce (identical inputs) or
diverged, with the changed dimension localized. Compares RECORDED manifests —
no data re-load — so it is cheap and side-effect free.

Usage:
    python tools/basket_reproducibility_check.py <directive_id>
        Compare every prior basket run of <directive_id> to its newest run.
    python tools/basket_reproducibility_check.py --runs <run_id_a> <run_id_b>
        Compare two specific run_ids.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE  # noqa: E402
from tools.basket_provenance import compare_basket_runs  # noqa: E402

RUNS_DIR = TRADE_SCAN_STATE / "runs"


def _load_manifest(run_id: str) -> dict | None:
    mf = RUNS_DIR / run_id / "manifest.json"
    if not mf.is_file():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return None


def _basket_runs_for_directive(directive_id: str) -> list[str]:
    """run_ids of basket runs whose run_state.json names this directive,
    newest first."""
    if not RUNS_DIR.is_dir():
        return []
    found: list[tuple[float, str]] = []
    for d in RUNS_DIR.iterdir():
        rs = d / "run_state.json"
        if not rs.is_file():
            continue
        try:
            state = json.loads(rs.read_text(encoding="utf-8"))
        except Exception:
            continue
        if state.get("directive_id") != directive_id:
            continue
        if (state.get("metadata") or {}).get("execution_mode") != "basket":
            continue
        found.append((d.stat().st_mtime, d.name))
    return [name for _, name in sorted(found, reverse=True)]


def _has_provenance(m: dict) -> bool:
    return bool((m.get("input_provenance") or {}).get("leg_data_sha256"))


def _report(ref_id: str, other_id: str) -> bool:
    ma, mb = _load_manifest(ref_id), _load_manifest(other_id)
    if ma is None or mb is None:
        print(f"  ! {other_id[:12]} vs {ref_id[:12]}: manifest missing — "
              "cannot compare (pruned run).")
        return False
    # Vacuous match guard: two runs that recorded no input provenance compare
    # equal only because there is nothing to differ. Do not call that
    # reproducible — it predates the provenance change.
    if not _has_provenance(ma) and not _has_provenance(mb):
        print(f"  ? {other_id[:12]} vs {ref_id[:12]}: INDETERMINATE (no input "
              "provenance recorded — run(s) predate the provenance change)")
        return True
    verdict = compare_basket_runs(ma, mb)
    if verdict["reproducible"]:
        print(f"  = {other_id[:12]} vs {ref_id[:12]}: REPRODUCIBLE (inputs identical)")
        return True
    print(f"   x {other_id[:12]} vs {ref_id[:12]}: NEW TRUTH — changed: "
          + ", ".join(verdict["changed"]))
    return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("directive_id", nargs="?", help="directive to scan for basket runs")
    p.add_argument("--runs", nargs=2, metavar=("RUN_A", "RUN_B"),
                   help="compare two specific run_ids")
    args = p.parse_args()

    if args.runs:
        ref, other = args.runs
        print(f"[basket-repro] comparing {other} -> {ref}")
        return 0 if _report(ref, other) else 1

    if not args.directive_id:
        p.error("provide a directive_id or --runs RUN_A RUN_B")

    runs = _basket_runs_for_directive(args.directive_id)
    if not runs:
        print(f"[basket-repro] no basket runs found for directive "
              f"'{args.directive_id}'.")
        return 0
    newest = runs[0]
    print(f"[basket-repro] {args.directive_id}: {len(runs)} basket run(s); "
          f"newest = {newest[:12]}")
    if len(runs) == 1:
        m = _load_manifest(newest)
        has = bool(m and (m.get("input_provenance") or {}).get("leg_data_sha256"))
        print("  (only one run; nothing to compare. input-provenance "
              f"recorded: {'yes' if has else 'no'})")
        return 0
    all_repro = True
    for older in runs[1:]:
        all_repro &= _report(newest, older)
    return 0 if all_repro else 1


if __name__ == "__main__":
    sys.exit(main())
