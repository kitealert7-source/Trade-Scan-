"""
Validation: Signal Integrity Guard + Strategy Kill-Switch
=========================================================
Runs five checks against the 01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00 strategy:

  1. Re-run capital_wrapper and confirm signal_hash column present.
  2. Verify hash reproducibility across two independent runs.
  3. Simulate one signal mismatch and confirm trade blocking.
  4. Simulate kill-switch — loss streak breach.
  5. Simulate kill-switch — equity drawdown breach.
"""

import csv
import sys
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT))

import capital_wrapper as cw
from execution_engine.strategy_guard import (
    StrategyGuard, GuardConfig,
    SignalMismatchError, StrategyHaltedError,
    _compute_signal_hash,
)

STRATEGY = "01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00"
PROFILE  = "FIXED_USD_V1"
GOLIVE   = PROJECT_ROOT / "strategies" / STRATEGY / "golive"

SEP  = "=" * 70
PASS = "[PASS]"
FAIL = "[FAIL]"


def _load_and_simulate():
    run_dirs = sorted([
        d for d in (PROJECT_ROOT / "backtests").iterdir()
        if d.is_dir() and d.name.startswith(STRATEGY)
    ])
    symbols      = sorted(set(d.name.split("_")[-1] for d in run_dirs))
    broker_specs = {s: cw.load_broker_spec(s) for s in symbols}

    conv = cw.ConversionLookup()
    qccs = set()
    for s in symbols:
        _, q = cw._parse_fx_currencies(s)
        if q:
            qccs.add(q)
    conv.load(qccs)

    trades  = cw.load_trades(run_dirs)
    events  = cw.build_events(trades)
    sevents = cw.sort_events(events)
    states  = cw.run_simulation(sevents, broker_specs, conv_lookup=conv)
    return states


