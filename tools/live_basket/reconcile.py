"""reconcile.py -- the broker-independent reconcile CORE for the live-basket shim.

PURE: given (latest target) + (tag-filtered broker positions) -> a Decision. No
I/O, no broker calls, stdlib-only -- so it is exhaustively unit-testable and
ports to the TS_Execution shim verbatim (the file format + this function ARE the
contract). The V0 vocabulary is exactly the ratified table:

    MATCH        actual == desired (or both FLAT)        -> NOOP
    NEED_OPEN    target IN,   broker flat                -> OPEN_GROUP
    NEED_CLOSE   target FLAT, broker non-empty           -> CLOSE_GROUP
    INCOHERENT   target IN, broker non-empty != desired  -> FLATTEN (reopen next
                 (partial / wrong side / wrong lot /        cycle; Review #3:
                  wrong epoch)                              never "complete" a
                                                            half-open basket, its
                                                            entry price is stale)

A position's identity is (symbol, side, lot, epoch) -- epoch recovered from the
order tag. Wrong lot is INCOHERENT, not MATCH: a different lot is a different
hedge ratio, i.e. a different spread than was backtested (Non-negotiable #3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from tools.live_basket.bridge import Target

_LOT_ROUND = 8


class ReconcileClass(str, Enum):
    MATCH = "MATCH"
    NEED_OPEN = "NEED_OPEN"
    NEED_CLOSE = "NEED_CLOSE"
    INCOHERENT = "INCOHERENT"


@dataclass(frozen=True)
class BrokerLeg:
    """A leg as seen on the broker, recovered from its order tag. (symbol, side,
    lot, epoch) make it self-identifying -- the statelessness linchpin."""
    symbol: str
    side: str
    lot: float
    epoch: int = 0


@dataclass(frozen=True)
class Decision:
    klass: ReconcileClass
    action: str                      # NOOP | OPEN_GROUP | CLOSE_GROUP | FLATTEN_INCOHERENT
    legs_to_open: tuple = ()         # tuple[Leg]
    legs_to_close: tuple = ()        # tuple[BrokerLeg]
    reason: str = ""


def _desired_set(target: Target):
    # desired leg epoch == the target's epoch (V0: always 0)
    return frozenset(
        (lg.symbol, lg.side, round(float(lg.lot), _LOT_ROUND), int(target.epoch))
        for lg in target.legs
    )


def _actual_set(broker_legs):
    return frozenset(
        (b.symbol, b.side, round(float(b.lot), _LOT_ROUND), int(b.epoch))
        for b in broker_legs
    )


def classify(target: Target, broker_legs) -> Decision:
    """Pure V0 reconcile classification. `broker_legs` = this basket's
    tag-filtered open positions (list[BrokerLeg])."""
    actual = list(broker_legs)

    if target.state == "FLAT":
        if not actual:
            return Decision(ReconcileClass.MATCH, "NOOP", reason="flat == flat")
        return Decision(
            ReconcileClass.NEED_CLOSE, "CLOSE_GROUP",
            legs_to_close=tuple(actual),
            reason=f"target FLAT, broker holds {len(actual)} leg(s)",
        )

    # target.state == "IN"
    if not actual:
        return Decision(
            ReconcileClass.NEED_OPEN, "OPEN_GROUP",
            legs_to_open=tuple(target.legs),
            reason="target IN, broker flat",
        )
    if _desired_set(target) == _actual_set(actual):
        return Decision(ReconcileClass.MATCH, "NOOP", reason="in == in")
    # non-empty, non-matching -> incoherent: flatten now, reopen cleanly next cycle
    return Decision(
        ReconcileClass.INCOHERENT, "FLATTEN_INCOHERENT",
        legs_to_close=tuple(actual),
        reason="broker legs != desired (partial / wrong side / lot / epoch)",
    )


__all__ = ["ReconcileClass", "BrokerLeg", "Decision", "classify"]
