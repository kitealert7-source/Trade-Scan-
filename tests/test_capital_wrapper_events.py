"""Phase 6 validation: Dynamic USD conversion vs static YAML calibration."""

import sys, csv, tempfile, shutil, yaml, json
import unittest
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.capital_wrapper import (
    load_trades, build_events, sort_events, run_simulation,
    ConversionLookup, _parse_fx_currencies,
    BROKER_SPECS_ROOT
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

class TestCapitalWrapperEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dirs = []
        self.symbols = sorted(set(t[0] for t in TRADES))
        for sym in self.symbols:
            d = self.tmp / ("TEST_" + sym)
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
            self.dirs.append(d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_phase_6_validation(self):
        trades = load_trades(self.dirs)
        events = build_events(trades)
        sorted_events = sort_events(events)

        broker_specs = {}
        for sym in self.symbols:
            with open(BROKER_SPECS_ROOT / f"{sym}.yaml", "r") as f:
                broker_specs[sym] = yaml.safe_load(f)

        # --- RUN A: Static (no conv_lookup) ---
        states_static = run_simulation(sorted_events, broker_specs, conv_lookup=None)

        # --- RUN B: Dynamic ---
        quote_ccys = set()
        for sym in self.symbols:
            _, q = _parse_fx_currencies(sym)
            if q:
                quote_ccys.add(q)

        conv = ConversionLookup()
        conv.load(quote_ccys)
        states_dynamic = run_simulation(sorted_events, broker_specs, conv_lookup=conv)

        # --- RUN C: Dynamic again (determinism) ---
        states_dynamic_2 = run_simulation(sorted_events, broker_specs, conv_lookup=conv)

        # 1. EURUSD: static == dynamic (USD quote, rate = 1.0)
        con_s = states_static["CONSERVATIVE_V1"]
        con_d = states_dynamic["CONSERVATIVE_V1"]
        eurusd_static_lots = [t["lot_size"] for t in con_s.closed_trades_log if "EURUSD" in t["trade_id"]]
        eurusd_dynamic_lots = [t["lot_size"] for t in con_d.closed_trades_log if "EURUSD" in t["trade_id"]]
        if eurusd_static_lots and eurusd_dynamic_lots:
            for a, b in zip(eurusd_static_lots, eurusd_dynamic_lots):
                self.assertAlmostEqual(a, b, places=8)

        # 2. USDJPY: dynamic should differ from static because rate varies
        usdjpy_static_lots = [t["lot_size"] for t in con_s.closed_trades_log if "USDJPY" in t["trade_id"]]
        usdjpy_dynamic_lots = [t["lot_size"] for t in con_d.closed_trades_log if "USDJPY" in t["trade_id"]]
        if usdjpy_static_lots and usdjpy_dynamic_lots:
            differs = any(abs(a - b) > 1e-8 for a, b in zip(usdjpy_static_lots, usdjpy_dynamic_lots))
            self.assertTrue(differs, "USDJPY sizing should vary by date")

        # 4. Invariants
        for label, states in [("STATIC", states_static), ("DYNAMIC", states_dynamic)]:
            for name, s in states.items():
                self.assertFalse(s._heat_breach, f"{label}/{name}: HEAT BREACH")
                self.assertFalse(s._leverage_breach, f"{label}/{name}: LEVERAGE BREACH")
                self.assertFalse(s._equity_negative, f"{label}/{name}: NEGATIVE EQUITY")

        # 5. Determinism
        for name in states_dynamic:
            s1 = states_dynamic[name]
            s2 = states_dynamic_2[name]
            self.assertAlmostEqual(s1.equity, s2.equity, places=2)
            self.assertEqual(s1.total_accepted, s2.total_accepted)

if __name__ == "__main__":
    unittest.main()
