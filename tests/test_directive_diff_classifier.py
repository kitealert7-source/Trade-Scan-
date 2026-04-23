"""Unit tests for tools.directive_diff_classifier.

Mechanical rule coverage:
  1. SIGNAL       - indicator import delta
  2. PARAMETER    - numeric-only delta
  3. COSMETIC     - prose-only delta
  4. UNCLASSIFIABLE - structural/type change (fail-closed)
"""

from tools.directive_diff_classifier import classify_diff


def _base_directive():
    return {
        "name": "X",
        "strategy": "X",
        "indicators": ["indicators.volatility.atr", "indicators.structure.choch_v2"],
        "execution_rules": {
            "entry_logic": {"type": "choch_structural_break"},
            "stop_loss": {"type": "atr_multiple", "atr_multiplier": 1.5},
            "take_profit": {"type": "atr_multiple", "atr_multiplier": 3.0},
        },
        "trade_management": {"direction": "long_and_short"},
        "description": "old prose",
    }


def test_signal_indicator_import_added():
    a = _base_directive()
    b = _base_directive()
    b["indicators"] = ["indicators.volatility.atr", "indicators.structure.choch_v3"]
    r = classify_diff(a, b)
    assert r["classification"] == "SIGNAL"
    assert "indicators.structure.choch_v3" in r["indicator_import_delta"]["added"]
    assert "indicators.structure.choch_v2" in r["indicator_import_delta"]["removed"]


def test_parameter_only_numeric_diff():
    a = _base_directive()
    b = _base_directive()
    b["execution_rules"]["stop_loss"]["atr_multiplier"] = 2.0
    r = classify_diff(a, b)
    assert r["classification"] == "PARAMETER"
    assert any("atr_multiplier" in leaf for leaf in r["numeric_diffs"])


def test_cosmetic_prose_only():
    a = _base_directive()
    b = _base_directive()
    b["description"] = "new prose, reworded"
    b["notes"] = "some notes"
    r = classify_diff(a, b)
    assert r["classification"] == "COSMETIC"


def test_cosmetic_with_identity_diffs_is_still_cosmetic():
    # Renaming or re-dating a directive must NOT be treated as a signal change.
    a = _base_directive()
    b = _base_directive()
    b["name"] = "Y"
    b["strategy"] = "Y"
    b["start_date"] = "2025-01-01"
    r = classify_diff(a, b)
    assert r["classification"] == "COSMETIC"


def test_signal_when_behavioral_filter_block_added():
    # Adding an enabled FilterStack block with real parameters is a
    # behavioral change -> SIGNAL (not UNCLASSIFIABLE).
    a = _base_directive()
    b = _base_directive()
    b["volatility_filter"] = {"enabled": True, "required_regime": 0, "operator": "gte"}
    r = classify_diff(a, b)
    assert r["classification"] == "SIGNAL"
    assert "volatility_filter" in r["filter_behavioral_blocks"]
    assert "filter-stack behavioral change" in r["reason"]


def test_cosmetic_when_disabled_filter_block_added():
    # Adding a disabled filter block is inert -> not SIGNAL.
    a = _base_directive()
    b = _base_directive()
    b["volatility_filter"] = {"enabled": False, "required_regime": 0}
    r = classify_diff(a, b)
    assert r["classification"] == "COSMETIC"
    assert r["filter_behavioral_blocks"] == []


def test_cosmetic_when_empty_filter_block_added():
    # {"enabled": True} with no other keys is not behaviorally effective.
    a = _base_directive()
    b = _base_directive()
    b["volatility_filter"] = {"enabled": True}
    r = classify_diff(a, b)
    assert r["classification"] == "COSMETIC"


def test_signal_when_filter_block_parameter_changes():
    # Modifying a parameter inside an existing enabled filter block -> SIGNAL.
    base = _base_directive()
    base["volatility_filter"] = {"enabled": True, "required_regime": 0}
    b = _base_directive()
    b["volatility_filter"] = {"enabled": True, "required_regime": 1}
    r = classify_diff(base, b)
    assert r["classification"] == "SIGNAL"
    assert "volatility_filter" in r["filter_behavioral_blocks"]


def test_signal_when_behavioral_filter_block_removed():
    # Removing a previously-enabled behavioral block -> SIGNAL.
    a = _base_directive()
    a["volatility_filter"] = {"enabled": True, "required_regime": 0}
    b = _base_directive()
    r = classify_diff(a, b)
    assert r["classification"] == "SIGNAL"
    assert "volatility_filter" in r["filter_behavioral_blocks"]


def test_unclassifiable_when_unknown_structural_block():
    # Unknown (non-FilterStack) new top-level block -> still fail-closed.
    a = _base_directive()
    b = _base_directive()
    b["foo_filter"] = {"enabled": True, "threshold": 0.5}
    r = classify_diff(a, b)
    assert r["classification"] == "UNCLASSIFIABLE"
    assert any(leaf.startswith("foo_filter") for leaf in r["structural_diffs"])


def test_unclassifiable_when_type_change():
    a = _base_directive()
    b = _base_directive()
    # entry_logic changes from dict to string - structural type flip.
    b["execution_rules"]["entry_logic"] = "choch_structural_break"
    r = classify_diff(a, b)
    assert r["classification"] == "UNCLASSIFIABLE"


def test_no_diff_is_cosmetic():
    # Two identical directives -> trivially cosmetic (no meaningful delta).
    a = _base_directive()
    b = _base_directive()
    r = classify_diff(a, b)
    assert r["classification"] == "COSMETIC"
    assert r["numeric_diffs"] == []
    assert r["structural_diffs"] == []


def test_signal_precedence_over_parameter():
    # If BOTH indicator import AND numeric params change, SIGNAL wins.
    a = _base_directive()
    b = _base_directive()
    b["indicators"] = ["indicators.volatility.atr", "indicators.structure.choch_v3"]
    b["execution_rules"]["stop_loss"]["atr_multiplier"] = 2.0
    r = classify_diff(a, b)
    assert r["classification"] == "SIGNAL"


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
