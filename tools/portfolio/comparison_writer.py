"""comparison_writer.py -- append-only writer for the `comparison` evidence ledger.

A `comparison` row is EVIDENCE: it is only allowed to exist when two SPECIFIC runs
were a valid, apples-to-apples basis for a deployment decision. `record_comparison`
REFUSES (raises ComparisonError; writes nothing) unless both runs are *certified*
(is_current=1 AND witness-complete) and the comparison is *sound* (same effective
input data, same engine stamp, the intended directive delta). There is no status
column -- existence is the certification. See comparison_schema.py for the contract.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from tools.portfolio.comparison_schema import COMPARISON_COLUMNS


class ComparisonError(RuntimeError):
    """Raised when a comparison is not valid evidence -- the row is refused, never
    written. Reasons: a run is missing / not current / witness-incomplete, or the
    two runs are not apples-to-apples (different data, different engine, or no
    intended directive delta)."""


def _certified_witnesses(conn, run_id: str) -> dict[str, Any]:
    """Return a certified run's witnesses, or raise. A run is CERTIFIED iff it is
    is_current=1 (the authoritative run) AND witness-complete (no NULL witnesses)."""
    row = conn.execute(
        "SELECT effective_input_sha256, engine_version, engine_abi, directive_sha256, "
        "is_current FROM cointegration_sheet WHERE run_id = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        raise ComparisonError(
            f"[REFUSED] run_id {run_id!r} not in cointegration_sheet -- not a "
            f"certified run; comparison evidence is scoped to cointegration runs."
        )
    eff, ev, ea, dsha, is_current = row
    if is_current != 1:
        raise ComparisonError(
            f"[REFUSED] run_id {run_id!r} is NOT current (is_current={is_current!r}). "
            f"A comparison may only cite the authoritative run; compare the "
            f"is_current=1 run, never a superseded one."
        )
    missing = [n for n, v in (
        ("effective_input_sha256", eff), ("engine_version", ev),
        ("engine_abi", ea), ("directive_sha256", dsha),
    ) if v in (None, "")]
    if missing:
        raise ComparisonError(
            f"[REFUSED] run_id {run_id!r} is witness-incomplete (NULL: {missing}). "
            f"A run with a missing identity witness cannot be comparison evidence."
        )
    return {"effective_input_sha256": eff, "engine": (ev, ea), "directive_sha256": dsha}


def certify_comparison(conn, left_run_id: str, right_run_id: str,
                       comparison_reason: str = "") -> dict[str, Any]:
    """Record (append-only) a comparison ONLY if it is valid evidence; otherwise
    raise ComparisonError and write nothing. Idempotent on identical
    (left, right, reason). Caller owns the connection lifecycle."""
    if not left_run_id or not right_run_id:
        raise ComparisonError("[REFUSED] left_run_id and right_run_id are required.")
    reason = str(comparison_reason or "")

    L = _certified_witnesses(conn, left_run_id)   # raises unless certified
    R = _certified_witnesses(conn, right_run_id)

    if L["effective_input_sha256"] != R["effective_input_sha256"]:
        raise ComparisonError(
            "[REFUSED] runs consumed DIFFERENT effective input data "
            "(effective_input_sha256 mismatch) -- not apples-to-apples."
        )
    if L["engine"] != R["engine"]:
        raise ComparisonError(
            "[REFUSED] runs used DIFFERENT engines "
            f"({L['engine']} vs {R['engine']}) -- not apples-to-apples."
        )
    if L["directive_sha256"] == R["directive_sha256"]:
        raise ComparisonError(
            "[REFUSED] runs share an IDENTICAL directive (no intended delta) -- "
            "this is not a comparison."
        )

    cid = hashlib.sha256(
        f"{left_run_id}|{right_run_id}|{reason}".encode("utf-8")
    ).hexdigest()
    row = {
        "comparison_id": cid,
        "left_run_id": left_run_id,
        "right_run_id": right_run_id,
        "comparison_reason": reason,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    cols = [c for c in COMPARISON_COLUMNS if c in row]
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f'INSERT INTO comparison ({col_names}) VALUES ({placeholders}) '
        f'ON CONFLICT("comparison_id") DO NOTHING',
        [row[c] for c in cols],
    )
    return dict(row)


def record_comparison(left_run_id: str, right_run_id: str,
                      comparison_reason: str = "") -> dict[str, Any]:
    """Open the authoritative ledger, record the comparison if it is valid
    evidence (else raise), and return the row. The deployment-evidence question
    is then existence:
        SELECT 1 FROM comparison WHERE left_run_id=? AND right_run_id=?
    """
    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    try:
        create_tables(conn)
        row = certify_comparison(conn, left_run_id, right_run_id, comparison_reason)
        conn.commit()
        return row
    finally:
        conn.close()


def read_comparisons(left_run_id: str, right_run_id: str) -> list[dict[str, Any]]:
    """The deployment-evidence lookup: recorded comparisons for a pair, newest
    first. A non-empty result means valid evidence exists (the row could only
    have been written if the comparison was sound)."""
    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    try:
        create_tables(conn)
        rows = conn.execute(
            "SELECT comparison_id, comparison_reason, created_at FROM comparison "
            "WHERE left_run_id = ? AND right_run_id = ? ORDER BY created_at DESC",
            (left_run_id, right_run_id),
        ).fetchall()
        keys = ("comparison_id", "comparison_reason", "created_at")
        return [dict(zip(keys, r)) for r in rows]
    finally:
        conn.close()


__all__ = [
    "ComparisonError",
    "certify_comparison",
    "record_comparison",
    "read_comparisons",
]
