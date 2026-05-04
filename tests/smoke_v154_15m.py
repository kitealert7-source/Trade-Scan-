"""
Smoke Test: Engine v1.5.4 — 15M with 1H Regime (was 4H)
=========================================================
This is where actual change happened. 15M now maps to 1H regime (was 4H).

Checking:
1. Regime distribution — should NOT collapse into 1 state
2. Trade count delta — expect change, but not chaos
3. Stability — no clustered overtrading or dead zones
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from config.path_authority import TRADE_SCAN_STATE as _TRADESCAN_STATE
os.chdir(PROJECT_ROOT)

import pandas as pd
import numpy as np

sys.path.insert(0, str(PROJECT_ROOT / "tools"))
import tools.run_stage1 as rs1
from tools.run_stage1 import resolve_regime_config, load_market_data
from engines.regime_state_machine import apply_regime_model

# Config — match the original directive
rs1.BROKER = "OctaFX"
rs1.TIMEFRAME = "15m"
rs1.START_DATE = "2025-01-02"      # from backtest_date_policy for 15m
rs1.END_DATE = "2026-03-20"
rs1.RESOLVED_WARMUP_BARS = 250
SYMBOL = "AUDUSD"

# =============================================================
# BASELINE: Load old results
# =============================================================
print("=" * 70)
print("SMOKE TEST: 15M ASRANGE S03 — AUDUSD — 1H Regime (was 4H)")
print("=" * 70)

baseline_path = _TRADESCAN_STATE / "runs" / "1d88721c24d006382612b471" / "data" / "results_tradelevel.csv"
df_bl = pd.read_csv(baseline_path)
# Filter to matching date range (baseline used different dates)
df_bl["entry_timestamp"] = pd.to_datetime(df_bl["entry_timestamp"])
df_bl_filtered = df_bl[
    (df_bl["entry_timestamp"] >= rs1.START_DATE) &
    (df_bl["entry_timestamp"] <= rs1.END_DATE)
]

print(f"\nBASELINE (4H regime):")
print(f"  Total trades (full run):  {len(df_bl)}")
print(f"  Trades in test window:    {len(df_bl_filtered)}")
print(f"  PnL (test window):        ${df_bl_filtered['pnl_usd'].sum():.2f}")
bl_regime = df_bl_filtered["market_regime"].value_counts()
bl_trend = df_bl_filtered["trend_label"].value_counts()

# =============================================================
# NEW: Compute 1H regime
# =============================================================
print(f"\n{'='*70}")
print("PHASE 1: Regime Computation (1H grid)")
print("=" * 70)

regime_tf, resample_freq = resolve_regime_config("15m")
print(f"  Config: 15m -> regime_tf={regime_tf}, resample_freq={resample_freq}")

print(f"  Loading {regime_tf.upper()} data for {SYMBOL}...")
df_regime = load_market_data(SYMBOL, tf_override=regime_tf)
if "timestamp" in df_regime.columns:
    df_regime["timestamp"] = pd.to_datetime(df_regime["timestamp"])
    df_regime = df_regime.set_index("timestamp", drop=False)

print(f"  Loaded {len(df_regime)} {regime_tf.upper()} bars")
print(f"  Computing regime model...")
df_regime = apply_regime_model(df_regime, resample_freq=resample_freq)

regime_cols = [
    "market_regime", "regime_id", "regime_age",
    "direction_state", "structure_state", "volatility_state",
    "trend_score", "trend_regime", "trend_label", "volatility_regime"
]
available_fields = [f for f in regime_cols if f in df_regime.columns]
print(f"  Regime columns: {len(available_fields)}/{len(regime_cols)}")

# Regime distribution on the regime-TF bars
print(f"\n  1H Regime Distribution (on 1H bars):")
regime_dist = df_regime["market_regime"].value_counts()
for r, c in regime_dist.items():
    print(f"    {r:<25s} {c:>5d} bars ({c/len(df_regime)*100:5.1f}%)")

trend_dist = df_regime["trend_label"].value_counts()
print(f"\n  1H Trend Distribution:")
for t, c in trend_dist.items():
    print(f"    {t:<25s} {c:>5d} bars ({c/len(df_regime)*100:5.1f}%)")

# STABILITY CHECK: regime must not collapse
n_regimes = len(regime_dist)
top_pct = regime_dist.iloc[0] / len(df_regime) * 100
print(f"\n  Stability check:")
print(f"    Distinct regimes:       {n_regimes} (need >= 3)")
print(f"    Top regime share:       {top_pct:.1f}% (need < 90%)")
regime_ok = n_regimes >= 3 and top_pct < 90
print(f"    Result:                 {'PASS' if regime_ok else 'FAIL'}")

# =============================================================
# PHASE 2: Merge + Engine Run
# =============================================================
print(f"\n{'='*70}")
print("PHASE 2: Engine Run (15M signal + 1H regime)")
print("=" * 70)

print(f"  Loading 15M signal data...")
df_signal = load_market_data(SYMBOL)
if "timestamp" in df_signal.columns:
    df_signal["timestamp"] = pd.to_datetime(df_signal["timestamp"])
    df_signal = df_signal.set_index("timestamp", drop=False)
print(f"  Signal: {len(df_signal)} 15M bars")

# Merge regime
df_merged = pd.merge_asof(
    df_signal.sort_index(),
    df_regime[available_fields].sort_index(),
    left_index=True,
    right_index=True,
    direction='backward',
    allow_exact_matches=True
)
print(f"  Merged: {len(df_merged)} bars")

# Load strategy
import importlib.util
strategy_path = _TRADESCAN_STATE / "runs" / "1d88721c24d006382612b471" / "strategy.py"
spec = importlib.util.spec_from_file_location("strategy_module", strategy_path)
strategy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strategy_module)
strategy = strategy_module.Strategy()

# Monkey-patch (same as pipeline)
import engines.regime_state_machine as rsm
rsm_original = rsm.apply_regime_model
strat_original = strategy.prepare_indicators

def patched_apply(df_in, resample_freq="1D"):
    return df_in
rsm.apply_regime_model = patched_apply

def patched_prepare(df_in):
    df_out = strat_original(df_in)
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

try:
    from engine_dev.universal_research_engine.v1_5_3.main import run_engine
    print(f"  Running engine...")
    trades = run_engine(df_merged, strategy)
    print(f"  Raw trades: {len(trades)}")

    # Filter warm-up
    start_dt = pd.Timestamp(rs1.START_DATE, tz="UTC")
    trades = [t for t in trades if pd.Timestamp(t["entry_timestamp"]) >= start_dt]
    print(f"  After warm-up filter: {len(trades)}")

    # =============================================================
    # PHASE 3: Comparison
    # =============================================================
    print(f"\n{'='*70}")
    print("RESULTS COMPARISON")
    print("=" * 70)

    bl_count = len(df_bl_filtered)
    new_count = len(trades)
    delta = new_count - bl_count
    delta_pct = (delta / bl_count * 100) if bl_count > 0 else 0

    print(f"\n  {'Metric':<30s} {'Baseline (4H)':<18s} {'New (1H)':<18s} {'Delta'}")
    print(f"  {'-'*80}")
    print(f"  {'Trade count':<30s} {bl_count:<18d} {new_count:<18d} {delta:+d} ({delta_pct:+.1f}%)")

    # Regime distribution on trades
    if trades:
        new_regimes = pd.Series([t.get("market_regime", "unknown") for t in trades if "market_regime" in t])
        new_trends = pd.Series([t.get("trend_label", "unknown") for t in trades if "trend_label" in t])

        if len(new_regimes) > 0:
            print(f"\n  Regime distribution on trades:")
            print(f"  {'Regime':<25s} {'Baseline':<12s} {'New (1H)':<12s}")
            print(f"  {'-'*50}")
            all_regimes = sorted(set(list(bl_regime.index) + list(new_regimes.value_counts().index)))
            for r in all_regimes:
                bl_c = bl_regime.get(r, 0)
                new_c = new_regimes.value_counts().get(r, 0)
                print(f"  {r:<25s} {bl_c:<12d} {new_c:<12d}")

        if len(new_trends) > 0:
            new_trend_vc = new_trends.value_counts()
            print(f"\n  Trend label distribution on trades:")
            print(f"  {'Label':<25s} {'Baseline':<12s} {'New (1H)':<12s}")
            print(f"  {'-'*50}")
            all_trends = sorted(set(list(bl_trend.index) + list(new_trend_vc.index)))
            for t in all_trends:
                bl_c = bl_trend.get(t, 0)
                new_c = new_trend_vc.get(t, 0)
                print(f"  {t:<25s} {bl_c:<12d} {new_c:<12d}")

    # Clustering check: trades per month
    if trades:
        entry_dates = pd.to_datetime([t["entry_timestamp"] for t in trades])
        monthly = entry_dates.to_period("M").value_counts().sort_index()
        print(f"\n  Trades per month (checking for dead zones / overtrading):")
        for period, count in monthly.items():
            bar = "#" * min(count, 60)
            flag = " *** SPIKE" if count > bl_count / len(monthly) * 3 else ""
            print(f"    {period}: {count:>4d} {bar}{flag}")

        # Dead zone check
        total_months = len(pd.period_range(start=rs1.START_DATE, end=rs1.END_DATE, freq="M"))
        active_months = len(monthly)
        dead_months = total_months - active_months
        print(f"\n  Active months: {active_months}/{total_months}"
              f"  Dead months: {dead_months}")

    # Verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print("=" * 70)
    issues = []
    if not regime_ok:
        issues.append("Regime collapsed")
    if abs(delta_pct) > 50:
        issues.append(f"Trade count delta too large ({delta_pct:+.1f}%)")
    if trades and dead_months > total_months * 0.3:
        issues.append(f"Too many dead months ({dead_months}/{total_months})")

    if not issues:
        print(f"  PASS — 1H regime produces valid, non-degenerate results for 15M")
        print(f"  Trade delta {delta:+d} ({delta_pct:+.1f}%) is within expected bounds")
    else:
        print(f"  FAIL — Issues: {', '.join(issues)}")

finally:
    rsm.apply_regime_model = rsm_original
    strategy.prepare_indicators = strat_original
