"""Tests for tools/summarize_recycle_events.py — the governed consumer
interface for rule telemetry (Research Artifact — Population Evidence;
TELEMETRY_GOVERNANCE_PROPOSAL_2026_06_12.md §5).

Covers: v0->v1 in-memory up-conversion, absent-file grace, summary
aggregation (numeric quantiles / boolean shares / categorical shares),
anchored capsule selection, and the tidy CSV export."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.summarize_recycle_events import (
    load_recycle_events,
    summarize,
    write_csv,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _capsule(tmp_path: Path, name: str, rows: list[dict] | None) -> Path:
    cap = tmp_path / name
    (cap / "raw").mkdir(parents=True, exist_ok=True)
    if rows is not None:
        _write_jsonl(cap / "raw" / "recycle_events.jsonl", rows)
    return cap


V0_ROWS = [
    {"bar_ts": "2024-09-10 04:15:00", "action": "HURST_BLOCK", "h": 0.58,
     "threshold": 0.55, "direction": -1},
    {"bar_ts": "2024-09-10 09:30:00", "action": "BASKET_OPEN", "direction": 1},
]

V1_ROWS = [
    {"schema_version": 1, "event_type": "MOVE_BLOCK",
     "timestamp": "2024-11-06T04:30:00", "rule_name": "r", "rule_version": 1,
     "run_id": "a" * 24, "directive_id": "D1", "basket_id": "AB",
     "payload": {"mm": 3.1, "leg": "ESP35", "non_reverting": False}},
    {"schema_version": 1, "event_type": "MOVE_BLOCK",
     "timestamp": "2024-11-06T05:30:00", "rule_name": "r", "rule_version": 1,
     "run_id": "a" * 24, "directive_id": "D1", "basket_id": "AB",
     "payload": {"mm": 2.2, "leg": "AUDJPY", "non_reverting": True}},
]


def test_reader_upconverts_v0_in_memory(tmp_path):
    p = tmp_path / "ev.jsonl"
    _write_jsonl(p, V0_ROWS)
    rows = load_recycle_events(p)
    assert len(rows) == 2
    blk = rows[0]
    assert blk["schema_version"] == 0
    assert blk["event_type"] == "HURST_BLOCK"
    assert blk["timestamp"].startswith("2024-09-10")
    assert blk["payload"]["h"] == 0.58
    assert "action" not in blk["payload"] and "bar_ts" not in blk["payload"]
    # identity unknown for v0 (ambient in the capsule path)
    assert blk["run_id"] is None and blk["directive_id"] is None
    # the on-disk artifact is untouched
    assert json.loads(p.read_text(encoding="utf-8").splitlines()[0]) == V0_ROWS[0]


def test_reader_passes_v1_through_and_absent_is_empty(tmp_path):
    p = tmp_path / "ev.jsonl"
    _write_jsonl(p, V1_ROWS)
    rows = load_recycle_events(p)
    assert rows == V1_ROWS
    assert load_recycle_events(tmp_path / "missing.jsonl") == []


def test_summarize_mixes_v0_v1_and_tolerates_absent(tmp_path):
    c1 = _capsule(tmp_path, "DIR_A_GP_X__E1_AB", V0_ROWS)
    c2 = _capsule(tmp_path, "DIR_B_GP_X__E2_CD", V1_ROWS)
    c3 = _capsule(tmp_path, "DIR_C_GP_X__E3_EF", None)  # no telemetry: valid
    out = summarize([c1, c2, c3])
    assert "capsules: 3" in out and "runs-with-events: 2" in out
    assert "HURST_BLOCK: count=1" in out
    assert "MOVE_BLOCK: count=2" in out
    assert "BASKET_OPEN: count=1" in out
    # numeric quantiles for mm, boolean share for non_reverting, categories for leg
    assert "mm" in out and "p05/p25/p50/p75/p95" in out
    assert "true-share = 50.0%" in out
    assert "ESP35:50%" in out


def test_csv_export_flattens_payload(tmp_path):
    c2 = _capsule(tmp_path, "DIR_B_GP_X__E2_CD", V1_ROWS)
    out_csv = tmp_path / "out.csv"
    n = write_csv([c2], str(out_csv), event_type="MOVE_BLOCK")
    assert n == 2
    text = out_csv.read_text(encoding="utf-8").splitlines()
    assert "payload.mm" in text[0] and "directive_id" in text[0]
    assert "3.1" in text[1]


def test_anchored_series_selection(tmp_path, monkeypatch):
    """--series matching is ANCHORED (tag__E), so sibling cohorts whose tag is
    a superstring do not contaminate the selection (the Z25 vs Z25_HF55
    lesson)."""
    import tools.summarize_recycle_events as sre
    base = tmp_path / "backtests"
    for name in ("90_X_L30_GP_Z25__E1_AB", "90_X_L30_GP_Z25_HF55__E1_AB",
                 "90_X_L30_GP_Z25__E2_CD"):
        (base / name / "raw").mkdir(parents=True)
    monkeypatch.setattr(sre, "_backtests_dir", lambda: base)
    sel = sre._select_capsules("GP_Z25", None, None)
    assert sorted(p.name for p in sel) == [
        "90_X_L30_GP_Z25__E1_AB", "90_X_L30_GP_Z25__E2_CD"]
    sel2 = sre._select_capsules("GP_Z25_HF55", None, None)
    assert [p.name for p in sel2] == ["90_X_L30_GP_Z25_HF55__E1_AB"]
