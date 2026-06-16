"""comparison_writer.py -- append-only, self-certifying writer for the
`comparison` ledger (deployability provenance).

`record_comparison(left, right, reason)` records the smallest deployable unit: an
immutable fact that two SPECIFIC runs were compared to support a decision, plus a
tri-state certification of whether that comparison was apples-to-apples. The
certification is computed at write time from each run's cointegration_sheet
witnesses (effective_input_sha256 = data, engine stamp = engine, directive_sha256
= the intended delta).

TRI-STATE: a missing witness -> `indeterminate`, never `yes`. SCOPE: certifies, does
NOT gate; engine compares the STAMP not the imported compute; no "which is better"
field (that is the operator's call, carried in comparison_reason). See
tools/portfolio/comparison_schema.py for the full contract.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from tools.portfolio.comparison_schema import COMPARISON_COLUMNS


class ComparisonError(RuntimeError):
    """Raised when a comparison references a run absent from cointegration_sheet."""


def _tri_same(a: Any, b: Any) -> str:
    """yes if both present and equal; no if both present and differ;
    indeterminate if either is missing (None/'')."""
    if a in (None, "") or b in (None, ""):
        return "indeterminate"
    return "yes" if a == b else "no"


def _tri_differ(a: Any, b: Any) -> str:
    """yes if both present and DIFFER (the intended directive delta); no if equal;
    indeterminate if either is missing."""
    if a in (None, "") or b in (None, ""):
        return "indeterminate"
    return "yes" if a != b else "no"


def _roll_up(*checks: str) -> str:
    """comparable = yes iff all yes; no if any no; else indeterminate."""
    if "no" in checks:
        return "no"
    if "indeterminate" in checks:
        return "indeterminate"
    return "yes"


def _witnesses(conn, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        'SELECT effective_input_sha256, engine_version, engine_abi, directive_sha256 '
        'FROM cointegration_sheet WHERE run_id = ? LIMIT 1',
        (run_id,),
    ).fetchone()
    if row is None:
        raise ComparisonError(
            f"[FATAL] run_id {run_id!r} not found in cointegration_sheet. Comparison "
            f"certification is scoped to cointegration runs (the witnesses live there)."
        )
    # engine identity = (engine_version, engine_abi) STAMP; key on engine_version
    # presence so an old NULL-engine row reads indeterminate, not a false match.
    return {
        "effective_input_sha256": row[0],
        "engine_version": row[1],
        "engine": (row[1], row[2]),
        "directive_sha256": row[3],
    }


def certify_comparison(conn, left_run_id: str, right_run_id: str,
                       comparison_reason: str = "") -> dict[str, Any]:
    """Compute the tri-state certification for (left, right) from their
    cointegration_sheet witnesses, append the comparison row (append-only;
    idempotent on identical left|right|reason), and return the certification.

    Caller owns the connection lifecycle (open / create_tables / commit / close)."""
    if not left_run_id or not right_run_id:
        raise ComparisonError("[FATAL] left_run_id and right_run_id are required.")
    reason = str(comparison_reason or "")

    L = _witnesses(conn, left_run_id)
    R = _witnesses(conn, right_run_id)

    data_match = _tri_same(L["effective_input_sha256"], R["effective_input_sha256"])
    # engine: indeterminate if either engine_version is missing, else compare the
    # (version, abi) stamp tuple.
    if L["engine_version"] in (None, "") or R["engine_version"] in (None, ""):
        engine_match = "indeterminate"
    else:
        engine_match = "yes" if L["engine"] == R["engine"] else "no"
    directive_differs = _tri_differ(L["directive_sha256"], R["directive_sha256"])
    comparable = _roll_up(data_match, engine_match, directive_differs)

    cid = hashlib.sha256(
        f"{left_run_id}|{right_run_id}|{reason}".encode("utf-8")
    ).hexdigest()
    row = {
        "comparison_id": cid,
        "left_run_id": left_run_id,
        "right_run_id": right_run_id,
        "comparison_reason": reason,
        "data_match": data_match,
        "engine_match": engine_match,
        "directive_differs": directive_differs,
        "comparable": comparable,
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
    return {
        "comparison_id": cid,
        "left_run_id": left_run_id,
        "right_run_id": right_run_id,
        "comparison_reason": reason,
        "data_match": data_match,
        "engine_match": engine_match,
        "directive_differs": directive_differs,
        "comparable": comparable,
    }


def record_comparison(left_run_id: str, right_run_id: str,
                      comparison_reason: str = "") -> dict[str, Any]:
    """Open the authoritative ledger, certify + append the comparison, return the
    certification. The deployability question is then a single lookup:
        SELECT comparable FROM comparison WHERE left_run_id=? AND right_run_id=?
    """
    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    try:
        create_tables(conn)
        cert = certify_comparison(conn, left_run_id, right_run_id, comparison_reason)
        conn.commit()
        return cert
    finally:
        conn.close()


def read_comparisons(left_run_id: str, right_run_id: str) -> list[dict[str, Any]]:
    """The deployability lookup: recorded comparisons for a pair, newest first."""
    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    try:
        create_tables(conn)
        rows = conn.execute(
            'SELECT comparison_reason, data_match, engine_match, directive_differs, '
            'comparable, created_at FROM comparison '
            'WHERE left_run_id = ? AND right_run_id = ? ORDER BY created_at DESC',
            (left_run_id, right_run_id),
        ).fetchall()
        keys = ("comparison_reason", "data_match", "engine_match",
                "directive_differs", "comparable", "created_at")
        return [dict(zip(keys, r)) for r in rows]
    finally:
        conn.close()


__all__ = [
    "ComparisonError",
    "certify_comparison",
    "record_comparison",
    "read_comparisons",
]
