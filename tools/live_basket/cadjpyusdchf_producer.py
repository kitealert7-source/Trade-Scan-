"""cadjpyusdchf_producer.py -- MINIMUM Option-2 live producer (V0 demo slice).

Per closed 15m bar: read CADJPY + USDCHF (+ USDJPY ref) OHLC directly from
MetaTrader5, run the promoted cointegration mechanic (pine_ratio_zrev_v1_zcross)
over the prefix, and emit mechanic-driven Targets (FLAT/IN) to the bridge via the
existing StreamingBasketRunner. The existing TS_Execution basket shim consumes
target.jsonl and executes the 2-leg group on the demo account.

SCOPE (deliberately minimal -- see the implementation plan):
  single basket CADJPYUSDCHF, 15M only, demo only, one machine.
  NO multi-basket, NO scheduler/orchestration, NO restart persistence beyond the
  bridge's own state-restore, NO Option-3 infra, NO production hardening.

Option 2 isolation: this process owns its OWN MetaTrader5 connection -- it does
NOT import TS_Execution (the contract forbids it). It does NOT place orders; it
only writes target.jsonl + the runner heartbeat. The shim places the orders and
enforces the hard demo-account allow-list gate.

USD-reference rates: the mechanic's per-bar USD P&L (_leg_pnl_usd_universal) needs
USD-anchored reference closes for each leg's QUOTE currency. For CADJPYUSDCHF:
  - USDCHF leg quote=CHF -> USDCHF self-references (it IS a USD-anchored leg).
  - CADJPY  leg quote=JPY -> needs an external USDJPY rate, joined as the column
    `usd_ref_USDJPY_close` (mirrors basket_data_loader.py:547). Hence USD_REF_SYMBOLS.

Run:
  python tools/live_basket/cadjpyusdchf_producer.py --once          # one live cycle, then exit
  python tools/live_basket/cadjpyusdchf_producer.py                 # live loop (writes targets only)
  python tools/live_basket/cadjpyusdchf_producer.py --replay-csv CADJPY=a.csv USDCHF=b.csv USDJPY=c.csv  # OFFLINE validation
Then, only on operator go-ahead, run the shim --live (separate process) to execute.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

# Resolve Trade_Scan root so `tools.*` imports work regardless of cwd.
_TS_ROOT = Path(__file__).resolve().parents[2]          # .../Trade_Scan
if str(_TS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TS_ROOT))

from tools.pipeline_utils import parse_directive                       # noqa: E402
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy  # noqa: E402
from tools.basket_pipeline import run_basket_pipeline                   # noqa: E402
from tools.live_basket.driver import (                                  # noqa: E402
    StreamingBasketRunner, target_sequence_from_records,
)

# ---- config (hardcoded; single basket / 15M / demo) ---------------------- #
BASKET_ID      = "CADJPYUSDCHF"
DIRECTIVE_ID   = "90_PORT_CADJPYUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS__E260312"
DIRECTIVE_PATH = _TS_ROOT / "backtest_directives" / "completed" / (DIRECTIVE_ID + ".txt")
MT5_TF_ATTR    = "TIMEFRAME_M15"     # 15m
FETCH_N        = 500                 # >> 2*n_window(30)=60 warmup; bounds the O(N^2) replay cost
POLL_SECONDS   = 60                  # < 300s shim heartbeat-staleness guard, so opens are never skipped
RUN_ID         = "DEMOPRODV0"        # provenance stamp threaded into per_bar_records
REPLAY_TAIL    = 1500                # offline validation: cap bars for bounded runtime

# External USD-reference pairs to join as `usd_ref_<PAIR>_close` (see module docstring).
# Derived for THIS basket from BOTH base+quote ccys of both legs, minus self-refs:
#   CADJPY -> base CAD (margin) -> USDCAD ; quote JPY (P&L) -> USDJPY
#   USDCHF -> base USD = 1.0    ; quote CHF -> USDCHF (self-referenced by the leg)
USD_REF_SYMBOLS = ("USDJPY", "USDCAD")

# Bridge dir the shim reads. Derived from repo layout (Documents/), NO TS_Execution import.
# MUST byte-match TS_Execution/src/basket_shim.py SIGNAL_DIR (TRADESCAN_STATE/TS_SIGNAL_STATE/h2_live/<id>).
SIGNAL_DIR = _TS_ROOT.parent / "TradeScan_State" / "TS_SIGNAL_STATE" / "h2_live" / BASKET_ID


# ---- mechanic wiring (the replay_fn the driver calls each bar) ----------- #
def _build_leg_strategies(parsed: dict) -> dict:
    """FRESH leg_strategies with a FRESH shared PineZRevArmedState. MUST be rebuilt
    per replay call: the entry protocol is a 2-bar state machine shared across both
    legs; reusing it across prefix-replays would pollute state. (run_pipeline.py
    _build_pine_zrev_legs builds it the same way.)"""
    shared = PineZRevArmedState()
    return {
        leg["symbol"]: PineZRevLegStrategy(
            symbol=leg["symbol"],
            position_direction=(+1 if leg["direction"] == "long" else -1),
            armed_state=shared,
        )
        for leg in parsed["basket"]["legs"]
    }


def _make_replay_fn(parsed: dict):
    sym_a = parsed["basket"]["legs"][0]["symbol"]
    sym_b = parsed["basket"]["legs"][1]["symbol"]

    def replay_fn(df_a_prefix: pd.DataFrame, df_b_prefix: pd.DataFrame):
        # PURITY: copy the frames (run mutates leg.df in place) + fresh leg_strategies
        # each call. run_basket_pipeline instantiates the rule fresh internally -> the
        # whole call is a pure function of the prefix. (df_*_prefix already carry the
        # usd_ref_<PAIR>_close columns the P&L needs -- attached by the caller.)
        leg_data = {sym_a: df_a_prefix.copy(), sym_b: df_b_prefix.copy()}
        result = run_basket_pipeline(
            parsed, leg_data, _build_leg_strategies(parsed),
            run_id=RUN_ID, directive_id=DIRECTIVE_ID,
        )
        return result.per_bar_records

    return replay_fn, sym_a, sym_b


def _attach_usd_refs(leg_df: pd.DataFrame, ref_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Attach `usd_ref_<PAIR>_close` columns (ffill onto the leg index) so the
    mechanic's USD P&L can convert each leg's quote currency. Mirrors
    basket_data_loader.py:547. Returns the same frame (mutated)."""
    for pair, ref_df in ref_frames.items():
        leg_df[f"usd_ref_{pair}_close"] = ref_df["close"].reindex(leg_df.index, method="ffill")
    return leg_df


