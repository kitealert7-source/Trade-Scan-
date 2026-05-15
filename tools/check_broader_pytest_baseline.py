"""Broader-pytest baseline gate — catches NEW test regressions at session-close.

The auto-populator in `tools/system_introspection.py` only checks the
*gate* test suite (5 fast files). The broader `tests/` suite (~800 tests)
includes integration tests, environment-sensitive tests, and stale-spec
tests that are tracked as known TDs in `SYSTEM_STATE.md` Manual section.

Without this tool, a NEW broader-pytest failure introduced between
sessions slips past session-close because:
  - The auto-populator doesn't run broader pytest (too slow).
  - The §9b gate's `HAS_BLOCKERS && HAS_AUTO_SECTION == 0` check passes
    so long as the auto section exists for ANY reason (post-merge watch,
    intent-index, sweep-registry).
  - Operator only sees the failure if they manually grep SYSTEM_STATE
    or run pytest themselves.

This tool closes the gap. It runs broader pytest, compares the failed
test set against `outputs/.session_state/broader_pytest_baseline.json`
(committed, append-only acknowledged failures), and:

  - Exits 0 if the failed set is identical to (or a subset of) baseline.
  - Exits 1 if NEW failures appeared (regression — block close).
  - Exits 2 on internal pytest error (couldn't even run).

Update flow when an operator intentionally accepts a new failure or
fixes an old one:

    python tools/check_broader_pytest_baseline.py --update-baseline

That refreshes the sidecar with the current failure set + records the
git SHA + timestamp + reason. The sidecar is the formal acknowledgment
that those failures are *known and accepted* until someone fixes them.

Sidecar schema (versioned):
    {
      "schema_version": 1,
      "failed": ["tests/foo.py::test_a", ...],   # sorted, fully-qualified
      "count": 3,
      "sha": "<commit at update time>",
      "updated_at": "2026-05-15T07:30:00+00:00",
      "rationale": "<operator-supplied reason for the baseline>"
    }
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR = REPO_ROOT / "outputs" / ".session_state" / "broader_pytest_baseline.json"
PYTEST_TIMEOUT_S = 600  # full broader suite was ~122s; 10× headroom


def _run_pytest() -> dict:
    """Run broader pytest and return parsed result.

    Returns dict with keys:
        failed: sorted list of "<file>::<test>" identifiers
        count: int (failures)
        passed: int
        skipped: int
        ok: bool (subprocess returned without timeout/exception)
        raw_tail: list[str] (last ~20 lines for diagnostic)
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no", "--no-header"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"pytest timed out after {PYTEST_TIMEOUT_S}s"}
    except Exception as e:
        return {"ok": False, "error": f"pytest failed to launch: {e}"}

    out = (proc.stdout or "") + (proc.stderr or "")
    failed: list[str] = []
    for line in out.splitlines():
        # pytest -q prints "FAILED <test_id> - <reason>" lines in the summary
        if line.startswith("FAILED "):
            parts = line.split(" ", 2)
            if len(parts) >= 2:
                failed.append(parts[1].strip())

    m_fail = re.search(r"(\d+)\s+failed", out)
    m_pass = re.search(r"(\d+)\s+passed", out)
    m_skip = re.search(r"(\d+)\s+skipped", out)

    return {
        "ok": True,
        "failed": sorted(set(failed)),
        "count": int(m_fail.group(1)) if m_fail else 0,
        "passed": int(m_pass.group(1)) if m_pass else 0,
        "skipped": int(m_skip.group(1)) if m_skip else 0,
        "raw_tail": out.splitlines()[-20:],
        "exit_code": proc.returncode,
    }


def _load_baseline() -> dict:
    if not SIDECAR.exists():
        return {"schema_version": 1, "failed": [], "count": 0, "sha": None,
                "updated_at": None, "rationale": "(no baseline yet)"}
    return json.loads(SIDECAR.read_text(encoding="utf-8"))


def _git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        return (proc.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def cmd_check() -> int:
    """Default mode: compare current pytest run to baseline. Block on regression."""
    baseline = _load_baseline()
    print("[check-broader-pytest] Running broader pytest suite (this takes ~2 min)...")
    result = _run_pytest()

    if not result.get("ok"):
        print(f"[check-broader-pytest] ERROR — {result.get('error', 'unknown')}", file=sys.stderr)
        return 2

    baseline_set = set(baseline.get("failed", []))
    current_set = set(result["failed"])

    new_failures = current_set - baseline_set
    fixed_failures = baseline_set - current_set

    print(f"[check-broader-pytest] Current : {result['count']} failed, "
          f"{result['passed']} passed, {result['skipped']} skipped")
    print(f"[check-broader-pytest] Baseline: {baseline.get('count', 0)} acknowledged "
          f"(updated {baseline.get('updated_at') or 'never'})")

    if new_failures:
        print()
        print(f"[check-broader-pytest] BLOCK — {len(new_failures)} NEW failure(s) since baseline:")
        for t in sorted(new_failures):
            print(f"  + {t}")
        print()
        print("[check-broader-pytest] Resolution:")
        print("  Option A — fix the failure(s), re-run this tool")
        print("  Option B — explicitly accept them (they become baseline TDs):")
        print("             python tools/check_broader_pytest_baseline.py --update-baseline")
        print("                  --rationale '<why these are accepted>'")
        return 1

    if fixed_failures:
        print()
        print(f"[check-broader-pytest] IMPROVEMENT — {len(fixed_failures)} prior failure(s) now pass:")
        for t in sorted(fixed_failures):
            print(f"  - {t}")
        print("  -> Refresh the baseline to lock in:")
        print("     python tools/check_broader_pytest_baseline.py --update-baseline "
              "--rationale 'fixed: <description>'")
        # Improvement is not a block. Operator chooses when to commit the
        # tightened baseline.

    if not new_failures and not fixed_failures:
        print("[check-broader-pytest] OK — failure set matches baseline exactly.")

    return 0


def cmd_update_baseline(rationale: str) -> int:
    """Update mode: refresh sidecar with current pytest state."""
    print("[check-broader-pytest] Running broader pytest to capture new baseline...")
    result = _run_pytest()
    if not result.get("ok"):
        print(f"[check-broader-pytest] ERROR — {result.get('error', 'unknown')}", file=sys.stderr)
        return 2

    SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "failed": result["failed"],
        "count": result["count"],
        "sha": _git_sha(),
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "rationale": rationale,
    }
    SIDECAR.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[check-broader-pytest] Baseline updated: {result['count']} failures locked in.")
    print(f"[check-broader-pytest] Sidecar: {SIDECAR.relative_to(REPO_ROOT)}")
    print(f"[check-broader-pytest] Stage + commit the sidecar to make the baseline durable.")
    return 0


def cmd_show() -> int:
    """Print current baseline (no pytest run)."""
    baseline = _load_baseline()
    print(json.dumps(baseline, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--update-baseline",
        action="store_true",
        help="Refresh the sidecar with current pytest state. Requires --rationale.",
    )
    p.add_argument(
        "--rationale",
        type=str,
        default="",
        help="Operator-supplied reason for the new baseline (required with --update-baseline).",
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="Print current baseline JSON; do not run pytest.",
    )
    args = p.parse_args()

    if args.show:
        return cmd_show()
    if args.update_baseline:
        if not args.rationale.strip():
            print("[check-broader-pytest] ERROR — --rationale is required with --update-baseline",
                  file=sys.stderr)
            return 2
        return cmd_update_baseline(args.rationale.strip())
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
