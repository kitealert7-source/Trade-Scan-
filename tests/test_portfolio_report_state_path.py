"""Regression — Stage-4 portfolio report must land under STATE_ROOT, never
under PROJECT_ROOT (the Trade_Scan source tree).

Background
----------
`stage_portfolio.py:173` originally invoked
``generate_strategy_portfolio_report(clean_id, project_root)`` with
``project_root = Trade_Scan/``. The report function expects
``root_dir / "strategies" / <id> / "portfolio_evaluation"`` to exist, but
``portfolio_evaluation/`` is written exclusively under
``STATE_ROOT/strategies/`` by ``portfolio_evaluator.py:209``. The wrong
root made the function early-return on every multi-asset directive —
silently dropping the ``PORTFOLIO_<id>.md`` report for ~30 days.

The 2026-05-12 fix passes ``STATE_ROOT`` instead. These tests pin three
invariants so the regression cannot return:

  1. Multi-asset → ``PORTFOLIO_<id>.md`` lands under
     ``STATE_ROOT/strategies/<id>/`` (not under ``PROJECT_ROOT``).
  2. Single-asset → Phase A §4.10 skip still holds (no
     ``PORTFOLIO_<id>.md`` for ``evaluated_assets`` ≤ 1).
  3. No writes ever land under ``Trade_Scan/strategies/<id>/`` for the
     portfolio-report code path. The orchestrator call site uses
     ``STATE_ROOT`` exclusively.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _seed_portfolio_evaluation(
    state_root: Path,
    strategy_id: str,
    *,
    evaluated_assets: list[str],
    extra_metadata: dict | None = None,
) -> Path:
    """Create a fixture STATE_ROOT/strategies/<id>/portfolio_evaluation/
    directory with the minimum JSON the report function reads.

    Returns the strategy dir (= write target for PORTFOLIO_<id>.md).
    """
    strat_dir = state_root / "strategies" / strategy_id
    eval_dir = strat_dir / "portfolio_evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "data_range": "2024-05-11 to 2026-05-11",
        "evaluation_timeframe": "5M",
        "total_trades": 1251,
        "net_pnl_usd": 2226.95,
        "profit_factor": 1.25,
        "max_dd_pct": 0.381,
        "return_dd_ratio": 5.84,
        "sharpe": 1.05,
        "sortino": 1.40,
        "cagr_pct": 0.10,
        "win_rate": 41.2,
        "expectancy": 1.78,
        "avg_correlation": 0.21,
    }
    (eval_dir / "portfolio_summary.json").write_text(
        json.dumps(summary), encoding="utf-8",
    )

    meta = {
        "start_date": "2024-05-11",
        "end_date": "2026-05-11",
        "evaluation_timeframe": "5M",
        "evaluated_assets": evaluated_assets,
        "constituent_run_ids": [f"run_{i}" for i in range(len(evaluated_assets))],
    }
    if extra_metadata:
        meta.update(extra_metadata)
    (eval_dir / "portfolio_metadata.json").write_text(
        json.dumps(meta), encoding="utf-8",
    )
    return strat_dir


# ---------------------------------------------------------------------------
# 1. Multi-asset → report lands under STATE_ROOT
# ---------------------------------------------------------------------------

def test_multi_asset_report_lands_under_state_root(tmp_path):
    """The fix: ``generate_strategy_portfolio_report(id, STATE_ROOT)`` must
    write the PORTFOLIO_<id>.md to STATE_ROOT/strategies/<id>/.
    """
    from tools.report.report_strategy_portfolio import (
        generate_strategy_portfolio_report,
    )

    state_root = tmp_path / "TradeScan_State"
    strat_dir = _seed_portfolio_evaluation(
        state_root,
        "MULTI_FAM_S01_V1_P01",
        evaluated_assets=["AUDUSD", "EURUSD", "GBPJPY", "AUDJPY", "EURAUD"],
    )

    generate_strategy_portfolio_report("MULTI_FAM_S01_V1_P01", state_root)

    expected = strat_dir / "PORTFOLIO_MULTI_FAM_S01_V1_P01.md"
    assert expected.exists(), (
        f"PORTFOLIO_*.md missing under STATE_ROOT — function failed to write. "
        f"Searched at: {expected}"
    )
    text = expected.read_text(encoding="utf-8")
    assert "MULTI_FAM_S01_V1_P01" in text
    # Sanity: it actually got the constituent assets
    assert "AUDUSD" in text
    assert "EURUSD" in text


# ---------------------------------------------------------------------------
# 2. Single-asset → Phase A §4.10 skip still holds
# ---------------------------------------------------------------------------

def test_single_asset_strategy_is_skipped(tmp_path, capsys):
    """Phase A §4.10 (commit eb4d10f): for single-asset strategies the
    per-strategy PORTFOLIO_<id>.md duplicates REPORT_<id>.md with no added
    information, so it is intentionally skipped. The path fix must NOT
    re-enable that write.
    """
    from tools.report.report_strategy_portfolio import (
        generate_strategy_portfolio_report,
    )

    state_root = tmp_path / "TradeScan_State"
    strat_dir = _seed_portfolio_evaluation(
        state_root,
        "SOLO_FAM_S01_V1_P01",
        evaluated_assets=["XAUUSD"],  # single asset
    )

    generate_strategy_portfolio_report("SOLO_FAM_S01_V1_P01", state_root)

    portfolio_md = strat_dir / "PORTFOLIO_SOLO_FAM_S01_V1_P01.md"
    assert not portfolio_md.exists(), (
        "Single-asset strategy should NOT produce PORTFOLIO_*.md (Phase A "
        f"§4.10 skip). Found unexpected file at: {portfolio_md}"
    )

    # The skip path emits a [REPORT-SKIP] log line — pin it as a visible
    # signal so the operator can tell skip apart from silent-drop.
    out = capsys.readouterr().out
    assert "[REPORT-SKIP]" in out
    assert "SOLO_FAM_S01_V1_P01" in out


# ---------------------------------------------------------------------------
# 3. No writes under PROJECT_ROOT/strategies/<id>/
# ---------------------------------------------------------------------------

def test_orchestrator_call_site_uses_state_root_not_project_root():
    """Source-level invariant: the orchestrator call site at
    ``tools/orchestration/stage_portfolio.py`` must pass ``STATE_ROOT`` to
    ``generate_strategy_portfolio_report``, never ``project_root``. A
    regression to ``project_root`` re-introduces the silent-drop bug.

    AST-level check rather than a runtime monkeypatch — keeps the
    intent legible at the call site itself.
    """
    src = (PROJECT_ROOT / "tools" / "orchestration" / "stage_portfolio.py").read_text(
        encoding="utf-8",
    )
    tree = ast.parse(src)

    call_sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fn_name = (
            fn.attr if isinstance(fn, ast.Attribute)
            else fn.id if isinstance(fn, ast.Name)
            else ""
        )
        if fn_name != "generate_strategy_portfolio_report":
            continue
        if len(node.args) < 2:
            continue
        # Second positional arg is `root_dir`. Capture the source identifier.
        root_arg = node.args[1]
        ident = (
            root_arg.id if isinstance(root_arg, ast.Name)
            else ast.unparse(root_arg)
        )
        call_sites.append((node.lineno, ident))

    assert call_sites, (
        "Expected at least one call to generate_strategy_portfolio_report in "
        "stage_portfolio.py — refactor regression?"
    )

    bad = [(ln, ident) for ln, ident in call_sites if ident == "project_root"]
    assert not bad, (
        "Regression: stage_portfolio.py passes `project_root` to "
        "generate_strategy_portfolio_report — re-introduces the 2026-05-12 "
        "silent-drop bug. Use STATE_ROOT. Offending call sites: "
        f"{bad}"
    )

    # And the positive form — every call site uses STATE_ROOT.
    for ln, ident in call_sites:
        assert ident == "STATE_ROOT", (
            f"stage_portfolio.py:{ln} passes `{ident}` to "
            f"generate_strategy_portfolio_report — expected STATE_ROOT. "
            f"The portfolio_evaluation/ directory lives under "
            f"TradeScan_State/strategies/ and the report needs root_dir to "
            f"point there for the path to resolve."
        )


def test_no_strategy_dir_created_under_project_root_on_clean_invocation(tmp_path):
    """Direct runtime check: when the report function runs against a tmp
    STATE_ROOT, it must NOT create any directories under PROJECT_ROOT.
    Pins the file-write boundary at the report function itself, not just
    at the call site.
    """
    from tools.report.report_strategy_portfolio import (
        generate_strategy_portfolio_report,
    )

    state_root = tmp_path / "TradeScan_State"
    _seed_portfolio_evaluation(
        state_root,
        "ISO_FAM_S01_V1_P01",
        evaluated_assets=["AUDUSD", "EURUSD"],  # multi-asset → real write
    )

    # Snapshot the existing contents of PROJECT_ROOT/strategies/ so any
    # new directory added by the function is detectable.
    project_strategies = PROJECT_ROOT / "strategies"
    pre_existing = (
        {p.name for p in project_strategies.iterdir() if p.is_dir()}
        if project_strategies.exists() else set()
    )

    generate_strategy_portfolio_report("ISO_FAM_S01_V1_P01", state_root)

    post = (
        {p.name for p in project_strategies.iterdir() if p.is_dir()}
        if project_strategies.exists() else set()
    )

    new_dirs = post - pre_existing
    assert "ISO_FAM_S01_V1_P01" not in new_dirs, (
        "Report function created a strategy dir under PROJECT_ROOT — "
        "ownership-boundary violation. The function should write exclusively "
        f"under the supplied root_dir ({state_root}). New dirs: {new_dirs}"
    )
