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

def test_leg_magic_deterministic_positive_and_distinct_per_leg():
    # P2 Design-Lock D2: per-leg magic -> each leg gets a distinct, deterministic
    # magic so TS_Execution's 1:1 magic->ticket->slot reconcile is reused per leg.
    b = "COINTREV_EURUSD_USDJPY_GP"
    assert bridge.leg_magic(b, 0) == bridge.leg_magic(b, 0)        # deterministic
    assert 0 < bridge.leg_magic(b, 0) <= 0x7FFFFFFF                # positive 31-bit
    assert bridge.leg_magic(b, 0) != bridge.leg_magic(b, 1)        # distinct per leg
    assert bridge.leg_magic(b, 0) != bridge.leg_magic("COINTREV_EURUSD_USDCHF_GP", 0)  # per basket


def test_leg_comment_roundtrip_and_carries_epoch():
    assert bridge.parse_leg_comment(bridge.leg_comment(0, 1)) == (0, 1)
    assert bridge.parse_leg_comment(bridge.leg_comment(7, 0)) == (7, 0)


def test_leg_comment_within_mt5_limit():
    # epoch + leg index stay within the 31-char comment budget for sane values
    assert len(bridge.leg_comment(999999, 9)) <= 31


# --- Windows-daemon atomic-write hardening (skill lessons 4 + 5) --------- #

def test_replace_retries_transient_winerror_then_succeeds(tmp_path, monkeypatch):
    """A transient WinError 5/32 (AV / preview lock on the destination) must be
    retried, not fail-closed -- a 24/5 writer hits this after many writes."""
    real_replace = bridge.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:                                   # first two attempts locked
            raise OSError(13, "access denied", None, 5)       # winerror=5
        return real_replace(src, dst)

    monkeypatch.setattr(bridge.os, "replace", flaky_replace)
    bridge.append_jsonl_atomic(tmp_path / bridge.TARGET_FILE,
                               Target("B", 1, "FLAT", []).as_dict())
    assert calls["n"] == 3                                     # 2 failures + 1 success
    assert bridge.read_latest_target(tmp_path).seq == 1


def test_replace_reraises_non_transient_error(tmp_path, monkeypatch):
    """A non-lock error must raise on the FIRST attempt -- never mask a real
    failure (e.g. disk full) as a retryable lock."""
    def bad_replace(src, dst):
        raise OSError(28, "no space left", None, 112)         # winerror 112, not 5/32

    monkeypatch.setattr(bridge.os, "replace", bad_replace)
    with pytest.raises(OSError):
        bridge.append_jsonl_atomic(tmp_path / bridge.TARGET_FILE,
                                   Target("B", 1, "FLAT", []).as_dict())


def test_cleanup_orphan_tmp_sweeps_debris_leaving_final_files(tmp_path):
    """A hard-kill between mkstemp and replace leaves .tmp debris; the sweep
    removes it without touching the real bridge files (older_than_s=0 forces it
    regardless of age)."""
    bridge.append_jsonl_atomic(tmp_path / bridge.TARGET_FILE,
                               Target("B", 1, "FLAT", []).as_dict())   # a real, final file
    (tmp_path / "target.jsonl.abc123.tmp").write_text("torn", encoding="utf-8")
    (tmp_path / "runner_heartbeat.json.deadbeef.tmp").write_text("torn", encoding="utf-8")

    assert bridge.cleanup_orphan_tmp(tmp_path, older_than_s=0.0) == 2
    assert not list(tmp_path.glob("*.tmp"))                   # debris gone
    assert bridge.read_latest_target(tmp_path).seq == 1       # real file untouched


def test_cleanup_orphan_tmp_spares_fresh_inflight(tmp_path):
    """A startup sweep must NOT delete a fresh tmp -- on a shared bridge dir it
    may be the OTHER writer's in-flight write (producer target/heartbeat vs
    consumer executions)."""
    fresh = tmp_path / "executions.jsonl.live.tmp"
    fresh.write_text("in-flight", encoding="utf-8")
    assert bridge.cleanup_orphan_tmp(tmp_path) == 0           # default 30s age guard
    assert fresh.exists()


def test_cleanup_orphan_tmp_prefix_scoped_spares_other_writers_tmp(tmp_path):
    """The decisive shared-dir race guard: a writer scoped to its OWN files never
    touches another writer's tmp -- even a STALLED (old) one whose age would
    otherwise look like debris. Producer sweep must leave the consumer's
    executions tmp alone, and vice versa."""
    import os
    import time as _time
    # an OLD (stalled) consumer tmp -- age guard alone would delete it
    other = tmp_path / "executions.jsonl.stalled.tmp"
    other.write_text("stalled live write", encoding="utf-8")
    old = _time.time() - 120
    os.utime(other, (old, old))
    # an OLD producer-owned tmp (genuine debris this writer owns)
    mine = tmp_path / "target.jsonl.crashed.tmp"
    mine.write_text("debris", encoding="utf-8")
    os.utime(mine, (old, old))

    removed = bridge.cleanup_orphan_tmp(
        tmp_path, files=(bridge.TARGET_FILE, bridge.HEARTBEAT_FILE))
    assert removed == 1                       # only the producer-owned tmp
    assert not mine.exists()                  # own debris swept
    assert other.exists()                     # other writer's tmp untouched despite age


def test_cleanup_orphan_tmp_missing_dir_is_noop(tmp_path):
    assert bridge.cleanup_orphan_tmp(tmp_path / "nope") == 0


def test_scripted_runner_sweeps_stale_orphans_on_init(tmp_path):
    """The runner clears genuine (old) crash debris when it starts (lesson 5 at
    the writer); a fresh in-flight tmp would be spared by the age guard."""
    import os
    import time as _time
    from tools.live_basket.runner import ScriptedRunner
    orphan = tmp_path / "target.jsonl.stale.tmp"
    orphan.write_text("torn", encoding="utf-8")
    old = _time.time() - 120                                  # genuine crash debris
    os.utime(orphan, (old, old))
    ScriptedRunner(tmp_path, "B")
    assert not list(tmp_path.glob("*.tmp"))
