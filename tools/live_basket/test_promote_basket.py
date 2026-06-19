"""Golden reproduction test for promote_basket (Phase C) — the anti-drift gate.

PROVES: for an already-promoted basket, promote_basket --dry-run regenerates a
descriptor + vault meta + history that MATCH the committed artifacts (modulo the
free-text note, and with the promotion timestamp INJECTED for determinism). If the
tool ever stops reproducing the hand-built exemplars, this fails before a bad
promotion can ship.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TS_ROOT = Path(__file__).resolve().parents[2]
if str(_TS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TS_ROOT))

from tools.live_basket.promote_basket import (   # noqa: E402
    promote, _STRATEGY_POOL, _DRY_RUN_VAULT, _RUNS,
)

# (basket, directive_id, run_id, promoted_at, window_mode) — the 3 real exemplars.
EXEMPLARS = [
    ("CADJPYUSDCHF", "90_PORT_CADJPYUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS__E260312",
     "75a5364168315d547b8d72dd", "2026-06-07T13:10:17Z", "current"),
    ("CHFJPYEURUSD", "90_PORT_CHFJPYEURUSD_15M_COINTREV_V3_L30_GP_ZCRS__E260506",
     "77732c3318aebe5ee2dccbe2", "2026-06-08T15:13:38Z", "current"),
    ("EURJPYGBPJPY", "90_PORT_EURJPYGBPJPY_15M_COINTREV_V3_L30_GP_ZCRS__E251031",
     "5bb2c9ed87cf96c61ec1114b", "2026-06-08T15:31:45Z", "recorded"),
]


def _available(basket, run_id):
    return ((_RUNS / run_id / "manifest.json").is_file()
            and (_STRATEGY_POOL / basket / "descriptor.json").is_file())


@pytest.mark.parametrize("basket,directive_id,run_id,promoted_at,window", EXEMPLARS)
def test_golden_reproduction(tmp_path, basket, directive_id, run_id, promoted_at, window):
    if not _available(basket, run_id):
        pytest.skip(f"{basket}: run receipt or descriptor not present")
    r = promote(directive_id, run_id, now=promoted_at, window_mode=window,
                dry_run=True, out_dir=str(tmp_path))

    # descriptor — exact match except the free-text notes
    gen = json.loads(Path(r["descriptor"]).read_text(encoding="utf-8"))
    exist = json.loads((_STRATEGY_POOL / basket / "descriptor.json").read_text(encoding="utf-8"))
    gen.pop("notes", None)
    exist.pop("notes", None)
    assert gen == exist, f"{basket} descriptor diverged"

    # vault meta — FULL match (provenance sha256 reproduced from the run manifest)
    gen_meta = json.loads(Path(r["meta"]).read_text(encoding="utf-8"))
    exist_meta = json.loads(
        (_DRY_RUN_VAULT / exist["vault_ref"] / basket / "meta.json").read_text(encoding="utf-8"))
    assert gen_meta == exist_meta, f"{basket} vault meta diverged"

    # history PROMOTED event — match except the free-text note
    gen_ev = json.loads(Path(r["history"]).read_text(encoding="utf-8").strip().splitlines()[-1])
    exist_ev = json.loads(
        (_STRATEGY_POOL / basket / "history.jsonl").read_text(encoding="utf-8").strip().splitlines()[0])
    gen_ev.pop("note", None)
    exist_ev.pop("note", None)
    assert gen_ev == exist_ev, f"{basket} history event diverged"

    # vault files copied
    for sub in ("directive.txt", "run_snapshot/manifest.json", "meta.json"):
        assert (Path(r["vault_dir"]) / sub).is_file(), f"{basket} vault missing {sub}"


def test_at_least_one_exemplar_reproducible():
    # guards against a vacuously-green suite if no exemplar data is present.
    assert any(_available(b, rid) for b, _, rid, _, _ in EXEMPLARS), \
        "no exemplar data present — golden test would be vacuous"


@pytest.mark.parametrize("basket,directive_id,run_id,promoted_at,window", EXEMPLARS)
def test_promote_colocates_immutable_directive(tmp_path, basket, directive_id, run_id, promoted_at, window):
    """Part A (2026-06-19): promotion writes an immutable directive.txt BESIDE the
    descriptor, so the live producer never again depends on the prune-exposed
    backtest_directives/completed/<id>.txt (the 2026-06-16 failure deleted all 5
    live baskets' directives there). Lock the co-location + that the co-located
    directive NAMES the descriptor's directive_id (the producer read-path
    consistency gate relies on this)."""
    if not _available(basket, run_id):
        pytest.skip(f"{basket}: run receipt or descriptor not present")
    r = promote(directive_id, run_id, now=promoted_at, window_mode=window,
                dry_run=True, out_dir=str(tmp_path))
    colocated = Path(r["descriptor"]).parent / "directive.txt"
    assert colocated.is_file(), "promotion must co-locate directive.txt beside descriptor.json"
    from tools.pipeline_utils import parse_directive
    assert parse_directive(colocated)["test"]["strategy"] == directive_id, \
        "co-located directive must name the descriptor's directive_id"


# ---------------------------------------------------------------------------
# Regression: --refresh argument construction
# ---------------------------------------------------------------------------
# DEFECT (found in live use 2026-06-09, NOT in review): promote_basket --refresh
# omitted refresh_cointegration.py's REQUIRED --category / --reason, so the very
# first live refresh aborted (exit 2). The --refresh path was never golden-tested
# (the golden test uses --run-id). These lock the arg construction so it can't
# regress — per "every observed failure becomes a fixture".
import tools.live_basket.promote_basket as _pb   # noqa: E402


def test_run_refresh_current_maps_to_data_fresh(monkeypatch):
    cap = {}
    monkeypatch.setattr(_pb.subprocess, "run", lambda cmd, **k: cap.__setitem__("cmd", cmd))
    _pb.run_refresh("90_PORT_X_15M_COINTREV_V3_L30_GP_ZCRS__E1", "current", "onboard X")
    cmd = cap["cmd"]
    assert cmd[cmd.index("--category") + 1] == "DATA_FRESH"          # current -> DATA_FRESH
    assert cmd[cmd.index("--reason") + 1] == "onboard X"             # reason passed through
    assert cmd[cmd.index("--window-mode") + 1] == "current"
    assert "90_PORT_X_15M_COINTREV_V3_L30_GP_ZCRS__E1" in cmd        # directive positional present


def test_run_refresh_recorded_maps_to_engine(monkeypatch):
    cap = {}
    monkeypatch.setattr(_pb.subprocess, "run", lambda cmd, **k: cap.__setitem__("cmd", cmd))
    _pb.run_refresh("D", "recorded", "operator override")
    cmd = cap["cmd"]
    assert cmd[cmd.index("--category") + 1] == "ENGINE"              # recorded (override) -> ENGINE
    assert cmd[cmd.index("--window-mode") + 1] == "recorded"


def test_promote_refresh_passes_default_reason_when_no_override(monkeypatch):
    # current-window promote with no override -> an auto reason is generated + passed.
    seen = {}
    monkeypatch.setattr(_pb, "run_refresh", lambda d, wm, reason: seen.update(wm=wm, reason=reason))
    monkeypatch.setattr(_pb, "_latest_run_for", lambda b: (_ for _ in ()).throw(SystemExit("stop after refresh")))
    monkeypatch.setattr(_pb, "directive_path", lambda d: _pb.Path("x"))
    monkeypatch.setattr(_pb, "derive_legs", lambda p: [("AAA", "long"), ("BBB", "short")])
    with pytest.raises(SystemExit):
        _pb.promote("DIR", run_id=None, refresh=True, window_mode="current", dry_run=True)
    assert seen["wm"] == "current" and seen["reason"]               # non-empty auto reason
