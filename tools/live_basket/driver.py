"""driver.py -- V0 streaming basket runner: basket semantics -> target semantics.

The final link in the chain `research semantics -> streaming semantics -> target
semantics`. Reuses `basket_runner` + the recycle rule UNCHANGED; all new code is
this thin Trade_Scan-side wrapper that converts the mechanic's per-bar position
state into bridge Targets. Zero TS_Execution code, zero broker.

REFERENCE IMPLEMENTATION, NOT a production optimization
-------------------------------------------------------
On each closed bar this REPLAYS the whole prefix [0..C] through `basket_runner`
and reads the latest bar's state. That is O(N^2) over a session and is chosen
ONLY because correctness > efficiency for V0 (one basket, parity already proven,
zero broker). It makes the emitted target a PURE FUNCTION of the data -- no
incremental state to drift. Production would stream incrementally / over a
bounded window; do NOT defend the prefix-replay as architecture.

Target derivation -- the boundary-robust rule (no lag needed)
-------------------------------------------------------------
The Target is derived from the LATEST replayed bar's `active_legs` (+ per-leg
lot/side). This is correct at the boundary: a pending entry-approval dropped at
the latest bar (its fire-bar doesn't exist yet) does NOT change `active_legs`
there -- fills land two bars after approval -- and the re-run-from-history
re-completes that approval on the next bar. So emitting from the latest bar gives
target TRANSITIONS identical to batch (a 1-bar lag would instead SHIFT them). The
parity gate (test_basket_runner_streaming_parity) locks the `active_legs`
equality this relies on.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from tools.live_basket import bridge
from tools.live_basket.bridge import Leg, Target, semantic_key


def _derive_state(record: dict, n_legs: int = 2):
    """(state, legs) from one per_bar_record. `active_legs` is the position
    truth; for a 2-leg basket it is 0 (FLAT) or n_legs (IN). leg_k_side is the
    cycle-aware effective_direction (+1 long / -1 short)."""
    active = int(record.get("active_legs", 0) or 0)
    if active == 0:
        return "FLAT", []
    if active != n_legs:
        raise ValueError(
            f"derive_target: unexpected active_legs={active} for a {n_legs}-leg "
            f"basket (V0 expects 0 or {n_legs}). A partial/single-leg state is an "
            f"execution incoherence, not a desired target."
        )
    legs = [
        Leg(record[f"leg_{k}_symbol"],
            "long" if float(record[f"leg_{k}_side"]) > 0 else "short",
            float(record[f"leg_{k}_lot"]))
        for k in range(n_legs)
    ]
    return "IN", legs


def target_sequence_from_records(records, basket_id: str, *, n_legs: int = 2):
    """Append-on-change Target sequence derived from a per_bar_records list (the
    BATCH-side derivation). Each Target differs from the previous in desired
    position; envelope (seq/bar_ts) is informational."""
    out, prev_key, seq = [], None, 0
    for rec in records:
        state, legs = _derive_state(rec, n_legs)
        key = semantic_key(state, 0, legs)
        if key != prev_key:
            out.append(Target(basket_id, seq, state, legs, bar_ts=str(rec.get("timestamp"))))
            seq += 1
            prev_key = key
    return out


def stream_target_sequence(dfA, dfB, replay_fn: Callable, basket_id: str,
                           *, n_legs: int = 2, start: int = 0):
    """REFERENCE streaming simulation: for each closed bar C, replay [0..C] and
    emit the LATEST bar's derived state (append-on-change). Returns the target
    transition sequence a live driver would emit. `replay_fn(dfA_pre, dfB_pre)`
    returns that prefix's per_bar_records (the mechanic re-run). `start` skips the
    warmup region's empty replays (those emit no records, so the sequence is
    unchanged) -- purely a cost saver for the O(N^2) reference path."""
    n = len(dfA)
    out, prev_key, seq = [], None, 0
    for c in range(start, n):
        records = replay_fn(dfA.iloc[:c + 1], dfB.iloc[:c + 1])
        if not records:
            continue  # warmup region: mechanic emits no records yet
        state, legs = _derive_state(records[-1], n_legs)
        key = semantic_key(state, 0, legs)
        if key != prev_key:
            out.append(Target(basket_id, seq, state, legs, bar_ts=str(records[-1].get("timestamp"))))
            seq += 1
            prev_key = key
    return out


class StreamingBasketRunner:
    """Live driver: on each closed bar, replay the accumulated prefix, derive the
    latest bar's target, and append-on-change to the bridge (+ heartbeat every
    bar). Mechanic-agnostic via `replay_fn`. The prefix-replay is the reference
    implementation (see module docstring)."""

    def __init__(self, bridge_dir, basket_id: str, replay_fn: Callable, *, n_legs: int = 2):
        self.bridge_dir = Path(bridge_dir)
        self.basket_id = basket_id
        self.replay_fn = replay_fn
        self.n_legs = n_legs
        self._seq = 0
        self._last_key = None
        # Restart-clean: restore emission state from the bridge so a re-instantiated
        # driver (watchdog restart) continues the seq and does NOT re-emit the
        # current target. Fresh session (empty bridge) -> starts at seq 0. The
        # bridge IS the state; the driver restores from it (Review #3 spirit).
        latest = bridge.read_latest_target(self.bridge_dir)
        if latest is not None and latest.basket_id == basket_id:
            self._last_key = latest.key
            self._seq = int(latest.seq) + 1

    def on_closed_bar(self, dfA_prefix, dfB_prefix):
        """Process the accumulated frames after a bar closes. Returns the Target
        written this bar, or None (warmup / no change)."""
        records = self.replay_fn(dfA_prefix, dfB_prefix)
        if not records:
            return None
        rec = records[-1]
        bar_ts = str(rec.get("timestamp"))
        state, legs = _derive_state(rec, self.n_legs)
        key = semantic_key(state, 0, legs)
        written = None
        if key != self._last_key:
            t = Target(self.basket_id, self._seq, state, legs, bar_ts=bar_ts)
            bridge.append_jsonl_atomic(self.bridge_dir / bridge.TARGET_FILE, t.as_dict())
            self._seq += 1
            self._last_key = key
            written = t
        bridge.write_heartbeat(self.bridge_dir, self.basket_id, bar_ts, last_target_seq=self._seq - 1)
        return written


__all__ = [
    "_derive_state", "target_sequence_from_records", "stream_target_sequence",
    "StreamingBasketRunner",
]
