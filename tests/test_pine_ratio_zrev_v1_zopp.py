"""Unit tests for PineRatioZRevRuleZOpp — the opposite-band (overshoot) exit
variant. The defining, must-be-correct behaviour: the exit fires when z reaches
the OPPOSITE side beyond +/- z_exit (entered at -2 -> exit at +1), and does NOT
fire on the same-side band (that is the zband rule). A sign error here would
silently test the wrong strategy, so this is locked directly."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from tools.recycle_rules.pine_ratio_zrev_v1_zopp import PineRatioZRevRuleZOpp  # noqa: E402
from tools.recycle_rules import RULE_CLASSES  # noqa: E402


def _rule():
    return PineRatioZRevRuleZOpp(z_entry=2.0, z_exit=1.0)


def test_entered_low_exits_at_opposite_plus1_not_same_side_minus1():
    """Entered at z=-2 (entry_z_sign=-1): must ride THROUGH zero and exit at
    +1 (opposite), NOT at -1 (same side — that's zband)."""
    r = _rule(); r._entry_z_sign = -1
    assert r._opp_exit_fires(-1.5) is False   # still on entry side
    assert r._opp_exit_fires(-1.0) is False   # SAME-side -1: must NOT exit (zband would)
    assert r._opp_exit_fires(0.0) is False    # at the mean: not yet
    assert r._opp_exit_fires(0.9) is False    # crossed zero but short of +1
    assert r._opp_exit_fires(1.0) is True     # opposite +1: EXIT
    assert r._opp_exit_fires(1.7) is True     # beyond +1: EXIT


def test_entered_high_exits_at_opposite_minus1_not_same_side_plus1():
    """Entered at z=+2 (entry_z_sign=+1): exit at -1 (opposite), NOT +1."""
    r = _rule(); r._entry_z_sign = 1
    assert r._opp_exit_fires(1.5) is False    # entry side
    assert r._opp_exit_fires(1.0) is False    # SAME-side +1: must NOT exit
    assert r._opp_exit_fires(-0.9) is False   # short of -1
    assert r._opp_exit_fires(-1.0) is True    # opposite -1: EXIT
    assert r._opp_exit_fires(-1.7) is True


def test_flat_never_exits():
    r = _rule(); r._entry_z_sign = 0
    for z in (-3.0, -1.0, 0.0, 1.0, 3.0):
        assert r._opp_exit_fires(z) is False


def test_z_exit_must_be_below_z_entry():
    with pytest.raises(ValueError, match="z_exit"):
        PineRatioZRevRuleZOpp(z_entry=2.0, z_exit=2.0)   # >= z_entry
    with pytest.raises(ValueError, match="z_exit"):
        PineRatioZRevRuleZOpp(z_entry=2.0, z_exit=0.0)   # <= 0


def test_registered_in_resolver():
    assert ("pine_ratio_zrev_v1_zopp", 1) in RULE_CLASSES
    assert RULE_CLASSES[("pine_ratio_zrev_v1_zopp", 1)] is PineRatioZRevRuleZOpp


def test_inherits_granular_sizing():
    # GP granular sizing must be available on the variant (exit-only change).
    r = PineRatioZRevRuleZOpp(z_entry=2.0, z_exit=1.0, sizing_mode="granular_parity")
    assert r.sizing_mode == "granular_parity"
    assert hasattr(r, "_granular_parity_lots")


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
