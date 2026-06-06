"""loop.py -- V0 OPERATIONAL DRY LOOP (no MT5, mock broker).

Ties the streaming driver + the reconcile shim into the continuously-running
chain the proposal's V0 describes (two parties, one bridge), so the behaviour
that only appears under CONTINUOUS RUNNING -- convergence every cycle, restart
resilience, both-legs-fresh no-ops, bridge-file consistency -- is exercised end
to end, not just per component. The mock broker stands in at the `read_positions`
seam where the real MT5 adapter plugs in (P2). DRY: the shim only logs; a tiny
in-loop "executor" applies the would-be fill to the mock so the next cycle
converges -- exactly what the real shim + broker do live.

Still zero TS_Execution code and zero broker intelligence: the loop is pure
Trade_Scan-side orchestration over the proven bridge + driver + shim.
"""
from __future__ import annotations

from pathlib import Path

from tools.live_basket import bridge
from tools.live_basket.driver import StreamingBasketRunner
from tools.live_basket.mock_broker import MockBroker
from tools.live_basket.shim import run_once

_FLATTENING = ("CLOSE_GROUP", "FLATTEN_INCOHERENT")


def run_dry_session(dfA, dfB, replay_fn, bridge_dir, basket_id, *, n_legs=2,
                    fresh_mask=None, restart_at=None, broker=None):
    """Run the whole chain over a continuous bar stream (mock broker, DRY).

    Per closed bar: both-legs-fresh gate -> driver emits target -> shim reconciles
    -> the dry executor applies the would-be fill so the next cycle can converge.

      fresh_mask : optional list[bool]; a False entry models a non-fresh bar (a
                   leg's bar missing/stale) -> deterministic no-op that bar.
      restart_at : optional bar index at which to re-instantiate the driver
                   (simulated watchdog restart; it restores state from the bridge).

    Returns {"log", "broker", "driver"} for assertions.
    """
    bridge_dir = Path(bridge_dir)
    driver = StreamingBasketRunner(bridge_dir, basket_id, replay_fn, n_legs=n_legs)
    broker = broker if broker is not None else MockBroker()
    log = []

    for c in range(len(dfA)):
        if restart_at is not None and c == restart_at:
            driver = StreamingBasketRunner(bridge_dir, basket_id, replay_fn, n_legs=n_legs)  # restart
        if fresh_mask is not None and not fresh_mask[c]:
            continue  # both-legs-fresh gate -> deterministic no-op this bar

        driver.on_closed_bar(dfA.iloc[:c + 1], dfB.iloc[:c + 1])
        rec = run_once(bridge_dir, broker.read_positions)
        if rec is None:
            continue

        action = rec["action"]
        if action == "OPEN_GROUP":
            broker.open_group(bridge.read_latest_target(bridge_dir))
        elif action in _FLATTENING:
            broker.close_group()

        log.append({"bar": c, "decision": rec["decision"], "action": action,
                    "acted_on_seq": rec.get("acted_on_seq")})

    return {"log": log, "broker": broker, "driver": driver}


__all__ = ["run_dry_session"]
