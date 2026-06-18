"""basket_producer.py — GENERIC live-basket producer (Option 2, demo).

Onboarding a basket is a CONFIG exercise, not a code-copy: provide its promoted
descriptor (TradeScan_State/strategy_pool/<ID>/descriptor.json) + its directive,
then run:

    python tools/live_basket/basket_producer.py --basket <BASKET_ID> [--poll 60]

Everything basket-specific — legs, USD-reference pairs, timeframe, the bridge
signal dir — is DERIVED from the descriptor + directive at startup. No per-basket
code edit. Supersedes the hardcoded cadjpyusdchf_producer.py (kept until migration).

Offline validation (no MT5, no bridge writes):
    python tools/live_basket/basket_producer.py --basket <ID> --replay-csv SYM=PATH ...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Resolve Trade_Scan root so `tools.*` imports work regardless of cwd.
_TS_ROOT = Path(__file__).resolve().parents[2]          # .../Trade_Scan
if str(_TS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TS_ROOT))

from tools.pipeline_utils import parse_directive                       # noqa: E402
from tools.recycle_strategies import PineZRevArmedState, PineZRevLegStrategy  # noqa: E402
from tools.basket_pipeline import run_basket_pipeline                   # noqa: E402
from tools.live_basket import demo_outcome_ledger as _dol               # noqa: E402
from tools.live_basket.driver import (                                  # noqa: E402
    StreamingBasketRunner, target_sequence_from_records,
)
from tools.live_basket import producer_rate_telemetry as _prt           # noqa: E402

_TRADESCAN_STATE = _TS_ROOT.parent / "TradeScan_State"
_DIRECTIVES_DIR = _TS_ROOT / "backtest_directives" / "completed"

# directive timeframe token -> MT5 TIMEFRAME_* attribute name
_TF_MAP = {
    "1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1",
}

DEFAULT_RUN_ID = "DEMOPRODV0"      # provenance stamp threaded into per_bar_records
DEFAULT_FETCH_N = 500              # >> 2*n_window warmup; bounds the O(N^2) replay cost
DEFAULT_POLL_SECONDS = 60          # < 300s shim heartbeat-staleness guard
REPLAY_TAIL = 1500                 # offline validation: cap bars for bounded runtime
# Daily-regime staleness threshold (calendar days). The screener reclassifies
# the 1d/252 cointegration regime daily; if the newest daily as_of is more than
# this many days behind the latest 15m bar, the regime is STALE -> we HOLD the
# last-known value (ffill keeps it) and warn, but do NOT flatten on the miss.
# 5d absorbs a weekend + a couple of missed screener runs without crying wolf.
COINT_REGIME_STALE_DAYS = 5


# ---- USD-reference derivation (inlined to keep the live producer dependency-light;
#      mirrors tools/basket_data_loader._required_ref_pairs — drift-checked by tests). #
_CCY_TO_USD_PAIR = {
    "EUR": "EURUSD", "GBP": "GBPUSD", "AUD": "AUDUSD", "NZD": "NZDUSD",
    "JPY": "USDJPY", "CHF": "USDCHF", "CAD": "USDCAD",
}


def _split_pair_ccys(symbol: str) -> tuple[str, str]:
    if len(symbol) != 6:
        return ("", "")
    return symbol[:3].upper(), symbol[3:].upper()


def _required_ref_pairs(trade_symbols: list[str]) -> list[str]:
    """USD-anchored pairs needed to convert each leg's currencies to USD, excluding
    any pair that is itself a trade leg (self-reference)."""
    needed: set[str] = set()
    for sym in trade_symbols:
        base, quote = _split_pair_ccys(sym)
        for ccy in (base, quote):
            if ccy and ccy != "USD" and ccy in _CCY_TO_USD_PAIR:
                ref = _CCY_TO_USD_PAIR[ccy]
                if ref not in trade_symbols:
                    needed.add(ref)
    return sorted(needed)


# ---- per-basket config, derived from the promoted descriptor + directive -------- #
@dataclass(frozen=True)
class BasketConfig:
    basket_id: str
    directive_id: str
    directive_path: Path
    parsed: dict
    legs: list
    sym_a: str
    sym_b: str
    mt5_tf_attr: str
    usd_ref_symbols: tuple
    signal_dir: Path
    run_id: str
    fetch_n: int
    # Daily cointegration regime lookback (252 / 504) from the directive's
    # basket.cointegration_join.lookback_days, or None when the directive does
    # not configure a join (regime gate then has no source -> column omitted).
    coint_lookback_days: int | None = None


def _descriptor_path(basket_id: str) -> Path:
    return _TRADESCAN_STATE / "strategy_pool" / basket_id / "descriptor.json"


def _timeframe_attr(parsed: dict) -> str:
    tf = parsed.get("timeframe") or parsed.get("test", {}).get("timeframe")
    if not tf:
        raise SystemExit("directive has no timeframe")
    if tf not in _TF_MAP:
        raise SystemExit(f"unsupported timeframe {tf!r}; known {sorted(_TF_MAP)}")
    return _TF_MAP[tf]


def derive_basket_config(basket_id: str, *, run_id: str = DEFAULT_RUN_ID,
                         fetch_n: int = DEFAULT_FETCH_N) -> BasketConfig:
    """Resolve everything basket-specific from the promoted descriptor + directive.

    This is the whole parameterization: descriptor -> directive_id -> directive ->
    legs/timeframe -> USD-refs + signal dir. Pure (no MT5); unit-tested for
    equivalence against the legacy hardcoded producer.
    """
    dpath = _descriptor_path(basket_id)
    if not dpath.exists():
        raise SystemExit(f"no promoted descriptor for basket {basket_id!r}: {dpath}")
    desc = json.loads(dpath.read_text(encoding="utf-8"))
    directive_id = desc["directive_id"]
    directive_path = _DIRECTIVES_DIR / (directive_id + ".txt")
    if not directive_path.exists():
        raise SystemExit(f"directive not found for {basket_id!r}: {directive_path}")
    parsed = parse_directive(directive_path)
    legs = parsed["basket"]["legs"]
    if len(legs) != 2:
        raise SystemExit(f"basket {basket_id!r} has {len(legs)} legs; the V0 producer supports exactly 2")
    leg_syms = [leg["symbol"] for leg in legs]
    cj = (parsed["basket"].get("cointegration_join") or {})
    coint_lookback_days = cj.get("lookback_days")
    return BasketConfig(
        basket_id=basket_id,
        directive_id=directive_id,
        directive_path=directive_path,
        parsed=parsed,
        legs=legs,
        sym_a=leg_syms[0],
        sym_b=leg_syms[1],
        mt5_tf_attr=_timeframe_attr(parsed),
        usd_ref_symbols=tuple(_required_ref_pairs(leg_syms)),
        signal_dir=_TRADESCAN_STATE / "TS_SIGNAL_STATE" / "h2_live" / basket_id,
        run_id=run_id,
        fetch_n=fetch_n,
        coint_lookback_days=coint_lookback_days,
    )


# ---- PRODUCER_START banner: resolved strategy params --------------------------- #
# Key recycle-rule params echoed in the PRODUCER_START banner so the running
# strategy config -- above all z_entry -- is auditable from the log alone, with
# no inferring from PID start time + the directive file (the 2026-06-11 live
# z_entry 2.0->2.5 switch was un-confirmable from the producer log). Defaults
# MIRROR the pine_ratio_zrev family in basket_pipeline._instantiate_rule; a key
# the directive omits is rendered with a `(default)` marker so a silently-
# defaulted value stands out. z_entry has NO downstream default (basket_pipeline
# now RAISES on a missing key) -> an omitted z_entry renders `(UNSET!)`, flagging
# a directive that will fail on the first cycle.
_BANNER_PARAM_DEFAULTS: tuple = (
    ("z_entry", None),                  # required downstream; no silent default
    ("n_window", 100),
    ("entry_mode", "centered"),
    ("coint_break_exit", False),
    ("entry_fill_timing", "next_bar_open"),
)


def _resolved_key_params(parsed: dict) -> str:
    """Render the resolved key recycle-rule params for the PRODUCER_START banner.

    Pulls from parsed['basket']['recycle_rule'] (name@version + params). Each
    listed key shows the directive's value, or -- when the directive omits it --
    the default basket_pipeline._instantiate_rule will apply, tagged `(default)`.
    z_entry has no downstream default, so an omitted z_entry renders `(UNSET!)`.
    """
    rule = (parsed.get("basket", {}) or {}).get("recycle_rule", {}) or {}
    params = rule.get("params") or {}
    name = rule.get("name", "?")
    version = rule.get("version", 1)
    toks = []
    for key, default in _BANNER_PARAM_DEFAULTS:
        if key in params:
            toks.append(f"{key}={params[key]}")
        elif default is None:
            toks.append(f"{key}=(UNSET!)")
        else:
            toks.append(f"{key}={default}(default)")
    return f"rule={name}@{version} params=[{' '.join(toks)}]"


# ---- mechanic wiring (generic; reads from cfg) --------------------------------- #
def _build_leg_strategies(parsed: dict) -> dict:
    """FRESH leg_strategies with a FRESH shared armed-state per replay call (the entry
    protocol is a 2-bar state machine shared across legs; reuse would pollute it)."""
    shared = PineZRevArmedState()
    # ZCRS v2 (2026-06-10): entry-fill timing from the directive. Default
    # next_bar_open (N+2); current_bar_open (N+1) adopted for the deployed
    # baskets per the canonical EFTN1 sweep (Pine-faithful, 1 bar earlier).
    et = (parsed["basket"].get("recycle_rule", {}).get("params") or {}).get("entry_fill_timing", "next_bar_open")
    return {
        leg["symbol"]: PineZRevLegStrategy(
            symbol=leg["symbol"],
            position_direction=(+1 if leg["direction"] == "long" else -1),
            armed_state=shared,
            execution_timing=et,
        )
        for leg in parsed["basket"]["legs"]
    }


# Diagnostic ledger (demo_tradelevel_v1) state — single producer process per basket.
# The replay returns only per_bar_records; stash recycle_events + per_leg_trades
# so _run_cycle can emit the per-cycle ledger with NO second engine call.
_DIAG_STASH: dict = {"recycle_events": [], "per_leg_trades": {}}
_LEDGER_KEYS: set = set()
_SCREENER_CON = None


def _make_replay_fn(cfg: BasketConfig):
    def replay_fn(df_a_prefix: pd.DataFrame, df_b_prefix: pd.DataFrame):
        # PURITY: copy frames (run mutates leg.df) + fresh leg_strategies each call.
        leg_data = {cfg.sym_a: df_a_prefix.copy(), cfg.sym_b: df_b_prefix.copy()}
        # D3 live cointegration-regime gate: join the DAILY 1d/lookback regime
        # (ffill-projected onto the 15m grid) onto BOTH legs as `coint_regime`.
        # One local SQLite read per cycle -- no MT5, no broker rate. The rule's
        # coint_break_exit gate reads this column; fail-safe 'broken' when absent.
        regime_daily = _fetch_daily_regime(cfg)
        for sym in (cfg.sym_a, cfg.sym_b):
            _attach_coint_regime(leg_data[sym], regime_daily, basket_id=cfg.basket_id)
        result = run_basket_pipeline(
            cfg.parsed, leg_data, _build_leg_strategies(cfg.parsed),
            run_id=cfg.run_id, directive_id=cfg.directive_id,
        )
        _DIAG_STASH["recycle_events"] = list(result.recycle_events)
        _DIAG_STASH["per_leg_trades"] = result.per_leg_trades
        return result.per_bar_records
    return replay_fn


def _attach_usd_refs(leg_df: pd.DataFrame, ref_frames: dict) -> pd.DataFrame:
    for pair, ref_df in ref_frames.items():
        leg_df[f"usd_ref_{pair}_close"] = ref_df["close"].reindex(leg_df.index, method="ffill")
    return leg_df


# ---- live cointegration-regime join (D3 gate; SQLite read, no MT5/broker rate) -- #
def _fetch_daily_regime(cfg: BasketConfig) -> pd.Series | None:
    """Daily 1d/<lookback> `coint_regime` series for this basket's pair.

    REUSES basket_data_loader.load_cointegration_factors_from_db (the same SQL
    the BACKTEST loader runs) -- no reimplemented query. Returns a date-indexed
    Series of regime strings, or None when no join is configured / the pair is
    absent / the DB is missing. None means 'no regime source' -> the caller
    fail-safes the column to 'broken' (never enter a spread we can't classify).

    A local SQLite read: no MT5 call, no broker rate consumed."""
    if cfg.coint_lookback_days is None:
        return None  # directive configured no cointegration_join -> no regime source
    try:
        from tools.basket_data_loader import load_cointegration_factors_from_db
        daily = load_cointegration_factors_from_db(
            cfg.sym_a, cfg.sym_b, int(cfg.coint_lookback_days),
        )
    except FileNotFoundError:
        print("  PRODUCER_REGIME_WARN  cointegration.db missing -> regime unavailable "
              "(fail-safe 'broken', no entries)", flush=True)
        return None
    except KeyError:
        print(f"  PRODUCER_REGIME_WARN  pair ({cfg.sym_a},{cfg.sym_b}) not in DB universe "
              "-> regime unavailable (fail-safe 'broken', no entries)", flush=True)
        return None
    if daily is None or daily.empty or "coint_regime" not in daily.columns:
        return None
    return daily["coint_regime"].sort_index()


def _attach_coint_regime(leg_df: pd.DataFrame, regime_daily: pd.Series | None,
                         *, basket_id: str = "") -> pd.DataFrame:
    """ffill-project the DAILY regime onto the leg's intraday (15m) bar index as
    the `coint_regime` column -- mirrors basket_data_loader.py:843-851 (reindex
    method='ffill'). Staleness / fail-safe policy (D3):

      * No regime source at all (regime_daily is None/empty) -> the ENTIRE column
        is 'broken' (fail safe to NOT entering -- never trade a spread we cannot
        classify).
      * Regime present but STALE (newest daily as_of > COINT_REGIME_STALE_DAYS
        behind the latest bar) -> HOLD the last-known regime (ffill already does
        this) and WARN. NO spurious flatten on a transient miss.
      * Bars BEFORE the first daily as_of (no prior classification) -> 'broken'
        (same fail-safe; ffill leaves them NaN, which we fill explicitly)."""
    idx = leg_df.index
    if regime_daily is None or len(regime_daily) == 0:
        leg_df["coint_regime"] = "broken"   # fail-safe: unclassifiable -> no entry
        return leg_df
    projected = regime_daily.reindex(idx, method="ffill")
    # Bars earlier than the first daily classification -> fail-safe 'broken'.
    projected = projected.where(projected.notna(), other="broken")
    leg_df["coint_regime"] = projected.astype("object")
    # Staleness warning (HOLD policy: ffill already carried the last value forward;
    # we only surface a warning, never alter behaviour on a transient miss).
    if len(idx) > 0:
        newest_asof = regime_daily.index.max()
        latest_bar = idx.max()
        age_days = (latest_bar.normalize() - newest_asof.normalize()).days
        if age_days > COINT_REGIME_STALE_DAYS:
            print(f"  PRODUCER_REGIME_WARN  {basket_id} daily regime STALE: newest "
                  f"as_of={newest_asof.date()} is {age_days}d behind latest bar "
                  f"{latest_bar.date()}; HOLDING last-known regime "
                  f"({regime_daily.iloc[-1]!r})", flush=True)
    return leg_df


# ---- MT5 bar reader (Option-2: own connection, OHLC only) ---------------------- #
def _connect_mt5():
    import MetaTrader5 as mt5  # local import: the only MT5 dependency
    _prt.record("initialize")
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    _prt.record("account_info")
    acct = mt5.account_info()
    if acct is None:
        mt5.shutdown()
        raise RuntimeError("MT5 account_info() is None -- terminal not logged in")
    print(f"  PRODUCER_MT5_OK  login={acct.login} server={acct.server} trade_mode={acct.trade_mode}",
          flush=True)
    return mt5


def _fetch_closed_bars(mt5, symbol: str, count: int, tf_attr: str) -> pd.DataFrame:
    _prt.record("copy_rates_from_pos")   # measure-only account-rate telemetry (no behaviour change)
    rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, tf_attr), 0, count)
    if rates is None or len(rates) < 2:
        n = "None" if rates is None else len(rates)
        raise RuntimeError(f"copy_rates_from_pos({symbol}) returned {n} rows; last_error={mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.DatetimeIndex(pd.to_datetime(df["time"], unit="s"), name="time")
    df = df[["open", "high", "low", "close"]].astype("float64")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.iloc[:-1]   # drop the forming bar (newest, after sort)


def _run_cycle(runner: StreamingBasketRunner, mt5, cfg: BasketConfig):
    df_a = _fetch_closed_bars(mt5, cfg.sym_a, cfg.fetch_n, cfg.mt5_tf_attr)
    df_b = _fetch_closed_bars(mt5, cfg.sym_b, cfg.fetch_n, cfg.mt5_tf_attr)
    ref_frames = {p: _fetch_closed_bars(mt5, p, cfg.fetch_n, cfg.mt5_tf_attr) for p in cfg.usd_ref_symbols}
    common_last = min([df_a.index[-1], df_b.index[-1], *[f.index[-1] for f in ref_frames.values()]])
    df_a = df_a[df_a.index <= common_last]
    df_b = df_b[df_b.index <= common_last]
    ref_frames = {p: f[f.index <= common_last] for p, f in ref_frames.items()}
    _attach_usd_refs(df_a, ref_frames)
    _attach_usd_refs(df_b, ref_frames)
    written = runner.on_closed_bar(df_a, df_b)
    if written is not None:
        print(f"  PRODUCER_TARGET  seq={written.seq} state={written.state} "
              f"bar_ts={written.bar_ts} legs={[(l.symbol, l.side) for l in written.legs]}", flush=True)
    else:
        latest = str(df_a.index[-1]) if len(df_a) else "?"
        print(f"  PRODUCER_NOOP    latest_closed_bar={latest} (no state change / warmup)", flush=True)

    # Diagnostic ledger (demo_tradelevel_v1): emit any newly-completed cycles.
    # Wrapped — a ledger failure must NEVER break signal generation.
    try:
        recs = _dol.assemble_cycles(
            _DIAG_STASH["recycle_events"], _DIAG_STASH["per_leg_trades"],
            basket_id=cfg.basket_id, epoch=getattr(cfg, "epoch", 0))
        n = _dol.emit_new(cfg.signal_dir / "DemoOutcomeLedger.jsonl", recs, _LEDGER_KEYS,
                          screener_con=_SCREENER_CON, sym_a=cfg.sym_a, sym_b=cfg.sym_b)
        if n:
            print(f"  PRODUCER_LEDGER  +{n} cycle(s) -> DemoOutcomeLedger.jsonl", flush=True)
    except Exception as e:
        print(f"  PRODUCER_LEDGER_ERROR  {type(e).__name__}: {e}", flush=True)


# ---- offline validation / replay (no MT5, no bridge write) --------------------- #
def _replay_csv(cfg: BasketConfig, sym_to_path: dict) -> int:
    replay_fn = _make_replay_fn(cfg)

    def _load(sym):
        if sym not in sym_to_path:
            raise SystemExit(f"--replay-csv missing CSV for required symbol {sym!r}")
        d = pd.read_csv(sym_to_path[sym], comment="#", parse_dates=["time"]).set_index("time").sort_index()
        return d[["open", "high", "low", "close"]].astype("float64").tail(REPLAY_TAIL)

    df_a, df_b = _load(cfg.sym_a), _load(cfg.sym_b)
    ref_frames = {p: _load(p) for p in cfg.usd_ref_symbols}
    _attach_usd_refs(df_a, ref_frames)
    _attach_usd_refs(df_b, ref_frames)
    print(f"  REPLAY_CSV  {cfg.sym_a}={len(df_a)} {cfg.sym_b}={len(df_b)} "
          f"refs={[(p, len(f)) for p, f in ref_frames.items()]}", flush=True)

    records = replay_fn(df_a, df_b)
    print(f"  REPLAY_RECORDS  n={len(records)}", flush=True)
    if not records:
        print("  REPLAY_FAIL  mechanic emitted 0 per_bar_records (warmup too short / no data)", flush=True)
        return 1
    targets = target_sequence_from_records(records, cfg.basket_id, n_legs=2)
    print(f"  REPLAY_TARGET_SEQUENCE  transitions={len(targets)}", flush=True)
    for t in targets:
        print(f"      ({t.seq}, {t.state}, {t.bar_ts})", flush=True)
    print(f"  REPLAY_OK  sawIN={any(t.state == 'IN' for t in targets)} "
          f"sawFLAT={any(t.state == 'FLAT' for t in targets)}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generic live-basket producer (Option 2, demo)")
    ap.add_argument("--basket", required=True,
                    help="promoted basket id (descriptor in TradeScan_State/strategy_pool/<ID>/)")
    ap.add_argument("--once", action="store_true", help="run one live cycle then exit")
    ap.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS, help="seconds between live cycles")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="provenance stamp")
    ap.add_argument("--fetch-n", type=int, default=DEFAULT_FETCH_N, help="bars fetched per cycle")
    ap.add_argument("--replay-csv", nargs="+", metavar="SYM=PATH",
                    help="OFFLINE validation: SYM=PATH for each leg + USD_REF symbol (no MT5, no bridge)")
    args = ap.parse_args()

    cfg = derive_basket_config(args.basket, run_id=args.run_id, fetch_n=args.fetch_n)

    if args.replay_csv:
        return _replay_csv(cfg, dict(kv.split("=", 1) for kv in args.replay_csv))

    cfg.signal_dir.mkdir(parents=True, exist_ok=True)
    print(f"  PRODUCER_START  basket={cfg.basket_id}  signal_dir={cfg.signal_dir}  "
          f"legs=({cfg.sym_a},{cfg.sym_b})  usd_refs={cfg.usd_ref_symbols}  tf={cfg.mt5_tf_attr}  "
          f"{_resolved_key_params(cfg.parsed)}", flush=True)
    runner = StreamingBasketRunner(cfg.signal_dir, cfg.basket_id, _make_replay_fn(cfg), n_legs=2)
    # Diagnostic ledger: seed dedup keys (survive restart) + open read-only screener DB.
    global _LEDGER_KEYS, _SCREENER_CON
    _LEDGER_KEYS = _dol.seed_keys(cfg.signal_dir / "DemoOutcomeLedger.jsonl")
    try:
        import sqlite3
        from tools.cointegration_db import SQLITE_DB
        _SCREENER_CON = sqlite3.connect(f"file:{SQLITE_DB}?mode=ro", uri=True)
        print(f"  PRODUCER_LEDGER  schema={_dol.SCHEMA_VERSION} seeded={len(_LEDGER_KEYS)} cycle(s)", flush=True)
    except Exception as e:
        print(f"  PRODUCER_LEDGER  screener DB unavailable ({e}); snapshots will be null", flush=True)
        _SCREENER_CON = None
    mt5 = _connect_mt5()
    _prt.start_telemetry(cfg.basket_id)   # measure-only MT5 rate telemetry -> producer.log
    try:
        while True:
            try:
                _run_cycle(runner, mt5, cfg)
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
