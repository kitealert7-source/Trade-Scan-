"""Phase 0 tests for replay_admission.contract — read-only Admission Contract.

Covers: strategy.py validation, experiment-definition normalization (3 sources +
precedence + "strategy.py only" case), indicator resolvability, and failure modes.
"""
import json
from pathlib import Path

import pytest

from replay_admission.contract import (
    ExperimentConfig,
    normalize_experiment,
    verify_experiment,
    extract_signature,
)

REAL_INDICATOR = "indicators.volatility.atr"  # exists in the repo


def _make_strategy(dirpath: Path, indicators=None, with_markers=True) -> Path:
    indicators = indicators if indicators is not None else [REAL_INDICATOR]
    sig = {"indicators": indicators, "execution_rules": {"entry_logic": {"type": "x"}}}
    body = json.dumps(sig, indent=4)
    if with_markers:
        content = (
            "class Strategy:\n"
            "    # --- STRATEGY SIGNATURE START ---\n"
            f"    STRATEGY_SIGNATURE = {body}\n"
            "    # --- STRATEGY SIGNATURE END ---\n"
        )
    else:
        content = f"class Strategy:\n    STRATEGY_SIGNATURE = {body}\n"
    sp = dirpath / "strategy.py"
    sp.write_text(content, encoding="utf-8")
    return sp


CLI = {"symbols": ["EURUSD"], "broker": "OctaFX", "timeframe": "1d",
       "start_date": "2016-01-01", "end_date": "2026-06-25"}


# --- verify_experiment happy path -------------------------------------------
def test_strategy_only_plus_cli_is_valid(tmp_path):
    _make_strategy(tmp_path)
    res = verify_experiment(tmp_path, cli=CLI)
    assert res.ok, res.errors
    assert res.experiment_source == "explicit"
    assert res.strategy_hash and len(res.strategy_hash) == 64
    assert REAL_INDICATOR in res.indicators


def test_experiment_json_source(tmp_path):
    _make_strategy(tmp_path)
    ej = tmp_path / "experiment.json"
    ej.write_text(json.dumps(CLI), encoding="utf-8")
    res = verify_experiment(tmp_path, experiment_json=ej, cli=CLI)
    assert res.ok, res.errors
    assert res.experiment_source == "experiment.json"  # json wins over cli


def test_recovered_source(tmp_path):
    _make_strategy(tmp_path)
    res = verify_experiment(tmp_path, recovered=CLI)
    assert res.ok, res.errors
    assert res.experiment_source == "recovered"


# --- failure modes -----------------------------------------------------------
def test_missing_strategy_py(tmp_path):
    res = verify_experiment(tmp_path, cli=CLI)
    assert not res.ok
    assert any("strategy.py not found" in e for e in res.errors)


def test_missing_signature_markers(tmp_path):
    _make_strategy(tmp_path, with_markers=False)
    res = verify_experiment(tmp_path, cli=CLI)
    assert not res.ok
    assert any("STRATEGY_SIGNATURE" in e for e in res.errors)


def test_no_experiment_definition_fails_loud(tmp_path):
    _make_strategy(tmp_path)
    res = verify_experiment(tmp_path)  # no json, no cli, no recovered
    assert not res.ok
    assert any("no definition" in e for e in res.errors)


def test_unresolved_indicator(tmp_path):
    _make_strategy(tmp_path, indicators=["indicators.fake.nonexistent_xyz"])
    res = verify_experiment(tmp_path, cli=CLI)
    assert not res.ok
    assert any("indicator unresolved" in e for e in res.errors)


def test_indicator_not_under_indicators_pkg(tmp_path):
    _make_strategy(tmp_path, indicators=["engines.something"])
    res = verify_experiment(tmp_path, cli=CLI)
    assert not res.ok
    assert any("not under indicators/" in e for e in res.errors)


# --- normalize_experiment ----------------------------------------------------
def test_normalize_precedence_json_over_cli_over_recovered(tmp_path):
    ej = tmp_path / "experiment.json"
    ej.write_text(json.dumps({**CLI, "broker": "FROM_JSON"}), encoding="utf-8")
    cfg, src, errs = normalize_experiment(
        experiment_json=ej, cli={**CLI, "broker": "FROM_CLI"}, recovered={**CLI, "broker": "FROM_REC"}
    )
    assert not errs and src == "experiment.json" and cfg.broker == "FROM_JSON"

    cfg, src, _ = normalize_experiment(cli={**CLI, "broker": "FROM_CLI"}, recovered={**CLI})
    assert src == "explicit" and cfg.broker == "FROM_CLI"

    cfg, src, _ = normalize_experiment(recovered={**CLI, "broker": "FROM_REC"})
    assert src == "recovered" and cfg.broker == "FROM_REC"


def test_normalize_accepts_start_end_aliases(tmp_path):
    cfg, src, errs = normalize_experiment(
        cli={"symbols": ["EURUSD"], "tf": "1d", "start": "2016-01-01", "end": "2026-06-25"}
    )
    assert not errs
    assert cfg.timeframe == "1d" and cfg.start_date == "2016-01-01" and cfg.end_date == "2026-06-25"
    assert cfg.broker == "OctaFX"  # default


def test_experiment_config_validate_flags_empty_symbols():
    cfg = ExperimentConfig(symbols=[], broker="OctaFX", timeframe="1d",
                           start_date="2016-01-01", end_date="2026-06-25")
    errs = cfg.validate()
    assert any("no symbols" in e for e in errs)
