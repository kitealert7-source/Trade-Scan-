"""
VRS_FAMILY Executor — Multi-Symbol VRS Strategy Execution
Derived from VRS001 (logic identical, parameters from broker specs)
"""

import csv
import hashlib
import os
import sys
import glob
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.execution_emitter import (
    TradeRecord,
    StandardMetrics,
    RiskMetrics,
    YearwiseRecord,
    GlossaryEntry,
    RunMetadata,
    emit_results,
    EmissionResult,
)

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
DATA_ROOT = PROJECT_ROOT / "data_root" / "MASTER_DATA"
BROKER_SPECS_ROOT = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"
DIRECTIVE_PATH = PROJECT_ROOT / "backtest_directives" / "active" / "VRS001.md"
TIMEFRAME = "4H"
STARTING_CAPITAL = 5000.0


def discover_eligible_symbols():
    """Discover symbols with both broker spec and 4H data."""
    eligible = []
    skipped = []
    
    # Get all broker specs
    spec_files = list(BROKER_SPECS_ROOT.glob("*.yaml"))
    
    for spec_file in spec_files:
        symbol = spec_file.stem  # e.g., EURUSD
        
        # Map symbol to data folder pattern
        # EURUSD -> EURUSD_OCTAFX_MASTER
        # BTCUSD -> BTC_OCTAFX_MASTER
        # ETHUSD -> ETH_OCTAFX_MASTER
        if symbol in ("BTCUSD", "ETHUSD"):
            data_folder_name = f"{symbol[:3]}_OCTAFX_MASTER"
        else:
            data_folder_name = f"{symbol}_OCTAFX_MASTER"
        
        data_folder = DATA_ROOT / data_folder_name
        
        if not data_folder.exists():
            skipped.append((symbol, f"Data folder not found: {data_folder_name}"))
            continue
        
        # Check for 4H clean files
        clean_folder = data_folder / "CLEAN"
        if not clean_folder.exists():
            skipped.append((symbol, "CLEAN folder not found"))
            continue
        
        pattern = f"{symbol}_OCTAFX_4h_*_CLEAN.csv"
        data_files = list(clean_folder.glob(pattern))
        
        if not data_files:
            # Try alternate pattern for crypto
            if symbol in ("BTCUSD", "ETHUSD"):
                pattern = f"{symbol}_OCTAFX_4h_*_CLEAN.csv"
                data_files = list(clean_folder.glob(pattern))
        
        if not data_files:
            skipped.append((symbol, "No 4H CLEAN data files"))
            continue
        
        eligible.append({
            "symbol": symbol,
            "spec_file": spec_file,
            "data_folder": clean_folder,
            "data_files": sorted(data_files),
        })
    
    return eligible, skipped


