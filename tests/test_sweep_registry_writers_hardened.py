"""Regression tests for INFRA-AUDIT C3 + M5 closure — sweep_registry writers.

Before fix:
  * `tools/orchestration/pre_execution.py::_update_sweep_registry_hash` used
    substring matching (`if f"directive_name: {strategy_name}" in lines[i]`)
    + direct write_text(), no lock. Substring vulnerability: directive
    "22_CONT_FX_15M" could match "22_CONT_FX_15M_RSIAVG" and "22_CONT_FX_15M_RSI"
    if both existed. Concurrency vulnerability: race with the canonical
    sweep_registry_gate writer.
  * `tools/new_pass.py::_register_patch` used regex-anchored text
    substitution + direct write_text(), no lock. Same race surface.

After fix:
  * Both callers route through the new canonical
    `tools/sweep_registry_gate.py::update_sweep_signature_hash` (for hash
    updates) or `reserve_sweep_identity` (for patch registration).
  * Both APIs acquire SWEEP_LOCK and use EXACT directive_name matching.
  * Tests verify: exact-identity match, no substring match, lock acquisition,
    no-op idempotency, and that bypass call sites no longer mutate YAML
    directly.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.sweep_registry_gate import (
    update_sweep_signature_hash,
    reserve_sweep_identity,
    SweepRegistryError,
)
import tools.sweep_registry_gate as srg_mod


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """Isolated sweep_registry.yaml seeded with a substring-collision case."""
    reg = tmp_path / "sweep_registry.yaml"
    lock = tmp_path / "sweep_registry.lock"
    seed = {
        "ideas": {
            "22": {
                "next_sweep": 4,
                "sweeps": {
                    "S01": {
                        "directive_name": "22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P00",
                        "signature_hash": "aaaa111122223333",
                        "signature_hash_full": "aaaa111122223333" + "0" * 48,
                        "reserved_at_utc": "2026-01-01T00:00:00+00:00",
                        "patches": {
                            "P01": {
                                "directive_name": "22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P01",
                                "signature_hash": "bbbb444455556666",
                                "signature_hash_full": "bbbb444455556666" + "0" * 48,
                                "reserved_at_utc": "2026-01-02T00:00:00+00:00",
                            }
                        }
                    },
                    "S02": {
                        # Substring-collision case: this directive's stem includes
                        # the literal text of S01's directive_name as a prefix-ish.
                        # The OLD substring matcher would have hit S01 by accident
                        # if it scanned for "22_CONT_FX_15M".
                        "directive_name": "22_CONT_FX_15M_RSIAVG_NEWSFILT_S02_V1_P00",
                        "signature_hash": "cccc777788889999",
                        "signature_hash_full": "cccc777788889999" + "0" * 48,
                        "reserved_at_utc": "2026-01-03T00:00:00+00:00",
                        "patches": {}
                    },
                    "S03": {
                        "directive_name": "22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P00",
                        "signature_hash": "dddd000011112222",
                        "signature_hash_full": "dddd000011112222" + "0" * 48,
                        "reserved_at_utc": "2026-01-04T00:00:00+00:00",
                        "patches": {}
                    }
                }
            }
        }
    }
    reg.write_text(yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(srg_mod, "SWEEP_REGISTRY_PATH", reg)
    monkeypatch.setattr(srg_mod, "SWEEP_LOCK_PATH", lock)
    return reg


# ---------------------------------------------------------------------------
# update_sweep_signature_hash — exact-identity, lock-protected
# ---------------------------------------------------------------------------

def test_update_finds_exact_directive_in_sweep_owner(isolated_registry):
    """Exact match on a sweep-level directive_name updates only that slot."""
    new_hash = "ffff" * 16  # 64-char hex
    result = update_sweep_signature_hash(
        idea_id="22",
        directive_name="22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P00",
        signature_hash=new_hash,
    )
    assert result["status"] == "updated"
    assert result["sweep"] == "S03"
    assert result["patch"] is None
    # Verify the on-disk YAML matches
    on_disk = yaml.safe_load(isolated_registry.read_text(encoding="utf-8"))
    s03 = on_disk["ideas"]["22"]["sweeps"]["S03"]
    assert s03["signature_hash_full"] == new_hash
    # Other slots untouched
    assert on_disk["ideas"]["22"]["sweeps"]["S01"]["signature_hash"] == "aaaa111122223333"
    assert on_disk["ideas"]["22"]["sweeps"]["S02"]["signature_hash"] == "cccc777788889999"


def test_update_finds_exact_directive_in_patch(isolated_registry):
    """Exact match on a patch directive_name updates only that patch."""
    new_hash = "1234" * 16
    result = update_sweep_signature_hash(
        idea_id="22",
        directive_name="22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P01",
        signature_hash=new_hash,
    )
    assert result["status"] == "updated"
    assert result["sweep"] == "S01"
    assert result["patch"] == "P01"
    on_disk = yaml.safe_load(isolated_registry.read_text(encoding="utf-8"))
    p01 = on_disk["ideas"]["22"]["sweeps"]["S01"]["patches"]["P01"]
    assert p01["signature_hash_full"] == new_hash
    # Sweep owner of S01 untouched
    assert on_disk["ideas"]["22"]["sweeps"]["S01"]["signature_hash"] == "aaaa111122223333"


def test_update_no_substring_collision(isolated_registry):
    """The old substring matcher would have updated whichever entry matched
    `directive_name: 22_CONT_FX_15M` first. The new exact-match API only
    updates entries whose directive_name is EXACTLY equal."""
    # Pass the COMMON prefix as the directive_name — should fail to find
    # exact match and raise (NOT silently update something else).
    with pytest.raises(SweepRegistryError) as excinfo:
        update_sweep_signature_hash(
            idea_id="22",
            directive_name="22_CONT_FX_15M",  # prefix only, no exact match
            signature_hash="ffff" * 16,
        )
    assert "SWEEP_NOT_FOUND" in str(excinfo.value)
    # Verify NO on-disk mutation
    on_disk = yaml.safe_load(isolated_registry.read_text(encoding="utf-8"))
    assert on_disk["ideas"]["22"]["sweeps"]["S01"]["signature_hash"] == "aaaa111122223333"
    assert on_disk["ideas"]["22"]["sweeps"]["S02"]["signature_hash"] == "cccc777788889999"
    assert on_disk["ideas"]["22"]["sweeps"]["S03"]["signature_hash"] == "dddd000011112222"


def test_update_idempotent_when_hash_unchanged(isolated_registry):
    """Updating with the same hash that's already recorded is a no-op."""
    existing = "aaaa111122223333" + "0" * 48
    result = update_sweep_signature_hash(
        idea_id="22",
        directive_name="22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P00",
        signature_hash=existing,
    )
    assert result["status"] == "unchanged"


