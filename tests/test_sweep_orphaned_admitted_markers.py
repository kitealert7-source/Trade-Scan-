"""Regression tests for tools/state_lifecycle/sweep_orphaned_admitted_markers.py.

Builds a synthetic backtest_directives/completed/ in tmp_path with a mix of
orphaned markers (no .txt sibling) and paired markers (with .txt sibling),
then exercises the dry-run and execute paths against a synthetic quarantine
root. Asserts that only orphans move, the manifest schema is well-formed,
and the operation is idempotent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.state_lifecycle import sweep_orphaned_admitted_markers as sw


def _build_tree(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    """Return (directives_dir, quarantine_root, paths)."""
    directives = tmp_path / "backtest_directives" / "completed"
    directives.mkdir(parents=True)
    quarantine = tmp_path / "TradeScan_State" / "quarantine"
    quarantine.mkdir(parents=True)

    paths = {}

    paired_txt = directives / "PAIRED_S01_V1_P00.txt"
    paired_txt.write_text("test:\n  name: PAIRED\n", encoding="utf-8")
    paired_marker = directives / "PAIRED_S01_V1_P00.txt.admitted"
    paired_marker.touch()
    paths["paired_txt"] = paired_txt
    paths["paired_marker"] = paired_marker

    orphan_a = directives / "ORPHAN_A_S01_V1_P00.txt.admitted"
    orphan_a.touch()
    orphan_b = directives / "ORPHAN_B_S02_V1_P00.txt.admitted"
    orphan_b.touch()
    paths["orphan_a"] = orphan_a
    paths["orphan_b"] = orphan_b

    return directives, quarantine, paths


def test_find_orphan_markers_distinguishes_paired_and_orphan(tmp_path, monkeypatch):
    directives, _, paths = _build_tree(tmp_path)
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    orphans = sw.find_orphan_markers(directives)

    assert set(orphans) == {paths["orphan_a"], paths["orphan_b"]}
    assert paths["paired_marker"] not in orphans


def test_dry_run_does_not_move_files(tmp_path, monkeypatch):
    directives, quarantine, paths = _build_tree(tmp_path)
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    manifest = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=False,
        timestamp="20260525T120000Z",
    )

    assert manifest["executed"] is False
    assert manifest["orphans_found"] == 2
    assert manifest["moved"] == 0
    assert paths["orphan_a"].exists()
    assert paths["orphan_b"].exists()
    assert paths["paired_marker"].exists()
    assert not (quarantine / "20260525T120000Z_admitted_orphan_sweep").exists()


def test_execute_moves_orphans_only(tmp_path, monkeypatch):
    directives, quarantine, paths = _build_tree(tmp_path)
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    manifest = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=True,
        timestamp="20260525T120000Z",
    )

    sweep_dir = quarantine / "20260525T120000Z_admitted_orphan_sweep" / "markers"
    assert manifest["executed"] is True
    assert manifest["orphans_found"] == 2
    assert manifest["moved"] == 2
    assert not paths["orphan_a"].exists()
    assert not paths["orphan_b"].exists()
    assert (sweep_dir / "ORPHAN_A_S01_V1_P00.txt.admitted").exists()
    assert (sweep_dir / "ORPHAN_B_S02_V1_P00.txt.admitted").exists()
    assert paths["paired_marker"].exists()
    assert paths["paired_txt"].exists()


def test_manifest_schema_per_entry(tmp_path, monkeypatch):
    directives, quarantine, _ = _build_tree(tmp_path)
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    manifest = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=True,
        timestamp="20260525T120000Z",
    )

    assert {"tool", "tool_version", "timestamp_utc", "executed", "orphans_found",
            "moved", "skipped", "entries", "manifest_path"} <= set(manifest)
    for entry in manifest["entries"]:
        assert {"original_path", "quarantine_destination", "size_bytes",
                "mtime_utc", "sha256"} == set(entry)
        assert entry["size_bytes"] == 0
        assert len(entry["sha256"]) == 64
        assert entry["mtime_utc"].endswith("+00:00")
        assert entry["original_path"].startswith("backtest_directives/completed/")


def test_manifest_written_to_disk(tmp_path, monkeypatch):
    directives, quarantine, _ = _build_tree(tmp_path)
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    manifest = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=True,
        timestamp="20260525T120000Z",
    )

    manifest_path = Path(manifest["manifest_path"])
    assert manifest_path.exists()
    disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert disk["orphans_found"] == 2
    assert disk["moved"] == 2
    assert len(disk["entries"]) == 2


def test_idempotent_second_execute_finds_nothing(tmp_path, monkeypatch):
    directives, quarantine, _ = _build_tree(tmp_path)
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    first = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=True,
        timestamp="20260525T120000Z",
    )
    second = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=True,
        timestamp="20260525T120001Z",
    )

    assert first["moved"] == 2
    assert second["moved"] == 0
    assert second["orphans_found"] == 0


def test_dry_run_with_no_orphans_emits_no_sweep_dir(tmp_path, monkeypatch):
    directives = tmp_path / "backtest_directives" / "completed"
    directives.mkdir(parents=True)
    quarantine = tmp_path / "TradeScan_State" / "quarantine"
    quarantine.mkdir(parents=True)
    txt = directives / "ONLY_PAIRED_S01_V1_P00.txt"
    txt.write_text("test:\n  name: ONLY_PAIRED\n", encoding="utf-8")
    (directives / "ONLY_PAIRED_S01_V1_P00.txt.admitted").touch()
    monkeypatch.setattr(sw, "PROJECT_ROOT", tmp_path)

    manifest = sw.sweep_orphan_markers(
        directives_dir=directives,
        quarantine_root=quarantine,
        execute=True,
        timestamp="20260525T120000Z",
    )

    assert manifest["orphans_found"] == 0
    assert manifest["moved"] == 0
    assert manifest["entries"] == []
    assert "manifest_path" not in manifest
    assert not (quarantine / "20260525T120000Z_admitted_orphan_sweep").exists()