def load_broker_spec(spec_file):
    """Load and validate broker spec."""
    with open(spec_file, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    
    required_fields = ["min_lot", "lot_step", "cost_model"]
    for field in required_fields:
        if field not in spec:
            raise ValueError(f"Missing required field: {field}")
    
    # Extract usd_per_unit from calibration
    calibration = spec.get("calibration", {})
    usd_pnl_per_price_unit = calibration.get("usd_pnl_per_price_unit_0p01")
    
    if usd_pnl_per_price_unit is None:
        raise ValueError("Missing calibration.usd_pnl_per_price_unit_0p01")
    
    return {
        "min_lot": float(spec["min_lot"]),
        "lot_step": float(spec["lot_step"]),
        "contract_size": spec.get("contract_size"),
        "usd_per_unit": float(usd_pnl_per_price_unit),
        "cost_model": spec["cost_model"],
    }


def load_data(data_files, symbol):
    """Load and combine data files."""
    dfs = []
    for f in data_files:
        df = pd.read_csv(f, parse_dates=["time"])
        dfs.append(df)
    
    if not dfs:
        return pd.DataFrame()
    
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.sort_values("time").drop_duplicates(subset=["time"]).reset_index(drop=True)
    return combined


def calculate_indicators(df):
    """Calculate indicators (identical to VRS001)."""
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


def run_strategy(df, min_lot, usd_per_unit, symbol):
    """Run VRS strategy (logic identical to VRS001)."""
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
    
    strategy_name = f"VRS_{symbol}_{TIMEFRAME}"
    
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
                    "strategy_name": strategy_name,
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
    """Compute standard metrics."""
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
    """Compute risk metrics."""
    equity_curve = []
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    
    for t in trades_list:
        cumulative += t["net_pnl"]
        equity_curve.append(cumulative)
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    
    max_dd_pct = max_dd / STARTING_CAPITAL if STARTING_CAPITAL > 0 else 0.0
    return_dd_ratio = net_pnl / max_dd if max_dd > 0 else 0.0
    
    return RiskMetrics(
        max_drawdown_usd=round(max_dd, 2),
        max_drawdown_pct=round(max_dd_pct, 4),
        return_dd_ratio=round(return_dd_ratio, 2),
    )


def compute_yearwise_metrics(trades_list):
    """Compute yearwise metrics."""
    years = {}
    for t in trades_list:
        year = t["exit_timestamp"].year
        if year not in years:
            years[year] = []
        years[year].append(t)
    
    records = []
    for year in sorted(years.keys()):
        year_trades = years[year]
        net_pnl = sum(t["net_pnl"] for t in year_trades)
        wins = sum(1 for t in year_trades if t["net_pnl"] > 0)
        trade_count = len(year_trades)
        win_rate = wins / trade_count if trade_count > 0 else 0.0
        
        records.append(YearwiseRecord(
            year=year,
            net_pnl_usd=round(net_pnl, 2),
            trade_count=trade_count,
            win_rate=round(win_rate, 4),
        ))
    
    return records


def build_glossary():
    """Build metrics glossary."""
    return [
        GlossaryEntry("net_pnl_usd", "Net Profit/Loss (USD)", "Total profit or loss in USD", "USD"),
        GlossaryEntry("win_rate", "Win Rate", "Percentage of winning trades (0.0 to 1.0)", "decimal"),
        GlossaryEntry("profit_factor", "Profit Factor", "Gross profit / gross loss", "ratio"),
        GlossaryEntry("trade_count", "Trade Count", "Total number of trades", "integer"),
        GlossaryEntry("max_drawdown_usd", "Max Drawdown (USD)", "Maximum peak-to-trough decline in USD", "USD"),
        GlossaryEntry("max_drawdown_pct", "Max Drawdown (%)", "Maximum drawdown as percentage of starting capital", "decimal"),
    ]


def compute_hash(filepath):
    """Compute SHA-256 hash."""
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def execute_symbol(symbol_info):
    """Execute Stage-1 for a single symbol."""
    symbol = symbol_info["symbol"]
    spec_file = symbol_info["spec_file"]
    data_files = symbol_info["data_files"]
    
    print(f"\n{'='*60}")
    print(f"Executing: {symbol}")
    print(f"{'='*60}")
    
    # Load broker spec
    try:
        broker_spec = load_broker_spec(spec_file)
        print(f"  Broker spec loaded: min_lot={broker_spec['min_lot']}, usd_per_unit={broker_spec['usd_per_unit']}")
    except Exception as e:
        return {"symbol": symbol, "status": "SKIPPED", "reason": f"Broker spec error: {e}"}
    
    # Load data
    df = load_data(data_files, symbol)
    if df.empty:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "No data loaded"}
    
    print(f"  Data loaded: {len(df)} bars")
    
    # Calculate indicators
    df = calculate_indicators(df)
    
    # Run strategy
    trades_list = run_strategy(df, broker_spec["min_lot"], broker_spec["usd_per_unit"], symbol)
    
    if not trades_list:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "No trades generated"}
    
    print(f"  Trades generated: {len(trades_list)}")
    
    # Compute metrics
    standard_metrics = compute_standard_metrics(trades_list)
    risk_metrics = compute_risk_metrics(trades_list, standard_metrics.net_pnl_usd)
    yearwise_metrics = compute_yearwise_metrics(trades_list)
    metrics_glossary = build_glossary()
    
    # Create trade records
    strategy_name = f"VRS_{symbol}_{TIMEFRAME}"
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
    
    # Build metadata
    directive_content = DIRECTIVE_PATH.read_text(encoding="utf-8")
    directive_hash = compute_hash(DIRECTIVE_PATH)
    engine_hash = compute_hash(__file__)
    
    data_fingerprint = hashlib.sha256(
        "".join(str(f) for f in data_files).encode()
    ).hexdigest()[:16]
    
    first_date = df["time"].min()
    last_date = df["time"].max()
    
    import uuid
    run_id = str(uuid.uuid4())
    
    metadata = RunMetadata(
        run_id=run_id,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=TIMEFRAME,
        date_range_start=first_date.isoformat(),
        date_range_end=last_date.isoformat(),
        execution_timestamp_utc=datetime.utcnow().isoformat() + "Z",
        engine_name="vrs_family_executor",
        engine_version="1.0.0",
        directive_hash=directive_hash,
        engine_hash=engine_hash,
        data_fingerprint=data_fingerprint,
        schema_version="1.0.0",
    )
    
    # Emit results
    result = emit_results(
        trades=trades,
        standard_metrics=standard_metrics,
        risk_metrics=risk_metrics,
        yearwise_metrics=yearwise_metrics,
        metrics_glossary=metrics_glossary,
        metadata=metadata,
        directive_content=directive_content,
        directive_filename="VRS001.md",
    )
    
    if result == EmissionResult.SUCCESS:
        output_path = PROJECT_ROOT / "backtests" / strategy_name
        print(f"  Stage-1 SUCCESS: {output_path}")
        return {
            "symbol": symbol,
            "status": "SUCCESS",
            "run_id": run_id,
            "strategy_name": strategy_name,
            "output_path": str(output_path),
            "trade_count": len(trades_list),
        }
    elif result == EmissionResult.FOLDER_EXISTS:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "Output folder already exists"}
    else:
        return {"symbol": symbol, "status": "FAILED", "reason": str(result)}


