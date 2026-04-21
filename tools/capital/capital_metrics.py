"""Deployable metric computation (pure numeric helpers)."""

from __future__ import annotations

from tools.capital.capital_portfolio_state import PortfolioState


def compute_deployable_metrics(state: PortfolioState, total_runs: int, total_assets: int) -> dict:
    """Compute all deployable metrics from PortfolioState data only."""
    # CAGR (geometric)
    tl = state.equity_timeline
    if len(tl) >= 2:
        first_ts = tl[0][0]
        last_ts = tl[-1][0]
        delta = last_ts - first_ts
        years = delta.total_seconds() / (365.25 * 86400)
        if years > 0 and state.equity > 0:
            cagr = (state.equity / state.starting_capital) ** (1.0 / years) - 1.0
        else:
            cagr = 0.0
    else:
        cagr = 0.0
        years = 0.0

    # Max DD %
    max_dd_pct = (state.max_drawdown_usd / state.peak_equity) if state.peak_equity > 0 else 0.0

    # MAR
    mar = cagr / max_dd_pct if max_dd_pct > 0 else 0.0

    # Rejection rate
    total_signals = state.total_accepted + state.total_rejected
    rejection_rate = state.total_rejected / total_signals if total_signals > 0 else 0.0

    # Capital-ceiling rejections (RETAIL_MAX_LOT_EXCEEDED): strategy outgrew the
    # broker-realistic lot cap. These are evidence of strong returns saturating
    # retail capacity, NOT execution failures — they are excluded from the
    # execution-health penalty in portfolio_evaluator._resolve_deployed_profile.
    retail_max_lot_rejected = sum(
        1 for rej in state.rejection_log if rej.get("reason") == "RETAIL_MAX_LOT_EXCEEDED"
    )
    execution_rejected = state.total_rejected - retail_max_lot_rejected
    execution_total = state.total_accepted + execution_rejected
    execution_rejection_rate = (
        execution_rejected / execution_total if execution_total > 0 else 0.0
    )

    # Heat utilization
    avg_heat = sum(state.heat_samples) / len(state.heat_samples) if state.heat_samples else 0.0
    pct_at_full_heat = sum(1 for h in state.heat_samples if h >= state.heat_cap * 0.95) / len(state.heat_samples) if state.heat_samples else 0.0

    # Longest loss streak
    longest_loss = 0
    current_loss = 0
    for t in state.closed_trades_log:
        if t["pnl_usd"] < 0:
            current_loss += 1
            if current_loss > longest_loss:
                longest_loss = current_loss
        else:
            current_loss = 0

    metrics = {
        "profile": state.profile_name,
        "total_constituent_runs": total_runs,
        "actual_max_concurrent_trades": state.max_concurrent,
        "configured_concurrency_cap": state.concurrency_cap,
        "total_assets_evaluated": total_assets,
        "starting_capital": state.starting_capital,
        "final_equity": round(state.equity, 2),
        "peak_equity": round(state.peak_equity, 2),
        "cagr": round(cagr, 6),
        "cagr_pct": round(cagr * 100, 4),
        "max_drawdown_usd": round(state.max_drawdown_usd, 2),
        "max_drawdown_pct": round(max_dd_pct * 100, 4),
        "mar": round(mar, 4),
        "total_accepted": state.total_accepted,
        "total_rejected": state.total_rejected,
        "rejection_rate_pct": round(rejection_rate * 100, 2),
        "retail_max_lot_rejected": retail_max_lot_rejected,
        "execution_rejection_rate_pct": round(execution_rejection_rate * 100, 2),
        "avg_heat_utilization_pct": round(avg_heat * 100, 4),
        "pct_time_at_full_heat": round(pct_at_full_heat * 100, 4),
        "longest_loss_streak": longest_loss,
        "realized_pnl": round(state.realized_pnl, 2),
        "simulation_years": round(years, 2) if len(tl) >= 2 else 0.0,
    }

    if state.min_lot_fallback:
        metrics.update({
            "risk_override_rate": round(state.total_risk_overrides / state.total_accepted * 100, 2) if state.total_accepted > 0 else 0.0,
            "avg_risk_multiple": round(sum(state.risk_multiples) / len(state.risk_multiples), 2) if state.risk_multiples else 0.0,
            "max_risk_multiple": round(max(state.risk_multiples), 2) if state.risk_multiples else 0.0,
        })

    return metrics
