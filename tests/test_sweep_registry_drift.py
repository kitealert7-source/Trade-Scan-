"""Lock sweep-registry DRIFT attribution + the human-gated repair tool.

The gate (tools/sweep_registry_gate.py) distinguishes a mis-filed (drifted) slot from a
genuine collision: when the occupying entry's directive_name parses to coordinates that
contradict the slot, it raises REGISTRY_DRIFT; otherwise the original COLLISION. The repair
tool (tools/repair_sweep_registry.py) is the sanctioned human-approved fix -- dry-run by
default, removing only the drifted entry on --apply, never touching siblings or the ledger.

Uses a self-contained synthetic registry (NOT the live one) so it cannot go flaky if the
real registry's drift is later repaired.
"""
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.sweep_registry_gate as G  # noqa: E402
import tools.repair_sweep_registry as R  # noqa: E402


def _full(c):
    return c * 64


def _short(c):
    return c * 16


def _registry():
    """Idea 22, sweep S02: a DRIFTED patch (S03 directive in the S02/P02 slot) and a
    CONSISTENT patch (S02 directive in the S02/P05 slot)."""
    return {
        "ideas": {
            "22": {
                "next_sweep": 3,
                "sweeps": {
                    "S02": {
                        "directive_name": "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P00",
                        "signature_hash": _short("1"),
                        "signature_hash_full": _full("1"),
                        "patches": {
                            "P02": {  # DRIFT: an S03 directive mis-filed under S02/P02
                                "directive_name": "22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P02",
                                "signature_hash": _short("2"),
                                "signature_hash_full": _full("2"),
                            },
                            "P05": {  # CONSISTENT: an S02 directive correctly under S02/P05
                                "directive_name": "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05",
                                "signature_hash": _short("3"),
                                "signature_hash_full": _full("3"),
                            },
                        },
                    },
                },
            },
        },
    }


@pytest.fixture
def temp_registry(tmp_path, monkeypatch):
    reg = tmp_path / "sweep_registry.yaml"
    reg.write_text(yaml.safe_dump(_registry(), sort_keys=False), encoding="utf-8")
    lock = tmp_path / "sweep_registry.yaml.lock"
    for mod in (G, R):
        monkeypatch.setattr(mod, "SWEEP_REGISTRY_PATH", reg)
        monkeypatch.setattr(mod, "SWEEP_LOCK_PATH", lock)
    return reg


# ---- gate attribution -------------------------------------------------------

def test_gate_drift_emits_registry_drift(temp_registry):
    with pytest.raises(G.SweepRegistryError) as ei:
        G.reserve_sweep_identity(
            "22", "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P02",
            _full("9"), requested_sweep="S02")
    assert "REGISTRY_DRIFT" in str(ei.value)
    assert "PATCH_COLLISION" not in str(ei.value)


def test_gate_consistent_slot_emits_patch_collision(temp_registry):
    with pytest.raises(G.SweepRegistryError) as ei:
        G.reserve_sweep_identity(
            "22", "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05",
            _full("9"), requested_sweep="S02")
    assert "PATCH_COLLISION" in str(ei.value)
    assert "REGISTRY_DRIFT" not in str(ei.value)


# ---- repair tool ------------------------------------------------------------

def test_repair_dry_run_makes_no_mutation(temp_registry):
    before = temp_registry.read_text(encoding="utf-8")
    sys.argv = ["repair", "--idea", "22", "--sweep", "S02", "--patch", "P02"]  # no --apply
    rc = R.main()
    assert rc == 0
    assert temp_registry.read_text(encoding="utf-8") == before  # unchanged


def test_repair_apply_removes_only_drifted_entry(temp_registry):
    sys.argv = ["repair", "--idea", "22", "--sweep", "S02", "--patch", "P02", "--apply"]
    rc = R.main()
    assert rc == 0
    reg = yaml.safe_load(temp_registry.read_text(encoding="utf-8"))
    patches = reg["ideas"]["22"]["sweeps"]["S02"]["patches"]
    assert "P02" not in patches                         # drifted entry removed
    assert "P05" in patches                             # sibling patch preserved
    assert (reg["ideas"]["22"]["sweeps"]["S02"]["directive_name"]
            == "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P00")  # sweep owner intact