def execute_stage2(strategy_name):
    """Execute Stage-2 for a completed Stage-1 run."""
    import subprocess
    
    run_folder = PROJECT_ROOT / "backtests" / strategy_name
    
    result = subprocess.run(
        ["python", str(PROJECT_ROOT / "tools" / "stage2_compiler.py"), str(run_folder)],
        capture_output=True,
        text=True,
    )
    
    if result.returncode == 0:
        return True
    else:
        print(f"  Stage-2 FAILED: {result.stderr}")
        return False


def main():
    """Main execution entry point."""
    print("VRS_FAMILY Multi-Symbol Executor")
    print("=" * 60)
    
    # Discover eligible symbols
    eligible, skipped = discover_eligible_symbols()
    
    print(f"\nEligible symbols: {len(eligible)}")
    for s in eligible:
        print(f"  - {s['symbol']}")
    
    print(f"\nSkipped symbols: {len(skipped)}")
    for symbol, reason in skipped:
        print(f"  - {symbol}: {reason}")
    
    # Execute each symbol
    results = []
    for symbol_info in eligible:
        result = execute_symbol(symbol_info)
        results.append(result)
        
        # If Stage-1 succeeded, run Stage-2
        if result["status"] == "SUCCESS":
            print(f"  Running Stage-2...")
            stage2_ok = execute_stage2(result["strategy_name"])
            result["stage2"] = "SUCCESS" if stage2_ok else "FAILED"
    
    # Summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    
    succeeded = [r for r in results if r["status"] == "SUCCESS"]
    skipped_exec = [r for r in results if r["status"] == "SKIPPED"]
    failed = [r for r in results if r["status"] == "FAILED"]
    
    print(f"\nSucceeded: {len(succeeded)}")
    for r in succeeded:
        stage2_status = r.get("stage2", "N/A")
        print(f"  - {r['symbol']}: {r['trade_count']} trades, Stage-2: {stage2_status}")
        print(f"    Path: {r['output_path']}")
    
    print(f"\nSkipped: {len(skipped_exec)}")
    for r in skipped_exec:
        print(f"  - {r['symbol']}: {r['reason']}")
    
    print(f"\nFailed: {len(failed)}")
    for r in failed:
        print(f"  - {r['symbol']}: {r['reason']}")


if __name__ == "__main__":
    main()
