"""Dispatcher for orchestration pipeline phases."""

from __future__ import annotations

from pathlib import Path


def run_preflight_semantic_checks(
    *,
    clean_id: str,
    d_path: Path,
    p_conf: dict,
    run_ids: list[str],
    symbols: list[str],
    dir_state_mgr,
    provision_only: bool,
    project_root: Path,
    python_exe: str,
    run_command,
) -> bool:
    from tools.orchestration.stage_preflight import run_preflight_semantic_checks as _run

    return _run(
        clean_id=clean_id,
        d_path=d_path,
        p_conf=p_conf,
        run_ids=run_ids,
        symbols=symbols,
        dir_state_mgr=dir_state_mgr,
        provision_only=provision_only,
        project_root=project_root,
        python_exe=python_exe,
        run_command=run_command,
    )


def run_symbol_execution_stages(
    *,
    clean_id: str,
    p_conf: dict,
    run_ids: list[str],
    symbols: list[str],
    project_root: Path,
    python_exe: str,
    run_command,
    registry_path: Path | None = None,
) -> None:
    from tools.orchestration.stage_symbol_execution import run_symbol_execution_stages as _run

    _run(
        clean_id=clean_id,
        p_conf=p_conf,
        run_ids=run_ids,
        symbols=symbols,
        project_root=project_root,
        python_exe=python_exe,
        run_command=run_command,
        registry_path=registry_path,
    )


def run_portfolio_and_post_stages(
    *,
    clean_id: str,
    p_conf: dict,
    run_ids: list[str],
    symbols: list[str],
    project_root: Path,
    python_exe: str,
    run_command,
) -> None:
    from tools.orchestration.stage_portfolio import run_portfolio_and_post_stages as _run

    _run(
        clean_id=clean_id,
        p_conf=p_conf,
        run_ids=run_ids,
        symbols=symbols,
        project_root=project_root,
        python_exe=python_exe,
        run_command=run_command,
    )
