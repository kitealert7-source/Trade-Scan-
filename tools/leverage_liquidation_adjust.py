"""leverage_liquidation_adjust.py -- analysis-layer liquidation floor for
leveraged-sizing studies.

WHY THIS EXISTS (2026-06-04 finding, forensic in
outputs/system_reports/06_strategy_research/SZVP_LEVERAGE_FORENSIC.md):
The basket backtest engine (engine_dev/universal_research_engine/v1_5_8, FROZEN)
does NOT enforce margin-call / liquidation. Under high-leverage sizing
(vol_parity, granular_parity) a basket can run to deeply NEGATIVE equity instead
of being liquidated at the stake. This inflates modeled downside past -100% and,
at extreme leverage (the SZVP vol-parity arm, ~1000-6000x), even lets a blown
account "recover" to a fictitious gain.

It is a BACKTEST-FIDELITY issue ONLY:
  * Live trades through MT5/OctaFx at fixed 0.01 lot (RAW_MIN_LOT_V1) and is
    margin-called/liquidated by the broker -- the engine never touches a live
    position, so there is no live exposure.
  * Notional / lot-equal sizing is mathematically bounded (a run cannot lose
    more than the stake), so production research is unaffected -- the floor is a
    no-op there.

The fix therefore lives in the ANALYSIS LAYER, deliberately NOT in the frozen
engine and NOT as run-halting logic (operator decision 2026-06-04: the engine
must keep generating complete backtests for screening; halting on liquidation
would stall corpus generation).

RULE: a run whose intra-run minimum equity fell below 0 would have been
liquidated; its realistic outcome is total loss of the stake:
    net% -> -100, maxDD% -> 100, ret/dd -> -1.0.
Apply this floor whenever ranking / tail-analysing a LEVERAGED sizing cohort.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_STAKE_USD = 1000.0


def liquidation_adjusted(
    *,
    net_pct: float,
    max_dd_pct: float,
    ret_dd: float,
    min_equity_usd: float | None,
    stake_usd: float = DEFAULT_STAKE_USD,
) -> dict:
    """Apply the analysis-layer liquidation floor to one run's metrics.

    If ``min_equity_usd`` < 0 the basket would have been liquidated at the
    stake -> total loss: returns net=-100.0, maxDD=100.0, ret_dd=-1.0,
    liquidated=True. Otherwise returns the inputs unchanged with
    liquidated=False. ``min_equity_usd=None`` (no per-bar artifact) is treated
    as "cannot confirm liquidation" -> pass through unchanged.

    Pure function; no I/O. ``stake_usd`` is accepted for API symmetry / future
    non-$1000 stakes but the floor outcome (-100% / 100% DD) is stake-relative
    and does not depend on its magnitude.
    """
    if min_equity_usd is not None and min_equity_usd < 0:
        return {"net_pct": -100.0, "max_dd_pct": 100.0, "ret_dd": -1.0, "liquidated": True}
    return {"net_pct": net_pct, "max_dd_pct": max_dd_pct, "ret_dd": ret_dd, "liquidated": False}


def min_equity_usd(directive_id: str, basket_id: str, backtests_dir: Path | None = None) -> float | None:
    """Intra-run minimum equity from the per-bar basket artifact, or None if the
    artifact is absent. The discriminant for the liquidation floor: < 0 => the
    account went insolvent intra-run (engine did not liquidate)."""
    if backtests_dir is None:
        from config.path_authority import TRADE_SCAN_STATE
        backtests_dir = Path(TRADE_SCAN_STATE) / "backtests"
    p = Path(backtests_dir) / f"{directive_id}_{basket_id}" / "raw" / "results_basket_per_bar.parquet"
    if not p.is_file():
        return None
    import pandas as pd
    try:
        col = pd.read_parquet(p, columns=["equity_total_usd"])["equity_total_usd"]
    except Exception:
        col = pd.read_parquet(p)["equity_total_usd"]
    return float(col.min())


__all__ = ["liquidation_adjusted", "min_equity_usd", "DEFAULT_STAKE_USD"]
