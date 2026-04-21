"""Directive-driven run-directory discovery."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from config.state_paths import BACKTESTS_DIR

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIRECTIVES_ROOT = _PROJECT_ROOT / "backtest_directives"

BACKTESTS_ROOT = BACKTESTS_DIR


def _find_directive_file(strategy_prefix: str) -> Optional[Path]:
    candidates = [
        DIRECTIVES_ROOT / "completed" / f"{strategy_prefix}.txt",
        DIRECTIVES_ROOT / "active" / f"{strategy_prefix}.txt",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _load_declared_symbols(directive_file: Path) -> List[str]:
    payload = yaml.safe_load(directive_file.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Directive root is not a mapping: {directive_file}")

    symbols = payload.get("symbols")
    if symbols is None and isinstance(payload.get("test"), dict):
        symbols = payload["test"].get("symbols")

    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    if not isinstance(symbols, list):
        raise ValueError(f"Directive has no valid symbols list: {directive_file}")

    clean = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    if not clean:
        raise ValueError(f"Directive symbols list is empty: {directive_file}")
    return clean


def discover_run_dirs(strategy_prefix: str) -> Tuple[List[Path], Optional[Path], List[str]]:
    """
    Resolve run directories from directive-declared symbols.

    Falls back to prefix scan only if no directive file is found.
    """
    directive_file = _find_directive_file(strategy_prefix)
    if directive_file is None:
        run_dirs = sorted([
            d for d in BACKTESTS_ROOT.iterdir()
            if d.is_dir() and d.name.startswith(strategy_prefix)
        ])
        return run_dirs, None, []

    declared_symbols = _load_declared_symbols(directive_file)
    run_dirs: List[Path] = []
    missing: List[str] = []
    for sym in declared_symbols:
        run_dir = BACKTESTS_ROOT / f"{strategy_prefix}_{sym}"
        if run_dir.is_dir():
            run_dirs.append(run_dir)
        else:
            missing.append(str(run_dir))
    if missing:
        raise FileNotFoundError(
            "Missing backtest directories for directive-declared symbols:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
    return sorted(run_dirs), directive_file, declared_symbols
