"""Tests for tools/active_logic_renderer.render_active_logic — the single source of
truth for human-readable "Active Logic" in the strategy card AND the basket report.

This locks the class of bug where a hardcoded per-strategy template mislabels every
strategy it was not written for (e.g. IBS rendered as the RSIAVG template
``rsi_avg_pullback | RSI(2) avg < 25 | trend_score abs>=2``). The renderer must read
ONLY the declared signature fields and invent nothing.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.active_logic_renderer import render_active_logic as R  # noqa: E402

IBS = {
    "execution_rules": {"stop_loss": {"atr_multiplier": 10.0, "type": "atr_multiple"},
                        "take_profit": {"enabled": False}, "trailing_stop": {"enabled": False}},
    "mean_reversion_rules": {"entry": {"long": {"ibs_entry_max": 0.2}},
                            "exit": {"max_bars": 1, "type": "time"}},
    "order_placement": {"execution_timing": "next_bar_open", "type": "market"},
}
RSI69 = {
    "execution_rules": {"stop_loss": {"atr_multiplier": 5.0, "type": "atr_multiple"},
                        "take_profit": {"enabled": False}},
    "mean_reversion_rules": {"entry": {"long": {"rsi_entry_max": 30, "regime_gate": "ema200_above"}},
                            "exit": {"max_bars": 10, "rsi_exit_long": 55, "type": "rsi_or_time"}},
    "order_placement": {"execution_timing": "next_bar_open"},
}
SPIKE = {
    "execution_rules": {"entry_logic": {"type": "spike_fade", "spike_atr_multiplier": 2.0,
                                       "direction": "both", "confirmation": "close"},
                        "stop_loss": {"atr_multiplier": 3.0},
                        "take_profit": {"enabled": True, "atr_multiplier": 1.5}},
    "order_placement": {"execution_timing": "next_bar_open"},
}
BASKET = {
    "recycle_rule": {"name": "pine_ratio_zrev_v1", "version": "1",
                    "params": {"z_entry": 2.5, "coint_break_exit": True}},
    "regime_gate": {"factor": "coint_regime", "operator": "==", "value": "cointegrated"},
    "harvest_threshold_usd": 200, "initial_stake_usd": 1000,
}
_ALL = (IBS, RSI69, SPIKE, BASKET)


def _txt(sig):
    return "\n".join(R(sig))


# ── Nothing invented (the original bug fingerprint) ──────────────────────────
def test_ibs_invents_nothing():
    t = _txt(IBS)
    # The exact tokens the old hardcoded RSIAVG template fabricated:
    for forbidden in ("rsi_avg_pullback", "RSI(2)", "RSI(", "trend_score",
                      "long_threshold", "short_threshold", "min_abs_trend_score"):
        assert forbidden not in t, f"invented token {forbidden!r} leaked into IBS render:\n{t}"


def test_rsi69_not_rsiavg_template():
    # The previously-mislabeled strategy must now read as itself.
    t = _txt(RSI69)
    assert "rsi_avg_pullback" not in t and "RSI(2)" not in t


# ── Reads the actual declared fields ─────────────────────────────────────────
def test_positive_fields_present():
    assert "ibs_entry_max=0.2" in _txt(IBS)
    assert "rsi_entry_max=30" in _txt(RSI69)
    assert "regime_gate=ema200_above" in _txt(RSI69)
    assert "spike_atr_multiplier=2.0" in _txt(SPIKE)
    assert "param_z_entry=2.5" in _txt(BASKET)


def test_type_fields_preserved():
    # Declared exit semantics must survive verbatim (audit surface).
    assert "type=time" in _txt(IBS)
    assert "type=rsi_or_time" in _txt(RSI69)
    assert "sl_type=atr_multiple" in _txt(IBS)


def test_gate_operator_pretty_printed():
    assert "Gate: coint_regime == cointegrated" in _txt(BASKET)
    assert "operator===" not in _txt(BASKET)


def test_no_empty_container_token():
    # The 'params' wrapper must be flattened (param_*), never a bare token.
    assert "params" not in _txt(BASKET).split()
    assert "param_z_entry=2.5" in _txt(BASKET)


def test_disabled_toggles_emit_nothing():
    # IBS has take_profit.enabled=False / trailing_stop.enabled=False -> no tp/trail tokens.
    t = _txt(IBS)
    assert "tp_" not in t and "trail_" not in t


# ── Serializer properties: deterministic, idempotent, order-independent ──────
def test_deterministic():
    for sig in _ALL:
        assert R(sig) == R(sig)


def test_idempotent_on_own_output():
    # render() consumes its own canonical output without gaining/losing information.
    for sig in _ALL:
        assert R(R(sig)) == R(sig)


def test_order_independent():
    def reorder(d):
        if isinstance(d, dict):
            return {k: reorder(v) for k, v in reversed(list(d.items()))}
        return d
    for sig in _ALL:
        assert R(sig) == R(reorder(copy.deepcopy(sig)))
