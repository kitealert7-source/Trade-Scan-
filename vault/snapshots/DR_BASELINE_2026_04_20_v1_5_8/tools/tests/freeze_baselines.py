"""
Freeze Baselines — Capture per-section raw JSON outputs from the current
robustness engine before any refactoring.

Usage:
    python tools/tests/freeze_baselines.py <prefix> --profile <profile>
    python tools/tests/freeze_baselines.py --all

Stores outputs under tools/tests/baselines/<prefix>_<profile>/
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from tools.utils.research import simulators, robustness, rolling, drawdown, friction

from tools.robustness.loader import load_canonical_artifacts

def _load(prefix: str, profile: str):
    return load_canonical_artifacts(prefix, profile, PROJECT_ROOT)


# ── Per-section capture ─────────────────────────────────────────────────────

def _safe_serialize(obj):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_safe_serialize(v) for v in obj]
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    return obj


def capture_sections(prefix, profile, tr_df, eq_df, metrics):
    """Run each computation module and capture raw results."""
    start_cap = metrics["starting_capital"]
    results = {}

    # Section 1: Edge metrics (from summary_metrics — already a JSON)
    results["edge_metrics"] = {
        "final_equity": metrics["final_equity"],
        "starting_capital": start_cap,
        "realized_pnl": metrics["realized_pnl"],
        "total_accepted": metrics["total_accepted"],
    }

    # Section 2: Tail
    results["tail_contribution"] = robustness.tail_contribution(tr_df)
    results["tail_removal"] = robustness.tail_removal(tr_df, start_cap=start_cap)

    # Section 3: Sequence MC (seed=42, 500 iterations)
    baseline = simulators.simulate_percent_path(tr_df, start_cap)
    results["baseline_simulation"] = baseline
    mc_df = simulators.run_random_sequence_mc(tr_df, iterations=500, start_cap=start_cap, seed=42)
    results["sequence_mc"] = {
        "median_cagr": float(mc_df["cagr"].median()),
        "p5_cagr": float(mc_df["cagr"].quantile(0.05)),
        "p95_cagr": float(mc_df["cagr"].quantile(0.95)),
        "median_dd": float(mc_df["max_dd_pct"].median()),
        "p95_dd": float(mc_df["max_dd_pct"].quantile(0.95)),
        "baseline_cagr": baseline["cagr"],
        "iterations": 500,
        "seed": 42,
    }

    # Section 4: Rolling windows
    win_df = rolling.rolling_window(eq_df, tr_df, window_days=365, step_days=30)
    stab = rolling.classify_stability(win_df)
    results["rolling"] = {
        "stability": stab,
        "window_count": len(win_df),
    }
    # Year-wise PnL
    tr_tmp = tr_df.copy()
    tr_tmp["year"] = pd.to_datetime(tr_tmp["exit_timestamp"]).dt.year
    year_pnl = tr_tmp.groupby("year")["pnl_usd"].sum()
    results["year_wise_pnl"] = {str(k): float(v) for k, v in year_pnl.items()}

    # Section 5/6: Drawdown
    clusters = drawdown.identify_dd_clusters(eq_df, top_n=3)
    dd_results = []
    for c in clusters:
        exp = drawdown.analyze_dd_exposure(tr_df, c)
        beh = drawdown.analyze_dd_trade_behavior(tr_df, c)
        dd_results.append({
            "max_dd_pct": c["max_dd_pct"],
            "duration_days": c["duration_days"],
            "exposure": exp,
            "behavior": beh,
        })
    results["drawdown"] = dd_results

    # Section 8: Streaks (computed inline in evaluate_robustness)
    pnls = tr_df["pnl_usd"].values
    wins = (pnls > 0).astype(int)
    losses = (pnls < 0).astype(int)
    
    def max_streak(arr):
        mx, cur = 0, 0
        for v in arr:
            if v: cur += 1; mx = max(mx, cur)
            else: cur = 0
        return mx
    
    results["streaks"] = {
        "max_win_streak": max_streak(wins),
        "max_loss_streak": max_streak(losses),
        "total_trades": len(pnls),
    }

    # Section 9: Friction
    fric = friction.run_friction_scenarios(tr_df)
    results["friction"] = fric

    # Section 10: Directional
    results["directional"] = robustness.directional_removal(tr_df)

    # Section 11: Early/Late
    results["early_late"] = robustness.early_late_split(tr_df, start_cap=start_cap)

    # Section 12: Symbol isolation
    symbols = sorted(tr_df["symbol"].unique())
    if len(symbols) > 1:
        results["symbol_isolation"] = robustness.symbol_isolation(tr_df, start_cap=start_cap)
    else:
        results["symbol_isolation"] = {"note": "single_asset_skip"}

    # Section 13: Symbol breakdown
    sym_pnl = tr_df.groupby("symbol")["pnl_usd"].agg(["sum", "count"])
    results["symbol_breakdown"] = {
        sym: {"pnl": float(row["sum"]), "trades": int(row["count"])}
        for sym, row in sym_pnl.iterrows()
    }

    # Section 14: Block bootstrap (seed=42, 100 iterations)
    try:
        from tools.utils.research.block_bootstrap import run_block_bootstrap
        bb_df = run_block_bootstrap(prefix, profile, iterations=100, seed=42)
        results["block_bootstrap"] = {
            "median_equity": float(bb_df["final_equity"].median()),
            "p5_equity": float(bb_df["final_equity"].quantile(0.05)),
            "p95_equity": float(bb_df["final_equity"].quantile(0.95)),
            "median_cagr": float(bb_df["cagr"].median()),
            "p5_cagr": float(bb_df["cagr"].quantile(0.05)),
            "median_dd": float(bb_df["max_dd_pct"].median()),
            "iterations": 100,
            "seed": 42,
        }
    except Exception as e:
        results["block_bootstrap"] = {"error": str(e)}

    return _safe_serialize(results)


# ── Main ────────────────────────────────────────────────────────────────────

ALL_CANDIDATES = [
    ("AK36_FX_PORTABILITY_4H", "CONSERVATIVE_V1"),    # 4H portfolio, long, high-trade
    ("AK37_FX_PORTABILITY_4H", "AGGRESSIVE_V1"),       # 4H portfolio, long, aggressive
    ("AK35_FX_PORTABILITY_4H", "CONSERVATIVE_V1"),     # 4H portfolio, long, moderate
    ("UltimateC_RegimeFilter_FX", "CONSERVATIVE_V1"),  # 1H portfolio, short-horizon
]


def freeze_one(prefix, profile):
    print(f"\n{'='*60}")
    print(f"FREEZING: {prefix} / {profile}")
    print(f"{'='*60}")

    tr_df, eq_df, metrics = _load(prefix, profile)
    print(f"  Loaded {len(tr_df)} trades, {len(eq_df)} equity points")

    # Capture per-section JSON
    sections = capture_sections(prefix, profile, tr_df, eq_df, metrics)

    # Write JSON
    out_dir = PROJECT_ROOT / "tools" / "tests" / "baselines" / f"{prefix}_{profile}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for section_name, section_data in sections.items():
        path = out_dir / f"{section_name}.json"
        with open(path, "w") as f:
            json.dump(section_data, f, indent=2, default=str)
        print(f"  [FROZEN] {section_name}.json")

    # Also freeze the full markdown report
    from tools.evaluate_robustness import main as _er_main
    import subprocess
    md_path = out_dir / "full_report.md"
    
    # Run cli.py as subprocess to capture its exact output
    result = subprocess.run(
        [sys.executable, "tools/robustness/cli.py", prefix,
         "--profile", profile, "--suite", "full"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT)
    )
    
    # Copy the generated report
    report_src = PROJECT_ROOT / "outputs" / "reports" / f"ROBUSTNESS_{prefix}_{profile}.md"
    if report_src.exists():
        import shutil
        shutil.copy2(report_src, md_path)
        print(f"  [FROZEN] full_report.md")
    else:
        print(f"  [WARN] Markdown report not found at {report_src}")

    # Write manifest
    manifest = {
        "prefix": prefix,
        "profile": profile,
        "frozen_at": datetime.utcnow().isoformat(),
        "trade_count": len(tr_df),
        "equity_points": len(eq_df),
        "sections_frozen": list(sections.keys()),
        "engine_version": "pre-consolidation",
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  [FROZEN] manifest.json")

    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Freeze robustness baselines")
    parser.add_argument("prefix", nargs="?", help="Strategy prefix")
    parser.add_argument("--profile", default="CONSERVATIVE_V1")
    parser.add_argument("--all", action="store_true", help="Freeze all representative strategies")
    args = parser.parse_args()

    if args.all:
        frozen = []
        for prefix, profile in ALL_CANDIDATES:
            try:
                out = freeze_one(prefix, profile)
                frozen.append((prefix, profile, str(out)))
            except Exception as e:
                print(f"  [ERROR] {prefix}/{profile}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n{'='*60}")
        print(f"FREEZE COMPLETE: {len(frozen)}/{len(ALL_CANDIDATES)} strategies")
        print(f"{'='*60}")
        for p, pr, path in frozen:
            print(f"  [OK] {p}/{pr} -> {path}")
    elif args.prefix:
        freeze_one(args.prefix, args.profile)
    else:
        parser.error("Provide a strategy prefix or use --all")


if __name__ == "__main__":
    main()
