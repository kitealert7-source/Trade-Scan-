"""Comparator primitives for the regression harness.

Every comparator returns (passed: bool, diff_text: str). `diff_text` is empty
on success; on failure it is a compact, human-readable explanation truncated
to ~20 lines so the summary stays triage-friendly.

Numeric float tolerance: rtol=1e-9, atol=1e-12 — tighter than any legitimate
metric drift so only true regressions fire.
"""

from __future__ import annotations

import difflib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from tools.regression.normalize import normalize_json, normalize_text

_MAX_DIFF_LINES = 20
_FLOAT_RTOL = 1e-9
_FLOAT_ATOL = 1e-12


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _truncate(lines: list[str]) -> str:
    if len(lines) <= _MAX_DIFF_LINES:
        return "\n".join(lines)
    head = lines[: _MAX_DIFF_LINES - 1]
    return "\n".join(head + [f"  ... ({len(lines) - _MAX_DIFF_LINES + 1} more lines suppressed)"])


def _floats_equal(a: Any, b: Any) -> bool:
    try:
        af, bf = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isnan(af) and math.isnan(bf):
        return True
    return math.isclose(af, bf, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL)


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------
def compare_json(got_path: Path, golden_path: Path) -> tuple[bool, str]:
    if not got_path.exists():
        return False, f"missing output: {got_path}"
    if not golden_path.exists():
        return False, f"missing golden: {golden_path}"
    try:
        got = json.loads(got_path.read_text(encoding="utf-8"))
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"parse error: {e}"

    diffs: list[str] = []
    _diff_json(normalize_json(golden), normalize_json(got), path="root", out=diffs)
    if not diffs:
        return True, ""
    return False, _truncate(diffs)


def _diff_json(golden: Any, got: Any, *, path: str, out: list[str]) -> None:
    if isinstance(golden, dict) and isinstance(got, dict):
        all_keys = sorted(set(golden) | set(got))
        for k in all_keys:
            if k not in golden:
                out.append(f"{path}.{k}: unexpected key in output: {got[k]!r}")
            elif k not in got:
                out.append(f"{path}.{k}: missing in output (golden: {golden[k]!r})")
            else:
                _diff_json(golden[k], got[k], path=f"{path}.{k}", out=out)
        return
    if isinstance(golden, list) and isinstance(got, list):
        if len(golden) != len(got):
            out.append(f"{path}: length differs (golden={len(golden)}, got={len(got)})")
            return
        for i, (g, o) in enumerate(zip(golden, got)):
            _diff_json(g, o, path=f"{path}[{i}]", out=out)
        return
    if isinstance(golden, (int, float)) and isinstance(got, (int, float)):
        if not _floats_equal(golden, got):
            out.append(f"{path}: expected {golden!r}, got {got!r}")
        return
    if golden != got:
        out.append(f"{path}: expected {golden!r}, got {got!r}")


# --------------------------------------------------------------------------
# CSV (via simple line-by-line normalization — avoids pandas dep for speed)
# --------------------------------------------------------------------------
def compare_csv(got_path: Path, golden_path: Path, *, sort_lines: bool = False) -> tuple[bool, str]:
    if not got_path.exists():
        return False, f"missing output: {got_path}"
    if not golden_path.exists():
        return False, f"missing golden: {golden_path}"
    got_lines = normalize_text(got_path.read_text(encoding="utf-8")).split("\n")
    golden_lines = normalize_text(golden_path.read_text(encoding="utf-8")).split("\n")
    if sort_lines and got_lines and golden_lines:
        # Keep header row pinned at top, sort the rest.
        got_lines = [got_lines[0]] + sorted(got_lines[1:])
        golden_lines = [golden_lines[0]] + sorted(golden_lines[1:])
    if got_lines == golden_lines:
        return True, ""
    diff = list(difflib.unified_diff(
        golden_lines, got_lines, fromfile="golden", tofile="got", lineterm=""
    ))
    return False, _truncate(diff)


