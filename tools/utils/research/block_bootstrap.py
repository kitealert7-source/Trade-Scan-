"""
Block bootstrap Monte Carlo via capital_wrapper replay.
Consumes deployable_trade_log.csv.  Calls capital_wrapper for simulation.
Never touches Stage1 or run_pipeline.
"""

import copy
import random
from pathlib import Path

import pandas as pd
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from config.state_paths import STRATEGIES_DIR, BACKTESTS_DIR
from tools.capital_wrapper import (
    load_trades,
    build_events,
    load_broker_spec,
    PortfolioState,
    get_usd_per_price_unit_static,
)
from tools.capital.capital_portfolio_state import PROFILES


def _shift_timestamp(dt_str: str, shift_years: int) -> str:
    dt = pd.to_datetime(dt_str)
    try:
        new_dt = dt.replace(year=dt.year + shift_years)
    except ValueError:
        new_dt = dt.replace(year=dt.year + shift_years, day=28)
    return new_dt.strftime("%Y-%m-%d %H:%M:%S")


def run_block_bootstrap(
    prefix: str,
    profile: str,
    iterations: int = 100,
    block_unit: str = "year",
    seed: int = 42,
) -> pd.DataFrame:
    """Year-block bootstrap MC using the capital wrapper simulation.

    Reads the deployable_trade_log.csv for the given prefix/profile,
    resamples year-blocks with replacement, and re-simulates through
    the wrapper's portfolio state machine.
    """
    random.seed(seed)

    if profile not in PROFILES:
        raise ValueError(
            f"Unknown capital profile '{profile}' — cannot bootstrap. "
            f"Known profiles: {sorted(PROFILES)}"
        )

    deploy_dir = STRATEGIES_DIR / prefix / "deployable" / profile
    acc_df = pd.read_csv(deploy_dir / "deployable_trade_log.csv")
    accepted_ids = set(acc_df["trade_id"])

    # Load raw trade dicts from backtest dirs
    run_dirs = sorted(
        [d for d in BACKTESTS_DIR.iterdir()
         if d.is_dir() and d.name.startswith(prefix)
         and (d / "raw" / "results_tradelevel.csv").exists()]
    )
    if not run_dirs:
        raise FileNotFoundError(f"No backtest directories found for prefix: {prefix}")

    orig_trades_raw = load_trades(run_dirs)
    for t in orig_trades_raw:
        t["trade_id"] = f"{t['strategy_name']}|{t['parent_trade_id']}"

    orig_trades = [t for t in orig_trades_raw if t["trade_id"] in accepted_ids]

    # Pre-load broker specs (canonical MT5 static valuation — no conversion lookup)
    broker_specs = {}
    for t in orig_trades:
        sym = t["symbol"]
        if sym not in broker_specs:
            broker_specs[sym] = load_broker_spec(sym)

    # Group by year
    years_dict: dict[int, list] = {}
    for t in orig_trades:
        yr = pd.to_datetime(t["entry_timestamp"]).year
        years_dict.setdefault(yr, []).append(t)

    unique_years = sorted(years_dict.keys())
    n_years = len(unique_years)
    base_year = unique_years[0]

    # Determine profile parameters from summary_metrics
    import json
    with open(deploy_dir / "summary_metrics.json", encoding="utf-8") as f:
        metrics = json.load(f)
    start_cap = metrics["starting_capital"]

    results = []
    for i in range(iterations):
        sampled = random.choices(unique_years, k=n_years)

        sim_trades = []
        for target_idx, orig_year in enumerate(sampled):
            target_year = base_year + target_idx
            shift = target_year - orig_year
            for t in years_dict[orig_year]:
                nt = copy.deepcopy(t)
                nt["parent_trade_id"] = f"{nt['parent_trade_id']}_MC_{i}_{target_idx}"
                nt["entry_timestamp"] = _shift_timestamp(t["entry_timestamp"], shift)
                nt["exit_timestamp"] = _shift_timestamp(t["exit_timestamp"], shift)
                sim_trades.append(nt)

        events = build_events(sim_trades)
        events.sort(key=lambda x: x.timestamp)

        if not events:
            continue

        # Replay under the ACTUAL profile being bootstrapped — resolved from the
        # canonical PROFILES registry (single source; capital_portfolio_state).
        # The previous hardcoded legacy params (risk 0.75% of $1k, heat 4%,
        # leverage 5) rejected every index-CFD trade (LOT_BELOW_VOL_MIN) and
        # emitted all-zero statistics with no error (root-caused 2026-07-02).
        profile_cfg = dict(PROFILES[profile])
        profile_cfg["starting_capital"] = start_cap
        state = PortfolioState(
            profile_name=f"MC_{i}",
            **profile_cfg,
        )

        sim_start = events[0].timestamp
        sim_end = events[-1].timestamp
        sim_years = max((sim_end - sim_start).days / 365.25, 1.0)

        for e in events:
            if e.event_type == "ENTRY":
                sym = e.symbol
                bs = broker_specs[sym]
                cs = float(bs["contract_size"])
                # Canonical MT5 static valuation — the SAME monetary model
                # run_simulation uses ("universal path for ALL instruments;
                # tick_value already accounts for currency"). The previous
                # deprecated dynamic-path call mispriced indices ~12x
                # (single-monetary-model invariant, 2026-07-02).
                usd_per_pu = get_usd_per_price_unit_static(bs)
                state.process_entry(e, usd_per_pu, cs)
            else:
                state.process_exit(e)

        # TRIPWIRE (2026-07-02): an iteration that accepts ZERO trades means the
        # profile/sizing replay is misconfigured — emitting flat-equity zeros
        # would silently reproduce the all-zero Section-14 defect. Fail loudly.
        if state.total_accepted == 0:
            sample = state.rejection_log[0] if state.rejection_log else {}
            raise RuntimeError(
                f"Block bootstrap iteration {i}: 0 of {len(sim_trades)} trades "
                f"accepted under profile '{profile}' — refusing to emit all-zero "
                f"statistics. First rejection: {sample.get('reason', 'n/a')} "
                f"({sample.get('detail', '')})"
            )

        cagr = (
            ((state.equity / start_cap) ** (1.0 / sim_years) - 1.0) * 100
            if state.equity > 0
            else -100.0
        )
        dd_pct = (
            (state.max_drawdown_usd / state.peak_equity) * 100
            if state.peak_equity > 0
            else 100.0
        )

        results.append(
            {
                "run": i + 1,
                "final_equity": state.equity,
                "cagr": cagr,
                "max_dd_pct": dd_pct,
            }
        )

    return pd.DataFrame(results)
