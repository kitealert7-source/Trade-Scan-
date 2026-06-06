"""mock_broker.py -- injectable broker position source for V0 (no MT5).

The shim reads positions through a `read_positions` callable; in V0 this mock
supplies them, and tests mutate it to simulate fills, partials (one-leg orphan),
wrong-lot, wrong-side, and wrong-epoch states for the incoherent-classification
+ restart proofs. The same `read_positions` seam is where the real MT5 adapter
plugs in a later slice -- the mock IS the broker boundary, so nothing in the
reconcile path is "simulator-only".
"""
from __future__ import annotations

from tools.live_basket.reconcile import BrokerLeg


class MockBroker:
    """A tag-filtered position book for one basket. `read_positions()` is the
    seam the shim consumes; the rest are test/executor controls that mutate the
    book the way a real executor's fills would."""

    def __init__(self, legs=None):
        self._legs = list(legs or [])

    # --- the seam the shim consumes -------------------------------------- #
    def read_positions(self):
        return list(self._legs)

    # --- executor-style mutations (what a real fill would do) ------------ #
    def open_group(self, target):
        """Simulate a clean atomic fill of the target's legs at the target epoch."""
        self._legs = [BrokerLeg(lg.symbol, lg.side, float(lg.lot), int(target.epoch))
                      for lg in target.legs]

    def close_group(self):
        self._legs = []

    # --- fault injection for the incoherent/restart proofs --------------- #
    def set_legs(self, legs):
        self._legs = list(legs)

    def set_flat(self):
        self._legs = []

    def drop_one_leg(self):
        """Simulate an exit/entry partial -> a single naked leg (orphan)."""
        self._legs = self._legs[:-1]

    def corrupt_lot(self, factor=2.0):
        """Simulate a wrong-lot fill (different hedge ratio => different spread)."""
        if self._legs:
            head = self._legs[0]
            self._legs[0] = BrokerLeg(head.symbol, head.side, head.lot * factor, head.epoch)


__all__ = ["MockBroker"]
