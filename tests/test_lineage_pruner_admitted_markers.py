"""Regression test: lineage_pruner must pair .txt.admitted sidecars with the
directive .txt during quarantine scans.

Background — pre-fix, the scan globbed `*.txt` only and left 433 .admitted
markers as orphans in backtest_directives/completed/ across the 2026-05-22
pipeline-state-cleanup. The orphan markers were 0-byte sentinels created at
admission (run_pipeline.admit_directive via `marker_path.touch()`), so their
presence-without-content created the false appearance of "truncated" directive
files. The fix pairs each <id>.txt with every existing <id>.txt<suffix>
sidecar listed in DIRECTIVE_SIDECAR_SUFFIXES.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.state_lifecycle import lineage_pruner as lp


def test_collect_directive_targets_pairs_admitted_sidecar(tmp_path):
    directives = tmp_path / "backtest_directives"
    (directives / "completed").mkdir(parents=True)

    txt = directives / "completed" / "TEST_DIR_S01_V1_P00.txt"
    txt.write_text("test:\n  name: TEST_DIR_S01_V1_P00\n", encoding="utf-8")
    sidecar = directives / "completed" / "TEST_DIR_S01_V1_P00.txt.admitted"
    sidecar.touch()

    targets = lp._collect_directive_targets(directives, keep_runs=set())

    assert txt in targets
    assert sidecar in targets


def test_collect_directive_targets_protects_pair_when_mapped(tmp_path):
    directives = tmp_path / "backtest_directives"
    (directives / "completed").mkdir(parents=True)

    txt = directives / "completed" / "PROTECTED_S01_V1_P00.txt"
    txt.write_text("test:\n  name: PROTECTED_S01_V1_P00\n", encoding="utf-8")
    sidecar = directives / "completed" / "PROTECTED_S01_V1_P00.txt.admitted"
    sidecar.touch()

    targets = lp._collect_directive_targets(
        directives,
        keep_runs={"PROTECTED_S01_V1_P00"},
    )

    assert targets == []


def test_collect_directive_targets_handles_missing_sidecar(tmp_path):
    directives = tmp_path / "backtest_directives"
    (directives / "completed").mkdir(parents=True)

    txt = directives / "completed" / "NO_MARKER_S01_V1_P00.txt"
    txt.write_text("test:\n  name: NO_MARKER_S01_V1_P00\n", encoding="utf-8")

    targets = lp._collect_directive_targets(directives, keep_runs=set())

    assert targets == [txt]


def test_collect_directive_targets_recursive(tmp_path):
    directives = tmp_path / "backtest_directives"
    (directives / "active_backup").mkdir(parents=True)
    (directives / "completed").mkdir(parents=True)

    a_txt = directives / "active_backup" / "A_S01_V1_P00.txt"
    a_txt.write_text("test:\n  name: A_S01_V1_P00\n", encoding="utf-8")
    a_marker = directives / "active_backup" / "A_S01_V1_P00.txt.admitted"
    a_marker.touch()

    c_txt = directives / "completed" / "C_S01_V1_P00.txt"
    c_txt.write_text("test:\n  name: C_S01_V1_P00\n", encoding="utf-8")
    c_marker = directives / "completed" / "C_S01_V1_P00.txt.admitted"
    c_marker.touch()

    targets = lp._collect_directive_targets(directives, keep_runs=set())

    assert set(targets) == {a_txt, a_marker, c_txt, c_marker}


def test_sidecar_suffixes_constant_includes_admitted():
    assert ".admitted" in lp.DIRECTIVE_SIDECAR_SUFFIXES
