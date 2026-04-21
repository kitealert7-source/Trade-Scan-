"""capital_replay — determinism of `compute_signal_hash`.

Choke-point: `compute_signal_hash` is the engine's identity contract between
research and live execution. Any change to its fields, ordering, precision,
or normalization breaks the TS_Execution signal-match check and silently
invalidates every deployed strategy.

Scenario: run the function against 10 canonical input tuples and compare
the resulting 16-char hashes to a frozen golden JSON.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tools.capital.capital_events import compute_signal_hash
from tools.regression.compare import compare_json
from tools.regression.runner import Result


# Canonical inputs exercise: string vs datetime timestamps, both directions,
# fractional prices, tiny risk distances, large values.
_CASES = [
    # (case_id, symbol, ts, direction, entry_price, risk_distance)
    ("c01_xauusd_long_str", "XAUUSD", "2025-01-15T12:00:00", 1, 2650.12345, 10.50000),
    ("c02_xauusd_short_dt", "XAUUSD",
     datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc), -1, 2650.12345, 10.50000),
    ("c03_eurusd_long",    "EURUSD", "2024-06-03T09:30:15", 1, 1.08745, 0.00250),
    ("c04_eurusd_short",   "EURUSD", "2024-06-03T09:30:15", -1, 1.08745, 0.00250),
    ("c05_btcusd_long",    "BTCUSD", "2025-03-01T00:00:00", 1, 84750.00000, 1250.50000),
    ("c06_precision_a",    "XAUUSD", "2026-01-01T00:00:00", 1, 2000.00001, 1.00001),
    ("c07_precision_b",    "XAUUSD", "2026-01-01T00:00:00", 1, 2000.00002, 1.00001),
    ("c08_zero_risk",      "USDJPY", "2024-11-11T11:11:11", -1, 152.500, 0.000),
    ("c09_large_price",    "US500",  "2025-07-04T14:00:00", 1, 5850.25000, 25.00000),
    ("c10_fractional_sec", "GBPUSD", "2025-02-20T08:15:30.500", 1, 1.26500, 0.00100),
]


def run(tmp_dir: Path, baseline_dir: Path, budget) -> list[Result]:
    # --- compute current outputs ---------------------------------------------
    got = {
        case_id: compute_signal_hash(sym, ts, direction, entry, risk)
        for (case_id, sym, ts, direction, entry, risk) in _CASES
    }
    got_path = tmp_dir / "signal_hashes.json"
    got_path.write_text(json.dumps(got, indent=2, sort_keys=True), encoding="utf-8")

    # Emit into golden_candidate/ so --update-baseline can promote it.
    candidate = tmp_dir / "golden_candidate" / "signal_hashes.json"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(json.dumps(got, indent=2, sort_keys=True), encoding="utf-8")

    # --- compare to golden ----------------------------------------------------
    golden_path = baseline_dir / "golden" / "signal_hashes.json"
    passed, diff = compare_json(got_path, golden_path)
    return [Result(
        scenario="capital_replay",
        artifact="signal_hashes.json",
        passed=passed,
        diff=diff,
    )]
