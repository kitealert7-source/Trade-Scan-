"""
test_post_merge_watch.py

Unit tests for the post-merge watch (observer model). Covers:

- Watch lifecycle: create -> observe -> auto-close (OK / FAIL)
- Single-watch invariant
- Cleanliness heuristic (batch_summary + run_metadata + no crash)
- Dirty path (crash_trace.log present)
- Idempotent reconcile
- De-dup under concurrent reconcile race
- Archive flow (refuses ACTIVE, succeeds for CLOSED_*)
- Cutoff filter (pre-create runs ignored)
- Malformed run_state.json silently skipped
- Missing watch / no runs dir / closed watch all no-op cleanly

Run:
    python -m pytest tools/tests/test_post_merge_watch.py -v
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect WATCH_PATH, ARCHIVE_DIR, RUNS_DIR to per-test fixtures."""
    runs = tmp_path / "runs"
    archive = tmp_path / "archive" / "post_merge_watches"
    watch_path = tmp_path / "post_merge_watch.json"
    runs.mkdir()

    import tools.post_merge_watch as pmw
    monkeypatch.setattr(pmw, "WATCH_PATH", watch_path)
    monkeypatch.setattr(pmw, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(pmw, "RUNS_DIR", runs)
    return {
        "runs": runs,
        "archive": archive,
        "watch_path": watch_path,
        "module": pmw,
    }


def _make_run(
    runs: Path,
    run_id: str,
    *,
    last_updated: str,
    has_batch: bool = True,
    has_metadata: bool = True,
    has_crash: bool = False,
) -> Path:
    """Synthesize a run dir with the artifact pattern of choice."""
    rd = runs / run_id
    (rd / "data").mkdir(parents=True, exist_ok=True)
    (rd / "run_state.json").write_text(
        json.dumps({
            "run_id": run_id,
            "directive_id": "TEST_DIRECTIVE",
            "last_updated": last_updated,
        }),
        encoding="utf-8",
    )
    if has_batch:
        (rd / "data" / "batch_summary.csv").write_text(
            "symbol,status,pnl\nTEST,SUCCESS,100\n", encoding="utf-8"
        )
    if has_metadata:
        (rd / "data" / "run_metadata.json").write_text(
            json.dumps({"run_id": run_id, "engine_version": "1.5.8"}),
            encoding="utf-8",
        )
    if has_crash:
        (rd / "crash_trace.log").write_text("FATAL\n", encoding="utf-8")
    return rd


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )


# ─── Lifecycle ──────────────────────────────────────────────────────────


def test_create_watch_writes_active_state(env):
    pmw = env["module"]
    w = pmw.create_watch("abcdef0", target_runs=5)
    assert w["status"] == "ACTIVE"
    assert w["target_runs"] == 5
    assert w["runs_remaining"] == 5
    assert w["runs_observed"] == []
    assert env["watch_path"].exists()


def test_create_refuses_when_active_exists(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=5)
    with pytest.raises(RuntimeError, match="ACTIVE watch already exists"):
        pmw.create_watch("def456", target_runs=5)