def _read_trade_log(profile=PROFILE):
    p = PROJECT_ROOT / "strategies" / STRATEGY / "deployable" / profile / "deployable_trade_log.csv"
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Test 1 — signal_hash column present after capital_wrapper run
# ---------------------------------------------------------------------------
def test_signal_hash_column_present():
    print(f"\n{SEP}")
    print("TEST 1 — signal_hash column present in deployable_trade_log.csv")
    print(SEP)

    import tempfile
    states = _load_and_simulate()
    tmp    = pathlib.Path(tempfile.mkdtemp())
    cw.emit_profile_artifacts(states[PROFILE], tmp)

    with (tmp / "deployable_trade_log.csv").open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
        row1   = next(csv.reader(fh))   # type: ignore  (re-opens; use DictReader below)

    with (tmp / "deployable_trade_log.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    has_col     = "signal_hash" in header
    all_filled  = all(len(r.get("signal_hash", "")) == 16 for r in rows)
    total       = len(rows)

    print(f"  Columns   : {header}")
    print(f"  Rows      : {total}")
    print(f"  Has col   : {has_col}")
    print(f"  All 16chr : {all_filled}")
    print(f"  Sample    : trade_id={rows[0]['trade_id']}  hash={rows[0]['signal_hash']}")

    if has_col and all_filled:
        print(f"  {PASS}")
        return rows
    else:
        print(f"  {FAIL}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Test 2 — Hash reproducibility across two independent runs
# ---------------------------------------------------------------------------
def test_hash_reproducibility():
    print(f"\n{SEP}")
    print("TEST 2 — Hash reproducibility (run 1 vs run 2)")
    print(SEP)

    import tempfile
    states1 = _load_and_simulate()
    states2 = _load_and_simulate()

    tmp1 = pathlib.Path(tempfile.mkdtemp())
    tmp2 = pathlib.Path(tempfile.mkdtemp())
    cw.emit_profile_artifacts(states1[PROFILE], tmp1)
    cw.emit_profile_artifacts(states2[PROFILE], tmp2)

    def read_hashes(p):
        with p.open(newline="", encoding="utf-8") as fh:
            return [r["signal_hash"] for r in csv.DictReader(fh)]

    h1 = read_hashes(tmp1 / "deployable_trade_log.csv")
    h2 = read_hashes(tmp2 / "deployable_trade_log.csv")

    identical = (h1 == h2)
    print(f"  Trades run1 : {len(h1)}")
    print(f"  Trades run2 : {len(h2)}")
    print(f"  Identical   : {identical}")

    if identical:
        print(f"  {PASS}")
    else:
        mismatches = sum(a != b for a, b in zip(h1, h2))
        print(f"  Mismatches  : {mismatches}")
        print(f"  {FAIL}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Test 3 — Signal mismatch blocks trade
# ---------------------------------------------------------------------------
def test_signal_mismatch_blocked():
    print(f"\n{SEP}")
    print("TEST 3 — Signal mismatch: trade must be blocked")
    print(SEP)

    guard = StrategyGuard.from_golive_package(GOLIVE)
    rows  = _read_trade_log()
    row   = rows[0]

    trade_id      = row["trade_id"]
    symbol        = row["symbol"]
    entry_ts      = row["entry_timestamp"]
    direction     = int(row["direction"])
    entry_price   = float(row["entry_price"])
    risk_distance = float(row["risk_distance"])

    # Correct signal — must pass silently
    guard.verify_signal(trade_id, symbol, entry_ts, direction, entry_price, risk_distance)
    print(f"  Correct signal  : passed (no exception)")

    # Tampered entry_price — must raise SignalMismatchError
    tampered_price = entry_price + 1.0
    blocked = False
    try:
        guard.verify_signal(trade_id, symbol, entry_ts, direction, tampered_price, risk_distance)
    except SignalMismatchError as e:
        blocked = True
        print(f"  Tampered signal : BLOCKED (SignalMismatchError)")
        print(f"    {str(e).splitlines()[0]}")

    if blocked:
        print(f"  {PASS}")
    else:
        print(f"  {FAIL} — mismatch was NOT blocked")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Test 4 — Kill-switch: loss streak breach halts strategy
# ---------------------------------------------------------------------------
def test_kill_switch_loss_streak():
    print(f"\n{SEP}")
    print("TEST 4 — Kill-switch: loss streak breach")
    print(SEP)

    guard = StrategyGuard.from_golive_package(GOLIVE)
    bl    = guard.baseline
    limit = int(bl.max_loss_streak * guard.config.max_loss_streak_multiplier) + 1

    print(f"  Historical max streak : {bl.max_loss_streak}")
    print(f"  Multiplier            : {guard.config.max_loss_streak_multiplier}")
    print(f"  Halt threshold        : >{bl.max_loss_streak * guard.config.max_loss_streak_multiplier:.1f}")
    print(f"  Feeding {limit} consecutive losses of -$10 each ...")

    halted = False
    halted_at = None
    for i in range(limit):
        try:
            guard.record_trade(-10.0)
        except StrategyHaltedError as e:
            halted    = True
            halted_at = i + 1
            print(f"  Halted after trade {halted_at}: {str(e).splitlines()[0]}")
            break

    print(f"  State : {guard.state}")
    if halted:
        print(f"  {PASS}")
    else:
        print(f"  {FAIL} — strategy was NOT halted")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Test 5 — Kill-switch: equity drawdown breach halts strategy
# ---------------------------------------------------------------------------
def test_kill_switch_equity_dd():
    print(f"\n{SEP}")
    print("TEST 5 — Kill-switch: equity drawdown breach")
    print(SEP)

    guard = StrategyGuard.from_golive_package(GOLIVE)
    bl    = guard.baseline
    cfg   = guard.config

    dd_floor  = bl.starting_equity - (cfg.dd_multiplier * bl.max_drawdown_usd)
    loss_size = bl.max_drawdown_usd * cfg.dd_multiplier + 1.0

    print(f"  Starting equity       : ${bl.starting_equity:,.2f}")
    print(f"  Historical max DD     : ${bl.max_drawdown_usd:,.2f}")
    print(f"  DD multiplier         : {cfg.dd_multiplier}")
    print(f"  Equity floor          : ${dd_floor:,.2f}")
    print(f"  Injecting single loss : -${loss_size:,.2f}")

    halted = False
    try:
        guard.record_trade(-loss_size)
    except StrategyHaltedError as e:
        halted = True
        print(f"  Halted: {str(e).splitlines()[0]}")

    print(f"  State : {guard.state}")
    print(f"  Equity: ${guard.equity:,.2f}")
    if halted:
        print(f"  {PASS}")
    else:
        print(f"  {FAIL} — strategy was NOT halted")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print()
    print(SEP)
    print("  SAFETY LAYER VALIDATION")
    print(f"  Strategy : {STRATEGY}")
    print(f"  Profile  : {PROFILE}")
    print(SEP)

    test_signal_hash_column_present()
    test_hash_reproducibility()
    test_signal_mismatch_blocked()
    test_kill_switch_loss_streak()
    test_kill_switch_equity_dd()

    print(f"\n{SEP}")
    print("  ALL TESTS PASSED")
    print(SEP)
    print()


if __name__ == "__main__":
    main()
