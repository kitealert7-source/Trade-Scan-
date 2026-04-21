"""Broker spec YAML loading + lot-normalization.

The broker-spec cache lives ONLY here (cache integrity rule).
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROKER_SPECS_ROOT = _PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"


# ======================================================================
# BROKER VOLUME SPEC NORMALIZATION
# ======================================================================
# Cache: loaded once per symbol per process — YAML I/O never happens per trade.
_BACKTEST_BROKER_SPECS: dict = {}


def _load_broker_spec_cached(symbol: str) -> dict | None:
    """Return per-symbol broker spec dict (from OctaFx YAML), or None if missing."""
    if symbol in _BACKTEST_BROKER_SPECS:
        return _BACKTEST_BROKER_SPECS[symbol]
    spec_path = BROKER_SPECS_ROOT / f"{symbol}.yaml"
    if not spec_path.exists():
        _BACKTEST_BROKER_SPECS[symbol] = None
        return None
    with open(spec_path, encoding="utf-8") as _f:
        spec = yaml.safe_load(_f)
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
    spec_path = BROKER_SPECS_ROOT / f"{symbol}.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"Missing broker spec: {spec_path}")
    with open(spec_path, "r") as f:
        return yaml.safe_load(f)


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
