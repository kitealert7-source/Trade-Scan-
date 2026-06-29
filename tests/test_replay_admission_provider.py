"""Phase 2a tests for replay_admission.admission — providers + helpers + the gate.

Covers the isolatable surface: resolve_strategy_id, materialize_replay_directive,
select_admission_provider, the DirectiveAdmission wrapper shape, and ReplayAdmission's
contract gate (raises on an inadmissible bundle BEFORE any state is written). The full
prepare_context success path writes real orchestrator state (strategies/, run_state,
registry) and is exercised by the Phase-2b end-to-end break-test.
"""
import json
from pathlib import Path

import pytest

from replay_admission.admission import (
    AdmissionProvider,
    DirectiveAdmission,
    ReplayAdmission,
    ReplayAdmissionError,
    materialize_replay_directive,
    resolve_strategy_id,
    select_admission_provider,
)
from replay_admission.bundle import ExperimentBundle
from replay_admission.contract import ExperimentConfig

EXP = ExperimentConfig(symbols=["EURUSD", "USDJPY"], broker="OctaFX", timeframe="1d",
                       start_date="2016-01-01", end_date="2026-06-25")


def _strategy_py(dirpath: Path, name="REPLAY_TEST_STRAT", indicators=("indicators.volatility.atr",)) -> Path:
    sig = {"indicators": list(indicators), "execution_rules": {"entry_logic": {"type": "x"}}}
    sp = dirpath / "strategy.py"
    sp.write_text(
        f'class Strategy:\n    name = "{name}"\n'
        "    # --- STRATEGY SIGNATURE START ---\n"
        f"    STRATEGY_SIGNATURE = {json.dumps(sig, indent=4)}\n"
        "    # --- STRATEGY SIGNATURE END ---\n",
        encoding="utf-8",
    )
    return sp


# --- resolve_strategy_id -----------------------------------------------------
def test_resolve_strategy_id_from_name_attr(tmp_path):
    sp = _strategy_py(tmp_path, name="02_VOL_IDX_1D_VOLEXP_X")
    assert resolve_strategy_id(sp, fallback="fb") == "02_VOL_IDX_1D_VOLEXP_X"


def test_resolve_strategy_id_fallback_when_absent(tmp_path):
    sp = tmp_path / "strategy.py"
    sp.write_text("class Strategy:\n    pass\n", encoding="utf-8")
    assert resolve_strategy_id(sp, fallback="bundle_dir_name") == "bundle_dir_name"


# --- materialize_replay_directive -------------------------------------------
def test_materialize_replay_directive_shape(tmp_path):
    import yaml

    path = materialize_replay_directive(tmp_path, "DIR_ID", "STRAT_ID", EXP, reason="unit")
    assert path.is_file()
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["symbols"] == ["EURUSD", "USDJPY"]
    t = doc["test"]
    assert t["name"] == "DIR_ID" and t["strategy"] == "STRAT_ID"
    assert t["broker"] == "OctaFX" and t["timeframe"] == "1d"
    assert t["start_date"] == "2016-01-01" and t["end_date"] == "2026-06-25"
    assert t["admission_kind"] == "REPLAY" and t["replay_reason"] == "unit"


# --- select_admission_provider ----------------------------------------------
def test_select_provider_bundle_dir_is_replay(tmp_path):
    _strategy_py(tmp_path)
    (tmp_path / "experiment.json").write_text("{}", encoding="utf-8")
    assert isinstance(select_admission_provider(tmp_path), ReplayAdmission)


def test_select_provider_directive_id_is_directive(tmp_path):
    # a plain directive id (not an on-disk bundle dir) → directive path
    assert isinstance(select_admission_provider("02_VOL_IDX_1D_VOLEXP_S00_V1_P00"), DirectiveAdmission)


def test_select_provider_experiment_bundle_instance_is_replay(tmp_path):
    sp = _strategy_py(tmp_path)
    b = ExperimentBundle(root=tmp_path, strategy_py=sp)
    assert isinstance(select_admission_provider(b), ReplayAdmission)


# --- provider shapes ---------------------------------------------------------
def test_providers_implement_protocol():
    assert isinstance(DirectiveAdmission(), AdmissionProvider)
    assert isinstance(ReplayAdmission(), AdmissionProvider)
    assert hasattr(DirectiveAdmission(), "prepare_context")
    assert hasattr(ReplayAdmission(), "prepare_context")


# --- ReplayAdmission contract gate (fails BEFORE writing state) -------------
def test_replay_admission_raises_on_inadmissible_bundle(tmp_path):
    # strategy.py present but NO experiment definition (no experiment.json/directive/cli)
    _strategy_py(tmp_path)
    b = ExperimentBundle(root=tmp_path, strategy_py=tmp_path / "strategy.py")
    with pytest.raises(ReplayAdmissionError) as exc:
        ReplayAdmission(tmp_path).prepare_context(b)
    assert "Admission Contract" in str(exc.value)


def test_replay_admission_raises_on_unresolved_indicator(tmp_path):
    _strategy_py(tmp_path, indicators=("indicators.fake.nope_xyz",))
    (tmp_path / "experiment.json").write_text(
        json.dumps({"symbols": ["EURUSD"], "broker": "OctaFX", "timeframe": "1d",
                    "start_date": "2016-01-01", "end_date": "2026-06-25"}),
        encoding="utf-8",
    )
    b = ExperimentBundle(root=tmp_path, strategy_py=tmp_path / "strategy.py",
                         experiment_json=tmp_path / "experiment.json")
    with pytest.raises(ReplayAdmissionError):
        ReplayAdmission(tmp_path).prepare_context(b)
