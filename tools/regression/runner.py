"""Regression harness orchestrator.

Discovers scenarios in tools/regression/scenarios/, runs each in a fresh
tmp workspace, aggregates Results, prints a summary table. Aborts cleanly
when MAX_FAILURES is reached to prevent diff storms.
"""

from __future__ import annotations

import importlib
import pkgutil
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAX_FAILURES = 20  # hard cap on aggregate failures before abort

_HARNESS_ROOT = Path(__file__).resolve().parent
_TMP_ROOT = _HARNESS_ROOT / "tmp"
_BASELINES_ROOT = _HARNESS_ROOT / "baselines"


@dataclass
class Result:
    scenario: str
    artifact: str
    passed: bool
    diff: str = ""  # empty on pass


@dataclass
class FailureBudget:
    """Mutable counter shared across scenarios; short-circuits when cap hit."""
    remaining: int = MAX_FAILURES
    aborted: bool = False

    def consume(self, failed: bool) -> None:
        if failed and not self.aborted:
            self.remaining -= 1
            if self.remaining <= 0:
                self.aborted = True

    def exceeded(self) -> bool:
        return self.aborted


# --------------------------------------------------------------------------
# Scenario discovery
# --------------------------------------------------------------------------
def discover_scenarios(layer_filter: str | None = None) -> list[tuple[str, Callable]]:
    """Return [(name, run_fn)] for every scenario module with a `run` callable."""
    from tools.regression import scenarios as scenarios_pkg

    found: list[tuple[str, Callable]] = []
    for _, name, _ in pkgutil.iter_modules(scenarios_pkg.__path__):
        if layer_filter and layer_filter not in name:
            continue
        mod = importlib.import_module(f"tools.regression.scenarios.{name}")
        run_fn = getattr(mod, "run", None)
        if callable(run_fn):
            found.append((name, run_fn))
    return sorted(found)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def reset_tmp() -> Path:
    if _TMP_ROOT.exists():
        shutil.rmtree(_TMP_ROOT)
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return _TMP_ROOT


def run_all(layer_filter: str | None = None) -> list[Result]:
    tmp_root = reset_tmp()
    baselines_root = _BASELINES_ROOT
    budget = FailureBudget()
    all_results: list[Result] = []

    scenarios = discover_scenarios(layer_filter)
    if not scenarios:
        print("[WARN] no scenarios discovered")
        return []

    for name, run_fn in scenarios:
        if budget.exceeded():
            all_results.append(Result(
                scenario=name, artifact="<aborted>", passed=False,
                diff="skipped: MAX_FAILURES reached in earlier scenarios",
            ))
            continue
        scn_tmp = tmp_root / name
        scn_tmp.mkdir(parents=True, exist_ok=True)
        scn_baseline = baselines_root / name

        t0 = time.perf_counter()
        try:
            results = run_fn(scn_tmp, scn_baseline, budget)
        except Exception as exc:  # surface scenario crashes as failures
            results = [Result(
                scenario=name, artifact="<crash>", passed=False,
                diff=f"scenario raised: {type(exc).__name__}: {exc}",
            )]
        elapsed = time.perf_counter() - t0

        for r in results:
            r.scenario = r.scenario or name
            all_results.append(r)
            budget.consume(not r.passed)

        # Persist per-scenario diffs so operators can triage.
        _write_diff_files(scn_tmp, results)
        print(f"  {name:<22} {elapsed:5.2f}s  "
              f"{sum(1 for r in results if r.passed)}/{len(results)} pass")

    return all_results


def _write_diff_files(scn_tmp: Path, results: list[Result]) -> None:
    for r in results:
        if r.passed or not r.diff:
            continue
        diff_path = scn_tmp / f"DIFF_{_safe_name(r.artifact)}.txt"
        diff_path.write_text(r.diff + "\n", encoding="utf-8")


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s)[:80]


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def print_summary(results: list[Result]) -> bool:
    """Print the aggregate summary. Returns True if all passed."""
    by_scenario: dict[str, list[Result]] = {}
    for r in results:
        by_scenario.setdefault(r.scenario, []).append(r)

    print()
    print("REGRESSION HARNESS")
    print("==================")
    total = 0
    passed = 0
    for name in sorted(by_scenario):
        scn_results = by_scenario[name]
        scn_pass = sum(1 for r in scn_results if r.passed)
        scn_total = len(scn_results)
        status = "PASS" if scn_pass == scn_total else "FAIL"
        print(f"{name:<22}: {scn_pass}/{scn_total}  {status}")
        total += scn_total
        passed += scn_pass
    print("-" * 34)
    print(f"TOTAL: {passed}/{total} PASS, {total - passed} FAIL")

    # Print failed artifacts with inline diffs.
    failures = [r for r in results if not r.passed]
    if failures:
        print()
        for r in failures[:10]:  # keep summary output compact
            print(f"[FAIL] {r.scenario}::{r.artifact}")
            if r.diff:
                for line in r.diff.split("\n")[:6]:
                    print(f"  {line}")
        if len(failures) > 10:
            print(f"  ... {len(failures) - 10} more failures (see tools/regression/tmp/*/DIFF_*.txt)")
    return passed == total
