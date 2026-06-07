"""Unit tests for tools/lint_guard_manifest_sync.py.

The lint blocks a commit when a Critical-Guard-Set tool is staged but
tools/tools_manifest.json was not regenerated AND restaged to match the
STAGED tool content. These drive the pure core (check_staged) with an
in-memory blob reader -- no real git repo required -- plus one test that
pins the local canonical hasher to the authoritative implementation.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.lint_guard_manifest_sync import (  # noqa: E402
    check_staged,
    _canonical_sha256_bytes,
)

# Real GUARD_FILES entries so the "tools/<key>" mapping is exercised for
# both a top-level and a subdirectory entry.
TOOL_KEY = "run_pipeline.py"
TOOL_PATH = "tools/run_pipeline.py"
SUBDIR_KEY = "orchestration/runner.py"
SUBDIR_PATH = "tools/orchestration/runner.py"
MANIFEST_PATH = "tools/tools_manifest.json"


def _manifest_blob(hashes: dict) -> bytes:
    return json.dumps({"file_hashes": hashes}).encode("utf-8")


def _reader(blobs: dict):
    def read(path):
        return blobs[path]  # KeyError if a not-staged path is read
    return read


def test_no_guarded_tool_staged_passes():
    # A tools/ file that is NOT in GUARD_FILES must be ignored.
    staged = ["docs/x.md", "tools/some_helper_not_guarded.py"]
    assert check_staged(staged, _reader({})) == []


def test_empty_staged_passes():
    assert check_staged([], _reader({})) == []


def test_guarded_tool_with_matching_manifest_passes():
    content = b"# run_pipeline v2\n"
    h = _canonical_sha256_bytes(content).upper()
    blobs = {TOOL_PATH: content, MANIFEST_PATH: _manifest_blob({TOOL_KEY: h})}
    assert check_staged([TOOL_PATH, MANIFEST_PATH], _reader(blobs)) == []


def test_guarded_tool_manifest_not_staged_fails():
    # Scenario B: tool staged, manifest regenerated in the working tree but
    # NOT git-added. The staged set lacks the manifest -> block.
    blobs = {TOOL_PATH: b"# changed\n"}
    problems = check_staged([TOOL_PATH], _reader(blobs))
    assert len(problems) == 1
    assert "not staged" in problems[0]
    assert TOOL_PATH in problems[0]


def test_guarded_tool_stale_manifest_fails():
    # Scenario A: tool changed, manifest staged but still has the old hash.
    new_content = b"# run_pipeline v2 (new)\n"
    old_hash = _canonical_sha256_bytes(b"# run_pipeline v1 (old)\n").upper()
    blobs = {
        TOOL_PATH: new_content,
        MANIFEST_PATH: _manifest_blob({TOOL_KEY: old_hash}),
    }
    problems = check_staged([TOOL_PATH, MANIFEST_PATH], _reader(blobs))
    assert len(problems) == 1
    assert "!=" in problems[0]


def test_guarded_tool_missing_key_fails():
    blobs = {
        TOOL_PATH: b"# changed\n",
        MANIFEST_PATH: _manifest_blob({}),  # manifest staged but no entry
    }
    problems = check_staged([TOOL_PATH, MANIFEST_PATH], _reader(blobs))
    assert len(problems) == 1
    assert "not present" in problems[0]


def test_subdir_guarded_tool_resolves():
    content = b"# runner\n"
    h = _canonical_sha256_bytes(content).upper()
    blobs = {SUBDIR_PATH: content, MANIFEST_PATH: _manifest_blob({SUBDIR_KEY: h})}
    assert check_staged([SUBDIR_PATH, MANIFEST_PATH], _reader(blobs)) == []
    # ...and a subdir entry missing its restaged manifest still fails.
    problems = check_staged([SUBDIR_PATH], _reader({SUBDIR_PATH: content}))
    assert len(problems) == 1
    assert SUBDIR_PATH in problems[0]


def test_multiple_guarded_tools_partial_failure():
    good = b"# good\n"
    good_h = _canonical_sha256_bytes(good).upper()
    bad = b"# bad new content\n"
    stale_h = _canonical_sha256_bytes(b"# bad old content\n").upper()
    blobs = {
        TOOL_PATH: good,
        SUBDIR_PATH: bad,
        MANIFEST_PATH: _manifest_blob({TOOL_KEY: good_h, SUBDIR_KEY: stale_h}),
    }
    problems = check_staged([TOOL_PATH, SUBDIR_PATH, MANIFEST_PATH], _reader(blobs))
    assert len(problems) == 1
    assert SUBDIR_PATH in problems[0]


def test_lowercase_manifest_hash_still_matches():
    content = b"# tool\n"
    h_lower = _canonical_sha256_bytes(content)  # lowercase, as a hand-edit might be
    blobs = {TOOL_PATH: content, MANIFEST_PATH: _manifest_blob({TOOL_KEY: h_lower})}
    assert check_staged([TOOL_PATH, MANIFEST_PATH], _reader(blobs)) == []


def test_unreadable_manifest_fails():
    blobs = {TOOL_PATH: b"# x\n", MANIFEST_PATH: b"{not valid json"}
    problems = check_staged([TOOL_PATH, MANIFEST_PATH], _reader(blobs))
    assert len(problems) == 1
    assert "unreadable" in problems[0]


def test_canonical_hash_matches_authoritative():
    """Pin the local bytes-hasher to verify_engine_integrity.canonical_sha256.
    If the canonical definition diverges, this fails and forces a fix."""
    from tools.verify_engine_integrity import canonical_sha256
    data = b"line1\r\nline2\r\n# crlf content\n"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tf:
        tf.write(data)
        tmp = Path(tf.name)
    try:
        assert _canonical_sha256_bytes(data) == canonical_sha256(tmp)
    finally:
        tmp.unlink()


def test_crlf_and_lf_hash_identical():
    assert _canonical_sha256_bytes(b"a\r\nb\r\n") == _canonical_sha256_bytes(b"a\nb\n")


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
