"""
Deployable Capital Wrapper â€” Phases 2â€“6
Phase 2: Event Queue Builder (load, decompose, sort)
Phase 3: Single-Profile PortfolioState
Phase 4: Multi-Profile Parallel Execution
Phase 5: Deployable Metric Engine + Artifact Output
Phase 6: Dynamic USD Conversion at Entry Time

Authority: CAPITAL_MIGRATION_IMPACT.md, MODULAR_IMPACT_VALIDATION.md

Orchestration only â€” implementation lives in tools/capital/ submodules:
  capital_events, capital_broker_spec, capital_fx,
  capital_portfolio_state, capital_metrics, capital_validation,
  capital_plotting, capital_artifacts, capital_directive_discovery.
"""

import sys
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Re-exports (stable external surface — kept under tools.capital_wrapper.* so
# existing imports in experiments/, tests/, archive/ continue to resolve.)
# ---------------------------------------------------------------------------
from config.state_paths import BACKTESTS_DIR, STRATEGIES_DIR

from tools.capital.capital_events import (  # noqa: F401
    EVENT_TYPE_ENTRY,
    EVENT_TYPE_EXIT,
    EVENT_TYPE_PARTIAL,
    EVENT_TYPE_PRIORITY,
    OPTIONAL_RECON_COLUMNS,
    OpenTrade,
    REQUIRED_COLUMNS,
    SIMULATION_SEED,
    TradeEvent,
    _normalize_hash_timestamp,
    _optional_float,
    _parse_ts,
    build_events,
    compute_signal_hash,
    load_partial_legs,
    load_trades,
    print_events,
    sort_events,
)
from tools.capital.capital_broker_spec import (  # noqa: F401
    BROKER_SPECS_ROOT,
    _BACKTEST_BROKER_SPECS,
    _load_broker_spec_cached,
    _normalize_lot_broker,
    get_usd_per_price_unit_static,
    load_broker_spec,
)
from tools.capital.capital_fx import (  # noqa: F401
    CONVERSION_MAP,
    ConversionLookup,
    _STATIC_FALLBACK_WARNED,
    _parse_fx_currencies,
    get_usd_per_price_unit_dynamic,
)
from tools.capital.capital_portfolio_state import (  # noqa: F401
    FLOAT_TOLERANCE,
    PROFILES,
    PortfolioState,
)
from tools.capital.capital_metrics import compute_deployable_metrics  # noqa: F401
from tools.capital.capital_validation import (  # noqa: F401
    _assert_partial_conservation,
    print_comparative_summary,
    print_validation_summary,
)
from tools.capital.capital_plotting import (  # noqa: F401
    plot_equity_curve,
    plot_overlay_comparison,
)
from tools.capital.capital_artifacts import (  # noqa: F401
    emit_comparison_json,
    emit_profile_artifacts,
)
from tools.capital.capital_directive_discovery import (  # noqa: F401
    DIRECTIVES_ROOT,
    _find_directive_file,
    _load_declared_symbols,
    discover_run_dirs,
)

from tools.capital_engine import run_simulation as _engine_run_simulation


# Back-compat alias — some experiments/CLI callers use BACKTESTS_ROOT.
BACKTESTS_ROOT = BACKTESTS_DIR


# ======================================================================
# SIMULATION WRAPPER
# ======================================================================

def run_simulation(sorted_events, broker_specs: Dict[str, dict],
                   profiles: Optional[Dict[str, dict]] = None,
                   conv_lookup: Optional[ConversionLookup] = None) -> Dict[str, PortfolioState]:
    """Compatibility wrapper that delegates simulation execution to capital_engine."""
    if profiles is None:
        profiles = PROFILES
    return _engine_run_simulation(
        sorted_events=sorted_events,
        broker_specs=broker_specs,
        profiles=profiles,
        conv_lookup=conv_lookup,
    )


# ======================================================================
# MAIN
# ======================================================================

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Deployable Capital Wrapper â€” Phase 3: Single-Profile Simulation"
    )
    parser.add_argument(
        "strategy_prefix",
        help="Strategy prefix to match backtest folders (e.g. AK31_FX_PORTABILITY_4H)",
    )
    args = parser.parse_args()
    prefix = args.strategy_prefix

    # Discover run directories
    run_dirs, directive_file, declared_symbols = discover_run_dirs(prefix)
    if not run_dirs:
        print(f"[FATAL] No backtest directories found matching prefix: {prefix}")
        sys.exit(1)

    print(f"[INIT] Strategy prefix: {prefix}")
    print(f"[INIT] Matched {len(run_dirs)} run directories")
    if directive_file is not None:
        print(f"[INIT] Directive source: {directive_file}")
        print(f"[INIT] Declared symbols: {declared_symbols}")
    else:
        print("[WARN] No directive found; using prefix-scan discovery (unfrozen universe).")

    # Phase 2: Load â†’ Build â†’ Sort
    trades = load_trades(run_dirs)
    partials_by_parent = load_partial_legs(run_dirs)
    events = build_events(trades, partials_by_parent)
    sorted_events = sort_events(events)

    # Discover unique symbols and load broker specs
    symbols = sorted(set(e.symbol for e in sorted_events))
    if declared_symbols:
        missing_in_events = sorted(set(declared_symbols) - set(symbols))
        extra_in_events = sorted(set(symbols) - set(declared_symbols))
        if missing_in_events or extra_in_events:
            print("[FATAL] Symbol mismatch between directive and event stream.")
            if missing_in_events:
                print(f"  Missing in events: {missing_in_events}")
            if extra_in_events:
                print(f"  Unexpected in events: {extra_in_events}")
            sys.exit(1)
    print(f"[INIT] Symbols detected: {symbols}")

    broker_specs = {}
    for sym in symbols:
        broker_specs[sym] = load_broker_spec(sym)
    print(f"[INIT] Broker specs loaded: {len(broker_specs)}")
    print(f"[INIT] Profiles: {list(PROFILES.keys())}")

    # MT5-verified static valuation — no dynamic conversion needed.
    # All broker specs now have MT5-derived usd_pnl_per_price_unit_0p01 = tick_value/tick_size*0.01
    # which already accounts for currency conversion (MT5 tick_value is in account currency).
    print("[INIT] Using MT5-verified static valuation (dynamic conversion disabled)")

    # Phase 4: Run multi-profile simulation (static MT5 valuation)
    states = run_simulation(sorted_events, broker_specs, conv_lookup=None)

    # Conservation checks (partial-aware). Fail-fast per invariant #1.
    _assert_partial_conservation(states, partials_by_parent)

    # Print per-profile validation
    for state in states.values():
        print_validation_summary(state)

    # Print comparative summary
    print_comparative_summary(states)

    # Phase 5: Emit artifacts
    deployable_root = STRATEGIES_DIR / args.strategy_prefix / "deployable"
    deployable_root.mkdir(parents=True, exist_ok=True)
    all_metrics = {}

    true_constituent_runs = len(run_dirs)
    if args.strategy_prefix.startswith("PF_"):
        meta_file = STRATEGIES_DIR / args.strategy_prefix / "portfolio_evaluation" / "portfolio_metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                    c_runs = m_data.get("constituent_run_ids", [])
                    if c_runs:
                        true_constituent_runs = len(c_runs)
            except Exception:
                pass

    for name, state in states.items():
        profile_dir = deployable_root / name
        metrics = emit_profile_artifacts(state, profile_dir, true_constituent_runs, len(symbols))
        plot_equity_curve(state, profile_dir)
        all_metrics[name] = metrics

    emit_comparison_json(all_metrics, states, deployable_root)
    plot_overlay_comparison(states, deployable_root)

    try:
        from tools.post_process_capital import process_profile_comparison
        process_profile_comparison(args.strategy_prefix)
    except Exception as e:
        print(f"[WARN] post_process_capital failed for {args.strategy_prefix}: {e}")

    print(f"[DONE] All artifacts emitted to {deployable_root}")


if __name__ == "__main__":
    main()
