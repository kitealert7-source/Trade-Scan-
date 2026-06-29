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
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR = REPO_ROOT / "outputs" / ".session_state" / "broader_pytest_baseline.json"
PYTEST_TIMEOUT_S = 600  # full suite ~80s 2-phase parallel @ 2026-06-25 (was ~172s serial); ample headroom
# Append-only runtime trend (gitignored) — feeds the close-gate runtime MONITOR.
DURATION_LOG = REPO_ROOT / "outputs" / ".session_state" / "broader_pytest_durations.jsonl"

# Base pytest flags shared by both phases. `-p no:cacheprovider` avoids a
# concurrent .pytest_cache write under xdist and keeps the run side-effect-free.
_PYTEST_BASE = ["-q", "--tb=no", "--no-header", "-p", "no:cacheprovider"]

# Worker count for the parallel phase. Pinned to "8" (not xdist's "auto", which is
# 14 = physical cores on this 14-core/20-thread box). A 2-pass interleaved sweep +
# a full-gate A/B (2026-06-25) found worker count is dominated by machine-load
# variance — 6/8/10/14 all within noise (~73-105s, single-run spread up to 2.3x) —
# so no count wins on wall time. Speed being a wash, 8 is chosen to leave core
# headroom for the suite's many subprocess-spawning tests AND for other work running
# during a close (matches the cointegration runner's proven 8-worker config).
# Override with BROADER_PYTEST_WORKERS (e.g. "auto"/"14"); monitor records the value.
PYTEST_NUM_WORKERS = os.environ.get("BROADER_PYTEST_WORKERS", "8").strip() or "8"

# Files that are NOT parallel-safe — they mutate/read shared, fixed-name on-disk
# state another test sees concurrently, so they run in a SECOND serial phase while
# everything else parallelizes (-n auto):
#   - test_engine_abi_{v1_5_9,adversarial}: the adversarial file backs up + TAMPERS
#     the LOCAL committed manifest + engine_abi/__init__.py (the tree the suite runs
#     in — worktree or real repo; abi_audit.py resolves both relative to its own
#     tree) then restores; v1_5_9 reads that manifest and importlib.reload()s the
#     ABI. These can't be sandboxed (the audit's whole point is to exercise the
#     actual triple-gate), and a crash mid-tamper dirties the tree — so they stay
#     serial.
# The 3 test_intent_injector_* files used to be here too; they were isolated at the
# ROOT instead — the hook honors INTENT_INJECTOR_STATE_ROOT and tests/conftest.py
# points each xdist worker at its own temp state dir — so they now parallelize
# safely (and no longer pollute the real .claude/logs). Add a file here only when a
# real shared-state race is proven AND it can't be sandboxed via a per-worker dir.
SERIAL_FILES = [
    "tests/test_engine_abi_v1_5_9.py",
    "tests/test_engine_abi_adversarial.py",
]


def _parse_pytest_output(out: str) -> dict:
    """Extract the FAILED-test set + pass/fail/skip counts from pytest -q output.

    The summary lines ("FAILED <id> - <reason>", "N passed", ...) are emitted
    identically by serial and xdist runs, so one parser covers both phases.
    """
    failed: list[str] = []
    for line in out.splitlines():
        if line.startswith("FAILED "):
            parts = line.split(" ", 2)
            if len(parts) >= 2:
                failed.append(parts[1].strip())

    def _n(pat: str) -> int:
        m = re.search(pat, out)
        return int(m.group(1)) if m else 0

    return {
        "failed": failed,
        "count": _n(r"(\d+)\s+failed"),
        "passed": _n(r"(\d+)\s+passed"),
        "skipped": _n(r"(\d+)\s+skipped"),
    }


def _pytest(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout,
    )


