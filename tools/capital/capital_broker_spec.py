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
# One monetary model, one authority: the MT5-derived calibration block
# (usd_pnl_per_price_unit_0p01 = tick_value/tick_size * 0.01) is AUTHORITATIVE.
#
# Canonical pricing field (2026-07-02, INVAR-005 phase 2):
#     pricing_units_per_lot — profit-ccy P&L per 1.0 price-unit move per
#     1.0 lot. THE only field pricing paths may consume. It is the persisted
#     representation of the calibration authority, derived at generation time
#     by verify_broker_specs.py --patch via derive_pricing_units_per_lot().
#
# Top-level contract_size is RAW MT5 METADATA (immutable, descriptive-only):
# it feeds drift detection (verify_broker_specs raw-vs-raw compare) and
# TS_Execution static/live validation, and must never be re-semanticized.
# Root cause of the 2026-07-02 SPX500 10x Stage-1 inflation: MT5 reports
# contract_size=10 for SPX500 while the tick calibration proves $1/pt/lot —
# Stage-1 sized from the metadata field instead of the calibration.
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

# Strict relative tolerance for USD-profit symbols, where the calibration is
# an exact USD figure (FX factor == 1) and equality must hold to float noise.
_USD_STRICT_RTOL = 1e-6


def derive_pricing_units_per_lot(contract_size: float | None,
                                 usd_per_pu_per_lot: float,
                                 profit_ccy: str) -> tuple[float, str]:
    """Derive the canonical pricing_units_per_lot from the calibration authority.

    Returns (value, basis):
      - MT5 contract_size consistent with the calibration (implied FX inside
        the per-currency band)  -> (contract_size, "MT5_CONTRACT_SIZE").
        Honest symbols: numerically identical to today's pricing.
      - Inconsistent + profit ccy USD -> (usd_per_pu_per_lot,
        "CALIBRATION_USD"). Exact, since FX(USD->USD) == 1 (the SPX500 case).
      - Inconsistent + non-USD profit ccy -> ValueError. The FX rate needed to
        back out units is unknowable here; an operator decision is required.
        REFUSE loudly, never guess.

    Single implementation shared by the generator (verify_broker_specs.py
    --patch) and the tests, so generation and validation can never diverge.
    """
    profit_ccy = str(profit_ccy).upper()
    band = _IMPLIED_FX_BANDS.get(profit_ccy)
    if band is None:
        raise ValueError(
            f"Cannot derive pricing_units_per_lot: no FX plausibility band for "
            f"profit currency '{profit_ccy}'. Add it to _IMPLIED_FX_BANDS after "
            f"operator review — refusing to guess."
        )
    if contract_size not in (None, 0):
        implied_fx = usd_per_pu_per_lot / float(contract_size)
        lo, hi = band
        if lo <= implied_fx <= hi:
            return float(contract_size), "MT5_CONTRACT_SIZE"
    if profit_ccy == "USD":
        return float(usd_per_pu_per_lot), "CALIBRATION_USD"
    raise ValueError(
        f"Cannot derive pricing_units_per_lot: MT5 contract_size="
        f"{contract_size} disagrees with calibrated usd_per_pu_per_lot="
        f"{usd_per_pu_per_lot:.6f} and profit currency '{profit_ccy}' is not "
        f"USD, so the unit count cannot be backed out without an FX rate. "
        f"Operator review required — refusing to guess."
    )


