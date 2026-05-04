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
    from tools.pipeline_utils import DirectiveStateManager
    
    state_mgr = DirectiveStateManager(directive_id)
    attempt_id = state_mgr.get_latest_attempt()
    
    planned_runs: list[dict] = []
    seen: set[str] = set()
    for symbol in symbols:
        run_id, _ = generate_run_id(directive_path, symbol, attempt_id=attempt_id)
        if run_id in seen:
            continue
        seen.add(run_id)
        planned_runs.append(
            {
                "run_id": run_id,
                "strategy": strategy_id,
                "symbol": symbol,
                "attempt_id": attempt_id,
            }
        )

    # Honor project_root for registry path so test fixtures can isolate to
    # a temp dir (matches Batch 1 portfolio_core fix pattern). When
    # project_root is None or the canonical PROJECT_ROOT, falls through to
    # the global RUNS_DIR so production behavior is unchanged.
    runs_root = Path(project_root) / "runs" if project_root else RUNS_DIR
    registry_path = runs_root / directive_id / "run_registry.json"
    merged = ensure_registry(registry_path, directive_id, planned_runs)
    
    # Track assigned Run IDs under the Attempt's FSM payload
    run_ids = [r["run_id"] for r in merged if r.get("attempt_id") == attempt_id]
    if not run_ids:
        # Fallback if registry merging did not explicitly maintain attempt_id locally
        run_ids = [r["run_id"] for r in planned_runs]
    state_mgr.register_run_ids(run_ids)
    
    return merged, registry_path
