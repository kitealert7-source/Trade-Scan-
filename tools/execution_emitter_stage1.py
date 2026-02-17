"""
Stage-1 Execution Emitter — SOP_OUTPUT Compliant
Owner: Stage-1
Computes and emits all metrics as defined in SOP_OUTPUT Section 4.

Required outputs:
- raw/results_tradelevel.csv
- raw/results_standard.csv
- raw/results_risk.csv
- raw/results_yearwise.csv
- raw/metrics_glossary.csv
- metadata/run_metadata.json
"""

import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class RawTradeRecord:
    """Trade record for Stage-1 emission. Owner: Stage-1."""
    strategy_name: str
    parent_trade_id: int
    sequence_index: int
    entry_timestamp: str
    exit_timestamp: str
    direction: int          # 1 = Long, -1 = Short
    entry_price: float
    exit_price: float
    bars_held: int
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    trade_high: Optional[float] = None
    trade_low: Optional[float] = None
    atr_entry: Optional[float] = None
    position_units: Optional[float] = None
    notional_usd: Optional[float] = None
    mfe_price: Optional[float] = None
    mae_price: Optional[float] = None
    mfe_r: Optional[float] = None
    mfe_r: Optional[float] = None
    mae_r: Optional[float] = None
    volatility_regime: Optional[str] = None  # "low", "normal", "high" per SOP_TESTING §7.y


@dataclass
class Stage1Metadata:
    """Run metadata. Owner: Stage-1."""
    run_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    date_range_start: str
    date_range_end: str
    execution_timestamp_utc: str
    engine_name: str
    engine_version: str
    broker: str
    schema_version: str = "1.1.0"  # Updated for SOP_OUTPUT v4.1 compliance
    reference_capital_usd: Optional[float] = None


# =============================================================================
# METRIC COMPUTATION (SOP_OUTPUT Section 4)
# =============================================================================

def compute_volatility_regimes(trades: List[RawTradeRecord]) -> None:
    """
    Compute volatility regime for each trade using ATR percentile method.
    Owner: Stage-1 (SOP_TESTING §7.y)
    
    Logic ported from Stage-2:
    - ATR proxy = trade_high - trade_low (if atr_entry missing)
    - Thresholds: 33rd and 66th percentiles of ATR values
    - Assigns: 'low', 'normal', 'high' to trade.volatility_regime
    - Mutates trades in-place
    """
    if not trades:
        return

    # Extract or compute ATRs
    atr_values = []
    for t in trades:
        atr = t.atr_entry if t.atr_entry is not None and t.atr_entry > 0 else 0.0
        if atr == 0 and t.trade_high is not None and t.trade_low is not None:
             # Fallback proxy
             atr = t.trade_high - t.trade_low
        
        if atr == 0 and t.entry_price > 0:
             # Final fallback
             atr = t.entry_price * 0.015
        
        atr_values.append(atr)
        
        # PERSISTENCE FIX: Save back to record for CSV emission
        if t.atr_entry is None or t.atr_entry == 0:
            t.atr_entry = atr

    # Compute thresholds
    sorted_atrs = sorted([a for a in atr_values if a > 0])
    if not sorted_atrs:
        for t in trades:
            t.volatility_regime = "normal"
        return

    n = len(sorted_atrs)
    p33_idx = int(n * 0.33)
    p66_idx = int(n * 0.66)
    
    p33_threshold = sorted_atrs[p33_idx] if p33_idx < n else sorted_atrs[-1]
    p66_threshold = sorted_atrs[p66_idx] if p66_idx < n else sorted_atrs[-1]

    # Assign regimes
    for i, t in enumerate(trades):
        val = atr_values[i]
        if val <= p33_threshold:
            t.volatility_regime = "low"
        elif val <= p66_threshold:
            t.volatility_regime = "normal"
        else:
            t.volatility_regime = "high"


