"""TD-004 regression — sweep registry auto-heal must not corrupt
existing entries when the slot key differs from the incoming request.

Background (FVG session, 2026-05-04):
  Two sibling sweeps under one idea share a transiently-matching
  signature_hash. The reservation flow saw "same lineage + same hash"
  on slot S01 and ran the auto-heal mutation BEFORE checking that the
  caller had requested a different slot ("S02"). The mutation rewrote
  S01.directive_name and S01.signature_hash to S02's values, silently
  corrupting S01's reservation.

Fix: tools/sweep_registry_gate.py:381-411 — slot-key validation now
runs before any payload mutation, and raises SWEEP_IDEMPOTENCY_MISMATCH
on mismatch so the existing slot is left untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import sweep_registry_gate as srg


# Synthetic idea_id outside the real registry's range (real max is in 60s
# as of 2026-05-04; 99 keeps this regression decoupled from production data).
SYNTHETIC_IDEA = "99"
S01_NAME = "99_REGRESSION_XAUUSD_1H_TDFOUR_S01_V1_P00"
S02_NAME = "99_REGRESSION_XAUUSD_1H_TDFOUR_S02_V1_P00"
SHARED_HASH_FULL = "a" * 64  # 64-char hex (canonical-length signature_hash)


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """Redirect sweep_registry_gate to a temp registry seeded with one
    sibling sweep whose hash collides with the incoming reservation."""
    reg_path = tmp_path / "sweep_registry.yaml"
    lock_path = tmp_path / "sweep_registry.lock"

    seed = {
        "version": 1,
        "ideas": {
            SYNTHETIC_IDEA: {
                "next_sweep": 3,
                "sweeps": {
                    "S01": {
                        "directive_name": S01_NAME,
                        "signature_hash": SHARED_HASH_FULL[:16],
                        "signature_hash_full": SHARED_HASH_FULL,
                        "reserved_at_utc": "2026-05-04T00:00:00+00:00",
                    },
                },
            },
        },
    }
    reg_path.write_text(yaml.safe_dump(seed), encoding="utf-8")

    monkeypatch.setattr(srg, "SWEEP_REGISTRY_PATH", reg_path)
    monkeypatch.setattr(srg, "SWEEP_LOCK_PATH", lock_path)
    return reg_path


def _read_registry(reg_path: Path) -> dict:
    return yaml.safe_load(reg_path.read_text(encoding="utf-8"))


class TestTD004AutoHealCorruption:

    def test_mismatched_slot_request_raises_before_mutation(self, isolated_registry):
        """Caller requests S02 but the matching-hash slot is S01 — raise
        SWEEP_IDEMPOTENCY_MISMATCH and leave S01 untouched.
        See tools/sweep_registry_gate.py:381-411 for the fix.
        """
        with pytest.raises(srg.SweepRegistryError, match="SWEEP_IDEMPOTENCY_MISMATCH"):
            srg.reserve_sweep_identity(
                idea_id=SYNTHETIC_IDEA,
                directive_name=S02_NAME,
                signature_hash=SHARED_HASH_FULL,
                requested_sweep="S02",
            )

        # Critical regression assertion — S01 must be unchanged. Pre-fix
        # the auto-heal would have rewritten directive_name to S02_NAME.
        post = _read_registry(isolated_registry)
        s01 = post["ideas"][SYNTHETIC_IDEA]["sweeps"]["S01"]
        assert s01["directive_name"] == S01_NAME, (
            f"TD-004 regression: S01.directive_name was silently rewritten "
            f"by auto-heal mutation. Got {s01['directive_name']!r}, "
            f"expected {S01_NAME!r}."
        )
        assert s01["signature_hash"] == SHARED_HASH_FULL[:16]
        assert s01["signature_hash_full"] == SHARED_HASH_FULL

    def test_matching_slot_request_returns_idempotent(self, isolated_registry):
        """Caller requests S01 against the matching slot S01 — same name,
        same hash → idempotent return. This is the legitimate happy path
        the auto-heal block exists to support; it must continue to work
        after the fix's reordering.
        """
        result = srg.reserve_sweep_identity(
            idea_id=SYNTHETIC_IDEA,
            directive_name=S01_NAME,
            signature_hash=SHARED_HASH_FULL,
            requested_sweep="S01",
        )
        assert result["status"] == "idempotent"
        assert result["sweep"] == "S01"
        assert result["strategy_name"] == S01_NAME

        # Slot still S01_NAME (no mutation, no corruption).
        post = _read_registry(isolated_registry)
        s01 = post["ideas"][SYNTHETIC_IDEA]["sweeps"]["S01"]
        assert s01["directive_name"] == S01_NAME
