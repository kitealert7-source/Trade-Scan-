"""Regression tests for INFRA-AUDIT C2 closure — manifest integrity guard.

Before fix: `verify_tools_timestamp_guard` accepted/rejected based on
file mtime vs manifest mtime. Race-prone on Windows NTFS, and trivially
defeated by regenerating the manifest after a tampered file (the new
manifest mtime makes the gate "pass" with stale recorded hashes).

After fix: gate compares actual file sha256 to the manifest's recorded
hash. Three test cases:
  1. Modified tool + stale manifest (manifest hash != file hash) -> FAIL
  2. Regenerated manifest with matching hashes                    -> PASS
  3. Timestamp spoofing (mtime touched but content unchanged)     -> PASS
                                                                     (correct: the gate is content-based, not time-based)
  4. Reverse spoofing (content changed but mtime restored)        -> FAIL
                                                                     (this is the attack the old gate missed)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import target module via importlib (run_pipeline.py is a script).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "run_pipeline_mod",
    PROJECT_ROOT / "tools" / "run_pipeline.py",
)
_run_pipeline = importlib.util.module_from_spec(_spec)
sys.modules["run_pipeline_mod"] = _run_pipeline
_spec.loader.exec_module(_run_pipeline)

verify_tools_timestamp_guard = _run_pipeline.verify_tools_timestamp_guard
PipelineExecutionError = _run_pipeline.PipelineExecutionError
_compute_manifest_file_hash = _run_pipeline._compute_manifest_file_hash


@pytest.fixture
def fake_repo(tmp_path):
    """Build a minimal project-root layout with a tool + manifest."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    tool = repo / "tools" / "fake_tool.py"
    tool.write_text("# v1\nprint('hi')\n", encoding="utf-8")
    h = _compute_manifest_file_hash(tool)
    manifest = repo / "tools" / "tools_manifest.json"
    manifest.write_text(
        json.dumps({"generated_at": "2026-05-03T00:00:00Z",
                    "file_hashes": {"fake_tool.py": h}}, indent=2),
        encoding="utf-8"
    )
    return repo, tool, manifest


def test_matching_hashes_pass(fake_repo):
    """Baseline: tool unchanged, manifest matches → guard passes silently."""
    repo, _, _ = fake_repo
    # Should not raise.
    verify_tools_timestamp_guard(repo)


def test_modified_tool_with_stale_manifest_fails(fake_repo):
    """Tool changes, manifest still references old hash → guard FAILs.
    This is the primary regression case."""
    repo, tool, _ = fake_repo
    tool.write_text("# tampered\n", encoding="utf-8")
    with pytest.raises(PipelineExecutionError) as excinfo:
        verify_tools_timestamp_guard(repo)
    msg = str(excinfo.value)
    assert "fake_tool.py" in msg
    assert "hash mismatch" in msg.lower()


def test_regenerated_manifest_passes(fake_repo):
    """Tool changes AND manifest regenerated with new hash → guard passes.
    This is the legitimate flow."""
    repo, tool, manifest = fake_repo
    tool.write_text("# v2 with intended changes\n", encoding="utf-8")
    new_hash = _compute_manifest_file_hash(tool)
    manifest.write_text(
        json.dumps({"generated_at": "2026-05-03T00:01:00Z",
                    "file_hashes": {"fake_tool.py": new_hash}}, indent=2),
        encoding="utf-8"
    )
    # Should not raise.
    verify_tools_timestamp_guard(repo)


def test_mtime_spoof_with_unchanged_content_passes(fake_repo):
    """Touch the tool's mtime past the manifest's mtime, but don't change
    the content. The OLD gate would fail this (mtime > manifest mtime).
    The NEW gate correctly passes — content-based, not time-based."""
    repo, tool, manifest = fake_repo
    # Make manifest mtime old, tool mtime new — content unchanged.
    old_mtime = manifest.stat().st_mtime - 3600  # 1h ago
    os.utime(manifest, (old_mtime, old_mtime))
    new_mtime = time.time()
    os.utime(tool, (new_mtime, new_mtime))
    # OLD gate would have failed. NEW gate passes.
    verify_tools_timestamp_guard(repo)


def test_reverse_mtime_spoof_with_changed_content_fails(fake_repo):
    """Tool content changed, mtime artificially restored to BEFORE manifest
    mtime. OLD mtime gate would PASS (file appears older than manifest).
    NEW gate FAILs because content hash mismatches. This is the attack the
    old gate could not detect."""
    repo, tool, manifest = fake_repo
    # Change content
    tool.write_text("# attack: drift hidden by mtime restore\n", encoding="utf-8")
    # Restore mtime to BEFORE manifest's mtime
    manifest_mtime = manifest.stat().st_mtime
    spoofed = manifest_mtime - 60
    os.utime(tool, (spoofed, spoofed))
    # OLD mtime-based gate would PASS here (file mtime < manifest mtime).
    # NEW hash-based gate must still FAIL.
    with pytest.raises(PipelineExecutionError) as excinfo:
        verify_tools_timestamp_guard(repo)
    assert "hash mismatch" in str(excinfo.value).lower()


def test_missing_tool_file_does_not_raise(fake_repo):
    """File listed in manifest but absent on disk: legacy behavior is to
    skip silently (caller may deliberately remove tools)."""
    repo, tool, _ = fake_repo
    tool.unlink()
    # Should not raise; missing file is not an integrity failure of the
    # gate itself.
    verify_tools_timestamp_guard(repo)


def test_missing_manifest_does_not_raise(fake_repo):
    """No manifest at all → no gate, return silently."""
    repo, _, manifest = fake_repo
    manifest.unlink()
    verify_tools_timestamp_guard(repo)


def test_recorded_hash_case_insensitive(fake_repo):
    """The manifest stores uppercase hex; verify lowercase entries also
    match (defensive — generate_guard_manifest writes uppercase but a
    hand-edit might use lowercase)."""
    repo, tool, manifest = fake_repo
    h_lower = _compute_manifest_file_hash(tool).lower()
    manifest.write_text(
        json.dumps({"file_hashes": {"fake_tool.py": h_lower}}, indent=2),
        encoding="utf-8"
    )
    # Should not raise.
    verify_tools_timestamp_guard(repo)


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