def compute_standard_metrics(trades: List[RawTradeRecord]) -> dict:
    """
    Compute results_standard.csv metrics.
    Owner: Stage-1
    
    Formulas from SOP_OUTPUT 4.2:
    - net_pnl_usd = SUM(pnl_usd)
    - trade_count = COUNT(trades)
    - win_rate = COUNT(pnl_usd > 0) / trade_count
    - profit_factor = SUM(pnl_usd > 0) / ABS(SUM(pnl_usd < 0))
    - gross_profit = SUM(pnl_usd WHERE pnl_usd > 0)
    - gross_loss = ABS(SUM(pnl_usd WHERE pnl_usd < 0))
    """
    if not trades:
        return {
            "net_pnl_usd": 0.0,
            "trade_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0
        }
    
    pnls = [t.pnl_usd for t in trades]
    
    net_pnl_usd = sum(pnls)
    trade_count = len(trades)
    winning_trades = [p for p in pnls if p > 0]
    losing_trades = [p for p in pnls if p < 0]
    
    win_count = len(winning_trades)
    win_rate = win_count / trade_count if trade_count > 0 else 0.0
    
    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    
    return {
        "net_pnl_usd": round(net_pnl_usd, 2),
        "trade_count": trade_count,
        "win_rate": round(win_rate, 4),  # Stored as decimal 0.0-1.0
        "profit_factor": round(profit_factor, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2)
    }


def compute_risk_metrics(trades: List[RawTradeRecord], reference_capital: float) -> dict:
    """
    Compute results_risk.csv metrics.
    Owner: Stage-1
    
    Formulas from SOP_OUTPUT 4.3 + SOP_TESTING §7:
    - max_drawdown_usd = MAX(cumulative_peak - cumulative_pnl)
    - max_drawdown_pct = max_drawdown_usd / reference_capital
    - return_dd_ratio = net_pnl_usd / max_drawdown_usd
    - sharpe_ratio = (avg_return - risk_free) / std_return * sqrt(252)
    - sortino_ratio = (avg_return - risk_free) / downside_std * sqrt(252)
    - k_ratio = equity_slope / std_error_of_slope
    - sqn = sqrt(N) * expectancy / std_pnl
    """
    import math
    
    if not trades:
        return {
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "return_dd_ratio": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "k_ratio": 0.0,
            "sqn": 0.0
        }
    
    pnls = [t.pnl_usd for t in trades]
    n = len(pnls)
    
    # Compute cumulative PnL series and equity curve
    equity_curve = []
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    
    for pnl in pnls:
        cumulative += pnl
        equity_curve.append(cumulative)
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    net_pnl = sum(pnls)
    max_dd_pct = max_drawdown / reference_capital if reference_capital > 0 else 0.0
    return_dd_ratio = net_pnl / max_drawdown if max_drawdown > 0 else 0.0
    
    # === SHARPE RATIO ===
    returns = [pnl / reference_capital for pnl in pnls] if reference_capital > 0 else [0.0] * n
    avg_return = sum(returns) / n if n > 0 else 0.0
    variance = sum((r - avg_return) ** 2 for r in returns) / n if n > 0 else 0.0
    std_return = math.sqrt(variance) if variance > 0 else 0.0
    sharpe_ratio = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0.0
    
    # === SORTINO RATIO ===
    downside_returns = [r for r in returns if r < 0]
    if downside_returns:
        downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0.0
        sortino_ratio = (avg_return / downside_std) * math.sqrt(252) if downside_std > 0 else 0.0
    else:
        sortino_ratio = avg_return * math.sqrt(252) if avg_return > 0 else 0.0
    
    # === K-RATIO ===
    if n >= 3:
        x_vals = list(range(n))
        x_mean = sum(x_vals) / n
        y_mean = sum(equity_curve) / n
        
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, equity_curve))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)
        
        if denominator > 0:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean
            residuals = [y - (slope * x + intercept) for x, y in zip(x_vals, equity_curve)]
            residual_ss = sum(r ** 2 for r in residuals)
            std_error = math.sqrt(residual_ss / (n - 2)) / math.sqrt(denominator) if n > 2 else 0.0
            k_ratio = slope / std_error if std_error > 0 else slope
        else:
            k_ratio = 0.0
    else:
        k_ratio = 0.0
    
    # === SQN ===
    avg_pnl = sum(pnls) / n if n > 0 else 0.0
    pnl_variance = sum((p - avg_pnl) ** 2 for p in pnls) / n if n > 0 else 0.0
    pnl_std = math.sqrt(pnl_variance) if pnl_variance > 0 else 0.0
    sqn = math.sqrt(n) * avg_pnl / pnl_std if pnl_std > 0 else 0.0
    
    return {
        "max_drawdown_usd": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),  # Stored as decimal
        "return_dd_ratio": round(return_dd_ratio, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "sortino_ratio": round(sortino_ratio, 2),
        "k_ratio": round(k_ratio, 2),
        "sqn": round(sqn, 2)
    }


