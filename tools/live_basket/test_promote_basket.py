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
