"""Broker spec YAML loading + lot-normalization.

The broker-spec cache lives ONLY here (cache integrity rule).
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROKER_SPECS_ROOT = _PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"


def broker_spec_path(symbol: str) -> Path:
    """Resolve the on-disk OctaFx broker-spec YAML for a symbol.

    Single source for the spec file path so every reader — the per-process
    cache loader, the bootstrap loader, and the provenance hasher — resolves
    the identical file, including under a worktree (BROKER_SPECS_ROOT is derived
    from this module's own location).
    """
    return BROKER_SPECS_ROOT / f"{symbol}.yaml"


# ======================================================================
# MONETARY CONSISTENCY GUARD (single-monetary-model invariant, 2026-07-02)
# ======================================================================
# One monetary model, multiple consumers: the MT5-derived calibration block
# (usd_pnl_per_price_unit_0p01 = tick_value/tick_size * 0.01) is AUTHORITATIVE.
# The top-level contract_size (profit-ccy per point per lot) must agree with it:
#     implied_fx = usd_per_pu_per_lot / contract_size  ≈  FX(profit_ccy → USD)
# A disagreement means two components would price the same trade differently
# (root cause of the 2026-07-02 SPX500 10x Stage-1 inflation: contract_size=10
# vs MT5-verified $1/pt/lot). This guard makes that drift a HARD failure at
# spec-load — refusing execution — instead of a silent divergence.
#
# Bands are deliberately wide (they tolerate years of FX drift between
# calibration refreshes) — any plausible spot stays inside; a 10x scale error
# escapes every band.
_IMPLIED_FX_BANDS = {
    "USD": (0.95, 1.05),
    "EUR": (0.80, 1.40),
    "GBP": (1.00, 1.70),
    "JPY": (0.0045, 0.0120),
    "AUD": (0.50, 0.90),
    "NZD": (0.45, 0.85),
    "CAD": (0.55, 0.95),
    "CHF": (0.90, 1.50),
}


def validate_monetary_consistency(spec: dict, symbol: str) -> None:
    """HARD gate: top-level contract_size must agree with the MT5 calibration.

    Specs without a calibration block (non-OctaFx legacy) pass through — they
    have no authoritative reference to check against and use dynamic paths.
    Raises ValueError (refusing execution) on inconsistency.
    """
    cal = spec.get("calibration") or {}
    usd_per_pu_0p01 = cal.get("usd_pnl_per_price_unit_0p01")
    contract_size = spec.get("contract_size")
    if usd_per_pu_0p01 is None or contract_size in (None, 0):
        return  # no authoritative calibration to check against
    profit_ccy = str(cal.get("currency_profit", "USD")).upper()
    band = _IMPLIED_FX_BANDS.get(profit_ccy)
    if band is None:
        return  # unknown profit ccy — no band defined; do not guess
    implied_fx = (float(usd_per_pu_0p01) * 100.0) / float(contract_size)
    lo, hi = band
    if not (lo <= implied_fx <= hi):
        raise ValueError(
            f"Broker specification monetary fields inconsistent for {symbol}.\n"
            f"Top-level contract specification disagrees with calibrated\n"
            f"usd_pnl_per_price_unit_0p01 beyond tolerance.\n"
            f"  contract_size={contract_size} ({profit_ccy}/pt/lot), "
            f"calibrated usd_per_pu_per_lot={float(usd_per_pu_0p01)*100.0:.6f} USD/pt/lot\n"
            f"  implied FX({profit_ccy}->USD)={implied_fx:.6f}, allowed band=[{lo}, {hi}]\n"
            f"Refusing execution. Align contract_size with the MT5-verified calibration\n"
            f"(single-monetary-model invariant, 2026-07-02)."
        )


# ======================================================================
# BROKER VOLUME SPEC NORMALIZATION
# ======================================================================
# Cache: loaded once per symbol per process — YAML I/O never happens per trade.
_BACKTEST_BROKER_SPECS: dict = {}


def _load_broker_spec_cached(symbol: str) -> dict | None:
    """Return per-symbol broker spec dict (from OctaFx YAML), or None if missing."""
    if symbol in _BACKTEST_BROKER_SPECS:
        return _BACKTEST_BROKER_SPECS[symbol]
    spec_path = broker_spec_path(symbol)
    if not spec_path.exists():
        _BACKTEST_BROKER_SPECS[symbol] = None
        return None
    with open(spec_path, encoding="utf-8") as _f:
        spec = yaml.safe_load(_f)
    validate_monetary_consistency(spec, symbol)  # hard gate (single-monetary-model)
    _BACKTEST_BROKER_SPECS[symbol] = spec
    return spec


def _normalize_lot_broker(raw_lot: float, symbol: str) -> float | None:
    """Apply broker volume constraints to a raw lot size.

    Mirrors the live normalize_lot() logic in execution_adapter.py:
      1. Floor-align to volume_step (never round up)
      2. Clamp to volume_max
      3. Return None if result < volume_min  → caller must DROP the trade

    No fallback to min_lot — a None return means the trade is silently skipped
    in the backtest exactly as it would be rejected in live execution.

    If no broker spec file exists for the symbol the raw_lot is returned
    unchanged (unknown symbol — no constraint to enforce).
    """
    spec = _load_broker_spec_cached(symbol)
    if spec is None:
        return raw_lot  # no spec on file — pass through

    vol_min  = float(spec.get("min_lot",  0.01))
    vol_max  = float(spec.get("max_lot",  500.0))
    vol_step = float(spec.get("lot_step", 0.01))

    if raw_lot <= 0.0 or vol_step <= 0.0:
        return None

    # Floor-align: steps = math.floor(raw / step)
    steps = math.floor(raw_lot / vol_step)
    normalized = round(steps * vol_step, 8)

    # Clamp to max
    if normalized > vol_max:
        normalized = vol_max

    # Drop below min
    if normalized < vol_min:
        return None

    return normalized


# ======================================================================
# BROKER SPEC LOADER (non-cached — used by CLI bootstrap)
# ======================================================================

def load_broker_spec(symbol: str) -> dict:
    """Load broker spec YAML for a symbol."""
    spec_path = broker_spec_path(symbol)
    if not spec_path.exists():
        raise FileNotFoundError(f"Missing broker spec: {spec_path}")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    validate_monetary_consistency(spec, symbol)  # hard gate (single-monetary-model)
    return spec


def get_usd_per_price_unit_static(spec: dict) -> float:
    """
    STATIC fallback: Derive USD PnL per 1.0 price unit move per 1.0 lot
    from broker YAML calibration.
    """
    cal = spec.get("calibration", {})
    usd_per_pu_0p01 = cal.get("usd_pnl_per_price_unit_0p01")
    if usd_per_pu_0p01 is None:
        raise ValueError(f"Broker spec for {spec.get('symbol','?')} missing calibration.usd_pnl_per_price_unit_0p01")
    return float(usd_per_pu_0p01) * 100.0  # Scale 0.01 lot -> 1.0 lot
