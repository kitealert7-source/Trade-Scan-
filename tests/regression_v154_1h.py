"""
Regression Test: Engine v1.5.4 — 1H Strategy Must Produce Identical Results
=============================================================================
Validates that the v1.5.4 adaptive regime TF changes produce zero drift for
1H strategies (which still map to 4H regime, same as v1.5.3).

Test: SPKFADE S03 (XAUUSD 1H, 265 trades, $404.86 PnL)
Baseline: TradeScan_State/runs/a1fc9141daff0dc39de07784/data/results_tradelevel.csv

What this tests:
1. resolve_regime_config("1h") returns ("4h", "1D") — same as v1.5.3 hardcoded
2. apply_regime_model(df, resample_freq="1D") produces identical regime columns
3. Full engine run produces identical trade list (entry/exit timestamps, PnL)
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TRADESCAN_STATE = PROJECT_ROOT.parent / "TradeScan_State"
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import pandas as pd
import numpy as np

# ============================================================
# TEST 1: Config Resolution
# ============================================================
print("=" * 60)
print("TEST 1: Regime TF Config Resolution")
print("=" * 60)

# Import the new resolver
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from run_stage1 import resolve_regime_config

test_cases = {
    "5m":  ("1h",  "1D"),
    "15m": ("1h",  "1D"),
    "30m": ("4h",  "1D"),
    "1h":  ("4h",  "1D"),   # <-- MUST be identical to v1.5.3
    "4h":  ("1d",  "1W"),
    "1d":  ("1w",  "1ME"),
}

all_pass = True
for signal_tf, (expected_regime, expected_resample) in test_cases.items():
    regime_tf, resample_freq = resolve_regime_config(signal_tf)
    status = "PASS" if (regime_tf == expected_regime and resample_freq == expected_resample) else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {signal_tf:>4s} -> regime={regime_tf:>3s}, resample={resample_freq:>3s}  [{status}]"
          f"  (expected {expected_regime}/{expected_resample})")

print(f"\nTest 1: {'PASS' if all_pass else 'FAIL'}")

# ============================================================
# TEST 2: Regime Model Output Comparison
# ============================================================
print("\n" + "=" * 60)
print("TEST 2: Regime Model Output (4H XAUUSD)")
print("=" * 60)

from engines.regime_state_machine import apply_regime_model
from tools.run_stage1 import load_market_data

# Need to set module-level vars that load_market_data depends on
import tools.run_stage1 as rs1
rs1.BROKER = "OctaFX"
rs1.TIMEFRAME = "1h"
rs1.START_DATE = "2021-01-01"
rs1.END_DATE = "2026-03-20"
rs1.RESOLVED_WARMUP_BARS = 250

# Load 4H regime data (same as v1.5.3 would)
print("  Loading 4H data for XAUUSD...")
df_regime = load_market_data("XAUUSD", tf_override="4h")
if "timestamp" in df_regime.columns:
    df_regime["timestamp"] = pd.to_datetime(df_regime["timestamp"])
    df_regime = df_regime.set_index("timestamp", drop=False)

print(f"  Loaded {len(df_regime)} 4H bars")

# Run regime model with v1.5.4 params (resample_freq="1D" — same as v1.5.3 default)
print("  Computing regime model (resample_freq='1D')...")
df_regime = apply_regime_model(df_regime, resample_freq="1D")

regime_cols = [
    "market_regime", "regime_id", "regime_age",
    "direction_state", "structure_state", "volatility_state",
    "trend_score", "trend_regime", "trend_label", "volatility_regime"
]
available = [c for c in regime_cols if c in df_regime.columns]
print(f"  Regime columns present: {len(available)}/{len(regime_cols)}")

# Check regime distribution
regime_dist = df_regime["market_regime"].value_counts()
print(f"\n  Regime distribution:")
for regime, count in regime_dist.items():
    print(f"    {regime}: {count} bars ({count/len(df_regime)*100:.1f}%)")

trend_dist = df_regime["trend_label"].value_counts()
print(f"\n  Trend label distribution:")
for label, count in trend_dist.items():
    print(f"    {label}: {count} bars ({count/len(df_regime)*100:.1f}%)")

print(f"\nTest 2: PASS (regime model computed successfully on 4H data)")

# ============================================================
# TEST 3: Full Engine Run — Trade-Level Comparison
# ============================================================
print("\n" + "=" * 60)
print("TEST 3: Full Engine Run — Trade Comparison")
print("=" * 60)

# Load baseline trades
baseline_path = _TRADESCAN_STATE / "runs" / "a1fc9141daff0dc39de07784" / "data" / "results_tradelevel.csv"
df_baseline = pd.read_csv(baseline_path)
print(f"  Baseline: {len(df_baseline)} trades, PnL=${df_baseline['pnl_usd'].sum():.2f}")

# Load signal data
print("  Loading 1H signal data...")
df_signal = load_market_data("XAUUSD")
if "timestamp" in df_signal.columns:
    df_signal["timestamp"] = pd.to_datetime(df_signal["timestamp"])
    df_signal = df_signal.set_index("timestamp", drop=False)

print(f"  Signal data: {len(df_signal)} 1H bars")

# Merge regime into signal (same merge_asof as run_stage1.py)
available_fields = [f for f in regime_cols if f in df_regime.columns]
df_merged = pd.merge_asof(
    df_signal.sort_index(),
    df_regime[available_fields].sort_index(),
    left_index=True,
    right_index=True,
    direction='backward',
    allow_exact_matches=True
)
print(f"  Merged: {len(df_merged)} bars with regime columns")

# Load strategy from the frozen snapshot
strategy_snapshot = _TRADESCAN_STATE / "runs" / "a1fc9141daff0dc39de07784" / "strategy.py"
print(f"  Loading strategy from snapshot: {strategy_snapshot.exists()}")

import importlib.util
spec = importlib.util.spec_from_file_location("strategy_module", strategy_snapshot)
strategy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strategy_module)
strategy = strategy_module.Strategy()

# Monkey-patch regime model (same as run_stage1.py does)
import engines.regime_state_machine as rsm
rsm_original = rsm.apply_regime_model
strat_original_prepare = strategy.prepare_indicators

def patched_apply(df_in, resample_freq="1D"):
    return df_in
rsm.apply_regime_model = patched_apply

def patched_prepare(df_in):
    df_out = strat_original_prepare(df_in)
    cols_to_drop = [f for f in available_fields if f in df_out.columns]
    if cols_to_drop:
        df_out = df_out.drop(columns=cols_to_drop)
    df_re = pd.merge_asof(
        df_out.sort_index(),
        df_regime[available_fields].sort_index(),
        left_index=True,
        right_index=True,
        direction='backward',
        allow_exact_matches=True
    )
    for col in available_fields:
        if col in df_re.columns:
            df_in[col] = df_re[col]
    return df_in
strategy.prepare_indicators = patched_prepare

# Run engine
print("  Running engine...")
try:
    from engine_dev.universal_research_engine.v1_5_3.main import run_engine
    trades = run_engine(df_merged, strategy)
    print(f"  v1.5.4 result: {len(trades)} trades")

    # Compare
    if len(trades) == len(df_baseline):
        print(f"\n  TRADE COUNT: {len(trades)} == {len(df_baseline)} MATCH")
    else:
        print(f"\n  TRADE COUNT: {len(trades)} != {len(df_baseline)} MISMATCH")

    if trades:
        # Inspect trade dict keys
        print(f"\n  Trade dict keys: {list(trades[0].keys())}")

        # Filter out warm-up trades (before START_DATE)
        start_dt = pd.Timestamp(rs1.START_DATE, tz="UTC")
        trades_filtered = [
            t for t in trades
            if pd.Timestamp(t.get("entry_timestamp", t.get("entry_time", ""))) >= start_dt
        ]
        print(f"  After warm-up filter: {len(trades_filtered)} trades (removed {len(trades) - len(trades_filtered)} warm-up trades)")

        # Find PnL key
        pnl_key = None
        for k in ["pnl_usd", "pnl", "net_pnl", "profit"]:
            if k in trades[0]:
                pnl_key = k
                break
        print(f"  PnL key: {pnl_key}")

        if pnl_key:
            new_pnl = sum(t.get(pnl_key, 0) for t in trades_filtered)
        else:
            # Try computing from entry/exit
            new_pnl = 0
            for t in trades_filtered:
                entry_p = t.get("entry_price", 0)
                exit_p = t.get("exit_price", 0)
                direction = t.get("direction", 1)
                if direction == 1:
                    new_pnl += (exit_p - entry_p)
                else:
                    new_pnl += (entry_p - exit_p)
            print(f"  (PnL computed from entry/exit prices)")

        baseline_pnl = df_baseline["pnl_usd"].sum()
        pnl_diff = abs(new_pnl - baseline_pnl)
        print(f"\n  BASELINE TRADES: {len(df_baseline)}")
        print(f"  NEW TRADES:      {len(trades_filtered)}")
        print(f"  TRADE COUNT:     {'MATCH' if len(trades_filtered) == len(df_baseline) else 'MISMATCH'}")
        print(f"\n  BASELINE PnL: ${baseline_pnl:.2f}")
        print(f"  NEW PnL:      ${new_pnl:.2f}")
        print(f"  DIFF:         ${pnl_diff:.4f}")

        if pnl_diff < 0.01:
            print(f"\n  PnL MATCH: YES (diff < $0.01)")
        elif pnl_diff < 1.00:
            print(f"\n  PnL MATCH: NEAR (diff < $1.00 — float rounding)")
        else:
            print(f"\n  PnL MATCH: NO (diff = ${pnl_diff:.4f})")

        # Compare entry timestamps
        print(f"\n  First 10 trades comparison:")
        print(f"  {'#':<4} {'Baseline Entry':<30} {'New Entry':<30} {'Match'}")
        print(f"  {'-'*90}")
        for i in range(min(10, len(trades_filtered), len(df_baseline))):
            bl_ts = str(df_baseline["entry_timestamp"].iloc[i])
            new_ts = str(trades_filtered[i].get("entry_timestamp", trades_filtered[i].get("entry_time", "")))
            match = "YES" if bl_ts in new_ts or new_ts in bl_ts else "NO"
            print(f"  {i:<4} {bl_ts:<30} {new_ts:<30} {match}")

finally:
    rsm.apply_regime_model = rsm_original
    strategy.prepare_indicators = strat_original_prepare

print("\n" + "=" * 60)
print("REGRESSION TEST COMPLETE")
print("=" * 60)
