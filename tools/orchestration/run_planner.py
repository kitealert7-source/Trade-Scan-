"""Run planning for directive execution."""

from __future__ import annotations

from pathlib import Path

from tools.orchestration.run_registry import ensure_registry
from tools.pipeline_utils import generate_run_id
from config.state_paths import RUNS_DIR


def plan_runs_for_directive(
    *,
    directive_id: str,
    directive_path: Path,
    strategy_id: str,
    symbols: list[str],
    project_root: Path,
) -> tuple[list[dict], Path]:
    """
    Convert directive into independent runs and persist plan to run registry.

    Returns (planned_runs, registry_path).
    """
    planned_runs: list[dict] = []
    seen: set[str] = set()
    for symbol in symbols:
        run_id, _ = generate_run_id(directive_path, symbol)
        if run_id in seen:
            continue
        seen.add(run_id)
        planned_runs.append(
            {
                "run_id": run_id,
                "strategy": strategy_id,
                "symbol": symbol,
            }
        )

    registry_path = RUNS_DIR / directive_id / "run_registry.json"
    merged = ensure_registry(registry_path, directive_id, planned_runs)
    return merged, registry_path