def compute_yearwise_metrics(trades: List[RawTradeRecord]) -> List[dict]:
    """
    Compute results_yearwise.csv metrics.
    Owner: Stage-1
    
    Columns from SOP_OUTPUT 4.4:
    - year (Integer)
    - net_pnl_usd (Float)
    - trade_count (Integer)
    - win_rate (Float)
    """
    if not trades:
        return []
    
    # Group trades by year
    yearly_data = {}
    for t in trades:
        try:
            year = int(t.exit_timestamp[:4])
        except (ValueError, TypeError):
            continue
        
        if year not in yearly_data:
            yearly_data[year] = {"pnls": [], "count": 0, "wins": 0}
        
        yearly_data[year]["pnls"].append(t.pnl_usd)
        yearly_data[year]["count"] += 1
        if t.pnl_usd > 0:
            yearly_data[year]["wins"] += 1
    
    result = []
    for year in sorted(yearly_data.keys()):
        data = yearly_data[year]
        net_pnl = sum(data["pnls"])
        trade_count = data["count"]
        win_rate = data["wins"] / trade_count if trade_count > 0 else 0.0
        
        result.append({
            "year": year,
            "net_pnl_usd": round(net_pnl, 2),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 4)
        })
    
    return result


def get_metrics_glossary() -> List[dict]:
    """
    Generate metrics_glossary.csv content.
    Owner: Stage-1
    """
    return [
        {"metric_key": "net_pnl_usd", "full_name": "Net Profit (USD)", "definition": "Sum of all trade PnL", "unit": "USD"},
        {"metric_key": "trade_count", "full_name": "Trade Count", "definition": "Total number of trades", "unit": "count"},
        {"metric_key": "win_rate", "full_name": "Win Rate", "definition": "Fraction of winning trades", "unit": "decimal"},
        {"metric_key": "profit_factor", "full_name": "Profit Factor", "definition": "Gross profit / Gross loss", "unit": "ratio"},
        {"metric_key": "gross_profit", "full_name": "Gross Profit", "definition": "Sum of winning trades", "unit": "USD"},
        {"metric_key": "gross_loss", "full_name": "Gross Loss", "definition": "Absolute sum of losing trades", "unit": "USD"},
        {"metric_key": "max_drawdown_usd", "full_name": "Max Drawdown (USD)", "definition": "Maximum peak-to-trough decline", "unit": "USD"},
        {"metric_key": "max_drawdown_pct", "full_name": "Max Drawdown (%)", "definition": "Max drawdown as fraction of capital", "unit": "decimal"},
        {"metric_key": "return_dd_ratio", "full_name": "Return/DD Ratio", "definition": "Net profit / Max drawdown", "unit": "ratio"},
        {"metric_key": "pnl_usd", "full_name": "Trade PnL", "definition": "(exit - entry) * position * direction", "unit": "USD"},
        {"metric_key": "r_multiple", "full_name": "R-Multiple", "definition": "PnL / Risk per trade", "unit": "ratio"},
        {"metric_key": "bars_held", "full_name": "Bars Held", "definition": "Number of bars in position", "unit": "count"},
    ]


# =============================================================================
# EMISSION FUNCTION
# =============================================================================