def _run_pytest() -> dict:
    """Run the broader pytest suite and return the parsed result.

    Two-phase for speed without losing coverage (~172s serial -> ~80s):
      Phase 1 — `tests/` with `-n auto --dist loadscope`, EXCLUDING SERIAL_FILES,
                so the ~2030-test bulk spreads across cores.
      Phase 2 — SERIAL_FILES on their own, serially (they are not parallel-safe).
    The two failure sets + counts are merged. If pytest-xdist is unavailable the
    Phase-1 launch reports an unrecognized `-n`; we transparently fall back to a
    single serial run over `tests/` (legacy behavior — same coverage, slower).

    Returns dict with keys: ok, failed, count, passed, skipped, elapsed_s,
    raw_tail, exit_code, mode (and error on failure).
    """
    t0 = time.perf_counter()
    ignore: list[str] = []
    for f in SERIAL_FILES:
        ignore += ["--ignore", f]

    # Phase 1 — parallel bulk.
    try:
        p1 = _pytest(["tests/", "-n", PYTEST_NUM_WORKERS, "--dist", "loadscope", *_PYTEST_BASE, *ignore],
                     PYTEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"pytest (parallel phase) timed out after {PYTEST_TIMEOUT_S}s",
                "elapsed_s": round(time.perf_counter() - t0, 1)}
    except Exception as e:
        return {"ok": False, "error": f"pytest failed to launch: {e}",
                "elapsed_s": round(time.perf_counter() - t0, 1)}
    out1 = (p1.stdout or "") + (p1.stderr or "")

    # Fallback: pytest-xdist not installed -> single serial run over tests/.
    if "unrecognized arguments: -n" in out1:
        try:
            ps = _pytest(["tests/", *_PYTEST_BASE], PYTEST_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"pytest timed out after {PYTEST_TIMEOUT_S}s",
                    "elapsed_s": round(time.perf_counter() - t0, 1)}
        outs = (ps.stdout or "") + (ps.stderr or "")
        r = _parse_pytest_output(outs)
        return {"ok": True, "failed": sorted(set(r["failed"])), "count": r["count"],
                "passed": r["passed"], "skipped": r["skipped"],
                "elapsed_s": round(time.perf_counter() - t0, 1),
                "raw_tail": outs.splitlines()[-20:], "exit_code": ps.returncode,
                "mode": "serial (xdist unavailable)"}

    r1 = _parse_pytest_output(out1)

    # Phase 2 — shared-state files, serial.
    try:
        p2 = _pytest([*SERIAL_FILES, *_PYTEST_BASE], PYTEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pytest (serial phase) timed out",
                "elapsed_s": round(time.perf_counter() - t0, 1)}
    except Exception as e:
        return {"ok": False, "error": f"pytest serial phase failed to launch: {e}",
                "elapsed_s": round(time.perf_counter() - t0, 1)}
    out2 = (p2.stdout or "") + (p2.stderr or "")
    r2 = _parse_pytest_output(out2)

    return {
        "ok": True,
        "failed": sorted(set(r1["failed"]) | set(r2["failed"])),
        "count": r1["count"] + r2["count"],
        "passed": r1["passed"] + r2["passed"],
        "skipped": r1["skipped"] + r2["skipped"],
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "raw_tail": out1.splitlines()[-10:] + out2.splitlines()[-10:],
        "exit_code": p1.returncode or p2.returncode,
        "mode": "parallel 2-phase",
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


def _log_duration(result: dict) -> None:
    """Append one runtime sample to the duration trend (best-effort).

    Feeds the 'broader-pytest close-gate runtime' MONITOR in SYSTEM_STATE: one
    JSONL line per full-suite run so the operator can see when the gate's wall
    time trends toward the bottleneck threshold (median > 4 min or > 3500 tests).
    xdist 2-phase parallelism is already enabled (475dfd39, 2026-06-25), so a
    re-crossing now means shard further / add workers / hunt a slow test — NOT
    "enable xdist" (already done). The trend is now a regression sentinel. Never
    raises — a log-write failure must not break the gate.
    """
    try:
        total = (result.get("passed", 0) + result.get("count", 0)
                 + result.get("skipped", 0))
        rec = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "elapsed_s": result.get("elapsed_s"),
            "total": total,
            "passed": result.get("passed", 0),
            "failed": result.get("count", 0),
            "skipped": result.get("skipped", 0),
            "workers": PYTEST_NUM_WORKERS,
            "mode": result.get("mode", "serial"),
            "sha": _git_sha(),
        }
        DURATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DURATION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def cmd_check() -> int:
    """Default mode: compare current pytest run to baseline. Block on regression."""
    baseline = _load_baseline()
    print("[check-broader-pytest] Running broader pytest suite (this takes ~2 min)...")
    result = _run_pytest()

    if not result.get("ok"):
        print(f"[check-broader-pytest] ERROR — {result.get('error', 'unknown')}", file=sys.stderr)
        return 2

    _log_duration(result)

    baseline_set = set(baseline.get("failed", []))
    current_set = set(result["failed"])

    new_failures = current_set - baseline_set
    fixed_failures = baseline_set - current_set

    print(f"[check-broader-pytest] Current : {result['count']} failed, "
          f"{result['passed']} passed, {result['skipped']} skipped "
          f"in {result.get('elapsed_s', '?')}s [{result.get('mode', 'serial')}]")
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
