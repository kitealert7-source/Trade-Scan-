"""basket_report.py — per-window report emitter for basket runs.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.3a (option 3 of the
artifact-discoverability gap report). Fills the per-window backtests/
folder so a basket run looks structurally like a per-symbol run when
opened from disk:

    backtests/<directive_id>_<basket_id>/
    ├── REPORT_<directive_id>.md
    ├── metadata/
    │   └── run_metadata.json
    └── raw/
        ├── bar_geometry.json
        ├── metrics_glossary.csv
        ├── results_basket.csv         (NEW — basket-specific telemetry)
        ├── results_risk.csv
        ├── results_standard.csv
        ├── results_tradelevel.csv     (already written by Path B)
        └── results_yearwise.csv

Scope discipline (Phase 5b.3a):
  - PER-WINDOW reporting only. The full basket-evaluator + deployable
    + portfolio_evaluation folder under TradeScan_State/strategies/
    is Phase 5b.3b/c, deferred until after Phase 5d.1 produces real
    multi-window data to inform the design.
  - Schema-compatible with per-symbol where it's meaningful (top-line
    metrics, risk metrics, yearwise breakdown). Basket-only telemetry
    (recycle events, harvest outcome) goes in a NEW results_basket.csv.
  - AK_Trade_Report.xlsx (formatted Excel) is a separate downstream
    stage; not in this phase.

Numeric conventions:
  - PnL is summed across all leg trades in trade-time order.
  - Drawdown is computed against trade-realized cumulative PnL only
    (per-symbol matches this; floating-PnL drawdown would require
    bar-level equity curve which is bigger scope).
  - Sharpe / Sortino are annualized using sqrt(252) trading days as
    the per-symbol convention does. Calculated on trade-level pnl
    (not bar-level returns). SQN uses pnl in USD as the R proxy
    when no risk_distance is available (baskets don't have one).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


__all__ = [
    "compute_basket_metrics",
    "write_per_window_report_artifacts",
    "write_basket_strategy_card",
]


_BASKET_METRICS_GLOSSARY_EXTRA = [
    ("recycle_event_count", "Recycle Event Count",
     "Number of winner-realize / loser-add events triggered by the basket rule",
     "count"),
    ("harvested_total_usd", "Harvested Total (USD)",
     "Cumulative cash banked at harvest exits (TARGET / FLOOR / TIME / BLOWN)",
     "USD"),
    ("final_realized_usd", "Final Realized (USD)",
     "Sum of pnl_usd across all per-leg trade records",
     "USD"),
    ("exit_reason", "Exit Reason",
     "TARGET | FLOOR | BLOWN | TIME | NONE (basket still open at window end)",
     "enum"),
]


# ---------------------------------------------------------------------------
# Metric calculators
# ---------------------------------------------------------------------------


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _compute_standard_metrics(df: pd.DataFrame) -> dict[str, float]:
    """Top-line metrics — matches per-symbol results_standard.csv schema."""
    if df.empty:
        return {"net_pnl_usd": 0.0, "trade_count": 0,
                "win_rate": 0.0, "profit_factor": 0.0,
                "gross_profit": 0.0, "gross_loss": 0.0}
    pnl = df["pnl_usd"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    gross_profit = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    return {
        "net_pnl_usd":    round(float(pnl.sum()), 2),
        "trade_count":    int(len(pnl)),
        "win_rate":       round(float((pnl > 0).mean()), 4),
        "profit_factor":  round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "gross_profit":   round(gross_profit, 2),
        "gross_loss":     round(gross_loss, 2),
    }


def _compute_risk_metrics(df: pd.DataFrame, starting_equity: float) -> dict[str, float]:
    """Drawdown + Sharpe/Sortino/SQN from trade-level pnl (matches per-symbol convention)."""
    if df.empty or starting_equity <= 0:
        return {k: 0.0 for k in [
            "max_drawdown_usd", "max_drawdown_pct", "return_dd_ratio",
            "sharpe_ratio", "sortino_ratio", "k_ratio", "sqn",
        ]}

    # Sort by exit_timestamp so cumulative PnL respects realization order.
    df_sorted = df.copy()
    df_sorted["exit_timestamp"] = pd.to_datetime(df_sorted["exit_timestamp"], errors="coerce")
    df_sorted = df_sorted.sort_values("exit_timestamp", na_position="last")
    pnl = df_sorted["pnl_usd"].astype(float).fillna(0.0)
    cum = pnl.cumsum()
    peak = cum.cummax()
    drawdown = peak - cum
    max_dd_usd = float(drawdown.max()) if not drawdown.empty else 0.0
    max_dd_pct = max_dd_usd / starting_equity if starting_equity > 0 else 0.0
    net_pnl = float(pnl.sum())
    return_dd = net_pnl / max_dd_usd if max_dd_usd > 0 else 0.0

    # Sharpe / Sortino / SQN — trade-level, simple form.
    n = len(pnl)
    mean = float(pnl.mean())
    std = float(pnl.std(ddof=1)) if n > 1 else 0.0
    downside = pnl[pnl < 0]
    dn_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sharpe = (mean / std) * np.sqrt(252) if std > 0 else 0.0
    sortino = (mean / dn_std) * np.sqrt(252) if dn_std > 0 else 0.0
    sqn = (mean / std) * np.sqrt(n) if std > 0 else 0.0

    # K-ratio: regression slope of equity curve / its standard error.
    # Per-symbol pipeline computes this; we approximate the same shape.
    if n >= 2:
        x = np.arange(n)
        slope, intercept = np.polyfit(x, cum.values, 1)
        residuals = cum.values - (slope * x + intercept)
        se = np.std(residuals, ddof=1) / np.sqrt(n) if n > 2 else float("inf")
        k_ratio = slope / se if se > 0 else 0.0
    else:
        k_ratio = 0.0

    return {
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "return_dd_ratio":  round(return_dd, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "sortino_ratio":    round(sortino, 2),
        "k_ratio":          round(float(k_ratio), 2),
        "sqn":              round(sqn, 2),
    }


def _compute_yearwise(df: pd.DataFrame) -> pd.DataFrame:
    """Per-year breakdown — matches per-symbol results_yearwise.csv schema."""
    if df.empty:
        return pd.DataFrame(columns=["year", "net_pnl_usd", "trade_count", "win_rate"])
    df_sorted = df.copy()
    df_sorted["exit_timestamp"] = pd.to_datetime(df_sorted["exit_timestamp"], errors="coerce")
    df_sorted = df_sorted.dropna(subset=["exit_timestamp"])
    if df_sorted.empty:
        return pd.DataFrame(columns=["year", "net_pnl_usd", "trade_count", "win_rate"])
    df_sorted["year"] = df_sorted["exit_timestamp"].dt.year
    grouped = df_sorted.groupby("year").agg(
        net_pnl_usd=("pnl_usd", lambda s: round(float(s.sum()), 2)),
        trade_count=("pnl_usd", "count"),
        win_rate=("pnl_usd", lambda s: round(float((s > 0).mean()), 4)),
    ).reset_index()
    return grouped


def _compute_basket_telemetry(basket_result: Any, df: pd.DataFrame) -> dict[str, Any]:
    """Basket-specific telemetry: recycle counts, harvest, exit reason."""
    final_realized = float(df["pnl_usd"].astype(float).sum()) if not df.empty else 0.0
    return {
        "recycle_event_count": int(len(basket_result.recycle_events)),
        "harvested_total_usd": round(float(basket_result.harvested_total_usd), 2),
        "final_realized_usd":  round(final_realized, 2),
        "exit_reason":         getattr(basket_result, "exit_reason", "") or "NONE",
    }


def _per_leg_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-leg breakdown for the markdown report."""
    if df.empty:
        return pd.DataFrame(columns=["symbol", "trades", "net_pnl_usd", "win_rate", "profit_factor"])
    rows = []
    for sym, grp in df.groupby("symbol"):
        pnl = grp["pnl_usd"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]
        gp = float(wins.sum())
        gl = float(abs(losses.sum()))
        rows.append({
            "symbol": sym,
            "trades": int(len(pnl)),
            "net_pnl_usd": round(float(pnl.sum()), 2),
            "win_rate": round(float((pnl > 0).mean()), 4),
            "profit_factor": round(gp / gl, 2) if gl > 0 else float("inf"),
        })
    return pd.DataFrame(rows)


