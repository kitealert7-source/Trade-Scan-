"""
Tests for the EARLY identity-tuple guard in tools/namespace_gate.py.

Verifies the registered-identity-set rule (forward-only, append-only):
  * a directive reusing an idea_id with a NEW (family/model/symbol/timeframe)
    tuple FAILs -- the tuple is not in that idea_id's registered identity set;
  * a tuple already registered under the idea_id (same identity, any
    sweep/variant/patch) PASSes (grandfathered, self-match);
  * a fresh idea_id (no registered identities yet) PASSes.

All state is synthesized under tmp_path; the production sweep_registry is never
read (DB/registry-touching test isolation).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.namespace_gate import (
    NamespaceValidationError,
    _registered_identity_set,
    _check_identity_registered,
)

# idea 42 = a legacy multi-symbol fan-out (mirrors the real registry shape: one
# idea_id owning many same-(family,model,tf) symbols, plus a patch under a sweep).
# idea 73 = a single-identity idea (the post-incident remediated shape).
_REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    ideas:
      '42':
        sweeps:
          S01:
            directive_name: 42_REV_EURUSD_1H_LIQSWEEP_S01_V1_P00
            signature_hash: aaaaaaaaaaaaaaaa
          S02:
            directive_name: 42_REV_USDJPY_1H_LIQSWEEP_S02_V1_P00
            signature_hash: bbbbbbbbbbbbbbbb
            patches:
              P02:
                directive_name: 42_REV_USDJPY_1H_LIQSWEEP_S02_V1_P02
                signature_hash: cccccccccccccccc
      '73':
        sweeps:
          S01:
            directive_name: 73_MR_US30_1D_VOLPULL_ATRFILT_S01_V1_P00
            signature_hash: dddddddddddddddd
    """)


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    p = tmp_path / "sweep_registry.yaml"
    p.write_text(_REGISTRY_YAML, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# Registered-identity-set extraction
# --------------------------------------------------------------------------- #
class TestRegisteredIdentitySet:
    def test_collects_sweeps_and_patches(self, registry: Path):
        s = _registered_identity_set("42", registry)
        assert ("REV", "LIQSWEEP", "EURUSD", "1H") in s
        assert ("REV", "LIQSWEEP", "USDJPY", "1H") in s
        # The S02 patch shares the S02 tuple -> the set still holds one USDJPY entry.
        assert len([t for t in s if t[2] == "USDJPY"]) == 1
        assert len(s) == 2

    def test_unknown_idea_is_empty(self, registry: Path):
        assert _registered_identity_set("99", registry) == set()

    def test_missing_registry_is_empty(self, tmp_path: Path):
        assert _registered_identity_set("42", tmp_path / "nope.yaml") == set()


# --------------------------------------------------------------------------- #
# The guard itself
# --------------------------------------------------------------------------- #
class TestIdentityGuard:
    # --- FAIL: a NEW tuple under an existing idea_id ---
    def test_new_symbol_fails(self, registry: Path):
        with pytest.raises(NamespaceValidationError) as ei:
            _check_identity_registered("73", ("MR", "VOLPULL", "NAS100", "1D"), registry)
        msg = str(ei.value)
        assert "NAMESPACE_IDENTITY_NOT_REGISTERED" in msg
        assert "not registered under idea_id '73'" in msg
        assert "MR VOLPULL US30 1D" in msg      # the registered identity is listed
        assert "MR VOLPULL NAS100 1D" in msg    # the current identity is shown
        assert "Allocate a new sequential idea_id" in msg

    def test_new_family_fails(self, registry: Path):
        with pytest.raises(NamespaceValidationError):
            _check_identity_registered("73", ("STR", "VOLPULL", "US30", "1D"), registry)

    def test_new_model_fails(self, registry: Path):
        with pytest.raises(NamespaceValidationError):
            _check_identity_registered("73", ("MR", "VOLEXP", "US30", "1D"), registry)

    def test_new_timeframe_fails(self, registry: Path):
        with pytest.raises(NamespaceValidationError):
            _check_identity_registered("73", ("MR", "VOLPULL", "US30", "4H"), registry)

    def test_new_symbol_under_multisymbol_idea_fails(self, registry: Path):
        # idea 42 is a legacy multi-symbol fan-out; a brand-new symbol still fails
        # forward (allocate a new idea_id) even though the idea owns many tuples.
        with pytest.raises(NamespaceValidationError):
            _check_identity_registered("42", ("REV", "LIQSWEEP", "US30", "1H"), registry)

    # --- PASS: grandfathered / self-match / fresh idea ---
    def test_registered_symbol_passes(self, registry: Path):
        # Returns None (no raise) for an already-registered identity.
        assert _check_identity_registered(
            "42", ("REV", "LIQSWEEP", "EURUSD", "1H"), registry
        ) is None

    def test_registered_identity_via_patch_passes(self, registry: Path):
        # USDJPY 1H is registered (S02 owner + its patch) -> any sweep/variant of
        # the SAME identity passes (S/V/P are not part of the identity tuple).
        assert _check_identity_registered(
            "42", ("REV", "LIQSWEEP", "USDJPY", "1H"), registry
        ) is None

    def test_fresh_idea_passes(self, registry: Path):
        # idea 88 has no registered identities -> establishes its first here.
        assert _check_identity_registered(
            "88", ("MR", "VOLPULL", "US30", "1D"), registry
        ) is None


# --------------------------------------------------------------------------- #
# End-to-end through validate_namespace (the surface directive_linter.py / the
# admission Stage -0.30 actually call), with all registry paths isolated.
# --------------------------------------------------------------------------- #
class TestValidateNamespaceIntegration:
    def _setup_paths(self, tmp_path: Path, monkeypatch, registry: Path):
        import tools.namespace_gate as ng

        token_dict = tmp_path / "token_dictionary.yaml"
        token_dict.write_text(
            textwrap.dedent("""\
                family: [MR]
                model: [VOLPULL]
                filter: [ATRFILT]
                timeframe: [1D]
                aliases: {}
            """),
            encoding="utf-8",
        )
        idea_reg = tmp_path / "idea_registry.yaml"
        idea_reg.write_text(
            textwrap.dedent("""\
                version: 1
                ideas:
                  '73':
                    family: MR
                    class: indicator_logic
                    regime: range
                    role: entry_edge
            """),
            encoding="utf-8",
        )
        monkeypatch.setattr(ng, "TOKEN_DICTIONARY_PATH", token_dict)
        monkeypatch.setattr(ng, "IDEA_REGISTRY_PATH", idea_reg)
        monkeypatch.setattr(ng, "SWEEP_REGISTRY_PATH", registry)
        return ng

    def _write_directive(self, tmp_path: Path, name: str, symbol: str) -> Path:
        d = tmp_path / f"{name}.txt"
        d.write_text(
            textwrap.dedent(f"""\
                test:
                  name: {name}
                  family: MR
                  strategy: {name}
                symbols:
                  - {symbol}
            """),
            encoding="utf-8",
        )
        return d

    def test_reused_idea_new_symbol_fails_end_to_end(self, tmp_path, monkeypatch, registry):
        ng = self._setup_paths(tmp_path, monkeypatch, registry)
        d = self._write_directive(
            tmp_path, "73_MR_NAS100_1D_VOLPULL_ATRFILT_S02_V1_P00", "NAS100"
        )
        with pytest.raises(NamespaceValidationError) as ei:
            ng.validate_namespace(d)
        assert "Identity tuple not registered under idea_id '73'" in str(ei.value)

    def test_reused_idea_same_identity_passes_end_to_end(self, tmp_path, monkeypatch, registry):
        ng = self._setup_paths(tmp_path, monkeypatch, registry)
        # Same identity as the registered 73 tuple (US30/1D), different sweep slot.
        d = self._write_directive(
            tmp_path, "73_MR_US30_1D_VOLPULL_ATRFILT_S09_V1_P00", "US30"
        )
        details = ng.validate_namespace(d)
        assert details["idea_id"] == "73"
        assert details["symbol"] == "US30"
