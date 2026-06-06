"""Reconcile-core + dry-convergence tests for the V0 live-basket shim.

These are the architecture-critical proofs for Slice 1 -- they answer the one
question that actually carried risk: *can two parties converge on broker truth
using target-state, and recover from restart / incoherent states?* The runner
and shim share ONLY the bridge files (a tmp dir); the broker is a mock behind the
`read_positions` seam. No MT5, no basket_pipeline.
"""
from __future__ import annotations

import pytest

from tools.live_basket import bridge
from tools.live_basket.bridge import Leg, Target
from tools.live_basket.mock_broker import MockBroker
from tools.live_basket.reconcile import BrokerLeg, ReconcileClass, classify
from tools.live_basket.runner import ScriptedRunner
from tools.live_basket.shim import run_once

_LEGS = [Leg("EURUSD", "long", 0.02), Leg("USDJPY", "short", 0.01)]


def _broker_match():
    return [BrokerLeg("EURUSD", "long", 0.02, 0), BrokerLeg("USDJPY", "short", 0.01, 0)]


# --- pure classification (the whole V0 vocabulary) ----------------------- #

def test_flat_flat_is_match():
    d = classify(Target("B", 1, "FLAT", []), [])
    assert d.klass is ReconcileClass.MATCH and d.action == "NOOP"


def test_flat_with_legs_needs_close():
    d = classify(Target("B", 1, "FLAT", []), _broker_match())
    assert d.klass is ReconcileClass.NEED_CLOSE and d.action == "CLOSE_GROUP"
    assert len(d.legs_to_close) == 2


def test_in_flat_needs_open():
    d = classify(Target("B", 1, "IN", _LEGS), [])
    assert d.klass is ReconcileClass.NEED_OPEN and d.action == "OPEN_GROUP"
    assert len(d.legs_to_open) == 2


def test_in_matching_is_match():
    d = classify(Target("B", 1, "IN", _LEGS), _broker_match())
    assert d.klass is ReconcileClass.MATCH and d.action == "NOOP"


def test_in_one_leg_is_incoherent():
    d = classify(Target("B", 1, "IN", _LEGS), _broker_match()[:1])
    assert d.klass is ReconcileClass.INCOHERENT and d.action == "FLATTEN_INCOHERENT"


def test_in_wrong_lot_is_incoherent():
    bad = [BrokerLeg("EURUSD", "long", 0.04, 0), BrokerLeg("USDJPY", "short", 0.01, 0)]
    assert classify(Target("B", 1, "IN", _LEGS), bad).klass is ReconcileClass.INCOHERENT


def test_in_wrong_side_is_incoherent():
    bad = [BrokerLeg("EURUSD", "short", 0.02, 0), BrokerLeg("USDJPY", "short", 0.01, 0)]
    assert classify(Target("B", 1, "IN", _LEGS), bad).klass is ReconcileClass.INCOHERENT


def test_in_wrong_epoch_is_incoherent():
    # a stale-instance position (epoch 0) when a future target wants epoch N would
    # be incoherent. V0 targets are epoch 0, so simulate the mismatch directly on
    # the broker side to prove the match-key includes epoch.
    stale = [BrokerLeg("EURUSD", "long", 0.02, 1), BrokerLeg("USDJPY", "short", 0.01, 1)]
    assert classify(Target("B", 1, "IN", _LEGS), stale).klass is ReconcileClass.INCOHERENT


# --- dry end-to-end convergence (runner + shim via the file bridge) ------ #

def _drive(bridge_dir, broker, clk):
    """One shim cycle with a deterministic clock; returns (decision, result)."""
    rec = run_once(bridge_dir, broker.read_positions, now=lambda: next(clk))
    return rec["decision"], rec["result"]


