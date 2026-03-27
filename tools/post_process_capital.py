import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.state_paths import STRATEGIES_DIR

def process_profile_comparison(strategy_id: str):
    deployable_dir = STRATEGIES_DIR / strategy_id / "deployable"
    comp_json_path = deployable_dir / "profile_comparison.json"

    if not comp_json_path.exists():
        print(f"[POST-PROCESS] No profile_comparison.json found at {comp_json_path}")
        return

    with open(comp_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "profiles" not in data:
        print("[POST-PROCESS] Invalid JSON format: missing 'profiles' key.")
        return

    # STEP 1: Determine effective capital
    # Primary: max_concurrent_trades from any profile (same value across all profiles)
    # Fallback: count unique (strategy, symbol) pairs from deployable_trade_log trade_id prefix
    max_concurrent = None
    for profile_data in data["profiles"].values():
        val = profile_data.get("max_concurrent_trades_during_test_period")
        if val is not None:
            try:
                max_concurrent = int(val)
            except (ValueError, TypeError):
                pass
            break

    if max_concurrent is not None and max_concurrent > 0:
        effective_capital = max_concurrent * 1000.0
        print(f"[CAPITAL] Using concurrency-based effective capital: {max_concurrent} × $1,000 = ${effective_capital:,.0f}")
    else:
        # Fallback: unique (strategy_prefix, symbol) pairs via trade_id
        strategy_symbol_pairs = set()
        for profile_name in data["profiles"].keys():
            trade_log_path = deployable_dir / profile_name / "deployable_trade_log.csv"
            if trade_log_path.exists():
                with open(trade_log_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        trade_id = row.get("trade_id", "")
                        sym = row.get("symbol", "").strip()
                        prefix = trade_id.split("|")[0].strip() if "|" in trade_id else trade_id.strip()
                        if prefix and sym:
                            strategy_symbol_pairs.add((prefix, sym))
                break  # one profile is enough — trades are the same across profiles
        n_pairs = len(strategy_symbol_pairs) if strategy_symbol_pairs else 1
        effective_capital = n_pairs * 1000.0
        print(f"[CAPITAL] Using fallback (strategy-symbol pairs): {n_pairs} × $1,000 = ${effective_capital:,.0f}")

    # STEP 2: Process each profile with utilization-based metrics
    before_fields = None
    for profile_name, profile_data in data["profiles"].items():
        # Capture before-fields for audit (first profile only)
        if before_fields is None:
            before_fields = list(profile_data.keys())

        # Read inputs
        max_drawdown_usd         = float(profile_data.get("max_drawdown_usd", 0.0))
        avg_heat_utilization_pct = float(profile_data.get("avg_heat_utilization_pct", 0.0))
        realized_pnl             = float(profile_data.get("realized_pnl", 0.0))
        starting_capital         = float(profile_data.get("starting_capital", 10000.0))
        total_accepted           = int(profile_data.get("total_accepted", 0))

        # Utilization metrics
        utilized_capital         = effective_capital * avg_heat_utilization_pct
        capital_efficiency_ratio = avg_heat_utilization_pct

        if utilized_capital > 1e-9:
            return_on_utilized_capital = realized_pnl / utilized_capital
        else:
            return_on_utilized_capital = 0.0

        # DD as a fraction of starting capital (unitless ratio, e.g. 0.0556 = 5.56%)
        max_drawdown_fraction = max_drawdown_usd / starting_capital

        # Return on starting capital (total, non-annualized)
        return_on_starting_capital = (
            realized_pnl / starting_capital
            if starting_capital > 1e-9 else 0.0
        )

        # Zero-trade flag
        no_trade_flag = total_accepted == 0

        # Validation flags
        capital_validity_flag  = (
            max_drawdown_usd <= starting_capital
            and utilized_capital <= effective_capital
        )
        if no_trade_flag:
            capital_validity_flag = False
        capital_efficiency_flag = capital_efficiency_ratio >= 0.1

        # Over-utilization
        over_utilization_ratio = (
            utilized_capital / effective_capital
            if effective_capital > 1e-9 else 0.0
        )
        over_utilization_flag = over_utilization_ratio > 1.0

        # Purge removed/renamed fields from prior runs
        for _stale in ("mar_utilized", "mar_starting", "max_drawdown_pct_normalized", "pnl_per_1000_utilized"):
            profile_data.pop(_stale, None)

        # Write fields
        profile_data["effective_capital"]            = effective_capital
        profile_data["utilized_capital"]             = round(utilized_capital, 4)
        profile_data["capital_efficiency_ratio"]     = round(capital_efficiency_ratio, 4)
        profile_data["return_on_utilized_capital"]   = round(return_on_utilized_capital, 4)
        profile_data["max_drawdown_fraction"]        = round(max_drawdown_fraction, 4)
        profile_data["capital_validity_flag"]        = capital_validity_flag
        profile_data["capital_efficiency_flag"]      = capital_efficiency_flag
        profile_data["over_utilization_ratio"]       = round(over_utilization_ratio, 4)
        profile_data["over_utilization_flag"]        = over_utilization_flag
        profile_data["no_trade_flag"]                = no_trade_flag

        # capital_insights block
        idle_capital = max(0.0, effective_capital - utilized_capital)

        return_on_effective_capital = (
            round(realized_pnl / effective_capital, 4)
            if effective_capital > 1e-9 else 0.0
        )
        profile_data["capital_insights"] = {
            "utilized_capital":              round(utilized_capital, 4),
            "idle_capital":                  round(idle_capital, 4),
            "return_on_starting_capital":    round(return_on_starting_capital, 4),
            "return_on_effective_capital":   return_on_effective_capital,
            # reuse top-level computed values (avoid drift)
            "return_on_utilized_capital":    profile_data.get("return_on_utilized_capital"),
            "max_drawdown_fraction":         profile_data.get("max_drawdown_fraction"),
            "utilization_pct":               round(capital_efficiency_ratio * 100, 2),
            "over_utilization_ratio":        round(over_utilization_ratio, 4),
            "over_utilization_flag":         over_utilization_flag,
            "no_trade_flag":                 no_trade_flag,
        }

    # Write back
    with open(comp_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Audit summary
    profile_count = len(data["profiles"])
    print(f"[POST-PROCESS] Profiles processed: {profile_count}")
    print(f"[POST-PROCESS] '_real' fields removed: cagr_real, mar_real, max_drawdown_pct_real")

    sample_name   = next(iter(data["profiles"]))
    sample        = data["profiles"][sample_name]
    new_fields    = [
        "effective_capital", "utilized_capital", "capital_efficiency_ratio",
        "return_on_utilized_capital", "max_drawdown_fraction",
        "capital_validity_flag", "capital_efficiency_flag",
        "over_utilization_ratio", "over_utilization_flag",
        "no_trade_flag", "capital_insights",
    ]
    removed_fields = [f for f in (before_fields or []) if "_real" in f]
    over_flags = [
        name for name, p in data["profiles"].items()
        if p.get("over_utilization_flag")
    ]
    no_trade = [
        name for name, p in data["profiles"].items()
        if p.get("no_trade_flag")
    ]
    print(f"[POST-PROCESS] Sample profile '{sample_name}':")
    print(f"  Fields removed : {removed_fields if removed_fields else '(none were present)'}")
    print(f"  Fields added   :")
    for k in new_fields:
        v = sample.get(k)
        print(f"    {k}: {'<block>' if isinstance(v, dict) else v}")
    if over_flags:
        print(f"[POST-PROCESS] WARN over-utilized profiles: {over_flags}")
    if no_trade:
        print(f"[POST-PROCESS] WARN zero-trade profiles   : {no_trade}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Post-process utilization-based capital metrics on profile_comparison.json")
    parser.add_argument("strategy_id", help="Strategy ID to post-process")
    args = parser.parse_args()
    process_profile_comparison(args.strategy_id)
