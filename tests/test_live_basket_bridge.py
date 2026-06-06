"""Contract + atomic-I/O tests for the V0 live-basket bridge.

Locks the load-bearing target-state contract: the ratified schema (no
`direction`; `epoch` reserved at 0; `target_hash` = envelope-free semantic
fingerprint; `seq` strictly increasing with GAPS ALLOWED), the separate
heartbeat channel, and the self-identifying order tag.
"""
from __future__ import annotations

import pytest

from tools.live_basket import bridge
from tools.live_basket.bridge import ContractError, Leg, Target


_LEGS = [Leg("EURUSD", "long", 0.02), Leg("USDJPY", "short", 0.01)]


# --- schema -------------------------------------------------------------- #

def test_target_roundtrip_has_no_direction_field():
    t = Target("B", 7, "IN", _LEGS, bar_ts="2026-06-05T13:55:00Z",
               emitted_at="2026-06-05T13:55:02Z")
    d = t.as_dict()
    assert "direction" not in d, "positions are the truth; no derived direction stored"
    back = Target.from_dict(d)
    assert back.state == "IN" and [(l.symbol, l.side, l.lot) for l in back.legs] == \
        [("EURUSD", "long", 0.02), ("USDJPY", "short", 0.01)]
    assert back.seq == 7 and back.epoch == 0


def test_target_hash_excludes_envelope_and_leg_order():
    a = Target("B", 1, "IN", _LEGS, bar_ts="t1", emitted_at="e1")
    b = Target("B", 99, "IN", list(reversed(_LEGS)), bar_ts="t2", emitted_at="e2")
    assert a.hash == b.hash, "hash must ignore seq/bar_ts/emitted_at and leg order"


def test_target_hash_changes_with_position():
    flat = Target("B", 1, "FLAT", [])
    inn = Target("B", 1, "IN", _LEGS)
    other = Target("B", 1, "IN", [Leg("EURUSD", "long", 0.02), Leg("USDJPY", "short", 0.02)])
    assert len({flat.hash, inn.hash, other.hash}) == 3


def test_epoch_reserved_zero_in_v0():
    with pytest.raises(ContractError):
        Target("B", 1, "IN", _LEGS, epoch=1)


def test_flat_requires_empty_legs_and_in_requires_legs():
    with pytest.raises(ContractError):
        Target("B", 1, "FLAT", _LEGS)
    with pytest.raises(ContractError):
        Target("B", 1, "IN", [])


@pytest.mark.parametrize("bad", [
    {"symbol": "", "side": "long", "lot": 0.01},
    {"symbol": "EURUSD", "side": "buy", "lot": 0.01},
    {"symbol": "EURUSD", "side": "long", "lot": 0.0},
    {"symbol": "EURUSD", "side": "long", "lot": -0.01},
])
def test_leg_validation(bad):
    with pytest.raises(ContractError):
        Leg(bad["symbol"], bad["side"], bad["lot"])


# --- atomic I/O + seq ---------------------------------------------------- #

def test_seq_gaps_allowed_latest_is_max(tmp_path):
    for s in (1, 2, 5):                       # a gap at 3,4 is contract-legal
        bridge.append_jsonl_atomic(tmp_path / bridge.TARGET_FILE,
                                   Target("B", s, "FLAT", []).as_dict())
    assert bridge.read_latest_target(tmp_path).seq == 5


def test_latest_is_max_seq_even_when_appended_out_of_order(tmp_path):
    for s in (5, 1, 3):
        bridge.append_jsonl_atomic(tmp_path / bridge.TARGET_FILE,
                                   Target("B", s, "FLAT", []).as_dict())
    assert bridge.read_latest_target(tmp_path).seq == 5


def test_append_leaves_no_tmp_files_and_parses(tmp_path):
    for s in range(1, 12):
        st = "IN" if s % 2 else "FLAT"
        bridge.append_jsonl_atomic(
            tmp_path / bridge.TARGET_FILE,
            Target("B", s, st, _LEGS if st == "IN" else []).as_dict(),
        )
    assert len(bridge.read_all_targets(tmp_path)) == 11
    assert not list(tmp_path.glob("*.tmp")), "atomic replace must leave no tmp residue"


def test_no_target_yet_returns_none(tmp_path):
    assert bridge.read_latest_target(tmp_path) is None


# --- heartbeat is a SEPARATE channel ------------------------------------ #

def test_heartbeat_roundtrip_separate_file(tmp_path):
    bridge.write_heartbeat(tmp_path, "B", "2026-06-05T14:00:00Z",
                           beat_at="2026-06-05T14:00:01Z", last_target_seq=3)
    hb = bridge.read_heartbeat(tmp_path)
    assert hb["beat_at"] == "2026-06-05T14:00:01Z" and hb["last_target_seq"] == 3
    assert (tmp_path / bridge.HEARTBEAT_FILE).is_file()
    assert not (tmp_path / bridge.TARGET_FILE).exists(), "heartbeat must not touch target.jsonl"


# --- order tags (self-identifying positions) ----------------------------- #

def test_basket_magic_deterministic_and_positive():
    m1 = bridge.basket_magic("COINTREV_EURUSD_USDJPY_GP")
    m2 = bridge.basket_magic("COINTREV_EURUSD_USDJPY_GP")
    assert m1 == m2 and 0 < m1 <= 0x7FFFFFFF
    assert m1 != bridge.basket_magic("COINTREV_EURUSD_USDCHF_GP")


def test_leg_comment_roundtrip_and_carries_epoch():
    assert bridge.parse_leg_comment(bridge.leg_comment(0, 1)) == (0, 1)
    assert bridge.parse_leg_comment(bridge.leg_comment(7, 0)) == (7, 0)


def test_leg_comment_within_mt5_limit():
    # epoch + leg index stay within the 31-char comment budget for sane values
    assert len(bridge.leg_comment(999999, 9)) <= 31