def validate_monetary_consistency(spec: dict, symbol: str) -> None:
    """HARD gate: the pricing representation must agree with the calibration.

    The validator never compares two equally-authoritative values — it checks
    the PERSISTED pricing field against the CALIBRATION authority it was
    derived from:

      - `pricing_units_per_lot` present (reconciled spec):
          expected = calibration-derived value.
          USD profit ccy  -> strict equality (rel tol 1e-6; FX factor is 1).
          non-USD         -> implied FX = usd_per_pu_per_lot /
                             pricing_units_per_lot must sit in the ccy band
                             (exact FX at calibration time is not persisted).
      - `pricing_units_per_lot` absent (legacy spec): fall back to the
        original contract_size-vs-calibration band check, byte-identical to
        the 2026-07-02 INVAR-005 behavior, so un-regenerated specs keep
        refusing exactly as before.

    Specs without a calibration block (non-OctaFx legacy) pass through — they
    have no authoritative reference to check against.
    Raises ValueError (refusing execution) on inconsistency.
    """
    cal = spec.get("calibration") or {}
    usd_per_pu_0p01 = cal.get("usd_pnl_per_price_unit_0p01")
    if usd_per_pu_0p01 is None:
        return  # no authoritative calibration to check against
    # Prefer the unrounded per-lot field when present (sibling invariant:
    # 0p01 == usd_per_pu_per_lot * 0.01, enforced by the generator); the
    # 6-dp-rounded 0p01 field x100 introduces rounding noise at small
    # magnitudes that would false-fail the strict USD check.
    _cal_upl = cal.get("usd_per_pu_per_lot")
    usd_per_pu_per_lot = (float(_cal_upl) if _cal_upl
                          else float(usd_per_pu_0p01) * 100.0)
    profit_ccy = str(cal.get("currency_profit", "USD")).upper()

    pricing_units = spec.get("pricing_units_per_lot")
    if pricing_units is not None:
        pricing_units = float(pricing_units)
        if pricing_units <= 0:
            raise ValueError(
                f"Broker spec for {symbol}: pricing_units_per_lot="
                f"{pricing_units} is not a positive number. Regenerate broker "
                f"specs using verify_broker_specs.py --patch."
            )
        if profit_ccy == "USD":
            if abs(pricing_units - usd_per_pu_per_lot) > _USD_STRICT_RTOL * usd_per_pu_per_lot:
                raise ValueError(
                    f"Broker spec monetary fields inconsistent for {symbol}.\n"
                    f"Persisted pricing_units_per_lot={pricing_units} does not "
                    f"equal the calibration authority "
                    f"usd_per_pu_per_lot={usd_per_pu_per_lot:.6f} (profit ccy "
                    f"USD -> strict equality required).\n"
                    f"Refusing execution. Regenerate broker specs using "
                    f"verify_broker_specs.py --patch\n"
                    f"(single-monetary-model invariant, 2026-07-02)."
                )
        else:
            band = _IMPLIED_FX_BANDS.get(profit_ccy)
            if band is None:
                raise ValueError(
                    f"Broker spec for {symbol}: pricing_units_per_lot present "
                    f"but profit currency '{profit_ccy}' has no FX band — "
                    f"cannot validate the persisted value against the "
                    f"calibration. Add the band to _IMPLIED_FX_BANDS after "
                    f"operator review."
                )
            implied_fx = usd_per_pu_per_lot / pricing_units
            lo, hi = band
            if not (lo <= implied_fx <= hi):
                raise ValueError(
                    f"Broker spec monetary fields inconsistent for {symbol}.\n"
                    f"Persisted pricing_units_per_lot={pricing_units} disagrees "
                    f"with the calibration authority beyond tolerance.\n"
                    f"  calibrated usd_per_pu_per_lot={usd_per_pu_per_lot:.6f} "
                    f"USD/pt/lot\n"
                    f"  implied FX({profit_ccy}->USD)={implied_fx:.6f}, allowed "
                    f"band=[{lo}, {hi}]\n"
                    f"Refusing execution. Regenerate broker specs using "
                    f"verify_broker_specs.py --patch\n"
                    f"(single-monetary-model invariant, 2026-07-02)."
                )
        return

    # ── Legacy fallback (spec not yet regenerated): original 2026-07-02 gate ──
    contract_size = spec.get("contract_size")
    if contract_size in (None, 0):
        return  # no authoritative reference to check against
    band = _IMPLIED_FX_BANDS.get(profit_ccy)
    if band is None:
        return  # unknown profit ccy — no band defined; do not guess
    implied_fx = usd_per_pu_per_lot / float(contract_size)
    lo, hi = band
    if not (lo <= implied_fx <= hi):
        raise ValueError(
            f"Broker specification monetary fields inconsistent for {symbol}.\n"
            f"Top-level contract specification disagrees with calibrated\n"
            f"usd_pnl_per_price_unit_0p01 beyond tolerance.\n"
            f"  contract_size={contract_size} ({profit_ccy}/pt/lot), "
            f"calibrated usd_per_pu_per_lot={usd_per_pu_per_lot:.6f} USD/pt/lot\n"
            f"  implied FX({profit_ccy}->USD)={implied_fx:.6f}, allowed band=[{lo}, {hi}]\n"
            f"Refusing execution. This spec predates the canonical pricing field —\n"
            f"regenerate broker specs using verify_broker_specs.py --patch\n"
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