def test_create_refuses_when_closed_exists(env):
    pmw = env["module"]
    # Manually plant a CLOSED watch
    env["watch_path"].write_text(json.dumps({
        "watch_id": "abc",
        "status": "CLOSED_OK",
        "target_runs": 5,
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="CLOSED_OK watch exists"):
        pmw.create_watch("def456", target_runs=5)


def test_create_rejects_zero_runs(env):
    pmw = env["module"]
    with pytest.raises(ValueError, match="target_runs must be"):
        pmw.create_watch("abc", target_runs=0)


# ─── Reconcile happy path ───────────────────────────────────────────────


def test_reconcile_observes_new_clean_runs(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=3)
    cutoff = pmw._read_watch()["created_at_utc"]

    # Three clean runs after cutoff
    for i in range(3):
        _make_run(env["runs"], f"run_{i:03d}", last_updated=_iso(offset_seconds=i + 1))

    w = pmw.reconcile_watch()
    assert w["status"] == "CLOSED_OK"
    assert w["runs_remaining"] == 0
    assert len(w["runs_observed"]) == 3
    for o in w["runs_observed"]:
        assert o["status"] == "clean"
    assert "all 3 observations clean" in w["close_verdict"]


def test_reconcile_observes_dirty_run(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=2)

    # 1 clean + 1 with crash trace
    _make_run(env["runs"], "run_clean", last_updated=_iso(1))
    _make_run(env["runs"], "run_crash",
              last_updated=_iso(2), has_batch=False, has_metadata=False, has_crash=True)

    w = pmw.reconcile_watch()
    assert w["status"] == "CLOSED_FAIL"
    statuses = sorted(o["status"] for o in w["runs_observed"])
    assert statuses == ["clean", "dirty"]
    assert "warmup regression" in w["close_verdict"]


def test_reconcile_dirty_when_artifacts_missing(env):
    """A run with run_state.json but no batch_summary or metadata is dirty —
    Stage1 didn't reach completion (likely warmup FATAL)."""
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)

    _make_run(env["runs"], "run_partial",
              last_updated=_iso(1), has_batch=False, has_metadata=False, has_crash=False)

    w = pmw.reconcile_watch()
    assert w["status"] == "CLOSED_FAIL"
    assert w["runs_observed"][0]["status"] == "dirty"


def test_reconcile_partial_progress_stays_active(env):
    """Less than target observed -> watch stays ACTIVE."""
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=5)

    _make_run(env["runs"], "run_one", last_updated=_iso(1))
    _make_run(env["runs"], "run_two", last_updated=_iso(2))

    w = pmw.reconcile_watch()
    assert w["status"] == "ACTIVE"
    assert len(w["runs_observed"]) == 2
    assert w["runs_remaining"] == 3


# ─── Cutoff / pre-create runs ───────────────────────────────────────────


def test_pre_cutoff_runs_ignored(env):
    """Runs whose last_updated < cutoff must not be counted."""
    pmw = env["module"]
    # Create runs in the past (1 hour ago) BEFORE the watch
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    _make_run(env["runs"], "run_pre1", last_updated=past)
    _make_run(env["runs"], "run_pre2", last_updated=past)

    pmw.create_watch("abc123", target_runs=2)

    # Now add one post-create run
    _make_run(env["runs"], "run_post", last_updated=_iso(1))

    w = pmw.reconcile_watch()
    assert len(w["runs_observed"]) == 1
    assert w["runs_observed"][0]["run_id"] == "run_post"
    assert w["status"] == "ACTIVE"  # only 1 of 2


# ─── Idempotence + concurrency ──────────────────────────────────────────


def test_reconcile_is_idempotent(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=3)
    for i in range(3):
        _make_run(env["runs"], f"run_{i}", last_updated=_iso(i + 1))

    w1 = pmw.reconcile_watch()
    w2 = pmw.reconcile_watch()
    w3 = pmw.reconcile_watch()
    assert w1 == w2 == w3
    assert w1["status"] == "CLOSED_OK"


def test_reconcile_dedups_run_ids(env):
    """Defensive: even if runs_observed somehow contains duplicates,
    de-dup runs at write time."""
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=3)

    # Inject a duplicate entry to simulate a race-window write
    w = pmw._read_watch()
    w["runs_observed"] = [
        {"run_id": "dup", "status": "clean", "has_batch_summary": True,
         "has_crash_trace": False, "observed_at_utc": _iso()},
        {"run_id": "dup", "status": "clean", "has_batch_summary": True,
         "has_crash_trace": False, "observed_at_utc": _iso()},
    ]
    pmw._atomic_write(env["watch_path"], w)

    # Add one more legit run
    _make_run(env["runs"], "real_run", last_updated=_iso(1))

    out = pmw.reconcile_watch()
    ids = [o["run_id"] for o in out["runs_observed"]]
    assert ids.count("dup") == 1, f"expected single 'dup' entry, got {ids}"


# ─── Robustness ─────────────────────────────────────────────────────────