def test_update_unknown_directive_raises(isolated_registry):
    """Updating a directive that isn't in the registry raises SWEEP_NOT_FOUND."""
    with pytest.raises(SweepRegistryError) as excinfo:
        update_sweep_signature_hash(
            idea_id="22",
            directive_name="22_BOGUS_NEVER_REGISTERED_S99_V1_P00",
            signature_hash="abcd" * 16,
        )
    assert "SWEEP_NOT_FOUND" in str(excinfo.value)


def test_update_missing_idea_raises(isolated_registry):
    """Updating under an idea_id that doesn't exist raises SWEEP_IDEA_UNREGISTERED."""
    with pytest.raises(SweepRegistryError) as excinfo:
        update_sweep_signature_hash(
            idea_id="99",  # not in seed
            directive_name="99_FAKE_S01_V1_P00",
            signature_hash="abcd" * 16,
        )
    assert "SWEEP_IDEA_UNREGISTERED" in str(excinfo.value)


def test_update_invalid_idea_format_raises(isolated_registry):
    """idea_id must be two-digit numeric."""
    with pytest.raises(SweepRegistryError):
        update_sweep_signature_hash(
            idea_id="abc",
            directive_name="anything",
            signature_hash="ffff" * 16,
        )


# ---------------------------------------------------------------------------
# Bypass call sites — verify they no longer mutate YAML directly
# ---------------------------------------------------------------------------

def test_pre_execution_uses_canonical_api():
    """Static check: pre_execution.py's _update_sweep_registry_hash MUST
    route through the canonical API and MUST NOT contain direct YAML
    write_text() or substring 'directive_name:' matching."""
    src = (PROJECT_ROOT / "tools" / "orchestration" / "pre_execution.py"
           ).read_text(encoding="utf-8")
    # Must reference the canonical API
    assert "update_sweep_signature_hash" in src, (
        "pre_execution.py must import update_sweep_signature_hash"
    )
    # Locate the function body
    fn_match = re.search(
        r"def _update_sweep_registry_hash\(.*?\)(.*?)(?=\n(?:def |\Z))",
        src, re.DOTALL,
    )
    assert fn_match, "_update_sweep_registry_hash function not found"
    body = fn_match.group(1)
    # Must NOT do direct write_text on the registry
    assert "registry_path.write_text" not in body, (
        "pre_execution.py still does direct write_text on sweep_registry.yaml"
    )
    # Must NOT do substring 'directive_name:' matching
    assert 'f"directive_name:' not in body, (
        "pre_execution.py still uses substring 'directive_name:' matching"
    )


def test_new_pass_uses_canonical_api():
    """Static check: new_pass.py's _register_patch MUST route through
    reserve_sweep_identity and MUST NOT contain direct YAML write_text() or
    text-substitution patch insertion."""
    src = (PROJECT_ROOT / "tools" / "new_pass.py").read_text(encoding="utf-8")
    fn_match = re.search(
        r"def _register_patch\(.*?\)(.*?)(?=\n(?:def |\Z))",
        src, re.DOTALL,
    )
    assert fn_match, "_register_patch function not found"
    body = fn_match.group(1)
    assert "reserve_sweep_identity" in body, (
        "new_pass.py _register_patch must use reserve_sweep_identity"
    )
    # Must NOT do direct YAML writes
    assert "SWEEP_REGISTRY.write_text" not in body, (
        "new_pass.py _register_patch still does direct write_text on sweep_registry.yaml"
    )


# ---------------------------------------------------------------------------
# Lock acquisition (smoke check)
# ---------------------------------------------------------------------------

def test_lock_acquired_during_update(isolated_registry, monkeypatch):
    """update_sweep_signature_hash must acquire SWEEP_LOCK_PATH. We instrument
    _acquire_lock / _release_lock to count calls."""
    calls = {"acq": 0, "rel": 0}
    real_acq = srg_mod._acquire_lock
    real_rel = srg_mod._release_lock
    def fake_acq(path):
        calls["acq"] += 1
        return real_acq(path)
    def fake_rel(fd, path):
        calls["rel"] += 1
        return real_rel(fd, path)
    monkeypatch.setattr(srg_mod, "_acquire_lock", fake_acq)
    monkeypatch.setattr(srg_mod, "_release_lock", fake_rel)

    update_sweep_signature_hash(
        idea_id="22",
        directive_name="22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P00",
        signature_hash="ffff" * 16,
    )
    assert calls["acq"] == 1
    assert calls["rel"] == 1


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
