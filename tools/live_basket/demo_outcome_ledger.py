"""demo_outcome_ledger.py — per-cycle diagnostic ledger for the live demo (2026-06-10).

Captures ONLY what MT5 cannot reconstruct: the strategy's signal context
(z at trigger/fill/exit, z-excursion, hedge ratio, lots, the cointegration
snapshot at entry & exit). MT5 stays the authoritative outcome source
(fills/P&L/commission/swap) — join by (magic, epoch, time). See
outputs/experiments/ for the design rationale ("Future Tony" diagnostic lens).

schema: demo_tradelevel_v1 — intentionally smaller than backtest tradelevel but
structurally compatible. Anchored on epoch.
"""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA_VERSION = "demo_tradelevel_v1"


def _screener_snapshot(con, sym_a: str, sym_b: str, as_of_date: str) -> dict:
    """Latest 252d cointegration row at-or-before as_of_date for the pair (either
    leg order). Pins what the screener 'saw' at the cycle boundary; `as_of` exposes
    any staleness (e.g. a missed daily refresh)."""
    from tools.cointegration_db import TABLE_NAME
    q = (f"SELECT as_of, adf_pvalue, half_life_days, regime, current_zscore "
         f"FROM {TABLE_NAME} WHERE pair_a=? AND pair_b=? AND lookback_days=252 "
         f"AND as_of<=? ORDER BY as_of DESC LIMIT 1")
    for a, b in ((sym_a, sym_b), (sym_b, sym_a)):
        r = con.execute(q, (a, b, as_of_date)).fetchone()
        if r:
            return {"as_of": r[0], "adf_pvalue": r[1], "half_life": r[2],
                    "daily_regime": r[3], "daily_z": r[4]}
    return {"as_of": None, "adf_pvalue": None, "half_life": None,
            "daily_regime": None, "daily_z": None}


def assemble_cycles(recycle_events, per_leg_trades, *, basket_id, epoch) -> list[dict]:
    """Pair BASKET_OPEN + CYCLE_Z_DIAG (k-th open ↔ k-th exit) into completed-cycle
    records. The trailing unmatched BASKET_OPEN (open, not yet exited) is skipped."""
    opens = [e for e in recycle_events if e.get("action") == "BASKET_OPEN"]
    zdiags = [e for e in recycle_events if e.get("action") == "CYCLE_Z_DIAG"]
    # index per-leg enriched trades by exit timestamp (the cycle exit bar)
    by_exit: dict = {}
    for sym, trs in (per_leg_trades or {}).items():
        for t in trs:
            by_exit.setdefault(str(t.get("exit_timestamp")), []).append((sym, t))
    recs = []
    for k in range(min(len(opens), len(zdiags))):
        o, z = opens[k], zdiags[k]
        exit_ts = str(z.get("bar_ts"))
        legs = [{
            "symbol": sym, "exit_source": t.get("exit_source"),
            "mae_r": t.get("mae_r"), "mfe_r": t.get("mfe_r"),
            "atr_entry": t.get("atr_entry"), "r_multiple": t.get("r_multiple"),
            "notional_usd": t.get("notional_usd"),
        } for sym, t in by_exit.get(exit_ts, [])]
        recs.append({
            "schema_version": SCHEMA_VERSION,
            "basket_id": basket_id, "epoch": epoch,
            "entry_bar_ts": str(o.get("bar_ts")), "exit_bar_ts": exit_ts,
            "direction": o.get("direction"),
            "entry_z": o.get("entry_z"),         # the TRIGGER z (hypothesis 1)
            "entry_fill_z": o.get("entry_fill_z"),  # fill z (hypothesis 5: in-z lag)
            "exit_z": z.get("exit_z"),
            "z_lo": z.get("z_lo"), "z_hi": z.get("z_hi"),
            "hedge_ratio": o.get("entry_r_bar"),
            "lots": o.get("entry_lots"),
            "legs": legs,
        })
    return recs


def seed_keys(ledger_path) -> set:
    """Read existing ledger entry_bar_ts keys (dedup across producer restarts)."""
    keys: set = set()
    p = Path(ledger_path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                keys.add(json.loads(line).get("entry_bar_ts"))
            except Exception:
                pass
    return keys


def emit_new(ledger_path, recs, logged_keys, *, screener_con=None,
             sym_a=None, sym_b=None) -> int:
    """Append cycles not already logged (dedup by entry_bar_ts). Screener snapshot
    attached only to NEW cycles (avoid re-querying the DB for old ones)."""
    new = [r for r in recs if r["entry_bar_ts"] not in logged_keys]
    if screener_con is not None and sym_a and sym_b:
        for r in new:
            r["screener_entry"] = _screener_snapshot(screener_con, sym_a, sym_b, r["entry_bar_ts"][:10])
            r["screener_exit"] = _screener_snapshot(screener_con, sym_a, sym_b, r["exit_bar_ts"][:10])
    p = Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")
            logged_keys.add(r["entry_bar_ts"])
    return len(new)