def test_no_watch_file_reconcile_returns_none(env):
    pmw = env["module"]
    assert pmw.reconcile_watch() is None


def test_closed_watch_not_mutated_by_reconcile(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)
    _make_run(env["runs"], "run_one", last_updated=_iso(1))
    w_before = pmw.reconcile_watch()
    assert w_before["status"] == "CLOSED_OK"

    # Add another run after closure; reconcile must NOT touch the watch
    _make_run(env["runs"], "run_extra", last_updated=_iso(99))
    w_after = pmw.reconcile_watch()
    assert w_after == w_before


def test_malformed_run_state_skipped(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)

    # Run with malformed run_state.json
    rd = env["runs"] / "bad_run"
    (rd / "data").mkdir(parents=True)
    (rd / "run_state.json").write_text("not json{", encoding="utf-8")

    # And a valid one
    _make_run(env["runs"], "good_run", last_updated=_iso(1))

    w = pmw.reconcile_watch()
    ids = [o["run_id"] for o in w["runs_observed"]]
    assert "bad_run" not in ids
    assert "good_run" in ids


def test_missing_runs_dir_no_op(env, monkeypatch):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)
    # Point RUNS_DIR at a nonexistent path
    monkeypatch.setattr(pmw, "RUNS_DIR", env["runs"].parent / "nonexistent")
    w = pmw.reconcile_watch()
    assert w["status"] == "ACTIVE"
    assert w["runs_observed"] == []


def test_run_without_run_state_json_skipped(env):
    """A run dir without run_state.json (orphan / partial) must not match."""
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)

    # Run dir but no run_state.json
    rd = env["runs"] / "orphan_run"
    rd.mkdir()
    (rd / "data").mkdir()

    # And a valid one
    _make_run(env["runs"], "valid_run", last_updated=_iso(1))

    w = pmw.reconcile_watch()
    ids = [o["run_id"] for o in w["runs_observed"]]
    assert "orphan_run" not in ids
    assert ids == ["valid_run"]


# ─── Archive flow ───────────────────────────────────────────────────────


def test_archive_refuses_active(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=5)
    with pytest.raises(RuntimeError, match="Cannot archive ACTIVE watch"):
        pmw.archive_watch()


def test_archive_moves_closed_watch(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)
    _make_run(env["runs"], "run_one", last_updated=_iso(1))
    pmw.reconcile_watch()  # auto-close

    target = pmw.archive_watch()
    assert target.exists()
    assert not env["watch_path"].exists()
    archived = json.loads(target.read_text(encoding="utf-8"))
    assert archived["status"] == "CLOSED_OK"
    assert archived["watch_id"] in target.name


def test_archive_no_watch_raises(env):
    pmw = env["module"]
    with pytest.raises(RuntimeError, match="No watch file at"):
        pmw.archive_watch()


def test_create_after_archive_succeeds(env):
    pmw = env["module"]
    pmw.create_watch("abc123", target_runs=1)
    _make_run(env["runs"], "run_one", last_updated=_iso(1))
    pmw.reconcile_watch()
    pmw.archive_watch()

    # Now we should be able to create a new watch
    w = pmw.create_watch("def456", target_runs=3)
    assert w["status"] == "ACTIVE"
    assert w["commit_hash"] == "def456"


# ─── Atomic write ───────────────────────────────────────────────────────


def test_atomic_write_no_partial_file_on_serialize_error(env, monkeypatch):
    """If json.dump raises, no half-written file remains at WATCH_PATH."""
    pmw = env["module"]
    # Plant a valid file first
    pmw._atomic_write(env["watch_path"], {"a": 1})
    pre = env["watch_path"].read_text(encoding="utf-8")

    # Build an unserializable payload
    class _Bad:
        pass

    with pytest.raises(TypeError):
        pmw._atomic_write(env["watch_path"], {"bad": _Bad()})

    # Original file should be intact, no .tmp residue
    post = env["watch_path"].read_text(encoding="utf-8")
    assert pre == post
    leftovers = [p for p in env["watch_path"].parent.iterdir()
                 if p.suffix == ".tmp"]
    assert leftovers == []
