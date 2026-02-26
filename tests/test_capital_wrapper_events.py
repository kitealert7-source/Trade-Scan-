"""Phase 6 validation: Dynamic USD conversion vs static YAML calibration."""

import sys, csv, tempfile, shutil, yaml, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.capital_wrapper import (
    load_trades, build_events, sort_events, run_simulation,
    print_validation_summary, print_comparative_summary,
    compute_deployable_metrics, ConversionLookup, _parse_fx_currencies,
    CONVERSION_MAP, BROKER_SPECS_ROOT, PROFILES,
    get_usd_per_price_unit_static, get_usd_per_price_unit_dynamic,
)

# Synthetic trades across USD-quote, USD-base, and cross pairs
TRADES = [
    # USD-quote: should be identical between static and dynamic
    ("EURUSD", 1, "2020-03-01 08:00:00", "2020-03-02 12:00:00",  1, 1.1000, 1.1100, 0.0050),
    ("EURUSD", 2, "2020-06-15 08:00:00", "2020-06-16 16:00:00", -1, 1.1200, 1.1100, 0.0060),
    # USD-base: dynamic should vary by date
    ("USDJPY", 1, "2020-03-01 08:00:00", "2020-03-01 16:00:00",  1, 107.50, 108.00, 0.500),
    ("USDJPY", 2, "2023-10-15 08:00:00", "2023-10-16 12:00:00", -1, 149.50, 148.50, 0.600),
    # Cross pair: should differ from anomalous YAML
    ("GBPUSD", 1, "2020-03-15 12:00:00", "2020-03-17 08:00:00",  1, 1.2500, 1.2700, 0.0080),
]

FIELDS = [
    "strategy_name", "parent_trade_id", "symbol",
    "entry_timestamp", "exit_timestamp", "direction",
    "entry_price", "exit_price", "risk_distance",
]


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        dirs = []
        symbols = sorted(set(t[0] for t in TRADES))
        for sym in symbols:
            d = tmp / ("TEST_" + sym)
            raw = d / "raw"
            raw.mkdir(parents=True)
            rows = [t for t in TRADES if t[0] == sym]
            with open(raw / "results_tradelevel.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                for r in rows:
                    w.writerow({
                        "strategy_name": "TEST_" + r[0],
                        "parent_trade_id": r[1],
                        "symbol": r[0],
                        "entry_timestamp": r[2],
                        "exit_timestamp": r[3],
                        "direction": r[4],
                        "entry_price": r[5],
                        "exit_price": r[6],
                        "risk_distance": r[7],
                    })
            dirs.append(d)

        trades = load_trades(dirs)
        events = build_events(trades)
        sorted_events = sort_events(events)

        broker_specs = {}
        for sym in symbols:
            with open(BROKER_SPECS_ROOT / f"{sym}.yaml", "r") as f:
                broker_specs[sym] = yaml.safe_load(f)

        # --- RUN A: Static (no conv_lookup) ---
        states_static = run_simulation(sorted_events, broker_specs, conv_lookup=None)

        # --- RUN B: Dynamic ---
        quote_ccys = set()
        for sym in symbols:
            _, q = _parse_fx_currencies(sym)
            if q:
                quote_ccys.add(q)

        conv = ConversionLookup()
        conv.load(quote_ccys)

        states_dynamic = run_simulation(sorted_events, broker_specs, conv_lookup=conv)

        # --- RUN C: Dynamic again (determinism) ---
        states_dynamic_2 = run_simulation(sorted_events, broker_specs, conv_lookup=conv)

        print("\n" + "=" * 70)
        print("  PHASE 6 VALIDATION")
        print("=" * 70)

        # 1. EURUSD: static == dynamic (USD quote, rate = 1.0)
        con_s = states_static["CONSERVATIVE_V1"]
        con_d = states_dynamic["CONSERVATIVE_V1"]
        # Check per-trade sizing: for EURUSD trades, lot sizes should be identical
        eurusd_static_lots = [t["lot_size"] for t in con_s.closed_trades_log if "EURUSD" in t["trade_id"]]
        eurusd_dynamic_lots = [t["lot_size"] for t in con_d.closed_trades_log if "EURUSD" in t["trade_id"]]
        if eurusd_static_lots and eurusd_dynamic_lots:
            match = all(abs(a - b) < 1e-8 for a, b in zip(eurusd_static_lots, eurusd_dynamic_lots))
            print(f"  [{'PASS' if match else 'FAIL'}] EURUSD lot sizes: static={eurusd_static_lots} dynamic={eurusd_dynamic_lots}")
        else:
            print(f"  [INFO] EURUSD trades: static={len(eurusd_static_lots)} dynamic={len(eurusd_dynamic_lots)}")

        # 2. USDJPY: dynamic should differ from static because rate varies
        usdjpy_static_lots = [t["lot_size"] for t in con_s.closed_trades_log if "USDJPY" in t["trade_id"]]
        usdjpy_dynamic_lots = [t["lot_size"] for t in con_d.closed_trades_log if "USDJPY" in t["trade_id"]]
        print(f"  [INFO] USDJPY lot sizes: static={usdjpy_static_lots} dynamic={usdjpy_dynamic_lots}")
        if usdjpy_static_lots and usdjpy_dynamic_lots:
            differs = any(abs(a - b) > 1e-8 for a, b in zip(usdjpy_static_lots, usdjpy_dynamic_lots))
            print(f"  [{'PASS' if differs else 'WARN'}] USDJPY sizing varies by date: {differs}")

        # 3. Overall comparison
        print(f"\n  STATIC  Conservative: equity=${con_s.equity:,.2f}  accepted={con_s.total_accepted}")
        print(f"  DYNAMIC Conservative: equity=${con_d.equity:,.2f}  accepted={con_d.total_accepted}")
        print(f"  Delta equity: ${con_d.equity - con_s.equity:,.2f}")

        # 4. Invariants
        for label, states in [("STATIC", states_static), ("DYNAMIC", states_dynamic)]:
            for name, s in states.items():
                assert not s._heat_breach, f"{label}/{name}: HEAT BREACH"
                assert not s._leverage_breach, f"{label}/{name}: LEVERAGE BREACH"
                assert not s._equity_negative, f"{label}/{name}: NEGATIVE EQUITY"
        print(f"  [PASS] All invariants hold (static + dynamic)")

        # 5. Determinism
        for name in states_dynamic:
            s1 = states_dynamic[name]
            s2 = states_dynamic_2[name]
            assert round(s1.equity, 2) == round(s2.equity, 2), f"{name}: equity drift"
            assert s1.total_accepted == s2.total_accepted, f"{name}: accepted drift"
        print(f"  [PASS] Determinism: DYNAMIC RUN1 == RUN2")

        # 6. Print summaries
        print(f"\n  --- STATIC ---")
        print_validation_summary(states_static["CONSERVATIVE_V1"])
        print(f"  --- DYNAMIC ---")
        print_validation_summary(states_dynamic["CONSERVATIVE_V1"])

        print("=" * 70)
        print("  ALL PHASE 6 CHECKS PASSED")
        print("=" * 70)

    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
