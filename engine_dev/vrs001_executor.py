"""
VRS001 Execution Script — Stage-1 SOP-Complete
Directive: VRS001.md
Symbol: ETHUSD / OctaFX / 4H
"""

import hashlib
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.execution_emitter import (
    emit_results,
    TradeRecord,
    StandardMetrics,
    RiskMetrics,
    YearwiseRecord,
    GlossaryEntry,
    RunMetadata,
    EmissionResult,
)


TRADE_SCAN_ROOT = Path(__file__).parent.parent
DATA_ROOT = TRADE_SCAN_ROOT / "data_root" / "MASTER_DATA" / "ETH_OCTAFX_MASTER" / "CLEAN"
DIRECTIVE_PATH = TRADE_SCAN_ROOT / "backtest_directives" / "active" / "VRS001.md"
BACKTESTS_ROOT = TRADE_SCAN_ROOT / "backtests"


def load_data():
    files = sorted(DATA_ROOT.glob("ETHUSD_OCTAFX_4h_*_CLEAN.csv"))
    dfs = []
    for f in files:
        df = pd.read_csv(f, parse_dates=["time"])
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.sort_values("time").reset_index(drop=True)
    return combined


def calculate_indicators(df):
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema_slope"] = df["ema200"].diff(20)
    
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    alpha = 1 / 2  # Wilder smoothing: alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi2"] = 100 - (100 / (1 + rs))
    df["rsi2_avg"] = (df["rsi2"].shift(1) + df["rsi2"].shift(2)) / 2
    
    # ATR-14 using Wilder smoothing
    tr1 = df["high"] - df["low"]
    tr2 = abs(df["high"] - df["close"].shift(1))
    tr3 = abs(df["low"] - df["close"].shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_alpha = 1 / 14
    df["atr14"] = tr.ewm(alpha=atr_alpha, adjust=False).mean()
    
    return df


def run_strategy(df, min_lot, usd_per_unit):
    trades = []
    in_pos = False
    trade_id = 1
    
    entry_idx = 0
    entry_price = 0.0
    direction = 0
    stop_price = 0.0
    tp_price = 0.0
    bars_held = 0
    trade_high = 0.0
    trade_low = float('inf')
    initial_risk = 0.0
    
    for i in range(202, len(df)):
        row = df.iloc[i]
        
        uptrend = row["close"] > row["ema200"] and row["ema_slope"] > 0
        downtrend = row["close"] < row["ema200"] and row["ema_slope"] < 0
        
        if not in_pos:
            rsi_avg = row["rsi2_avg"]
            
            if uptrend and rsi_avg <= 25:
                direction = 1
                entry_price = row["close"]
                stop_price = entry_price * 0.985
                initial_risk = entry_price - stop_price
                tp_price = entry_price + 2.0 * initial_risk
                entry_idx = i
                bars_held = 0
                trade_high = row["high"]
                trade_low = row["low"]
                in_pos = True
                
            elif downtrend and rsi_avg >= 75:
                direction = -1
                entry_price = row["close"]
                stop_price = entry_price * 1.015
                initial_risk = stop_price - entry_price
                tp_price = entry_price - 2.0 * initial_risk
                entry_idx = i
                bars_held = 0
                trade_high = row["high"]
                trade_low = row["low"]
                in_pos = True
                
        else:
            bars_held += 1
            trade_high = max(trade_high, row["high"])
            trade_low = min(trade_low, row["low"])
            exit_price = None
            
            rsi_exit = (direction == 1 and row["rsi2"] > 75) or (direction == -1 and row["rsi2"] < 25)
            timeout = bars_held >= 15
            
            if direction == 1:
                stop_hit = row["low"] <= stop_price
                tp_hit = row["high"] >= tp_price
                hard_stop_hit = row["low"] <= entry_price * 0.98
            else:
                stop_hit = row["high"] >= stop_price
                tp_hit = row["low"] <= tp_price
                hard_stop_hit = row["high"] >= entry_price * 1.02
            
            if hard_stop_hit:
                exit_price = entry_price * (0.98 if direction == 1 else 1.02)
            elif stop_hit:
                exit_price = stop_price
            elif tp_hit:
                exit_price = tp_price
            elif rsi_exit:
                exit_price = row["close"]
            elif timeout:
                exit_price = row["close"]
            
            if exit_price is not None:
                if initial_risk <= 0:
                    raise ValueError(f"Trade {trade_id}: initial_risk must be > 0, got {initial_risk}")
                
                if direction == 1:
                    mfe_price = trade_high - entry_price
                    mae_price = entry_price - trade_low
                else:
                    mfe_price = entry_price - trade_low
                    mae_price = trade_high - entry_price
                
                mfe_price = max(0.0, mfe_price)
                mae_price = max(0.0, mae_price)
                mfe_r = mfe_price / initial_risk
                mae_r = mae_price / initial_risk
                
                price_diff = (exit_price - entry_price) * direction
                position_units = min_lot / 0.01
                net_pnl = price_diff * usd_per_unit * position_units
                notional_usd = position_units * entry_price
                atr_entry = float(df.iloc[entry_idx]["atr14"]) if not pd.isna(df.iloc[entry_idx]["atr14"]) else 0.0
                
                trades.append({
                    "strategy_name": "VRS001_ETHUSD_4H",
                    "parent_trade_id": trade_id,
                    "sequence_index": 0,
                    "entry_timestamp": df.iloc[entry_idx]["time"],
                    "exit_timestamp": row["time"],
                    "direction": direction,
                    "entry_price": float(entry_price),
                    "exit_price": float(exit_price),
                    "net_pnl": round(float(net_pnl), 2),
                    "bars_held": bars_held,
                    "atr_entry": round(atr_entry, 4),
                    "position_units": round(position_units, 4),
                    "notional_usd": round(float(notional_usd), 2),
                    "mfe_price": round(float(mfe_price), 4),
                    "mae_price": round(float(mae_price), 4),
                    "mfe_r": round(float(mfe_r), 4),
                    "mae_r": round(float(mae_r), 4),
                })
                trade_id += 1
                in_pos = False
                trade_high = 0.0
                trade_low = float('inf')
    
    return trades


def compute_standard_metrics(trades_list):
    if not trades_list:
        return None
    
    net_pnl = sum(t["net_pnl"] for t in trades_list)
    wins = sum(1 for t in trades_list if t["net_pnl"] > 0)
    trade_count = len(trades_list)
    win_rate = wins / trade_count if trade_count > 0 else 0.0
    
    gross_profit = sum(t["net_pnl"] for t in trades_list if t["net_pnl"] > 0)
    gross_loss = abs(sum(t["net_pnl"] for t in trades_list if t["net_pnl"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    
    return StandardMetrics(
        net_pnl_usd=net_pnl,
        win_rate=win_rate,
        profit_factor=profit_factor,
        trade_count=trade_count,
    )


def compute_risk_metrics(trades_list, net_pnl):
    if not trades_list:
        return None
    
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    
    for t in trades_list:
        cumulative += t["net_pnl"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    
    max_dd_pct = max_dd / 5000.0 if max_dd > 0 else 0.0
    return_dd_ratio = net_pnl / max_dd if max_dd > 0 else 0.0
    
    return RiskMetrics(
        max_drawdown_usd=max_dd,
        max_drawdown_pct=min(max_dd_pct, 1.0),
        sharpe_ratio=None,
        sortino_ratio=None,
        return_dd_ratio=return_dd_ratio,
    )


def compute_yearwise_metrics(trades_list):
    if not trades_list:
        return []
    
    by_year = {}
    for t in trades_list:
        year = t["exit_timestamp"].year
        if year not in by_year:
            by_year[year] = []
        by_year[year].append(t)
    
    records = []
    for year in sorted(by_year.keys()):
        year_trades = by_year[year]
        net_pnl = sum(t["net_pnl"] for t in year_trades)
        count = len(year_trades)
        wins = sum(1 for t in year_trades if t["net_pnl"] > 0)
        win_rate = wins / count if count > 0 else 0.0
        
        records.append(YearwiseRecord(
            year=year,
            net_pnl_usd=net_pnl,
            trade_count=count,
            win_rate=win_rate,
            max_drawdown_pct=None,
        ))
    
    return records


def build_glossary():
    return [
        GlossaryEntry("net_pnl_usd", "Net Profit (USD)", "Total profit minus total loss in USD", "USD"),
        GlossaryEntry("win_rate", "Win Rate", "Fraction of winning trades (0.0-1.0)", "decimal"),
        GlossaryEntry("profit_factor", "Profit Factor", "Gross profit divided by gross loss", "ratio"),
        GlossaryEntry("trade_count", "Trade Count", "Total number of completed trades", "count"),
        GlossaryEntry("max_drawdown_usd", "Max Drawdown (USD)", "Maximum peak-to-trough decline in USD", "USD"),
        GlossaryEntry("max_drawdown_pct", "Max Drawdown (%)", "Maximum drawdown as fraction of capital (0.0-1.0)", "decimal"),
        GlossaryEntry("return_dd_ratio", "Return/DD Ratio", "Net profit divided by max drawdown", "ratio"),
    ]


def compute_hash(filepath):
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    df = load_data()
    if df.empty:
        print("Stage-1 execution aborted. Run is void.")
        print("Stage of failure: No data loaded")
        return
    
    df = calculate_indicators(df)
    
    min_lot = 0.01
    usd_per_unit = 0.10
    
    trades_list = run_strategy(df, min_lot, usd_per_unit)
    
    if not trades_list:
        print("Stage-1 execution aborted. Run is void.")
        print("Stage of failure: No trades generated")
        return
    
    standard_metrics = compute_standard_metrics(trades_list)
    risk_metrics = compute_risk_metrics(trades_list, standard_metrics.net_pnl_usd)
    yearwise_metrics = compute_yearwise_metrics(trades_list)
    metrics_glossary = build_glossary()
    
    trades = [
        TradeRecord(
            strategy_name=t["strategy_name"],
            parent_trade_id=t["parent_trade_id"],
            sequence_index=t["sequence_index"],
            entry_timestamp=t["entry_timestamp"].isoformat(),
            exit_timestamp=t["exit_timestamp"].isoformat(),
            direction=t["direction"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            net_pnl=t["net_pnl"],
            bars_held=t["bars_held"],
            atr_entry=t["atr_entry"],
            position_units=t["position_units"],
            notional_usd=t["notional_usd"],
            mfe_price=t["mfe_price"],
            mae_price=t["mae_price"],
            mfe_r=t["mfe_r"],
            mae_r=t["mae_r"],
        )
        for t in trades_list
    ]
    
    directive_content = DIRECTIVE_PATH.read_text(encoding="utf-8")
    directive_hash = compute_hash(DIRECTIVE_PATH)
    engine_hash = compute_hash(__file__)
    
    data_files = sorted(DATA_ROOT.glob("ETHUSD_OCTAFX_4h_*_CLEAN.csv"))
    data_fingerprint = hashlib.sha256(
        "".join(str(f) for f in data_files).encode()
    ).hexdigest()[:16]
    
    metadata = RunMetadata(
        run_id=str(uuid.uuid4()),
        strategy_name="VRS001_ETHUSD_4H",
        symbol="ETHUSD",
        timeframe="4H",
        date_range_start=df["time"].min().isoformat(),
        date_range_end=df["time"].max().isoformat(),
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name="vrs001_executor",
        engine_version="1.0.0",
        directive_hash=directive_hash,
        engine_hash=engine_hash,
        data_fingerprint=data_fingerprint,
        schema_version="1.0.0",
    )
    
    result = emit_results(
        trades=trades,
        standard_metrics=standard_metrics,
        risk_metrics=risk_metrics,
        yearwise_metrics=yearwise_metrics,
        metrics_glossary=metrics_glossary,
        metadata=metadata,
        directive_content=directive_content,
        directive_filename="VRS001.md",
        backtests_root=BACKTESTS_ROOT,
    )
    
    if result == EmissionResult.SUCCESS:
        strategy_folder = BACKTESTS_ROOT / "VRS001_ETHUSD_4H"
        print(f"Path: {strategy_folder}")
        print("Emitted files:")
        print(f"  - {strategy_folder}/execution/results_tradelevel.csv")
        print(f"  - {strategy_folder}/execution/results_standard.csv")
        print(f"  - {strategy_folder}/execution/results_risk.csv")
        print(f"  - {strategy_folder}/execution/results_yearwise.csv")
        print(f"  - {strategy_folder}/execution/metrics_glossary.csv")
        print(f"  - {strategy_folder}/metadata/run_metadata.json")
        print(f"  - {strategy_folder}/VRS001.md")
        print()
        print("Stage-1 SOP-complete execution finished successfully. All authoritative artifacts emitted.")
    else:
        print("Stage-1 execution aborted. Run is void.")
        print(f"Stage of failure: {result.value}")


if __name__ == "__main__":
    main()