# ---- MT5 bar reader (Option-2: own connection, OHLC only) ---------------- #
def _connect_mt5():
    import MetaTrader5 as mt5  # local import: this is the only MT5 dependency
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    acct = mt5.account_info()
    if acct is None:
        mt5.shutdown()
        raise RuntimeError("MT5 account_info() is None -- terminal not logged in")
    print(f"  PRODUCER_MT5_OK  login={acct.login} server={acct.server} trade_mode={acct.trade_mode}",
          flush=True)
    return mt5


def _fetch_closed_bars(mt5, symbol: str, count: int) -> pd.DataFrame:
    """Closed 15m OHLC for `symbol` as a time-indexed DataFrame. Drops the forming
    bar (rates[-1]); matches the leg-df contract the mechanic expects."""
    rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, MT5_TF_ATTR), 0, count)
    if rates is None or len(rates) < 2:
        n = "None" if rates is None else len(rates)
        raise RuntimeError(f"copy_rates_from_pos({symbol}) returned {n} rows; last_error={mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.DatetimeIndex(pd.to_datetime(df["time"], unit="s"), name="time")
    df = df[["open", "high", "low", "close"]].astype("float64")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # Drop the forming bar AFTER sorting so we always remove the NEWEST bar,
    # robust to MT5 return order (copy_rates_from_pos is ascending, but don't rely on it).
    return df.iloc[:-1]


def _run_cycle(runner: StreamingBasketRunner, mt5, sym_a: str, sym_b: str):
    df_a = _fetch_closed_bars(mt5, sym_a, FETCH_N)
    df_b = _fetch_closed_bars(mt5, sym_b, FETCH_N)
    ref_frames = {p: _fetch_closed_bars(mt5, p, FETCH_N) for p in USD_REF_SYMBOLS}
    # Align all frames to a common latest CLOSED bar: a new bar forming between the
    # sequential per-symbol fetches must not leave them ending on different bars.
    common_last = min([df_a.index[-1], df_b.index[-1], *[f.index[-1] for f in ref_frames.values()]])
    df_a = df_a[df_a.index <= common_last]
    df_b = df_b[df_b.index <= common_last]
    ref_frames = {p: f[f.index <= common_last] for p, f in ref_frames.items()}
    _attach_usd_refs(df_a, ref_frames)
    _attach_usd_refs(df_b, ref_frames)
    written = runner.on_closed_bar(df_a, df_b)               # Target on change + heartbeat every cycle
    latest = str(df_a.index[-1]) if len(df_a) else "?"
    if written is not None:
        print(f"  PRODUCER_TARGET  seq={written.seq} state={written.state} "
              f"bar_ts={written.bar_ts} legs={[(l.symbol, l.side) for l in written.legs]}", flush=True)
    else:
        print(f"  PRODUCER_NOOP    latest_closed_bar={latest} (no state change / warmup)", flush=True)


# ---- offline validation / replay (no MT5, no bridge write) --------------- #
def _replay_csv(parsed: dict, sym_to_path: dict[str, str]) -> int:
    """OFFLINE: feed historical OHLC CSVs through the EXACT replay_fn the live loop
    uses, derive the target sequence, and assert the per_bar_record contract. Proves
    the mechanic emits a target sequence from plain OHLC + the usd_ref join. No MT5,
    no orders, no bridge writes."""
    replay_fn, sym_a, sym_b = _make_replay_fn(parsed)

    def _load(sym):
        if sym not in sym_to_path:
            raise SystemExit(f"--replay-csv missing CSV for required symbol {sym!r}")
        d = pd.read_csv(sym_to_path[sym], comment="#", parse_dates=["time"]).set_index("time").sort_index()
        return d[["open", "high", "low", "close"]].astype("float64").tail(REPLAY_TAIL)

    df_a, df_b = _load(sym_a), _load(sym_b)
    ref_frames = {p: _load(p) for p in USD_REF_SYMBOLS}
    _attach_usd_refs(df_a, ref_frames)
    _attach_usd_refs(df_b, ref_frames)
    print(f"  REPLAY_CSV  {sym_a}={len(df_a)} {sym_b}={len(df_b)} refs={[(p, len(f)) for p, f in ref_frames.items()]}  "
          f"common~{len(df_a.index.intersection(df_b.index))}  cols_a={list(df_a.columns)}", flush=True)

    records = replay_fn(df_a, df_b)
    print(f"  REPLAY_RECORDS  n={len(records)}", flush=True)
    if not records:
        print("  REPLAY_FAIL  mechanic emitted 0 per_bar_records (warmup too short / no data)", flush=True)
        return 1
    need = {"active_legs", "leg_0_symbol", "leg_0_side", "leg_0_lot",
            "leg_1_symbol", "leg_1_side", "leg_1_lot", "timestamp"}
    missing = need - set(records[-1].keys())
    if missing:
        print(f"  REPLAY_FAIL  per_bar_record missing keys: {sorted(missing)}", flush=True)
        return 1

    targets = target_sequence_from_records(records, BASKET_ID, n_legs=2)
    states = [(t.seq, t.state, str(t.bar_ts)) for t in targets]
    print(f"  REPLAY_TARGET_SEQUENCE  transitions={len(targets)}", flush=True)
    for s in states:
        print(f"      {s}", flush=True)
    print(f"  REPLAY_OK  per_bar_record contract satisfied; "
          f"sawIN={any(t.state=='IN' for t in targets)} sawFLAT={any(t.state=='FLAT' for t in targets)}",
          flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CADJPYUSDCHF V0 live-basket producer (Option 2, demo)")
    ap.add_argument("--once", action="store_true", help="run one live cycle then exit")
    ap.add_argument("--poll", type=float, default=POLL_SECONDS, help="seconds between live cycles")
    ap.add_argument("--replay-csv", nargs="+", metavar="SYM=PATH",
                    help="OFFLINE validation: SYM=PATH for each leg + USD_REF symbol (no MT5, no bridge)")
    args = ap.parse_args()

    parsed = parse_directive(DIRECTIVE_PATH)

    if args.replay_csv:
        sym_to_path = dict(kv.split("=", 1) for kv in args.replay_csv)
        return _replay_csv(parsed, sym_to_path)

    replay_fn, sym_a, sym_b = _make_replay_fn(parsed)
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  PRODUCER_START  basket={BASKET_ID}  signal_dir={SIGNAL_DIR}  legs=({sym_a},{sym_b})  "
          f"usd_refs={USD_REF_SYMBOLS}", flush=True)
    runner = StreamingBasketRunner(SIGNAL_DIR, BASKET_ID, replay_fn, n_legs=2)
    mt5 = _connect_mt5()
    try:
        while True:
            try:
                _run_cycle(runner, mt5, sym_a, sym_b)
            except Exception as e:                            # one bad cycle must not kill the loop
                print(f"  PRODUCER_CYCLE_ERROR  {type(e).__name__}: {e}", flush=True)
            if args.once:
                break
            time.sleep(args.poll)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