def compute_basket_metrics(
    df_trades: pd.DataFrame,
    basket_result: Any,
    *,
    starting_equity: float = 1000.0,
) -> dict[str, Any]:
    """Compute every metric block. Used by tests + by the writer."""
    return {
        "standard": _compute_standard_metrics(df_trades),
        "risk":     _compute_risk_metrics(df_trades, starting_equity),
        "yearwise": _compute_yearwise(df_trades),
        "basket":   _compute_basket_telemetry(basket_result, df_trades),
        "per_leg":  _per_leg_summary(df_trades),
    }


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _write_csv_dict(path: Path, row: dict[str, Any]) -> None:
    """Write a single-row CSV from a dict (matches per-symbol convention)."""
    pd.DataFrame([row]).to_csv(path, index=False)


def _write_metrics_glossary(path: Path) -> None:
    """Copy the per-symbol glossary verbatim + append basket-only metric defs.

    The per-symbol glossary lives in a known artifact at
    backtests/<sample>/raw/metrics_glossary.csv. We embed the canonical
    rows here so we don't depend on a sibling backtest existing.
    """
    base_rows = [
        ("net_pnl_usd",      "Net Profit (USD)",      "Sum of all trade PnL", "USD"),
        ("trade_count",      "Trade Count",           "Total number of trades", "count"),
        ("win_rate",         "Win Rate",              "Fraction of winning trades", "decimal"),
        ("profit_factor",    "Profit Factor",         "Gross profit / Gross loss", "ratio"),
        ("gross_profit",     "Gross Profit",          "Sum of winning trades", "USD"),
        ("gross_loss",       "Gross Loss",            "Absolute sum of losing trades", "USD"),
        ("max_drawdown_usd", "Max Drawdown (USD)",    "Maximum peak-to-trough decline", "USD"),
        ("max_drawdown_pct", "Max Drawdown (%)",      "Max drawdown as fraction of capital", "decimal"),
        ("return_dd_ratio",  "Return/DD Ratio",       "Net profit / Max drawdown", "ratio"),
        ("sharpe_ratio",     "Sharpe Ratio",          "Annualized risk-adjusted return", "ratio"),
        ("sortino_ratio",    "Sortino Ratio",         "Annualized downside-risk-adjusted return", "ratio"),
        ("k_ratio",          "K-Ratio",               "Equity curve slope / standard error", "ratio"),
        ("sqn",              "SQN",                   "System Quality Number", "ratio"),
        ("pnl_usd",          "Trade PnL",             "(exit - entry) * position * direction", "USD"),
        ("r_multiple",       "R-Multiple",            "PnL / Risk per trade", "ratio"),
        ("bars_held",        "Bars Held",             "Number of bars in position", "count"),
    ]
    rows = base_rows + _BASKET_METRICS_GLOSSARY_EXTRA
    df = pd.DataFrame(rows, columns=["metric_key", "full_name", "definition", "unit"])
    df.to_csv(path, index=False)


