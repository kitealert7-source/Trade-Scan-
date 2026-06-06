"""bridge.py -- the V0 live-basket target-state bridge CONTRACT (LOCKED 2026-06-06).

Single source of truth for the on-disk interface between the live-basket *runner*
(emits desired target state) and the *shim* (reconciles broker truth to target).
The file format IS the interface -- neither side imports the other; both conform
to CONTRACT.md. STDLIB-ONLY by design, so the reconcile core (reconcile.py) and
these schemas port to the TS_Execution shim without a Trade_Scan dependency
(TS_Execution's only governed dependency stays `engine_abi`).

Operator-ratified decisions baked in here:
  - `epoch` RESERVED from day one; V0 hard-guards it to 0 (never incremented).
    It rides in the order tag so a future basis-reset recycle needs no schema /
    broker-tag migration.
  - NO `direction` field -- the legs ARE the position (one source of truth);
    basket direction is derived when needed, never stored.
  - `seq` strictly increasing, GAPS ALLOWED; current target = max-seq record.
  - `target_hash` = semantic fingerprint (state+epoch+legs only; excludes the
    envelope seq/bar_ts/emitted_at). DIAGNOSTIC ONLY -- V0 logic never branches
    on it (the runner's append-on-change uses semantic_key, its structured
    mirror).
  - Heartbeat is a SEPARATE channel (runner_heartbeat.json), updated every cycle
    even when the target is unchanged -- liveness must not be inferred from
    target age (Review #4).

See CONTRACT.md for the full specification + rationale.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1

# Bridge files live under <bridge_dir> = TS_SIGNAL_STATE/h2_live/<basket_id>/.
TARGET_FILE = "target.jsonl"
HEARTBEAT_FILE = "runner_heartbeat.json"
EXECUTIONS_FILE = "executions.jsonl"

_VALID_STATES = ("FLAT", "IN")
_VALID_SIDES = ("long", "short")
_MT5_COMMENT_MAX = 31  # MetaTrader5 order comment hard limit


class ContractError(ValueError):
    """Any violation of the bridge contract (bad schema / state / seq / tag)."""


def utc_now_iso() -> str:
    """Default wall-clock stamp (UTC, ISO-8601). Injectable everywhere a stamp
    is taken, so tests are deterministic."""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Leg:
    """A single position leg: the position truth, not an interpretation."""
    symbol: str
    side: str            # "long" | "short"
    lot: float

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ContractError("Leg.symbol is required")
        if self.side not in _VALID_SIDES:
            raise ContractError(f"Leg.side must be one of {_VALID_SIDES}, got {self.side!r}")
        if not (float(self.lot) > 0):
            raise ContractError(f"Leg.lot must be > 0, got {self.lot!r}")

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "side": self.side, "lot": float(self.lot)}


def _canonical_legs(legs) -> list:
    """Legs reduced to their SEMANTIC content, sorted by symbol (stable order)."""
    return [[lg.symbol, lg.side, round(float(lg.lot), 8)]
            for lg in sorted(legs, key=lambda x: x.symbol)]


def target_hash(state: str, epoch: int, legs) -> str:
    """Deterministic semantic fingerprint of a DESIRED POSITION -- diagnostics
    only (V0 logic never branches on it). Stable across re-emissions of the same
    position; EXCLUDES the envelope (seq / bar_ts / emitted_at)."""
    payload = json.dumps(
        {"state": state, "epoch": int(epoch), "legs": _canonical_legs(legs)},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def semantic_key(state: str, epoch: int, legs) -> tuple:
    """Structured desired-position identity the runner uses for append-on-change
    (the logic path; target_hash is its diagnostic mirror)."""
    return (state, int(epoch), tuple(tuple(x) for x in _canonical_legs(legs)))


@dataclass
class Target:
    """One desired-position record on target.jsonl. `state` + `legs` ARE the
    position; there is deliberately no `direction` field."""
    basket_id: str
    seq: int
    state: str                       # "FLAT" | "IN"
    legs: list                       # list[Leg]; empty iff FLAT
    epoch: int = 0                   # RESERVED; V0 hard-guards to 0
    bar_ts: Optional[str] = None     # market-time "as of" (the closed bar)
    emitted_at: str = field(default_factory=utc_now_iso)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.state not in _VALID_STATES:
            raise ContractError(f"Target.state must be one of {_VALID_STATES}, got {self.state!r}")
        if self.state == "FLAT" and self.legs:
            raise ContractError("FLAT target must have empty legs")
        if self.state == "IN" and not self.legs:
            raise ContractError("IN target must have >= 1 leg")
        if int(self.epoch) != 0:
            raise ContractError(f"V0 epoch is reserved and must be 0, got {self.epoch!r}")
        if int(self.seq) < 0:
            raise ContractError(f"seq must be >= 0, got {self.seq!r}")
        # normalize legs to Leg instances (accept dicts on construction)
        norm = []
        for lg in self.legs:
            norm.append(lg if isinstance(lg, Leg) else Leg(lg["symbol"], lg["side"], float(lg["lot"])))
        self.legs = norm

    @property
    def hash(self) -> str:
        return target_hash(self.state, self.epoch, self.legs)

    @property
    def key(self) -> tuple:
        return semantic_key(self.state, self.epoch, self.legs)

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "basket_id": self.basket_id,
            "seq": int(self.seq),
            "epoch": int(self.epoch),
            "state": self.state,
            "bar_ts": self.bar_ts,
            "emitted_at": self.emitted_at,
            "target_hash": self.hash,       # diagnostic stamp
            "legs": [lg.as_dict() for lg in self.legs],
        }

    @staticmethod
    def from_dict(d: dict) -> "Target":
        legs = [Leg(x["symbol"], x["side"], float(x["lot"])) for x in d.get("legs", [])]
        return Target(
            basket_id=d["basket_id"], seq=int(d["seq"]), state=d["state"], legs=legs,
            epoch=int(d.get("epoch", 0)), bar_ts=d.get("bar_ts"),
            emitted_at=d.get("emitted_at") or utc_now_iso(),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )


# --------------------------------------------------------------------------- #
# Atomic I/O -- every bridge-file mutation is a whole-file atomic replace, so a
# reader never observes a torn file. Single writer per file (no write contention).
# O(n) per append is irrelevant at bridge volumes (target: a few/day).
# --------------------------------------------------------------------------- #

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)            # atomic on POSIX + Windows
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _read_records(path: Path) -> list:
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_jsonl_atomic(path: Path, record: dict) -> None:
    """Append one record via whole-file atomic replace (single writer; readers
    never see a partial line)."""
    path = Path(path)
    existing = path.read_bytes() if path.is_file() else b""
    line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    _atomic_write_bytes(path, existing + line)


def read_latest_target(bridge_dir) -> Optional[Target]:
    """Current target = the record with the MAX `seq` (gaps allowed). None if no
    target has been written yet."""
    recs = _read_records(Path(bridge_dir) / TARGET_FILE)
    if not recs:
        return None
    return Target.from_dict(max(recs, key=lambda r: int(r["seq"])))


def read_all_targets(bridge_dir) -> list:
    return [Target.from_dict(r) for r in _read_records(Path(bridge_dir) / TARGET_FILE)]


def write_heartbeat(bridge_dir, basket_id: str, bar_ts, *,
                    beat_at: Optional[str] = None, last_target_seq=None) -> dict:
    """Overwrite the SEPARATE liveness file every runner cycle (Review #4:
    liveness must not be inferred from target age)."""
    rec = {
        "schema_version": SCHEMA_VERSION,
        "basket_id": basket_id,
        "bar_ts": bar_ts,
        "beat_at": beat_at or utc_now_iso(),
        "last_target_seq": last_target_seq,
    }
    _atomic_write_bytes(Path(bridge_dir) / HEARTBEAT_FILE,
                        (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8"))
    return rec


def read_heartbeat(bridge_dir) -> Optional[dict]:
    p = Path(bridge_dir) / HEARTBEAT_FILE
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def read_executions(bridge_dir) -> list:
    return _read_records(Path(bridge_dir) / EXECUTIONS_FILE)


# --------------------------------------------------------------------------- #
# Order tags -- a broker position must be self-identifying as (basket, epoch,
# leg) so the reconcile loop is stateless. `magic` carries basket identity;
# `comment` carries (epoch, leg_index). Epoch is in the tag FROM DAY ONE so a
# future basis-reset recycle needs no broker-side tag migration.
# --------------------------------------------------------------------------- #

def leg_magic(basket_id: str, leg_index: int) -> int:
    """Deterministic positive 31-bit MT5 magic PER LEG = hash("{basket_id}|L{leg}").

    P2 Design-Lock D2: per-leg (NOT per-basket) magic so TS_Execution's proven
    1 magic -> 1 ticket -> 1 slot reconcile path is reused UNCHANGED per leg
    (a shared basket magic would trip its duplicate-magic discard). Basket
    identity lives in the comment tag (`leg_comment`, audit/epoch only), never as
    the reconcile key. Stable across runs; no Date/Random."""
    if not basket_id:
        raise ContractError("basket_id is required for leg_magic")
    key = f"{basket_id}|L{int(leg_index)}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def leg_comment(epoch: int, leg_index: int) -> str:
    """MT5 comment tag carrying (epoch, leg_index) within the 31-char limit."""
    c = f"e{int(epoch)}L{int(leg_index)}"
    if len(c) > _MT5_COMMENT_MAX:
        raise ContractError(f"leg comment {c!r} exceeds MT5 {_MT5_COMMENT_MAX}-char limit")
    return c


def parse_leg_comment(comment: str) -> tuple:
    """Inverse of leg_comment -> (epoch, leg_index)."""
    m = re.fullmatch(r"e(\d+)L(\d+)", (comment or "").strip())
    if not m:
        raise ContractError(f"unparseable leg comment {comment!r}")
    return int(m.group(1)), int(m.group(2))


__all__ = [
    "SCHEMA_VERSION", "TARGET_FILE", "HEARTBEAT_FILE", "EXECUTIONS_FILE",
    "ContractError", "utc_now_iso", "Leg", "Target", "target_hash", "semantic_key",
    "append_jsonl_atomic", "read_latest_target", "read_all_targets",
    "write_heartbeat", "read_heartbeat", "read_executions",
    "leg_magic", "leg_comment", "parse_leg_comment",
]
