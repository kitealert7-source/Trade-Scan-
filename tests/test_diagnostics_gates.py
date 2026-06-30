"""Diagnostic Contract — the two converted gates (Phase 1).

Forces each gate and asserts:
  * the structured contract is now spoken (rendered block + correct
    category/next_action/severity pulled from the catalog), AND
  * the DECISION is unchanged (additive reporting only):
      - canonicalizer still raises CanonicalizationError (exception type
        preserved -> every existing catch-site keeps working);
      - the classifier admission path still raises PipelineAdmissionPause with
        exit_code 0 (non-fatal pause), not a hard error.

Uses isolated fixtures / a crafted verdict; no production state is touched.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.canonicalizer import CanonicalizationError, canonicalize
from tools.classifier_gate import GateVerdict
from tools.orchestration.admission_controller import AdmissionStage
from tools.orchestration.pipeline_errors import PipelineAdmissionPause


# ---------------------------------------------------------------------------
# canonicalizer.UNKNOWN_NESTED_KEY (Stage -0.25)
# ---------------------------------------------------------------------------
def _minimal_directive(extra_block=None):
    d = {
        "test": {
            "name": "X", "family": "STR", "strategy": "X", "version": 1,
            "broker": "OctaFx", "timeframe": "1h", "start_date": "2024-01-02",
            "end_date": "2026-03-20", "research_mode": True, "signal_version": 1,
            "description": "t",
        },
        "symbols": ["USDJPY"],
        "indicators": ["indicators.volatility.atr"],
        "execution_rules": {
            "stop_loss": {"atr_multiplier": 1.5},
            "take_profit": {"atr_multiplier": 3.0},
        },
    }
    if extra_block:
        d.update(extra_block)
    return d


def test_unknown_nested_key_decision_preserved_and_contract_spoken():
    parsed = _minimal_directive({"volatility_filter": {"bogus_unknown_key": True}})

    with pytest.raises(CanonicalizationError) as ei:
        canonicalize(parsed)
    err = ei.value

    # Decision preserved: exception TYPE unchanged (existing catch-sites + the
    # existing test's match="UNKNOWN_NESTED_KEY" still work).
    assert re.search("UNKNOWN_NESTED_KEY", str(err))

    # Contract now spoken: a Diagnostic is carried with the right metadata.
    diag = err.diagnostic
    assert diag is not None
    assert diag.code == "canonicalizer.UNKNOWN_NESTED_KEY"
    assert diag.category == "SCHEMA"
    assert diag.next_action == "stop_and_request_approval"
    assert diag.severity == "error"
    assert diag.auto_fixable is False

    # Rendered block present in the message (the single output path).
    msg = str(err)
    for label in ("ERROR", "CAUSE", "WHY NOW", "SOURCE", "REMEDY", "NEXT ACTION"):
        assert label in msg
    # Original content preserved: offending block + key are reported.
    assert "volatility_filter" in msg
    assert "bogus_unknown_key" in msg


def test_unknown_nested_key_message_is_console_safe():
    parsed = _minimal_directive({"volatility_filter": {"bogus_unknown_key": True}})
    with pytest.raises(CanonicalizationError) as ei:
        canonicalize(parsed)
    str(ei.value).encode("cp1252")  # no stray non-ASCII glyph -> no console crash


# ---------------------------------------------------------------------------
# classifier.IDENTITY_CHANGE (admission Stage -0.21)
# ---------------------------------------------------------------------------
def _identity_change_verdict():
    return GateVerdict(
        verdict="BLOCK",
        reason="Identity change within idea 73 ...",
        classification="IDENTITY_CHANGE",
        prior_directive="MR_VOLPULL_US30_1D",
        prior_max_signal_version=1,
        current_signal_version=1,
        current_indicators_hash="abc123",
        prior_indicators_hash=None,
        details={
            "model": "VOLPULL",
            "asset_class": "INDEX",
            "idea_id": 73,
            "identity_change": ["symbol"],
            "current_identity": ["MR", "VOLPULL", "NAS100", "1D"],
            "prior_identity": ["MR", "VOLPULL", "US30", "1D"],
        },
    )


def _ctx():
    return SimpleNamespace(directive_path=Path("dummy_directive.txt"),
                           directive_id="D-IDENT-TEST")


def test_identity_change_decision_preserved_and_contract_spoken(monkeypatch):
    monkeypatch.setattr("tools.classifier_gate.evaluate",
                        lambda _path: _identity_change_verdict())

    with pytest.raises(PipelineAdmissionPause) as ei:
        AdmissionStage()._run_classifier_gate(_ctx())
    err = ei.value

    # Decision preserved: still a non-fatal admission pause (exit 0).
    assert err.exit_code == 0
    # Log substring preserved for any existing log-grep expectations.
    assert "STAGE -0.21 CLASSIFIER GATE" in str(err)

    # Contract now spoken: carried Diagnostic + rendered block.
    diag = err.diagnostic
    assert diag is not None
    assert diag.code == "classifier.IDENTITY_CHANGE"
    assert diag.category == "IDENTITY"
    assert diag.next_action == "stop_and_request_approval"
    assert diag.severity == "error"

    msg = str(err)
    for label in ("ERROR", "CAUSE", "WHY NOW", "SOURCE", "REMEDY", "NEXT ACTION", "AUTO-FIX"):
        assert label in msg
    # Identity tuples + remedy specifics are rendered.
    assert "NAS100" in msg
    assert "US30" in msg


def test_non_identity_block_keeps_legacy_message(monkeypatch):
    # A different BLOCK reason must keep its prior plain message (Phase 1 wires
    # ONLY IDENTITY_CHANGE) and carry no diagnostic.
    verdict = GateVerdict(
        verdict="BLOCK",
        reason="SIGNAL delta without signal_version bump",
        classification="SIGNAL",
        prior_directive="PRIOR",
        prior_max_signal_version=2,
        current_signal_version=2,
        current_indicators_hash="h",
        prior_indicators_hash="h",
        details={},
    )
    monkeypatch.setattr("tools.classifier_gate.evaluate", lambda _path: verdict)

    with pytest.raises(PipelineAdmissionPause) as ei:
        AdmissionStage()._run_classifier_gate(_ctx())
    err = ei.value
    assert err.exit_code == 0
    assert "SIGNAL delta without signal_version bump" in str(err)
    assert getattr(err, "diagnostic", None) is None


def test_classifier_pass_does_not_raise(monkeypatch):
    verdict = GateVerdict(
        verdict="PASS",
        reason="first-of-kind",
        classification="N/A",
        prior_directive=None,
        prior_max_signal_version=None,
        current_signal_version=1,
        current_indicators_hash="h",
        prior_indicators_hash=None,
        details={},
    )
    monkeypatch.setattr("tools.classifier_gate.evaluate", lambda _path: verdict)
    # Must not raise.
    AdmissionStage()._run_classifier_gate(_ctx())