def _bar_seconds_for_timeframe(tf: str) -> int:
    tf = (tf or "").strip().lower()
    table = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
             "1h": 3600, "4h": 14400, "1d": 86400}
    return table.get(tf, 300)


def _write_run_metadata(
    path: Path, *, run_id: str, directive_id: str, basket_id: str,
    parsed_directive: dict, engine_version: str, leg_symbols: list[str],
) -> None:
    test_block = parsed_directive.get("test", {}) or {}
    payload = {
        "run_id":           run_id,
        "strategy_name":    directive_id,
        "basket_id":        basket_id,
        "execution_mode":   "basket",
        "leg_symbols":      leg_symbols,
        "timeframe":        test_block.get("timeframe", "5m"),
        "date_range": {
            "start": str(test_block.get("start_date", "")),
            "end":   str(test_block.get("end_date", "")),
        },
        "execution_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "engine_name":      "Universal_Research_Engine",
        "engine_version":   engine_version,
        "broker":           test_block.get("broker", "OctaFx"),
        "schema_version":   "1.2.0-basket",
        "reference_capital_usd": 1000.0,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_basket_md_report(
    path: Path, *, run_id: str, directive_id: str, basket_id: str,
    parsed_directive: dict, metrics: dict[str, Any],
) -> None:
    test_block = parsed_directive.get("test", {}) or {}
    basket_block = parsed_directive.get("basket", {}) or {}
    rule = basket_block.get("recycle_rule", {}) or {}
    legs = basket_block.get("legs", []) or []

    std = metrics["standard"]
    risk = metrics["risk"]
    bsk = metrics["basket"]
    yw_df = metrics["yearwise"]
    leg_df = metrics["per_leg"]

    lines: list[str] = []
    lines.append(f"# Basket Report — {directive_id}")
    lines.append("")
    lines.append(f"Run ID: `{run_id}`")
    lines.append(f"Basket ID: `{basket_id}`")
    lines.append(f"Recycle Rule: `{rule.get('name', '?')}@{rule.get('version', '?')}`")
    lines.append(f"Timeframe: {test_block.get('timeframe', '?')}")
    lines.append(f"Date Range: {test_block.get('start_date', '?')} → {test_block.get('end_date', '?')}")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## Basket Composition")
    lines.append("")
    lines.append("| Symbol | Lot | Direction |")
    lines.append("|--------|-----|-----------|")
    for leg in legs:
        lines.append(f"| {leg.get('symbol', '?')} | {leg.get('lot', '?')} | {leg.get('direction', '?')} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## Top-Line Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Trades | {std['trade_count']} |")
    lines.append(f"| Net PnL | ${std['net_pnl_usd']:,.2f} |")
    lines.append(f"| Win Rate | {std['win_rate']*100:.1f}% |")
    lines.append(f"| Profit Factor | {std['profit_factor']} |")
    lines.append(f"| Gross Profit | ${std['gross_profit']:,.2f} |")
    lines.append(f"| Gross Loss | ${std['gross_loss']:,.2f} |")
    lines.append("")
    lines.append("## Risk")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Max DD (USD) | ${risk['max_drawdown_usd']:,.2f} |")
    lines.append(f"| Max DD (%) | {risk['max_drawdown_pct']*100:.2f}% |")
    lines.append(f"| Return / DD | {risk['return_dd_ratio']} |")
    lines.append(f"| Sharpe | {risk['sharpe_ratio']} |")
    lines.append(f"| Sortino | {risk['sortino_ratio']} |")
    lines.append(f"| K-Ratio | {risk['k_ratio']} |")
    lines.append(f"| SQN | {risk['sqn']} |")
    lines.append("")
    lines.append("## Basket Telemetry")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Recycle Events | {bsk['recycle_event_count']} |")
    lines.append(f"| Harvested Total (USD) | ${bsk['harvested_total_usd']:,.2f} |")
    lines.append(f"| Final Realized (USD) | ${bsk['final_realized_usd']:,.2f} |")
    lines.append(f"| Exit Reason | {bsk['exit_reason']} |")
    lines.append("")

    lines.append("## Per-Leg Breakdown")
    lines.append("")
    if leg_df.empty:
        lines.append("_(no trades recorded)_")
    else:
        lines.append("| Symbol | Trades | Net PnL | Win % | PF |")
        lines.append("|--------|--------|---------|-------|-----|")
        for _, row in leg_df.iterrows():
            lines.append(f"| {row['symbol']} | {int(row['trades'])} | "
                         f"${row['net_pnl_usd']:,.2f} | {row['win_rate']*100:.1f}% | "
                         f"{row['profit_factor']} |")
    lines.append("")

    lines.append("## Yearwise Performance")
    lines.append("")
    if yw_df.empty:
        lines.append("_(insufficient timestamped trades)_")
    else:
        lines.append("| Year | Trades | Net PnL | Win % |")
        lines.append("|------|--------|---------|-------|")
        for _, row in yw_df.iterrows():
            lines.append(f"| {int(row['year'])} | {int(row['trade_count'])} | "
                         f"${row['net_pnl_usd']:,.2f} | {row['win_rate']*100:.1f}% |")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_basket_strategy_card(
    out_dir: Path,
    *,
    directive_id: str,
    run_id: str,
    parsed_directive: dict,
    engine_version: str,
) -> Path:
    """Write STRATEGY_CARD.md for a basket — basket-flavored equivalent of
    tools/generate_strategy_card.py's per-symbol output.

    Matches the per-symbol card's section layout:
      1. Header line (directive, run_id, engine, generated)
      2. Configuration table (basket-specific fields)
      3. Active Logic (one-liner of recycle + gate + harvest)
      4. Hypothesis (from directive notes/description)
      5. Testing Logic (from directive description)
      6. Changes from Previous Run (P-diff scaffolding; basket diff is
         deferred until a second pass exists)

    This is the basket counterpart to generate_strategy_card.generate_strategy_card,
    which assumes a strategy.py with STRATEGY_SIGNATURE. Basket directives
    don't have one — the rule lives in tools/recycle_rules/<name>.py and
    its parameters live in the directive's basket block.
    """
    from datetime import datetime, timezone

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    test_block = parsed_directive.get("test", {}) or {}
    basket_block = parsed_directive.get("basket", {}) or {}
    rule = basket_block.get("recycle_rule", {}) or {}
    legs = basket_block.get("legs", []) or []
    regime_gate = basket_block.get("regime_gate", {}) or {}
    rule_params = rule.get("params", {}) or {}

    # Parse sweep/pass from the directive name (mirrors generate_strategy_card._parse_name)
    import re
    m = re.search(r"_S(\d+)_V(\d+)_P(\d+)$", directive_id)
    if m:
        sweep_str = f"S{int(m.group(1)):02d}"
        version_str = f"V{int(m.group(2))}"
        pass_str = f"P{int(m.group(3)):02d}"
    else:
        sweep_str = version_str = pass_str = "?"

    timeframe = (test_block.get("timeframe") or "?").upper()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    basket_id = basket_block.get("basket_id", "?")
    rule_name = rule.get("name", "?")
    rule_version = rule.get("version", "?")

    lines: list[str] = []
    lines.append(f"# STRATEGY CARD — {directive_id}")
    lines.append("")
    lines.append(
        f"**Basket:** {basket_id}  |  **Timeframe:** {timeframe}  |  "
        f"**Sweep:** {sweep_str}  |  **Pass:** {pass_str}  |  "
        f"**Run ID:** `{run_id}`  |  **Engine:** {engine_version}  |  "
        f"**Generated:** {generated}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Configuration table ----
    lines.append("## Configuration")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|-----------|-------|")
    lines.append(f"| `execution_mode` | basket |")
    lines.append(f"| `basket.basket_id` | {basket_id} |")
    lines.append(f"| `basket.leg_count` | {len(legs)} |")
    leg_specs = ";".join(
        f"{l.get('symbol')}:{l.get('lot')}:{l.get('direction')}" for l in legs
    )
    lines.append(f"| `basket.legs` | {leg_specs} |")
    if "initial_stake_usd" in basket_block:
        lines.append(f"| `basket.initial_stake_usd` | {basket_block['initial_stake_usd']} |")
    if "harvest_threshold_usd" in basket_block:
        lines.append(f"| `basket.harvest_threshold_usd` | {basket_block['harvest_threshold_usd']} |")
    lines.append(f"| `basket.recycle_rule.name@version` | {rule_name}@{rule_version} |")
    for k in sorted(rule_params.keys()):
        lines.append(f"| `basket.recycle_rule.params.{k}` | {rule_params[k]} |")
    if regime_gate:
        gate_factor = regime_gate.get("factor", "?")
        gate_op = regime_gate.get("operator", "?")
        gate_val = regime_gate.get("value", "?")
        lines.append(f"| `basket.regime_gate` | {gate_factor} {gate_op} {gate_val} |")
    lines.append("")

    # ---- Active Logic ----
    lines.append("## Active Logic")
    lines.append("")
    parts: list[str] = []
    parts.append(f"Rule: {rule_name}@{rule_version}")
    if regime_gate:
        parts.append(
            f"Gate: {regime_gate.get('factor', '?')} "
            f"{regime_gate.get('operator', '?')} {regime_gate.get('value', '?')}"
        )
    if "harvest_threshold_usd" in basket_block:
        parts.append(f"Harvest: ${basket_block['harvest_threshold_usd']}")
    elif "harvest_target_usd" in rule_params:
        parts.append(f"Harvest: ${rule_params['harvest_target_usd']}")
    if "trigger_usd" in rule_params:
        parts.append(f"Trigger: ${rule_params['trigger_usd']}")
    lines.append(" | ".join(parts) if parts else "(no rule attached)")
    lines.append("")

    # ---- Hypothesis ----
    lines.append("## Hypothesis")
    lines.append("")
    notes = (test_block.get("notes") or "").strip()
    if notes:
        lines.append(notes)
    else:
        lines.append("[UNAVAILABLE]")
    lines.append("")

    # ---- Testing Logic ----
    lines.append("## Testing Logic")
    lines.append("")
    description = (test_block.get("description") or "").strip()
    if description:
        lines.append(description)
    else:
        lines.append("[UNAVAILABLE]")
    lines.append("")

    # ---- Changes from Previous Run ----
    lines.append("## Changes from Previous Run")
    lines.append("")
    if pass_str == "P00" and sweep_str == "S00":
        lines.append("Initial run — no previous pass.")
    elif pass_str == "P00":
        lines.append(f"Sweep transition (S(prev) → {sweep_str}) — basket-pass diff "
                     f"not yet implemented for cross-sweep comparisons.")
    else:
        lines.append(f"Basket-pass diff vs P(n-1) not yet implemented — "
                     f"H2 family currently has only the in-sample pass on disk. "
                     f"Phase 5d.1 multi-window will populate prior passes.")
    lines.append("")
    lines.append("---")
    lines.append("*Auto-generated — do not edit. Regenerated on every basket dispatch.*")

    card_path = out_dir / "STRATEGY_CARD.md"
    card_path.write_text("\n".join(lines), encoding="utf-8")
    return card_path


def write_per_window_report_artifacts(
    out_dir: Path,
    *,
    run_id: str,
    directive_id: str,
    basket_result: Any,
    df_trades: pd.DataFrame,
    parsed_directive: dict,
    engine_version: str,
    starting_equity: float = 1000.0,
) -> dict[str, Path]:
    """Write all per-window report files for a basket run.

    Returns a dict {file_purpose: written_path} for the caller to log.
    """
    out_dir = Path(out_dir)
    raw_dir = out_dir / "raw"
    meta_dir = out_dir / "metadata"
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    metrics = compute_basket_metrics(df_trades, basket_result, starting_equity=starting_equity)
    basket_id = basket_result.basket_id
    leg_symbols = [l.get("symbol") for l in basket_result.legs]
    timeframe = (parsed_directive.get("test", {}) or {}).get("timeframe", "5m")

    paths: dict[str, Path] = {}

    # results_standard.csv
    p = raw_dir / "results_standard.csv"
    _write_csv_dict(p, metrics["standard"])
    paths["standard"] = p

    # results_risk.csv
    p = raw_dir / "results_risk.csv"
    _write_csv_dict(p, metrics["risk"])
    paths["risk"] = p

    # results_yearwise.csv
    p = raw_dir / "results_yearwise.csv"
    metrics["yearwise"].to_csv(p, index=False)
    paths["yearwise"] = p

    # results_basket.csv (NEW — basket-specific telemetry)
    p = raw_dir / "results_basket.csv"
    _write_csv_dict(p, metrics["basket"])
    paths["basket"] = p

    # metrics_glossary.csv
    p = raw_dir / "metrics_glossary.csv"
    _write_metrics_glossary(p)
    paths["glossary"] = p

    # bar_geometry.json
    p = raw_dir / "bar_geometry.json"
    p.write_text(json.dumps({"median_bar_seconds": _bar_seconds_for_timeframe(timeframe)},
                            indent=2), encoding="utf-8")
    paths["bar_geometry"] = p

    # metadata/run_metadata.json
    p = meta_dir / "run_metadata.json"
    _write_run_metadata(
        p, run_id=run_id, directive_id=directive_id, basket_id=basket_id,
        parsed_directive=parsed_directive, engine_version=engine_version,
        leg_symbols=leg_symbols,
    )
    paths["metadata"] = p

    # REPORT_<directive_id>.md
    p = out_dir / f"REPORT_{directive_id}.md"
    _write_basket_md_report(
        p, run_id=run_id, directive_id=directive_id, basket_id=basket_id,
        parsed_directive=parsed_directive, metrics=metrics,
    )
    paths["report"] = p

    return paths
