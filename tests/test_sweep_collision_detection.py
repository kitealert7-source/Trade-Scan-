"""Regression test for INFRA-NEWS-009 — sweep slot collision detection.

Before fix: registering an occupied sweep slot with a different directive_name
either silently overwrote the entry (direct YAML edits) or raised a generic
SWEEP_COLLISION error without suggesting recovery.

After fix:
  * SWEEP_COLLISION error message includes the next free slot suggestion.
  * The recommended path (CLI helper / API call) hard-fails on collision and
    reports the next free slot the caller should use.
  * Same identity registering the same slot is still idempotent (no false
    positive collision).

Note: tests use a temp sweep_registry.yaml via monkeypatching to avoid any
mutation of the production registry.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import yaml

from tools.sweep_registry_gate import (
    reserve_sweep_identity,
    SweepRegistryError,
)
import tools.sweep_registry_gate as srg_mod


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    reg = tmp_path / "sweep_registry.yaml"
    lock = tmp_path / "sweep_registry.lock"
    # Seed: idea 99 has S05 already claimed.
    seed = {
        "ideas": {
            "99": {
                "next_sweep": 6,
                "sweeps": {
                    "S05": {
                        "directive_name": "99_TEST_FX_15M_FAKE_S05_V1_P00",
                        "signature_hash": "abc1234567890def",
                        "signature_hash_full": "abc1234567890def" + "0" * 48,
                        "reserved_at_utc": "2026-05-03T00:00:00+00:00",
                    }
                }
            }
        }
    }
    reg.write_text(yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(srg_mod, "SWEEP_REGISTRY_PATH", reg)
    monkeypatch.setattr(srg_mod, "SWEEP_LOCK_PATH", lock)
    return reg


def test_collision_with_different_directive_hard_fails(isolated_registry):
    """Trying to claim S05 (already held by 99_TEST_FX_15M_FAKE_S05_V1_P00) with a
    different directive_name must HARD_FAIL with SWEEP_COLLISION."""
    with pytest.raises(SweepRegistryError) as excinfo:
        reserve_sweep_identity(
            idea_id="99",
            directive_name="99_TEST_FX_30M_OTHER_S05_V1_P00",  # different
            signature_hash="ff" * 32,
            requested_sweep="S05",
            auto_advance=True,
        )
    msg = str(excinfo.value)
    assert "SWEEP_COLLISION" in msg
    assert "99_TEST_FX_15M_FAKE_S05_V1_P00" in msg


def test_collision_error_suggests_next_free_slot(isolated_registry):
    """The SWEEP_COLLISION error must surface the next free slot for remediation."""
    with pytest.raises(SweepRegistryError) as excinfo:
        reserve_sweep_identity(
            idea_id="99",
            directive_name="99_TEST_FX_30M_OTHER_S05_V1_P00",
            signature_hash="ff" * 32,
            requested_sweep="S05",
            auto_advance=True,
        )
    msg = str(excinfo.value)
    assert "Next free slot" in msg
    # next_sweep was 6, S06 is free → should suggest S06
    assert "S06" in msg


def test_same_identity_idempotent_no_collision(isolated_registry):
    """Re-registering the same directive at the same slot is idempotent."""
    result = reserve_sweep_identity(
        idea_id="99",
        directive_name="99_TEST_FX_15M_FAKE_S05_V1_P00",
        signature_hash="abc1234567890def" + "0" * 48,
        requested_sweep="S05",
        auto_advance=True,
    )
    assert result["status"] == "idempotent"
    assert result["sweep"] == "S05"


def test_auto_advance_picks_next_free_slot(isolated_registry):
    """No requested_sweep + auto_advance → picks the next free slot, not S05."""
    result = reserve_sweep_identity(
        idea_id="99",
        directive_name="99_TEST_FX_1H_NEW_S99_V1_P00",
        signature_hash="11" * 32,
        requested_sweep=None,
        auto_advance=True,
    )
    assert result["status"] == "reserved"
    assert result["sweep"] == "S06"


def test_collision_at_specific_slot_with_existing_patch_sibling(isolated_registry):
    """If the new directive is a patch-sibling of the slot owner, it should be
    accepted as a patch under that slot (not flagged as collision). Verifies
    the collision check doesn't false-positive on legitimate patch additions."""
    result = reserve_sweep_identity(
        idea_id="99",
        directive_name="99_TEST_FX_15M_FAKE_S05_V1_P01",  # patch-sibling
        signature_hash="22" * 32,
        requested_sweep="S05",
        auto_advance=True,
    )
    assert result["status"] == "reserved"
    assert result["sweep"] == "S05"


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