def test_repair_refuses_to_touch_a_consistent_slot(temp_registry):
    sys.argv = ["repair", "--idea", "22", "--sweep", "S02", "--patch", "P05", "--apply"]
    rc = R.main()
    assert rc == 1  # not drifted -> refuse (genuine, not corruption)
    reg = yaml.safe_load(temp_registry.read_text(encoding="utf-8"))
    assert "P05" in reg["ideas"]["22"]["sweeps"]["S02"]["patches"]  # untouched


# ---- orphan-reservation release ---------------------------------------------
# An FS-orphan is a namespace lock with no backing strategy folder AND no run
# history -- a failed-attempt signature-idempotency lock. Distinct from DRIFT
# (a mis-filed but present strategy). Releasing it frees the slot + signature so
# the concept can register fresh. The runs-history check is the safety rail:
# a pruned-but-ran strategy keeps real provenance and must NOT be released.

from datetime import datetime, timezone  # noqa: E402

_ORPHAN_NAME = "22_CONT_FX_15M_RSIAVG_TRENDFILT_S20_V1_P00"


def _orphan_reg():
    return {"ideas": {"22": {"next_sweep": 21, "sweeps": {"S20": {
        "directive_name": _ORPHAN_NAME,
        "signature_hash": _short("a"), "signature_hash_full": _full("a"),
        "patches": {}}}}}}


@pytest.fixture
def orphan_registry(tmp_path, monkeypatch):
    reg = tmp_path / "sweep_registry.yaml"
    reg.write_text(yaml.safe_dump(_orphan_reg(), sort_keys=False), encoding="utf-8")
    lock = tmp_path / "sweep_registry.yaml.lock"
    for mod in (G, R):
        monkeypatch.setattr(mod, "SWEEP_REGISTRY_PATH", reg)
        monkeypatch.setattr(mod, "SWEEP_LOCK_PATH", lock)
    monkeypatch.setattr(R, "STRATEGIES_DIR", tmp_path / "strategies")
    return reg, tmp_path


def _no_runs(_name):
    return None


def _has_runs(_name):
    return datetime(2026, 5, 3, tzinfo=timezone.utc)


def test_orphan_true_when_folder_gone_and_no_runs(orphan_registry, monkeypatch):
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _no_runs)
    assert R._is_fs_orphan(_ORPHAN_NAME) is True


def test_orphan_false_when_folder_exists(orphan_registry, monkeypatch):
    _, tmp = orphan_registry
    (tmp / "strategies" / _ORPHAN_NAME).mkdir(parents=True)
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _no_runs)
    assert R._is_fs_orphan(_ORPHAN_NAME) is False


def test_orphan_false_when_has_run_history(orphan_registry, monkeypatch):
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _has_runs)
    assert R._is_fs_orphan(_ORPHAN_NAME) is False


def test_release_orphan_dry_run_no_mutation(orphan_registry, monkeypatch):
    reg, _ = orphan_registry
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _no_runs)
    before = reg.read_text(encoding="utf-8")
    assert R.cmd_release_orphan(R._load_yaml(reg), "22", "S20", None, apply=False) == 0
    assert reg.read_text(encoding="utf-8") == before


def test_release_orphan_apply_removes_reservation(orphan_registry, monkeypatch):
    reg, _ = orphan_registry
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _no_runs)
    assert R.cmd_release_orphan(R._load_yaml(reg), "22", "S20", None, apply=True) == 0
    assert "S20" not in yaml.safe_load(reg.read_text(encoding="utf-8"))["ideas"]["22"]["sweeps"]


def test_release_refuses_when_folder_exists(orphan_registry, monkeypatch):
    reg, tmp = orphan_registry
    (tmp / "strategies" / _ORPHAN_NAME).mkdir(parents=True)
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _no_runs)
    assert R.cmd_release_orphan(R._load_yaml(reg), "22", "S20", None, apply=True) == 1
    assert "S20" in yaml.safe_load(reg.read_text(encoding="utf-8"))["ideas"]["22"]["sweeps"]


def test_release_refuses_when_has_run_history(orphan_registry, monkeypatch):
    reg, _ = orphan_registry
    monkeypatch.setattr(R, "_get_directive_first_execution_timestamp", _has_runs)
    assert R.cmd_release_orphan(R._load_yaml(reg), "22", "S20", None, apply=True) == 1
    assert "S20" in yaml.safe_load(reg.read_text(encoding="utf-8"))["ideas"]["22"]["sweeps"]
