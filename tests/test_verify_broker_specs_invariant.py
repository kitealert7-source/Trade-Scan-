"""Invariant guard for verify_broker_specs.patch_yaml.

Regression for the sibling-field drift fixed 2026-06-02: ``--patch`` rewrote
``calibration.usd_per_pu_per_lot`` from MT5 on every run but only re-synced
``calibration.usd_pnl_per_price_unit_0p01`` when it drifted >15%, so the two
silently diverged (up to ~3.7% on AUD-cross / index symbols), biasing
capital-layer USD P&L (capital_broker_spec / simulation / capital_wrapper read
the 0p01 field). patch_yaml must keep the invariant

    usd_pnl_per_price_unit_0p01 == round(usd_per_pu_per_lot * 0.01, 6)

on every patch, matching create_yaml_from_mt5.
"""
import yaml
import pytest

from tools.verify_broker_specs import patch_yaml


def _write_spec(path, *, usd_per_pu_per_lot, usd_pnl_0p01):
    """Write a broker-spec YAML with a (possibly inconsistent) calibration block."""
    spec = {
        "broker": "OctaFX",
        "symbol": "TESTSYM",
        "contract_size": 100000.0,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "calibration": {
            "base_lot": 0.01,
            "usd_pnl_per_price_unit_0p01": usd_pnl_0p01,
            "usd_per_pu_per_lot": usd_per_pu_per_lot,
            "status": "MT5_VERIFIED",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(spec, f, sort_keys=False, allow_unicode=True)


def _findings(usd_per_pu_per_lot):
    """Minimal findings dict carrying a fresh MT5 usd_per_pu_per_lot.

    The patched spec must be monetary-consistent or patch_yaml's generation
    gate (INVAR-005 phase 2, 2026-07-02) refuses the write. USD profit ccy +
    contract_size == usd_per_pu_per_lot keeps every magnitude reconcilable
    (implied FX == 1.0) so this file can keep testing its own subject — the
    0p01 sibling-field invariant — across arbitrary scales.
    """
    return {
        "symbol": "TESTSYM",
        "patch": {"contract_size": usd_per_pu_per_lot},
        "mt5": {
            "contract_size": usd_per_pu_per_lot,
            "usd_per_pu_per_lot": usd_per_pu_per_lot,
            "tick_value": usd_per_pu_per_lot * 0.001,
            "tick_size": 0.001,
            "currency_profit": "USD",
            "digits": 3,
        },
    }


def _load_cal(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["calibration"]


def test_patch_corrects_stale_0p01(tmp_path):
    """A 0p01 left stale by the old <15%-drift no-patch path is re-synced."""
    spec = tmp_path / "TESTSYM.yaml"
    # Stale: 0p01 reflects an old rate, inconsistent with usd_per_pu_per_lot.
    _write_spec(spec, usd_per_pu_per_lot=627.081125, usd_pnl_0p01=6.270143)

    patch_yaml(spec, _findings(626.05647))

    cal = _load_cal(spec)
    assert cal["usd_per_pu_per_lot"] == 626.05647
    assert cal["usd_pnl_per_price_unit_0p01"] == 6.260565
    # The invariant itself.
    assert cal["usd_pnl_per_price_unit_0p01"] == round(cal["usd_per_pu_per_lot"] * 0.01, 6)


@pytest.mark.parametrize("uppl", [626.05647, 13.4529, 127092.256269, 0.071577, 1000.0])
def test_patch_enforces_invariant_across_magnitudes(tmp_path, uppl):
    """0p01 == usd_per_pu_per_lot * 0.01 regardless of starting state or scale."""
    spec = tmp_path / "TESTSYM.yaml"
    # Start deliberately inconsistent so a no-op write would fail the assert.
    _write_spec(spec, usd_per_pu_per_lot=1.0, usd_pnl_0p01=999.0)

    patch_yaml(spec, _findings(uppl))

    cal = _load_cal(spec)
    assert cal["usd_per_pu_per_lot"] == uppl
    assert cal["usd_pnl_per_price_unit_0p01"] == round(uppl * 0.01, 6)
