"""Phase 1 tests for replay_admission.bundle — ExperimentBundle spec + loader.

Covers: is_bundle / load_bundle member location, directive→experiment recovery, and
verify_bundle composing the Phase-0 contract incl. real indicator-manifest verification
(via the chip's snapshot tools) — manifest present (clean + drift) and absent (warning).
"""
import json
from pathlib import Path

import pytest

from replay_admission.bundle import (
    ExperimentBundle,
    experiment_from_directive,
    is_bundle,
    load_bundle,
    verify_bundle,
)
from replay_admission.contract import REPO_ROOT
from tools.run_indicator_snapshot import snapshot_indicators

REAL_INDICATOR = "indicators.volatility.atr"
CLI = {"symbols": ["EURUSD"], "broker": "OctaFX", "timeframe": "1d",
       "start_date": "2016-01-01", "end_date": "2026-06-25"}
DIRECTIVE_YAML = (
    "symbols:\n- EURUSD\n"
    "test:\n  broker: OctaFX\n  timeframe: 1d\n"
    "  start_date: '2016-01-01'\n  end_date: '2026-06-25'\n"
)


def _make_strategy_py(dirpath: Path, indicators=(REAL_INDICATOR,)) -> Path:
    sig = {"indicators": list(indicators), "execution_rules": {"entry_logic": {"type": "x"}}}
    content = (
        "from indicators.volatility.atr import atr\n"
        "class Strategy:\n"
        "    # --- STRATEGY SIGNATURE START ---\n"
        f"    STRATEGY_SIGNATURE = {json.dumps(sig, indent=4)}\n"
        "    # --- STRATEGY SIGNATURE END ---\n"
    )
    sp = dirpath / "strategy.py"
    sp.write_text(content, encoding="utf-8")
    return sp


# --- is_bundle / load_bundle ------------------------------------------------
def test_is_bundle_strategy_plus_experiment(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "experiment.json").write_text(json.dumps(CLI), encoding="utf-8")
    assert is_bundle(tmp_path)


def test_is_bundle_strategy_plus_directive(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "directive.txt").write_text(DIRECTIVE_YAML, encoding="utf-8")
    assert is_bundle(tmp_path)


def test_is_bundle_strategy_only_is_false(tmp_path):
    _make_strategy_py(tmp_path)
    assert not is_bundle(tmp_path)


def test_is_bundle_no_strategy_is_false(tmp_path):
    (tmp_path / "experiment.json").write_text(json.dumps(CLI), encoding="utf-8")
    assert not is_bundle(tmp_path)


def test_load_bundle_locates_members(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "experiment.json").write_text(json.dumps(CLI), encoding="utf-8")
    (tmp_path / "directive.txt").write_text(DIRECTIVE_YAML, encoding="utf-8")
    snapshot_indicators(tmp_path, tmp_path / "strategy.py", REPO_ROOT, write_once=False)
    b = load_bundle(tmp_path)
    assert isinstance(b, ExperimentBundle)
    assert b.strategy_py.name == "strategy.py"
    assert b.experiment_json and b.directive_txt
    assert b.indicators_manifest and b.indicators_snapshot_dir
    assert b.has_indicator_provenance


def test_load_bundle_optional_members_none(tmp_path):
    _make_strategy_py(tmp_path)
    b = load_bundle(tmp_path)
    assert b.experiment_json is None and b.directive_txt is None
    assert b.indicators_manifest is None and not b.has_indicator_provenance


def test_load_bundle_missing_strategy_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_bundle(tmp_path)


# --- experiment_from_directive ----------------------------------------------
def test_experiment_from_directive_parses_test_block(tmp_path):
    d = tmp_path / "directive.txt"
    d.write_text(DIRECTIVE_YAML, encoding="utf-8")
    exp = experiment_from_directive(d)
    assert exp["symbols"] == ["EURUSD"]
    assert exp["broker"] == "OctaFX" and exp["timeframe"] == "1d"
    assert exp["start_date"] == "2016-01-01" and exp["end_date"] == "2026-06-25"


def test_experiment_from_directive_missing_file(tmp_path):
    assert experiment_from_directive(tmp_path / "nope.txt") is None


# --- verify_bundle -----------------------------------------------------------
def test_verify_bundle_experiment_json_no_manifest_warns(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "experiment.json").write_text(json.dumps(CLI), encoding="utf-8")
    res = verify_bundle(tmp_path)
    assert res.ok, res.errors
    assert res.experiment_source == "experiment.json"
    assert any("indicator provenance absent" in w for w in res.warnings)


def test_verify_bundle_recovers_experiment_from_directive(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "directive.txt").write_text(DIRECTIVE_YAML, encoding="utf-8")
    res = verify_bundle(tmp_path)  # no experiment.json, no cli → recover from directive
    assert res.ok, res.errors
    assert res.experiment_source == "recovered"
    assert res.experiment.symbols == ["EURUSD"]


def test_verify_bundle_real_manifest_clean(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "experiment.json").write_text(json.dumps(CLI), encoding="utf-8")
    snapshot_indicators(tmp_path, tmp_path / "strategy.py", REPO_ROOT, write_once=False)
    res = verify_bundle(tmp_path)
    assert res.ok, res.errors
    assert not any("indicator provenance absent" in w for w in res.warnings)  # manifest present


def test_verify_bundle_drift_fails_loud(tmp_path):
    _make_strategy_py(tmp_path)
    (tmp_path / "experiment.json").write_text(json.dumps(CLI), encoding="utf-8")
    snapshot_indicators(tmp_path, tmp_path / "strategy.py", REPO_ROOT, write_once=False)
    # Tamper the recorded hash → live atr no longer matches → drift.
    mpath = tmp_path / "indicators_manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["modules"][0]["sha256"] = "0" * 64
    mpath.write_text(json.dumps(m), encoding="utf-8")
    res = verify_bundle(tmp_path)
    assert not res.ok
    assert any("DRIFT" in e for e in res.errors)


def test_verify_bundle_no_experiment_definition_fails(tmp_path):
    _make_strategy_py(tmp_path)  # strategy.py only, nothing to define the experiment
    res = verify_bundle(tmp_path)
    assert not res.ok
    assert any("no definition" in e for e in res.errors)
