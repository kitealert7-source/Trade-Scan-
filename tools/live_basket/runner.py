"""runner.py -- V0 Slice-1 SCRIPTED target emitter (deliberately thin).

NOT the real basket_pipeline runner (that integration is a later slice). It
emits a hand-authored sequence of desired states to the bridge so the bridge +
shim + reconcile convergence can be proven WITHOUT the research mechanic -- the
Slice-1 uncertainty is "do two processes converge on broker truth via
target-state", not "can apply() generate targets" (already evidenced).

Behaviour (the runner half of the contract):
  - APPEND-ON-CHANGE: a new target line is written only when the desired position
    changes (compared via semantic_key, never via target_hash -- the hash is a
    diagnostic stamp, not logic). `seq` is strictly increasing (this emitter uses
    a contiguous counter; gaps are contract-legal but not produced here).
  - HEARTBEAT EVERY STEP: the separate liveness file is written on every cycle,
    even when the target is unchanged, so runner-death detection keys on the
    heartbeat, not on target age (Review #4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tools.live_basket import bridge


class ScriptedRunner:
    """Thin Slice-1 runner: you feed it desired states; it maintains seq +
    append-on-change + the heartbeat. Stdlib-only, deterministic with injected
    timestamps."""

    def __init__(self, bridge_dir, basket_id: str, *, seq_start: int = 1):
        self.bridge_dir = Path(bridge_dir)
        self.basket_id = basket_id
        self._seq = int(seq_start)
        self._last_key: Optional[tuple] = None
        self._last_seq_written: Optional[int] = None

    def step(self, state: str, legs=(), *, bar_ts=None, emitted_at=None):
        """One runner cycle. Appends a target iff the desired position changed,
        and always writes the heartbeat. Returns the Target written, or None."""
        legs = list(legs)
        key = bridge.semantic_key(state, 0, legs)
        written = None
        if key != self._last_key:
            target = bridge.Target(
                basket_id=self.basket_id, seq=self._seq, state=state, legs=legs,
                epoch=0, bar_ts=bar_ts, emitted_at=emitted_at or bridge.utc_now_iso(),
            )
            bridge.append_jsonl_atomic(self.bridge_dir / bridge.TARGET_FILE, target.as_dict())
            self._last_key = key
            self._last_seq_written = self._seq
            self._seq += 1
            written = target
        bridge.write_heartbeat(
            self.bridge_dir, self.basket_id, bar_ts,
            beat_at=emitted_at, last_target_seq=self._last_seq_written,
        )
        return written


__all__ = ["ScriptedRunner"]
