"""cointegration_provenance.py -- assemble a cointegration_sheet row from a
completed run (orchestration-side; NOT part of the sink-only writer).

This is the "smart" assembler that keeps the writer dumb. It:
  - pulls identity from the parsed directive,
  - pulls regime provenance from the admission gate (evaluate_window_validity,
    which reads the screener once -- orchestration is allowed to),
  - merges in caller-computed canonical metrics + reproducibility fields.

It performs NO parquet read (canonical metrics are passed in by the caller) and
writes nothing -- it returns a plain dict for append_cointegration_row().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.basket_ledger import leg_specs_string
from tools.portfolio.cointegration_schema import METRICS_FN_VERSION
from tools.window_validity_gate import evaluate_window_validity


def _canonical_pair(symbols: list[str]) -> tuple[str, str]:
    """Match the screener/loader canonical ordering (sorted, upper)."""
    a, b = sorted([symbols[0].upper(), symbols[1].upper()])
    return a, b


def _s(v: Any) -> str | None:
    """Stringify a value (dates may arrive as datetime.date from YAML)."""
    return None if v is None else str(v)


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def build_cointegration_row(
    *,
    parsed: dict[str, Any],
    directive_path: Path,
    run_id: str,
    directive_id: str,
    directive_hash: str,
    backtests_path: str,
    vault_path: str,
    canonical: dict[str, Any],
    trades_total: int,
    completed_at_utc: str,
    stake_usd: float,
    n_obs: int | None = None,
    parquet_sha256: str | None = None,
    engine_version: str | None = None,
    engine_abi: str = "engine_abi.v1_5_9",
    classifier_version: str | None = None,
    data_vintage: str | None = None,
) -> dict[str, Any]:
    """Assemble a cointegration_sheet row dict. Reads the screener once via the
    window-validity gate; performs no parquet read (canonical is passed in)."""
    basket = parsed.get("basket", {}) or {}
    test = parsed.get("test", {}) or {}
    legs = basket.get("legs", []) or []
    coint_join = basket.get("cointegration_join", {}) or {}

    symbols = [leg.get("symbol") for leg in legs if leg.get("symbol")]
    pair_a, pair_b = _canonical_pair(symbols)

    wv = evaluate_window_validity(directive_path)

    return {
        # identity + lineage
        "run_id": run_id,
        "directive_id": directive_id,
        "pair_a": pair_a,
        "pair_b": pair_b,
        "candidate_key": coint_join.get("candidate_key"),
        "leg_specs": leg_specs_string(legs),
        "completed_at_utc": completed_at_utc,
        # config
        "timeframe": _s(test.get("timeframe")),
        "lookback_days": coint_join.get("lookback_days"),
        # run window
        "test_start": _s(test.get("start_date")),
        "test_end": _s(test.get("end_date")),
        "n_obs": n_obs,
        "stake_usd": _f(stake_usd),
        # regime provenance (from the gate -- the screener is read here, never
        # by the writer)
        "span_start": wv.span_start,
        "span_end": wv.span_end,
        "continuous_span_obs": wv.continuous_span_obs,
        "fragment_count": wv.fragment_count,
        "pct_cointegrated": _f(wv.pct_cointegrated),
        "regime_state": wv.regime_state,
        "window_validation_status": wv.ledger_window_status,
        "classifier_version": classifier_version,
        # reproducibility
        "engine_version": engine_version,
        "engine_abi": engine_abi,
        "strategy_code_sha256": None,  # N/A for baskets (no strategy.py)
        "directive_sha256": directive_hash,
        "data_vintage": data_vintage,
        "parquet_sha256": parquet_sha256,
        "vault_path": vault_path,
        "backtests_path": backtests_path,
        # metrics (caller-computed via canonical_metrics)
        "canonical_net_pct": _f(canonical.get("net_pct")),
        "canonical_max_dd_pct": _f(canonical.get("max_dd_pct")),
        "canonical_max_dd_pct_vs_stake": _f(canonical.get("max_dd_pct_vs_stake")),
        "canonical_ret_dd": _f(canonical.get("ret_dd")),
        "canonical_final_equity_usd": _f(canonical.get("final_equity_usd")),
        "cycle_win_rate_pct": _f(canonical.get("cycle_win_rate_pct")),
        "cycles_completed": (
            None if canonical.get("cycles_completed") is None
            else int(canonical["cycles_completed"])
        ),
        "trades_total": int(trades_total),
        "metrics_fn_version": METRICS_FN_VERSION,
    }


__all__ = ["build_cointegration_row"]
