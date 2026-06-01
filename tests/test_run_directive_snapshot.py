"""Run-folder directive co-location — every run carries its source directive.

strategy.py / basket leg+rule code can only be produced AFTER reading the
directive, so the directive is the irreproducible source. Co-locating a
byte-for-byte copy at runs/<run_id>/directive.txt (write-once) makes each run
self-describing and reproducible even if the directive is later cleaned out of
completed/. Forward paths: run_stage1 (single-strategy) + run_pipeline basket
dispatch. Backfill: tools/backfill_run_directives.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from tools.run_directive_snapshot import (  # noqa: E402
    DIRECTIVE_SNAPSHOT_NAME,
    DirectiveSnapshotError,
    find_live_directive,
    require_directive_snapshot,
    snapshot_run_directive,
)


def test_find_live_directive_resolves_completed_fixture():
    # The restored basket fixture lives in completed/ — a real live directive.
    p = find_live_directive("90_PORT_H2_5M_RECYCLE_S01_V1_P00", REPO_ROOT)
    assert p is not None
    assert p.name == "90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt"
    assert p.is_file()


def test_find_live_directive_missing_returns_none():
    assert find_live_directive("99_NO_SUCH_DIRECTIVE_V1_P00", REPO_ROOT) is None


def test_snapshot_writes_and_is_write_once(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    src = tmp_path / "90_FOO_S01_V1_P00.txt"
    src.write_text("test:\n  name: foo\nbasket:\n  legs: []\n", encoding="utf-8")

    first = snapshot_run_directive(run_dir, src)
    assert (run_dir / DIRECTIVE_SNAPSHOT_NAME).is_file()
    assert first["written"] is True
    assert first["filename"] == "90_FOO_S01_V1_P00.txt"
    assert len(first["sha256"]) == 64

    # Write-once: second call must not overwrite, reports written=False.
    second = snapshot_run_directive(run_dir, src)
    assert second["written"] is False
    assert second["sha256"] == first["sha256"]


def test_snapshot_missing_source_returns_none(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert snapshot_run_directive(run_dir, tmp_path / "nope.txt") is None
    assert snapshot_run_directive(run_dir, None) is None


# ── Enforcement: require_directive_snapshot is mandatory (fail-loud) ─────────


def test_require_succeeds_on_present_directive(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    src = tmp_path / "90_X_S01_V1_P00.txt"
    src.write_text("test:\n  name: x\n", encoding="utf-8")
    snap = require_directive_snapshot(run_dir, src)
    assert (run_dir / DIRECTIVE_SNAPSHOT_NAME).is_file()
    assert snap["filename"] == "90_X_S01_V1_P00.txt"


def test_require_raises_when_directive_missing(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # The rule must NOT be silently skippable: a missing/None source raises.
    with pytest.raises(DirectiveSnapshotError):
        require_directive_snapshot(run_dir, tmp_path / "does_not_exist.txt")
    with pytest.raises(DirectiveSnapshotError):
        require_directive_snapshot(run_dir, None)
