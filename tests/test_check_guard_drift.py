"""Unit tests for tools/check_guard_drift.py.

check_guard_drift is the EARLY-WARNING (working-tree) twin of the commit-time
lint and the run-time guard: find_drift() lists guarded tools whose on-disk
canonical hash differs from tools_manifest.json. These drive the pure core
against a synthetic temp project (no real repo / git needed), plus one test
that pins the local canonical hasher to the authoritative implementation --
the same discipline as test_lint_guard_manifest_sync.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.check_guard_drift import (  # noqa: E402
    canonical_sha256_path,
    find_drift,
)


def _build_project(tmp: Path, files: dict[str, bytes], manifest: dict) -> Path:
    """Create tmp/tools/<key> for each file and tmp/tools/tools_manifest.json.

    Manifest keys are tools-relative (e.g. "run_pipeline.py",
    "orchestration/runner.py"), matching the real layout. Returns the manifest
    path.
    """
    tools = tmp / "tools"
    for rel, content in files.items():
        p = tools / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    mpath = tools / "tools_manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    return mpath


def _hash(content: bytes) -> str:
    """Canonical (LF-normalized, uppercase) hash of raw bytes, via a temp file."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tf:
        tf.write(content)
        p = Path(tf.name)
    try:
        return canonical_sha256_path(p)
    finally:
        p.unlink()


def test_in_sync_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        content = b"# run_pipeline\n"
        mpath = _build_project(
            tmp,
            {"run_pipeline.py": content},
            {"file_hashes": {"run_pipeline.py": _hash(content)}},
        )
        assert find_drift(project_root=tmp, manifest_path=mpath) == []


def test_drift_detected():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        old_hash = _hash(b"# old content\n")
        mpath = _build_project(
            tmp,
            {"run_pipeline.py": b"# NEW content\n"},  # on disk != manifest
            {"file_hashes": {"run_pipeline.py": old_hash}},
        )
        drift = find_drift(project_root=tmp, manifest_path=mpath)
        assert len(drift) == 1
        assert drift[0]["file"] == "run_pipeline.py"
        assert drift[0]["status"] == "DRIFT"
        assert drift[0]["manifest"] == old_hash
        assert drift[0]["disk"] == _hash(b"# NEW content\n")


def test_missing_file_reported():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # Manifest records a file we never create on disk.
        mpath = _build_project(
            tmp,
            {},
            {"file_hashes": {"deleted_tool.py": _hash(b"# gone\n")}},
        )
        drift = find_drift(project_root=tmp, manifest_path=mpath)
        assert len(drift) == 1
        assert drift[0]["status"] == "MISSING"
        assert drift[0]["file"] == "deleted_tool.py"
        assert drift[0]["disk"] is None


def test_subdir_key_resolves():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        good = b"# runner\n"
        bad_new = b"# runner CHANGED\n"
        mpath = _build_project(
            tmp,
            {"orchestration/runner.py": bad_new, "run_pipeline.py": good},
            {
                "file_hashes": {
                    "orchestration/runner.py": _hash(b"# runner OLD\n"),
                    "run_pipeline.py": _hash(good),
                }
            },
        )
        drift = find_drift(project_root=tmp, manifest_path=mpath)
        # Only the subdir entry drifts; the in-sync top-level entry is silent.
        assert [x["file"] for x in drift] == ["orchestration/runner.py"]
        assert drift[0]["status"] == "DRIFT"


def test_lowercase_manifest_hash_still_matches():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        content = b"# tool\n"
        lower = _hash(content).lower()  # as a hand-edit / older manifest might store
        mpath = _build_project(
            tmp,
            {"run_pipeline.py": content},
            {"file_hashes": {"run_pipeline.py": lower}},
        )
        assert find_drift(project_root=tmp, manifest_path=mpath) == []


def test_missing_manifest_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        absent = tmp / "tools" / "tools_manifest.json"
        assert find_drift(project_root=tmp, manifest_path=absent) == []


def test_unreadable_manifest_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mpath = tmp / "tools" / "tools_manifest.json"
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text("{not valid json", encoding="utf-8")
        # Never crash on a corrupt manifest -- the runtime guard owns that.
        assert find_drift(project_root=tmp, manifest_path=mpath) == []


def test_crlf_and_lf_hash_identical():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        crlf = tmp / "crlf.py"
        lf = tmp / "lf.py"
        crlf.write_bytes(b"a\r\nb\r\n")
        lf.write_bytes(b"a\nb\n")
        assert canonical_sha256_path(crlf) == canonical_sha256_path(lf)


def test_canonical_hash_matches_authoritative():
    """Pin canonical_sha256_path to verify_engine_integrity.canonical_sha256.
    If the canonical definition diverges, this fails and forces a fix."""
    from tools.verify_engine_integrity import canonical_sha256

    data = b"line1\r\nline2\r\n# crlf content\n"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tf:
        tf.write(data)
        tmp = Path(tf.name)
    try:
        # canonical_sha256 returns lowercase; check_guard_drift returns uppercase.
        assert canonical_sha256_path(tmp) == canonical_sha256(tmp).upper()
    finally:
        tmp.unlink()


if __name__ == "__main__":
    import subprocess

    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