def test_dry_convergence_flat_in_flat(tmp_path):
    clk = iter(f"2026-06-05T14:00:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()

    runner.step("FLAT", emitted_at=next(clk))
    assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")

    tgt = runner.step("IN", _LEGS, emitted_at=next(clk))
    assert _drive(tmp_path, broker, clk) == ("NEED_OPEN", "WOULD_OPEN")
    broker.open_group(tgt)                                   # executor fills
    assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")   # converged

    runner.step("FLAT", emitted_at=next(clk))
    assert _drive(tmp_path, broker, clk) == ("NEED_CLOSE", "WOULD_CLOSE")
    broker.close_group()
    assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")   # converged

    # the bridge accumulated exactly the 3 desired-state changes (append-on-change)
    assert [t.state for t in bridge.read_all_targets(tmp_path)] == ["FLAT", "IN", "FLAT"]


def test_restart_is_stateless_no_double_open(tmp_path):
    """After an open converges, a FRESH run_once (== a restart with empty memory)
    must NOT re-open -- it re-derives MATCH from latest target + broker truth."""
    clk = iter(f"2026-06-05T14:01:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()
    tgt = runner.step("IN", _LEGS, emitted_at=next(clk))
    assert _drive(tmp_path, broker, clk) == ("NEED_OPEN", "WOULD_OPEN")
    broker.open_group(tgt)
    # three independent "restarts" -- each is just another stateless call
    for _ in range(3):
        assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")


def test_restart_midsequence_recovers_from_broker_truth(tmp_path):
    """Open is filled but the shim 'dies' before it ever saw the match; on restart
    it reconciles to broker truth (MATCH), never double-sends."""
    clk = iter(f"2026-06-05T14:02:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()
    tgt = runner.step("IN", _LEGS, emitted_at=next(clk))
    broker.open_group(tgt)                       # filled out-of-band
    # first cycle the (restarted) shim ever runs:
    assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")


def test_incoherent_one_leg_flattens_then_reopens(tmp_path):
    """One-leg orphan under an IN target -> FLATTEN; after the executor flattens,
    the next cycles reopen cleanly and converge (Review #3 flatten->re-converge)."""
    clk = iter(f"2026-06-05T14:03:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()
    tgt = runner.step("IN", _LEGS, emitted_at=next(clk))
    broker.open_group(tgt)
    assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")

    broker.drop_one_leg()                         # exit/entry partial -> naked leg
    assert _drive(tmp_path, broker, clk) == ("INCOHERENT", "WOULD_FLATTEN")
    broker.set_flat()                             # executor flattens
    assert _drive(tmp_path, broker, clk) == ("NEED_OPEN", "WOULD_OPEN")
    broker.open_group(tgt)                         # clean reopen
    assert _drive(tmp_path, broker, clk) == ("MATCH", "NOOP")


def test_incoherent_wrong_lot_flattens(tmp_path):
    clk = iter(f"2026-06-05T14:04:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()
    tgt = runner.step("IN", _LEGS, emitted_at=next(clk))
    broker.open_group(tgt)
    broker.corrupt_lot(2.0)                        # wrong hedge ratio
    assert _drive(tmp_path, broker, clk) == ("INCOHERENT", "WOULD_FLATTEN")


def test_executions_log_correlates_by_target_hash(tmp_path):
    """The executions log carries acted_on_seq + target_hash so a 3 AM operator
    can line up target.jsonl <-> executions.jsonl <-> broker."""
    clk = iter(f"2026-06-05T14:05:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()
    tgt = runner.step("IN", _LEGS, emitted_at=next(clk))
    run_once(tmp_path, broker.read_positions, now=lambda: next(clk))
    ex = bridge.read_executions(tmp_path)[-1]
    assert ex["acted_on_seq"] == tgt.seq and ex["target_hash"] == tgt.hash


def test_dry_mode_never_mutates_broker(tmp_path):
    """In DRY mode the shim only logs; the broker book is untouched by run_once."""
    clk = iter(f"2026-06-05T14:06:{s:02d}Z" for s in range(60))
    runner = ScriptedRunner(tmp_path, "B")
    broker = MockBroker()
    runner.step("IN", _LEGS, emitted_at=next(clk))
    before = broker.read_positions()
    run_once(tmp_path, broker.read_positions, now=lambda: next(clk))   # says WOULD_OPEN
    assert broker.read_positions() == before == []
