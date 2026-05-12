"""
Execution friction stress tests — slippage only.
Artifact-only: consumes deployable_trade_log.csv.

v2.0: Config-driven cost model (config/execution_costs.yaml).
      Tiered robustness: baseline / stress / extreme.
      Spread is NOT modeled — already included in OctaFX OHLC prices.
      Only slippage (execution delay, market impact) is unmodeled friction.
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ── Config loading ────────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "execution_costs.yaml"
_cached_config = None


def _load_config() -> dict:
    """Load execution cost config. Cache after first read."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cached_config = yaml.safe_load(f)
        logger.info("[FRICTION] Loaded cost config: %s", _CONFIG_PATH)
    else:
        logger.warning(
            "[FRICTION] config/execution_costs.yaml not found — using legacy fallback. "
            "Create config/execution_costs.yaml for realistic cost modeling."
        )
        _cached_config = _LEGACY_FALLBACK
    return _cached_config


def reset_config_cache():
    """Force reload on next access (for testing)."""
    global _cached_config
    _cached_config = None


# Legacy fallback — replicates prior behavior when config is absent
_LEGACY_FALLBACK = {
    "default": {"slippage_pips": 0.5},
    "tiers": {
        "baseline": {"label": "Baseline", "slippage_pips": 0.0},
        "stress": {"label": "Slip 0.5 pip/side", "slippage_pips": 0.5},
        "extreme": {"label": "Slip 1.0 pip/side", "slippage_pips": 1.0},
    },
    "bounds": {"min_pips": 0.0, "max_pips": 3.0},
}

# ── Validation ────────────────────────────────────────────────────────────────


def _validate_cost(value: float, label: str, config: dict) -> float:
    """Assert cost within configured bounds. Warn and clamp if out of range."""
    bounds = config.get("bounds", {"min_pips": 0.0, "max_pips": 3.0})
    lo = bounds.get("min_pips", 0.0)
    hi = bounds.get("max_pips", 3.0)
    if value < lo:
        logger.warning("[FRICTION] %s = %.2f below min (%.2f) — clamped", label, value, lo)
        return lo
    if value > hi:
        logger.warning("[FRICTION] %s = %.2f above max (%.2f) — clamped", label, value, hi)
        return hi
    return value


def get_tier_costs(tier_name: str) -> dict:
    """Return slippage_pips for a named tier. Validates bounds."""
    config = _load_config()
    tiers = config.get("tiers", {})
    tier = tiers.get(tier_name)
    if tier is None:
        logger.warning("[FRICTION] Unknown tier '%s' — using default", tier_name)
        tier = config.get("default", {"slippage_pips": 0.2})

    slip = _validate_cost(tier.get("slippage_pips", 0.2), f"{tier_name}.slippage_pips", config)
    label = tier.get("label", tier_name.title())

    return {"slippage_pips": slip, "label": label}


# ── Core cost calculation ─────────────────────────────────────────────────────


def _pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def _cost_per_trade(row: pd.Series, slippage_pips: float) -> float:
    """Estimate slippage cost in USD for a single trade.

    slippage_pips is the ROUND-TRIP slippage (entry + exit combined).
    """
    sym = row["symbol"]
    pip = _pip_size(sym)

    if slippage_pips == 0:
        return 0.0

    price_drag = slippage_pips * pip
    price_diff = abs(row["exit_price"] - row["entry_price"]) if "exit_price" in row.index else 0

    if price_diff < pip * 0.1:
        lots = row["lot_size"] if "lot_size" in row.index else 0.01
        return 10.0 * lots * slippage_pips

    return (abs(row["pnl_usd"]) / price_diff) * price_drag


