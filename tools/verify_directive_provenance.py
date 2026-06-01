"""Gate: every run/strategy whose source directive is RECOVERABLE must carry
directive.txt — the detective half of the directive co-location rule.

The mandatory source snapshot (run_stage1 / run_pipeline / strategy_provisioner)
guarantees NEW runs co-locate their directive. This gate is the tripwire that
catches anything that slips through (a bypassed hook, a hand-created folder, a
historical gap) WITHOUT punishing the irrecoverable past:

  - Scan runs/ + strategies/ for folders lacking directive.txt (fast stat).
  - Subtract the acknowledged baseline (grandfathered genuine losses).
  - For each NEW missing folder, check whether its directive is still
    recoverable (live -> quarantine -> git -> any-git-path -> base):
      * recoverable but missing  -> VIOLATION (exit 1) — it SHOULD have it.
      * unrecoverable             -> a new genuine loss (acknowledge via
                                     --update-baseline).

Mirrors tools/check_broader_pytest_baseline.py. Wire into session-close /
preflight. Dry check by default; --update-baseline acknowledges current state.

    python tools/verify_directive_provenance.py
    python tools/verify_directive_provenance.py --update-baseline --rationale "..."
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.backfill_run_directives import (  # noqa: E402
    DIRECTIVE_SNAPSHOT_NAME,
    _items_for_target,
    _resolve_directive,
)

SIDECAR = PROJECT_ROOT / "outputs" / ".session_state" / "directive_provenance_baseline.json"


def _missing(target: str) -> list[tuple[str, str]]:
    """(folder_id, directive_id) for folders of `target` lacking directive.txt."""
    out = []
    for folder, did in _items_for_target(target):
        if not (folder / DIRECTIVE_SNAPSHOT_NAME).exists():
            out.append((f"{target}:{folder.name}", did or ""))
    return out


def _load_baseline() -> set[str]:
    if not SIDECAR.exists():
        return set()
    try:
        return set(json.loads(SIDECAR.read_text(encoding="utf-8")).get("grandfathered", []))
    except Exception:
        return set()


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update-baseline", action="store_true",
                    help="acknowledge the current missing set as grandfathered losses")
    ap.add_argument("--rationale", default="")
    args = ap.parse_args()

    missing = _missing("runs") + _missing("strategies")
    missing_ids = {m[0] for m in missing}

    if args.update_baseline:
        SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        SIDECAR.write_text(json.dumps({
            "schema_version": 1,
            "grandfathered": sorted(missing_ids),
            "count": len(missing_ids),
            "sha": _git_sha(),
            "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "rationale": args.rationale or "directives unrecoverable from any source (pre-preservation loss)",
        }, indent=2) + "\n", encoding="utf-8")
        print(f"[directive-provenance] baseline updated: {len(missing_ids)} grandfathered "
              f"folders acknowledged. Stage + commit {SIDECAR.relative_to(PROJECT_ROOT)}.")
        return 0

    baseline = _load_baseline()
    new_missing = [(fid, did) for fid, did in missing if fid not in baseline]

    violations, new_losses = [], []
    for fid, did in new_missing:
        content, _ = _resolve_directive(did) if did else (None, None)
        (violations if content else new_losses).append((fid, did))

    print(f"[directive-provenance] missing directive.txt: {len(missing_ids)} "
          f"(baseline grandfathered: {len(baseline)})")
    if new_losses:
        print(f"[directive-provenance] {len(new_losses)} new UNRECOVERABLE loss(es) "
              f"(acknowledge with --update-baseline):")
        for fid, did in new_losses[:10]:
            print(f"    - {fid}  {did}")

    if violations:
        print(f"\n[directive-provenance] BLOCK — {len(violations)} folder(s) whose directive "
              f"IS recoverable but is NOT co-located (rule bypassed):")
        for fid, did in violations[:15]:
            print(f"    + {fid}  {did}")
        print("\n  Fix: python tools/backfill_run_directives.py "
              "--target <runs|strategies> --apply")
        return 1

    print("[directive-provenance] OK — every recoverable directive is co-located.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
