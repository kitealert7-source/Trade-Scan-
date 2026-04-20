"""
Verification script: collision-randomization before vs after comparison.
Run after patching run_simulation() in capital_wrapper.py.
"""
import sys, statistics
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import tools.capital_wrapper as cw
from config.state_paths import BACKTESTS_DIR


def run_old(sorted_events, broker_specs, conv_lookup):
    """Reproduce pre-patch sequential ordering (no shuffle)."""
    profiles = cw.PROFILES
    states = {}
    for name, params in profiles.items():
        states[name] = cw.PortfolioState(
            profile_name=name,
            starting_capital=params["starting_capital"],
            risk_per_trade=params["risk_per_trade"],
            heat_cap=params["heat_cap"],
            leverage_cap=params["leverage_cap"],
            min_lot=params["min_lot"],
            lot_step=params["lot_step"],
            concurrency_cap=params.get("concurrency_cap"),
            fixed_risk_usd=params.get("fixed_risk_usd"),
            dynamic_scaling=params.get("dynamic_scaling", False),
            min_position_pct=params.get("min_position_pct", 0.0),
            min_lot_fallback=params.get("min_lot_fallback", False),
            max_risk_multiple=params.get("max_risk_multiple", 3.0),
            track_risk_override=params.get("track_risk_override", False),
        )
    sfb, scs, sqc = {}, {}, {}
    for sym, spec in broker_specs.items():
        sfb[sym] = cw.get_usd_per_price_unit_static(spec)
        scs[sym] = float(spec["contract_size"])
        _, q = cw._parse_fx_currencies(sym)
        sqc[sym] = q if q else "USD"

    for event in sorted_events:
        sym = event.symbol
        cs = scs[sym]
        if event.event_type == cw.EVENT_TYPE_ENTRY:
            usd_per_pu, _ = cw.get_usd_per_price_unit_dynamic(
                cs, sqc[sym], event.timestamp.date(), conv_lookup, sfb[sym], sym
            )
            for state in states.values():
                state.process_entry(event, usd_per_pu, cs)
        elif event.event_type == cw.EVENT_TYPE_EXIT:
            for state in states.values():
                state.process_exit(event)
    return states


def sym_stats(states):
    acc = defaultdict(lambda: defaultdict(int))
    rej = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for pname, state in states.items():
        for t in state.closed_trades_log:
            acc[pname][t["symbol"]] += 1
        for r in state.rejection_log:
            rej[pname][r["symbol"]][r["reason"]] += 1
    return acc, rej


def main():
    strategy = "01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00"
    run_dirs = sorted(
        [d for d in BACKTESTS_DIR.iterdir() if d.is_dir() and d.name.startswith(strategy)]
    )
    symbols = sorted(set(d.name.split("_")[-1] for d in run_dirs))
    broker_specs = {s: cw.load_broker_spec(s) for s in symbols}

    conv_lookup = cw.ConversionLookup()
    qccs = set()
    for s in symbols:
        _, q = cw._parse_fx_currencies(s)
        if q:
            qccs.add(q)
    conv_lookup.load(qccs)

    trades = cw.load_trades(run_dirs)
    events = cw.build_events(trades)
    sorted_events = cw.sort_events(events)

    old   = run_old(sorted_events, broker_specs, conv_lookup)
    new1  = cw.run_simulation(sorted_events, broker_specs, conv_lookup=conv_lookup)
    new2  = cw.run_simulation(sorted_events, broker_specs, conv_lookup=conv_lookup)

    oa, or_ = sym_stats(old)
    na, nr  = sym_stats(new1)
    na2, _  = sym_stats(new2)

    profiles = list(cw.PROFILES.keys())

    print("=" * 80)
    print("  COLLISION-RANDOMIZATION VERIFICATION REPORT")
    print(f"  Strategy: {strategy}  |  RNG seed: 42")
    print("=" * 80)

    for pname in profiles:
        os_ = old[pname]
        ns  = new1[pname]
        print(f"\n-- {pname} --")
        print(f"  {'Symbol':<10} {'Old_Acc':>9} {'New_Acc':>9} {'Delta':>7}  "
              f"{'Old_LevRej':>11} {'New_LevRej':>11}  {'Old_HeatRej':>12} {'New_HeatRej':>12}")
        print("  " + "-" * 90)
        for sym in symbols:
            o_a  = oa[pname][sym];  n_a  = na[pname][sym]
            o_lr = or_[pname][sym].get("LEVERAGE_CAP", 0)
            n_lr = nr[pname][sym].get("LEVERAGE_CAP", 0)
            o_hr = or_[pname][sym].get("HEAT_CAP", 0) + or_[pname][sym].get("HEAT_CAP_EDGE", 0)
            n_hr = nr[pname][sym].get("HEAT_CAP", 0)  + nr[pname][sym].get("HEAT_CAP_EDGE", 0)
            print(f"  {sym:<10} {o_a:>9} {n_a:>9} {n_a - o_a:>+7}  "
                  f"{o_lr:>11} {n_lr:>11}  {o_hr:>12} {n_hr:>12}")
        print(f"  {'TOTAL':<10} {os_.total_accepted:>9} {ns.total_accepted:>9} "
              f"{ns.total_accepted - os_.total_accepted:>+7}")
        print(f"  Final equity:   OLD ${os_.equity:,.2f}   NEW ${ns.equity:,.2f}   "
              f"delta=${ns.equity - os_.equity:+.2f}")
        print(f"  Max concurrent: OLD {os_.max_concurrent}   NEW {ns.max_concurrent}")
        inv = ("PASS" if not ns._heat_breach and not ns._leverage_breach
               and not ns._equity_negative else "FAIL")
        print(f"  Invariants (heat / leverage / equity): {inv}")

    print("\n-- REPRODUCIBILITY CHECK (run1 vs run2, seed=42) --")
    for pname in profiles:
        ns  = new1[pname]
        ns2 = new2[pname]
        pnl1 = [t["pnl_usd"] for t in ns.closed_trades_log]
        pnl2 = [t["pnl_usd"] for t in ns2.closed_trades_log]
        match = (
            ns.equity == ns2.equity
            and ns.total_accepted == ns2.total_accepted
            and pnl1 == pnl2
        )
        print(f"  {pname:<38}: {'IDENTICAL' if match else 'MISMATCH !!!'}")

    print("\n-- BIAS REDUCTION: std-dev of accepted counts (excl. USDJPY: pre-existing leverage cap) --")
    for pname in profiles:
        syms5 = [s for s in symbols if s != "USDJPY"]
        o_std = statistics.stdev([oa[pname][s] for s in syms5])
        n_std = statistics.stdev([na[pname][s] for s in syms5])
        print(f"  {pname:<38}: old_std={o_std:.1f}  new_std={n_std:.1f}  delta={n_std - o_std:+.1f}")


if __name__ == "__main__":
    main()
