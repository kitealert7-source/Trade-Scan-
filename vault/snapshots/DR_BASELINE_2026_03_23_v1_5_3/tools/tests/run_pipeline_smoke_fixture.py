"""
run_pipeline_smoke_fixture.py

Run a production-like pipeline smoke test from an isolated fixture and
optionally clean all generated artifacts afterwards.

Usage:
    python tools/tests/run_pipeline_smoke_fixture.py
    python tools/tests/run_pipeline_smoke_fixture.py --keep-artifacts
    python tools/tests/run_pipeline_smoke_fixture.py --fixture-id <ID>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import generate_run_id  # noqa: E402


DEFAULT_FIXTURE_ID = "02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S06_V1_P00"

FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "pipeline_smoke"
ACTIVE_DIR = PROJECT_ROOT / "backtest_directives" / "INBOX"
COMPLETED_DIR = PROJECT_ROOT / "backtest_directives" / "completed"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
BACKTESTS_DIR = PROJECT_ROOT / "backtests"
RUNS_DIR = PROJECT_ROOT / "runs"
REPORTS_DIR = PROJECT_ROOT / "reports_summary"

STRATEGY_MASTER_PATH = BACKTESTS_DIR / "Strategy_Master_Filter.xlsx"
PORTFOLIO_MASTER_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"


def _run(cmd: list[str]) -> None:
    print(f"\n[CMD] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def _load_fixture_paths(fixture_id: str) -> tuple[Path, Path]:
    directive_src = FIXTURE_ROOT / f"{fixture_id}.txt"
    strategy_src = FIXTURE_ROOT / "strategies" / fixture_id / "strategy.py"
    if not directive_src.exists():
        raise FileNotFoundError(f"Fixture directive missing: {directive_src}")
    if not strategy_src.exists():
        raise FileNotFoundError(f"Fixture strategy missing: {strategy_src}")
    return directive_src, strategy_src


def _extract_symbols(directive_path: Path) -> list[str]:
    payload = yaml.safe_load(directive_path.read_text(encoding="utf-8")) or {}
    test_block = payload.get("test", {}) if isinstance(payload, dict) else {}
    symbols = (
        payload.get("symbols")
        or payload.get("Symbols")
        or test_block.get("symbols")
        or test_block.get("Symbols")
        or []
    )
    if isinstance(symbols, str):
        symbols = [symbols]
    if not isinstance(symbols, list):
        return []
    return [str(s).strip() for s in symbols if str(s).strip()]


def _stage_fixture(fixture_id: str, directive_src: Path, strategy_src: Path) -> Path:
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    directive_dst = ACTIVE_DIR / f"{fixture_id}.txt"
    strategy_dst = STRATEGIES_DIR / fixture_id / "strategy.py"
    strategy_dst.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(directive_src, directive_dst)
    shutil.copy2(strategy_src, strategy_dst)

    print(f"[STAGE] Directive -> {directive_dst}")
    print(f"[STAGE] Strategy  -> {strategy_dst}")
    return directive_dst


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _remove_file(path: Path) -> None:
    if path.exists():
        path.unlink()


def _prune_strategy_master(fixture_id: str) -> int:
    if not STRATEGY_MASTER_PATH.exists():
        return 0
    df = pd.read_excel(STRATEGY_MASTER_PATH)
    if "strategy" not in df.columns:
        return 0
    mask = (
        df["strategy"].astype(str).str.startswith(f"{fixture_id}_")
        | (df["strategy"].astype(str) == fixture_id)
    )
    removed = int(mask.sum())
    if removed > 0:
        df = df[~mask].reset_index(drop=True)
        df.to_excel(STRATEGY_MASTER_PATH, index=False)
        _run(
            [
                sys.executable,
                "tools/format_excel_artifact.py",
                "--file",
                str(STRATEGY_MASTER_PATH),
                "--profile",
                "strategy",
            ]
        )
    return removed


def _prune_portfolio_master(fixture_id: str) -> int:
    if not PORTFOLIO_MASTER_PATH.exists():
        return 0
    df = pd.read_excel(PORTFOLIO_MASTER_PATH)
    if "portfolio_id" not in df.columns:
        return 0
    mask = df["portfolio_id"].astype(str) == fixture_id
    removed = int(mask.sum())
    if removed > 0:
        df = df[~mask].reset_index(drop=True)
        df.to_excel(PORTFOLIO_MASTER_PATH, index=False)
        _run(
            [
                sys.executable,
                "tools/format_excel_artifact.py",
                "--file",
                str(PORTFOLIO_MASTER_PATH),
                "--profile",
                "portfolio",
            ]
        )
    return removed


def _collect_run_dirs_for_fixture(fixture_id: str, symbols: list[str], directive_path: Path) -> set[Path]:
    run_dirs: set[Path] = set()

    # Deterministic run IDs for current fixture content.
    for symbol in symbols:
        run_id, _ = generate_run_id(directive_path, symbol)
        run_dirs.add(RUNS_DIR / run_id)

    # Historical run directories tied to this directive ID.
    if RUNS_DIR.exists():
        for item in RUNS_DIR.iterdir():
            if not item.is_dir():
                continue
            state_files = list(item.glob("run_state.json*"))
            for sf in state_files:
                try:
                    payload = json.loads(sf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(payload.get("directive_id", "")) == fixture_id:
                    run_dirs.add(item)
                    break

    # Directive state folder.
    run_dirs.add(RUNS_DIR / fixture_id)
    return run_dirs


def _cleanup_runtime_artifacts(fixture_id: str, symbols: list[str], directive_path: Path) -> None:
    print("\n[CLEANUP] Removing fixture runtime artifacts...")

    # Active directive + staged strategy.
    _remove_file(ACTIVE_DIR / f"{fixture_id}.txt")
    _remove_file(COMPLETED_DIR / f"{fixture_id}.txt")
    _remove_tree(STRATEGIES_DIR / fixture_id)

    # Backtest outputs for fixture prefix.
    for item in BACKTESTS_DIR.glob(f"{fixture_id}_*"):
        _remove_tree(item)
    _remove_file(BACKTESTS_DIR / f"batch_summary_{fixture_id}.csv")

    # Summary reports.
    _remove_file(REPORTS_DIR / f"REPORT_{fixture_id}.md")
    _remove_file(REPORTS_DIR / f"PORTFOLIO_{fixture_id}.md")

    # Run state directories.
    for run_dir in _collect_run_dirs_for_fixture(fixture_id, symbols, directive_path):
        _remove_tree(run_dir)

    # Sheet row cleanup.
    removed_strategy = _prune_strategy_master(fixture_id)
    removed_portfolio = _prune_portfolio_master(fixture_id)
    print(
        f"[CLEANUP] Removed Strategy_Master_Filter rows: {removed_strategy} | "
        f"Master_Portfolio_Sheet rows: {removed_portfolio}"
    )


def _validate_pipeline_result(fixture_id: str) -> None:
    if not PORTFOLIO_MASTER_PATH.exists():
        raise RuntimeError("Master_Portfolio_Sheet.xlsx not found after run.")

    df = pd.read_excel(PORTFOLIO_MASTER_PATH)
    if "portfolio_id" not in df.columns:
        raise RuntimeError("Master_Portfolio_Sheet missing portfolio_id column.")

    rows = df[df["portfolio_id"].astype(str) == fixture_id]
    if rows.empty:
        raise RuntimeError(f"No portfolio ledger row found for fixture: {fixture_id}")

    row = rows.iloc[-1]
    required_cols = [
        "reference_capital_usd",
        "theoretical_pnl",
        "realized_pnl",
        "realized_pnl_usd",
        "deployed_profile",
        "trades_accepted",
        "trades_rejected",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"Portfolio ledger missing required columns: {missing}")

    if pd.isna(row["realized_pnl"]) or pd.isna(row["realized_pnl_usd"]):
        raise RuntimeError("realized_pnl / realized_pnl_usd not populated by smoke run.")
    if pd.isna(row["theoretical_pnl"]):
        raise RuntimeError("theoretical_pnl not populated by smoke run.")
    if pd.isna(row["deployed_profile"]):
        raise RuntimeError("deployed_profile not populated by smoke run.")

    ref_idx = df.columns.get_loc("reference_capital_usd")
    theo_idx = df.columns.get_loc("theoretical_pnl")
    if theo_idx != ref_idx + 1:
        raise RuntimeError(
            "Portfolio ledger column order regression: "
            "theoretical_pnl must be immediately after reference_capital_usd."
        )

    profile_comparison = STRATEGIES_DIR / fixture_id / "deployable" / "profile_comparison.json"
    if not profile_comparison.exists():
        raise RuntimeError(f"Missing deployable profile comparison: {profile_comparison}")

    print(
        "[VALIDATION] OK "
        f"portfolio_id={fixture_id} "
        f"realized_pnl={row['realized_pnl']} "
        f"profile={row['deployed_profile']} "
        f"accepted={row['trades_accepted']} "
        f"rejected={row['trades_rejected']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pipeline smoke fixture in isolated mode.")
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID, help="Fixture ID to run.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep staged and generated runtime artifacts after execution.",
    )
    args = parser.parse_args()

    fixture_id = args.fixture_id
    directive_src, strategy_src = _load_fixture_paths(fixture_id)

    # Parse symbols from fixture source so cleanup works even if staging fails.
    symbols = _extract_symbols(directive_src)
    if not symbols:
        raise RuntimeError(f"No symbols found in fixture directive: {directive_src}")

    run_ok = False

    try:
        # Start from a clean runtime state for deterministic smoke execution.
        _cleanup_runtime_artifacts(fixture_id, symbols, directive_src)

        _stage_fixture(fixture_id, directive_src, strategy_src)
        _run([sys.executable, "tools/run_pipeline.py", fixture_id])
        _validate_pipeline_result(fixture_id)
        run_ok = True
    finally:
        if not args.keep_artifacts:
            _cleanup_runtime_artifacts(fixture_id, symbols, directive_src)
        elif run_ok:
            print("[INFO] Keeping fixture artifacts (--keep-artifacts enabled).")

    if run_ok:
        print("[DONE] Pipeline smoke fixture PASSED.")
    else:
        raise RuntimeError("Pipeline smoke fixture FAILED.")


if __name__ == "__main__":
    main()