def apply_friction(
    tr_df: pd.DataFrame,
    slippage_pips: float = 0.0,
    *,
    spread_mult: float = None,
) -> pd.DataFrame:
    """Apply slippage drag to trade PnLs; return a copy with adjusted pnl_usd.

    slippage_pips: per-side slippage in pips. Applied as round-trip (2 sides).

    Legacy interface (backward compat):
        spread_mult: ignored (spreads are in OHLC data). Kept for API compat.
    """
    result = tr_df.copy()

    if spread_mult is not None:
        logger.warning(
            "[FRICTION] spread_mult parameter is deprecated — spreads are already "
            "in OHLC prices. Only slippage is applied."
        )

    # Per-side -> round-trip
    rt_slip = slippage_pips * 2
    costs = []
    for _, row in result.iterrows():
        costs.append(_cost_per_trade(row, rt_slip))
    result["friction_cost"] = costs
    result["pnl_usd_adjusted"] = result["pnl_usd"] - result["friction_cost"]
    return result


# ── Tiered friction scenarios ─────────────────────────────────────────────────


def _compute_scenario(tr_df: pd.DataFrame, label: str,
                      slippage_pips: float, base_net: float) -> dict:
    """Run one friction scenario and return metrics dict."""
    adj = apply_friction(tr_df, slippage_pips=slippage_pips)
    net = adj["pnl_usd_adjusted"].sum()

    wins = adj.loc[adj["pnl_usd_adjusted"] > 0, "pnl_usd_adjusted"].sum()
    losses = abs(adj.loc[adj["pnl_usd_adjusted"] < 0, "pnl_usd_adjusted"].sum())
    pf = wins / losses if losses > 0 else 999.0

    deg = (1 - net / base_net) * 100 if base_net != 0 else 0.0
    avg_cost = adj["friction_cost"].mean()
    total_cost = adj["friction_cost"].sum()

    logger.info(
        "[FRICTION] %s | slip=%.2f/side | net=$%.2f | PF=%.2f | avg_cost=$%.4f",
        label, slippage_pips, net, pf, avg_cost,
    )

    return {
        "scenario": label,
        "slippage_pips": slippage_pips,
        "net_profit": net,
        "pf": pf,
        "degradation_pct": deg,
        "avg_friction_cost": avg_cost,
        "total_friction_cost": total_cost,
        "trade_count": len(adj),
    }


def run_tiered_friction(tr_df: pd.DataFrame) -> dict:
    """Run slippage stress test across all configured tiers.

    Returns:
        {
            "config_source": str,
            "tiers": {
                "baseline": {...},
                "stress": {...},
                "extreme": {...},
            }
        }
    """
    config = _load_config()
    is_fallback = not _CONFIG_PATH.exists()

    base_net = tr_df["pnl_usd"].sum()
    tier_names = ["baseline", "stress", "extreme"]
    tier_results = {}

    for name in tier_names:
        costs = get_tier_costs(name)
        result = _compute_scenario(
            tr_df, costs["label"],
            costs["slippage_pips"],
            base_net,
        )
        result["tier"] = name
        tier_results[name] = result

    return {
        "config_source": "legacy_fallback" if is_fallback else str(_CONFIG_PATH.name),
        "tiers": tier_results,
    }


def run_friction_scenarios(tr_df: pd.DataFrame) -> list[dict]:
    """Run tiered friction and return flat list for backward compatibility.

    This is the primary interface called by runner.py.
    Returns list of dicts: raw baseline + 3 tiers.
    """
    tiered = run_tiered_friction(tr_df)
    results = []

    # Always include a zero-cost baseline for reference
    base_net = tr_df["pnl_usd"].sum()
    wins = tr_df.loc[tr_df["pnl_usd"] > 0, "pnl_usd"].sum()
    losses = abs(tr_df.loc[tr_df["pnl_usd"] < 0, "pnl_usd"].sum())
    pf_raw = wins / losses if losses > 0 else 999.0

    results.append({
        "scenario": "No Friction (raw)",
        "tier": "raw",
        "slippage_pips": 0.0,
        "net_profit": base_net,
        "pf": pf_raw,
        "degradation_pct": 0.0,
        "avg_friction_cost": 0.0,
        "total_friction_cost": 0.0,
        "trade_count": len(tr_df),
    })

    # Add tiered results
    for tier_name in ["baseline", "stress", "extreme"]:
        tier_data = tiered["tiers"].get(tier_name)
        if tier_data:
            results.append(tier_data)

    return results
