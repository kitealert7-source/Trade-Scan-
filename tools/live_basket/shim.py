"""shim.py -- the stateless live-basket reconcile loop (V0, DRY).

Holds NO durable state: every cycle re-derives from (latest target on the bridge)
+ (tag-filtered broker positions). Restart == the first cycle with empty memory,
so there is no separate recovery / reconnect / repair mode (Review #3). DRY mode
logs the would-be action to executions.jsonl and NEVER touches the broker; a
later slice adds LIVE mode behind the same `read_positions` seam (mock now, MT5
later).

The shim is intentionally a set of functions, not an object -- statelessness is
the contract, and an object with fields invites someone to cache broker/target
state across cycles, which is exactly the split-brain failure the target-state
design removes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from tools.live_basket import bridge
from tools.live_basket.reconcile import classify

# action -> the DRY result label written to executions.jsonl
_DRY_RESULT = {
    "NOOP": "NOOP",
    "OPEN_GROUP": "WOULD_OPEN",
    "CLOSE_GROUP": "WOULD_CLOSE",
    "FLATTEN_INCOHERENT": "WOULD_FLATTEN",
}


def run_once(
    bridge_dir,
    read_positions: Callable[[], list],
    *,
    mode: str = "DRY",
    now: Callable[[], str] = bridge.utc_now_iso,
) -> dict | None:
    """One reconcile cycle. Reads the latest target + the (tag-filtered) broker
    positions, classifies, appends an execution record, and returns it. Returns
    None when no target has been written yet (nothing to reconcile to).

    Pure w.r.t. its own memory: calling it again IS a restart. In DRY mode it
    does not mutate the broker -- the caller/executor would apply the action.
    """
    target = bridge.read_latest_target(bridge_dir)
    if target is None:
        return None

    broker_legs = list(read_positions())
    decision = classify(target, broker_legs)

    rec = {
        "schema_version": bridge.SCHEMA_VERSION,
        "basket_id": target.basket_id,
        "acted_on_seq": target.seq,
        "epoch": target.epoch,
        "decision": decision.klass.value,
        "action": decision.action,
        "mode": mode,
        "observed": "FLAT" if not broker_legs else f"IN[{len(broker_legs)}]",
        "result": _DRY_RESULT[decision.action] if mode == "DRY" else "PENDING",
        "target_hash": target.hash,        # diagnostic correlation across files
        "at": now(),
        "detail": decision.reason,
    }
    bridge.append_jsonl_atomic(Path(bridge_dir) / bridge.EXECUTIONS_FILE, rec)
    return rec


def run_loop(
    bridge_dir,
    read_positions: Callable[[], list],
    *,
    mode: str = "DRY",
    poll_seconds: float = 1.0,
    max_cycles: int | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], str] = bridge.utc_now_iso,
) -> int:
    """Poll the bridge and reconcile every `poll_seconds`. Thin wrapper over
    run_once for the eventual process; tests drive run_once directly. Returns the
    number of cycles executed. `max_cycles` bounds it for tests; `sleep` is
    injectable (defaults to time.sleep) so it is non-blocking in tests."""
    if sleep is None:
        import time
        sleep = time.sleep
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        run_once(bridge_dir, read_positions, mode=mode, now=now)
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        sleep(poll_seconds)
    return cycles


__all__ = ["run_once", "run_loop"]