def emit_stage1(
    trades: List[RawTradeRecord],
    metadata: Stage1Metadata,
    directive_content: str,
    directive_filename: str,
    output_root: Path,
    median_bar_seconds: int = 0
) -> Path:
    """
    Emit all Stage-1 artifacts as defined in SOP_OUTPUT Section 4.
    Owner: Stage-1
    
    Emits:
    - raw/results_tradelevel.csv
    - raw/results_standard.csv
    - raw/results_risk.csv
    - raw/results_yearwise.csv
    - raw/metrics_glossary.csv
    - metadata/run_metadata.json
    - <directive_copy>
    """
    
    # 1. Prepare Directory Structure
    out_folder = output_root / metadata.strategy_name
    raw_dir = out_folder / "raw"
    metadata_dir = out_folder / "metadata"
    
    raw_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Emit results_tradelevel.csv (SOP 4.1)
    tradelevel_fields = [
        "strategy_name", "parent_trade_id", "sequence_index",
        "entry_timestamp", "exit_timestamp", "direction",
        "entry_price", "exit_price", "pnl_usd", "r_multiple",
        "trade_high", "trade_low", "bars_held", 
        "atr_entry", "position_units", "notional_usd", 
        "mfe_price", "mae_price", "mfe_r", "mae_r",
        "volatility_regime"
    ]
    
    # Compute volatility regimes before emission (SOP_TESTING §7.y)
    compute_volatility_regimes(trades)
    
    with open(raw_dir / "results_tradelevel.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=tradelevel_fields)
        writer.writeheader()
        for t in trades:
            writer.writerow({
                "strategy_name": t.strategy_name,
                "parent_trade_id": t.parent_trade_id,
                "sequence_index": t.sequence_index,
                "entry_timestamp": t.entry_timestamp,
                "exit_timestamp": t.exit_timestamp,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_usd": round(t.pnl_usd, 2),
                "r_multiple": round(t.r_multiple, 2),
                "trade_high": t.trade_high if t.trade_high is not None else "",
                "trade_low": t.trade_low if t.trade_low is not None else "",
                "bars_held": t.bars_held,
                "atr_entry": t.atr_entry if t.atr_entry is not None else "",
                "position_units": t.position_units if t.position_units is not None else "",
                "notional_usd": t.notional_usd if t.notional_usd is not None else "",
                "mfe_price": t.mfe_price if t.mfe_price is not None else "",
                "mae_price": t.mae_price if t.mae_price is not None else "",
                "mfe_r": t.mfe_r if t.mfe_r is not None else "",
                "mae_r": t.mae_r if t.mae_r is not None else "",
                "volatility_regime": t.volatility_regime if t.volatility_regime else "normal"
            })
    
    # 3. Emit results_standard.csv (SOP 4.2)
    standard_metrics = compute_standard_metrics(trades)
    standard_fields = ["net_pnl_usd", "trade_count", "win_rate", "profit_factor", "gross_profit", "gross_loss"]
    with open(raw_dir / "results_standard.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=standard_fields)
        writer.writeheader()
        writer.writerow(standard_metrics)
    
    # 4. Emit results_risk.csv (SOP 4.3)
    if not metadata.reference_capital_usd or metadata.reference_capital_usd <= 0:
        raise ValueError("Stage-1 Metadata missing valid reference_capital_usd")
    reference_capital = metadata.reference_capital_usd
    risk_metrics = compute_risk_metrics(trades, reference_capital)
    risk_fields = ["max_drawdown_usd", "max_drawdown_pct", "return_dd_ratio", "sharpe_ratio", "sortino_ratio", "k_ratio", "sqn"]
    with open(raw_dir / "results_risk.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=risk_fields)
        writer.writeheader()
        writer.writerow(risk_metrics)
    
    # 5. Emit results_yearwise.csv (SOP 4.4)
    yearwise_metrics = compute_yearwise_metrics(trades)
    yearwise_fields = ["year", "net_pnl_usd", "trade_count", "win_rate"]
    with open(raw_dir / "results_yearwise.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=yearwise_fields)
        writer.writeheader()
        for row in yearwise_metrics:
            writer.writerow(row)
    
    # 6. Emit metrics_glossary.csv (SOP 4.6)
    glossary = get_metrics_glossary()
    glossary_fields = ["metric_key", "full_name", "definition", "unit"]
    with open(raw_dir / "metrics_glossary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=glossary_fields)
        writer.writeheader()
        for row in glossary:
            writer.writerow(row)
    
    # 7. Emit run_metadata.json (SOP 4.5)
    meta_dict = {
        "run_id": metadata.run_id,
        "strategy_name": metadata.strategy_name,
        "symbol": metadata.symbol,
        "timeframe": metadata.timeframe,
        "date_range": {
            "start": metadata.date_range_start,
            "end": metadata.date_range_end
        },
        "execution_timestamp_utc": metadata.execution_timestamp_utc,
        "engine_name": metadata.engine_name,
        "engine_version": metadata.engine_version,
        "broker": metadata.broker,
        "schema_version": metadata.schema_version,
        "reference_capital_usd": metadata.reference_capital_usd
    }
    with open(metadata_dir / "run_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_dict, f, indent=2)
        
    # 7b. Emit bar_geometry.json (v5 Metric Integrity)
    if median_bar_seconds > 0:
        with open(raw_dir / "bar_geometry.json", "w", encoding="utf-8") as f:
            json.dump({"median_bar_seconds": median_bar_seconds}, f, indent=2)
    
    # 8. Copy Directive
    with open(out_folder / directive_filename, "w", encoding="utf-8") as f:
        f.write(directive_content)
    
    return out_folder
