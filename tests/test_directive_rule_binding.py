"""Tests for tools/rule_binding_gate.check_directive_rule_binding.

Covers the six acceptance cases from ENFORCEMENT_PLAN_2026-05-27.md Task A:
  1. mismatch reject
  2. ambiguous multi-match reject (both patterns in the message)
  3. known corpus passes
  4. smoke admit path passes (non-basket directive -> gate no-op)
  5. Phase A1 unknown-pattern WARN + telemetry JSONL written
  6. Phase A2 unknown-pattern hard reject

Plus two operator-mandated extras:
  7. rule_name comparison is case-sensitive (no silent lowercase)
  8. legacy_patterns match -> WARN with match_class='legacy' in telemetry
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import tools.rule_binding_gate as gate_module
from tools.rule_binding_gate import (
    RuleBindingGateError,
    check_directive_rule_binding,
)


@pytest.fixture
def patched_registry(tmp_path, monkeypatch):
    """Each test installs its own controlled registry."""

    def _set(registry_yaml: str) -> Path:
        reg_path = tmp_path / "directive_rule_binding.yaml"
        reg_path.write_text(registry_yaml, encoding="utf-8")
        monkeypatch.setattr(gate_module, "REGISTRY_PATH", reg_path)
        return reg_path

    return _set


@pytest.fixture
def patched_telemetry(tmp_path, monkeypatch):
    out_dir = tmp_path / "telemetry"
    monkeypatch.setattr(gate_module, "TELEMETRY_DIR", out_dir)
    return out_dir


def _write_directive(path: Path, *, rule_name: str | None) -> Path:
    payload: dict = {}
    if rule_name is not None:
        payload["recycle_rule"] = {"name": rule_name}
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


# 1 — mismatch
def test_mismatch_rejects(tmp_path, patched_registry):
    patched_registry(
        "meta: {strict_unknown: false}\n"
        "bindings:\n"
        "  - pattern: '(?:^|_)COINTREV_V2_L\\d+(?:_|$)'\n"
        "    rule_name: cointegration_meanrev_v1_2\n"
    )
    d = _write_directive(
        tmp_path / "90_PORT_AUDJPYAUDNZD_15M_COINTREV_V2_L252.txt",
        rule_name="pine_ratio_zrev_v1",
    )
    with pytest.raises(RuleBindingGateError, match="MISMATCH"):
        check_directive_rule_binding(d)


# 2 — ambiguous multi-match
def test_ambiguous_multi_match_rejects_with_both_patterns(tmp_path, patched_registry):
    patched_registry(
        "meta: {strict_unknown: false}\n"
        "bindings:\n"
        "  - pattern: '(?:^|_)PAIRX_S\\d+(?:_|$)'\n"
        "    rule_name: H3_spread\n"
        "  - pattern: 'S\\d+_V\\d+'\n"
        "    rule_name: H3_spread\n"
    )
    d = _write_directive(
        tmp_path / "90_PORT_X_15M_PAIRX_S15_V1.txt",
        rule_name="H3_spread",
    )
    with pytest.raises(RuleBindingGateError) as exc_info:
        check_directive_rule_binding(d)
    msg = str(exc_info.value)
    assert "AMBIGUOUS" in msg
    assert "PAIRX_S" in msg
    assert "S\\d+_V\\d+" in msg


# 3 — known corpus (positive)
def test_known_corpus_passes(tmp_path, patched_registry):
    patched_registry(
        "meta: {strict_unknown: false}\n"
        "bindings:\n"
        "  - pattern: '(?:^|_)PAIRX_S\\d+_V\\d+_P\\d+(?:_|$)'\n"
        "    rule_name: H3_spread\n"
    )
    d = _write_directive(
        tmp_path / "90_PORT_EURUSDUSDJPY_15M_PAIRX_S15_V1_P03.txt",
        rule_name="H3_spread",
    )
    check_directive_rule_binding(d)  # no raise


# 4 — smoke admit path (non-basket directive)
def test_non_basket_directive_skipped(tmp_path, patched_registry):
    patched_registry(
        "meta: {strict_unknown: true}\n"  # strict on, would reject if gate fired
        "bindings: []\n"
    )
    d = _write_directive(
        tmp_path / "01_MR_FX_1H_ULTC_REGFILT_S07_V1_P02.txt",
        rule_name=None,  # non-basket: no recycle_rule field
    )
    check_directive_rule_binding(d)  # no raise


# 5 — Phase A1 unknown -> WARN + telemetry
def test_phase_a1_unknown_warns_and_logs_telemetry(
    tmp_path, patched_registry, patched_telemetry, capsys
):
    patched_registry(
        "meta: {strict_unknown: false}\n"
        "bindings: []\n"
    )
    d = _write_directive(
        tmp_path / "99_PORT_NEWFAMILY_15M_NEWTOKEN_S01_V1_P00.txt",
        rule_name="some_new_rule",
    )
    check_directive_rule_binding(d)  # admits

    out = capsys.readouterr().out
    assert "[RULE_BINDING_GATE][WARN]" in out
    assert "UNKNOWN pattern" in out

    files = sorted(patched_telemetry.glob("unknown_rule_bindings_*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").splitlines()[-1]
    payload = json.loads(line)
    assert payload["directive_name"] == d.stem
    assert payload["observed_rule_name"] == "some_new_rule"
    assert payload["match_class"] == "unknown"
    assert payload["candidate_fragment"] == "NEWTOKEN_S01_V1_P00"
    assert "timestamp_utc" in payload


# 6 — Phase A2 unknown -> hard reject
def test_phase_a2_unknown_rejects(tmp_path, patched_registry):
    patched_registry(
        "meta: {strict_unknown: true}\n"
        "bindings: []\n"
    )
    d = _write_directive(
        tmp_path / "99_PORT_NEWFAMILY_15M_NEWTOKEN_S01_V1_P00.txt",
        rule_name="some_new_rule",
    )
    with pytest.raises(RuleBindingGateError, match="UNKNOWN pattern"):
        check_directive_rule_binding(d)


# 7 — casing sensitivity (operator-mandated)
def test_rule_name_comparison_is_case_sensitive(tmp_path, patched_registry):
    patched_registry(
        "meta: {strict_unknown: false}\n"
        "bindings:\n"
        "  - pattern: '(?:^|_)PAIRX_S\\d+_V\\d+_P\\d+(?:_|$)'\n"
        "    rule_name: H3_spread\n"
    )
    d = _write_directive(
        tmp_path / "90_PORT_X_15M_PAIRX_S15_V1_P03.txt",
        rule_name="h3_spread",  # wrong case
    )
    with pytest.raises(RuleBindingGateError, match="MISMATCH"):
        check_directive_rule_binding(d)


# 8 — legacy_patterns match -> WARN with match_class='legacy'
def test_legacy_pattern_warns_with_legacy_class(
    tmp_path, patched_registry, patched_telemetry, capsys
):
    patched_registry(
        "meta: {strict_unknown: false}\n"
        "bindings: []\n"
        "legacy_patterns:\n"
        "  - pattern: '(?:^|_)COINTREV_S\\d+_V\\d+_P\\d+(?:_|$)'\n"
        "    note: 'discovered 2026-05-28'\n"
    )
    d = _write_directive(
        tmp_path / "91_PORT_AUDUSDEURAUD_15M_COINTREV_S12_V1_P00.txt",
        rule_name="COINTREV_meanrev",
    )
    check_directive_rule_binding(d)  # admits

    out = capsys.readouterr().out
    assert "LEGACY pattern detected" in out
    assert "legacy pattern detected; explicit binding decision required" in out

    files = sorted(patched_telemetry.glob("unknown_rule_bindings_*.jsonl"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    assert payload["match_class"] == "legacy"
    assert payload["observed_rule_name"] == "COINTREV_meanrev"
    assert payload["candidate_fragment"] == "COINTREV_S12_V1_P00"