# --------------------------------------------------------------------------
# Markdown / free-form text
# --------------------------------------------------------------------------
def compare_text(got_path: Path, golden_path: Path) -> tuple[bool, str]:
    if not got_path.exists():
        return False, f"missing output: {got_path}"
    if not golden_path.exists():
        return False, f"missing golden: {golden_path}"
    got = normalize_text(got_path.read_text(encoding="utf-8"))
    golden = normalize_text(golden_path.read_text(encoding="utf-8"))
    if got == golden:
        return True, ""
    diff = list(difflib.unified_diff(
        golden.split("\n"), got.split("\n"),
        fromfile="golden", tofile="got", lineterm=""
    ))
    return False, _truncate(diff)


# --------------------------------------------------------------------------
# JSONL — line-by-line normalized JSON compare
# --------------------------------------------------------------------------
def compare_jsonl(got_path: Path, golden_path: Path) -> tuple[bool, str]:
    if not got_path.exists():
        return False, f"missing output: {got_path}"
    if not golden_path.exists():
        return False, f"missing golden: {golden_path}"
    got_lines = [l for l in got_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    golden_lines = [l for l in golden_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(got_lines) != len(golden_lines):
        return False, f"line count differs (golden={len(golden_lines)}, got={len(got_lines)})"
    diffs: list[str] = []
    for i, (gl, ol) in enumerate(zip(golden_lines, got_lines)):
        try:
            g = normalize_json(json.loads(gl))
            o = normalize_json(json.loads(ol))
        except json.JSONDecodeError as e:
            diffs.append(f"line {i}: JSON parse error: {e}")
            continue
        line_diffs: list[str] = []
        _diff_json(g, o, path=f"line[{i}]", out=line_diffs)
        diffs.extend(line_diffs)
    if not diffs:
        return True, ""
    return False, _truncate(diffs)


# --------------------------------------------------------------------------
# YAML — parsed + normalized (never raw text)
# --------------------------------------------------------------------------
def compare_yaml(got_path: Path, golden_path: Path) -> tuple[bool, str]:
    if not got_path.exists():
        return False, f"missing output: {got_path}"
    if not golden_path.exists():
        return False, f"missing golden: {golden_path}"
    try:
        import yaml  # deferred — harness does not require yaml when skipped
    except ImportError:
        return False, "pyyaml not installed (required for YAML compare)"
    try:
        got = yaml.safe_load(got_path.read_text(encoding="utf-8"))
        golden = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"YAML parse error: {e}"
    diffs: list[str] = []
    _diff_json(normalize_json(golden), normalize_json(got), path="root", out=diffs)
    if not diffs:
        return True, ""
    return False, _truncate(diffs)


# --------------------------------------------------------------------------
# SQLite — table dumps ordered by PK
# --------------------------------------------------------------------------
def compare_sqlite_table(
    got_db: Path, golden_db: Path, *, table: str, order_by: str = "rowid"
) -> tuple[bool, str]:
    if not got_db.exists():
        return False, f"missing output DB: {got_db}"
    if not golden_db.exists():
        return False, f"missing golden DB: {golden_db}"
    try:
        got_rows = _dump_table(got_db, table, order_by)
        golden_rows = _dump_table(golden_db, table, order_by)
    except sqlite3.Error as e:
        return False, f"sqlite error: {e}"
    if got_rows == golden_rows:
        return True, ""
    if len(got_rows) != len(golden_rows):
        return False, (
            f"table {table}: row count differs "
            f"(golden={len(golden_rows)}, got={len(got_rows)})"
        )
    diffs: list[str] = []
    for i, (g, o) in enumerate(zip(golden_rows, got_rows)):
        if g != o:
            diffs.append(f"row {i}: expected {g}, got {o}")
    return False, _truncate(diffs)


def _dump_table(db_path: Path, table: str, order_by: str) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
        return list(cur.fetchall())
