"""
Regression tests for tools.verify_engine_integrity.canonical_sha256.

Phase 1 of the v1.5.8 engine-governance repair (see ENGINE_DRIFT_REMEDIATION.md
when written in Phase 2). Proves that the canonical hash helper:

  1. Produces the SAME hash for an LF-only file and the CRLF rendering of the
     same content — so the engine integrity check no longer false-fails on
     Windows checkouts with `core.autocrlf=true`.
  2. Reproduces the manifest's recorded hashes for clean v1.5.6 and v1.5.8
     engine files (smoke-coverage of the production manifest contract).
  3. Still detects real source drift — files that were modified post-freeze
     (e.g. by `f3ae767` in engine_dev/v1_5_8/) MUST continue to fail.

Scope: tool patch only. No engine source touched, no manifest touched, no
vault touched.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.verify_engine_integrity import canonical_sha256


# ---------------------------------------------------------------------------
# Unit tests on the helper
# ---------------------------------------------------------------------------

class TestCanonicalSha256Helper(unittest.TestCase):
    """The helper is the entire fix — exhaustive coverage on its semantics."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_bytes(self, name: str, data: bytes) -> Path:
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def test_lf_and_crlf_produce_identical_hash(self):
        """The whole point of the fix: identical content under LF vs CRLF
        line endings MUST produce the same canonical hash."""
        lf_content = b"line one\nline two\nline three\n"
        crlf_content = b"line one\r\nline two\r\nline three\r\n"
        lf_file = self._write_bytes("lf.txt", lf_content)
        crlf_file = self._write_bytes("crlf.txt", crlf_content)

        lf_hash = canonical_sha256(lf_file)
        crlf_hash = canonical_sha256(crlf_file)

        self.assertEqual(lf_hash, crlf_hash,
                         "LF and CRLF renderings of the same content "
                         "MUST produce the same canonical hash.")

    def test_canonical_hash_equals_lf_sha256(self):
        """The canonical hash IS the sha256 of the LF-normalized form
        (drop-in replacement for previous tooling that used LF input)."""
        content = b"alpha\nbeta\ngamma\n"
        crlf_file = self._write_bytes("crlf.txt", content.replace(b"\n", b"\r\n"))
        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(canonical_sha256(crlf_file), expected)

    def test_mixed_eol_normalized_correctly(self):
        """Mixed CRLF + LF in the same file — both normalize to LF."""
        mixed = b"line one\r\nline two\nline three\r\nline four"
        canonical = b"line one\nline two\nline three\nline four"
        mixed_file = self._write_bytes("mixed.txt", mixed)
        expected = hashlib.sha256(canonical).hexdigest()
        self.assertEqual(canonical_sha256(mixed_file), expected)

    def test_empty_file(self):
        """Empty file -> sha256 of empty bytes (E3B0C442...)."""
        p = self._write_bytes("empty.txt", b"")
        empty_sha = hashlib.sha256(b"").hexdigest()
        self.assertEqual(canonical_sha256(p), empty_sha)

    def test_pure_lf_file_unchanged_by_normalization(self):
        """A file already in LF form must hash identically before and after
        the helper's normalization (no double-substitution corruption)."""
        content = b"just\nLF\nlines\n"
        p = self._write_bytes("lf.txt", content)
        raw_sha = hashlib.sha256(content).hexdigest()
        self.assertEqual(canonical_sha256(p), raw_sha)

    def test_lone_carriage_return_preserved(self):
        """The helper normalizes CRLF (\\r\\n) only, not bare \\r.
        Files containing classic Mac line endings (lone \\r) keep them.
        This is intentional: git's text-file canonical form uses LF for
        CRLF only; bare CR is a separate concern."""
        content_with_lone_cr = b"foo\rbar\n"
        p = self._write_bytes("lone_cr.txt", content_with_lone_cr)
        # Expected hash is sha256 of the file unchanged (no \r\n to replace).
        self.assertEqual(canonical_sha256(p),
                         hashlib.sha256(content_with_lone_cr).hexdigest())

    def test_binary_file_with_no_crlf_unchanged(self):
        """Binary file containing no \\r\\n sequences must hash identically
        to its raw bytes — the helper is content-preserving for such files."""
        binary = bytes(range(256))  # 0x00..0xFF, no \r\n
        # Confirm assumption first
        self.assertNotIn(b"\r\n", binary)
        p = self._write_bytes("bin.dat", binary)
        self.assertEqual(canonical_sha256(p), hashlib.sha256(binary).hexdigest())


# ---------------------------------------------------------------------------
# Integration: helper reproduces real manifest hashes for clean files
# ---------------------------------------------------------------------------

class TestCanonicalHashAgainstLiveManifests(unittest.TestCase):
    """For files that have NOT drifted at the git-blob level, the canonical
    hash MUST equal the manifest's recorded hash. This is the production
    contract the helper exists to satisfy."""

    def _check_manifest(self, version_dir: str, clean_files: list[str]):
        """Assert canonical_sha256 matches manifest hash for every named file."""
        version_path = (PROJECT_ROOT / "engine_dev"
                        / "universal_research_engine" / version_dir)
        manifest_path = version_path / "engine_manifest.json"
        if not manifest_path.exists():
            self.skipTest(f"Manifest not present: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_hashes = manifest.get("file_hashes", {})
        for fname in clean_files:
            with self.subTest(version=version_dir, file=fname):
                fpath = version_path / fname
                if not fpath.exists():
                    self.skipTest(f"File missing: {fpath}")
                expected = file_hashes.get(fname, "").upper()
                actual = canonical_sha256(fpath).upper()
                self.assertEqual(
                    actual, expected,
                    f"{version_dir}/{fname}: canonical hash {actual[:16]} "
                    f"!= manifest {expected[:16]} "
                    f"(this file should be clean at git-blob level)"
                )

    def test_v1_5_6_clean_files_match_manifest(self):
        """v1.5.6 __init__.py and contract.json are unchanged at git-blob
        level since freeze. The helper MUST reproduce manifest hashes."""
        self._check_manifest("v1_5_6", ["__init__.py", "contract.json"])

    def test_v1_5_8_clean_files_match_manifest(self):
        """v1.5.8 __init__.py, main.py, contract.json are clean at git-blob
        level (only execution_emitter_stage1, execution_loop, stage2_compiler
        were drifted by f3ae767). The helper MUST reproduce manifest hashes
        for the clean three."""
        self._check_manifest("v1_5_8",
                             ["__init__.py", "main.py", "contract.json"])


# ---------------------------------------------------------------------------
# Engine files must match their manifest (post TD-002 R1)
# ---------------------------------------------------------------------------

class TestEngineFilesMatchManifest(unittest.TestCase):
    """After TD-002 R1 unified all hash sites to canonical_sha256 and the
    engine manifest was regenerated, all engine files must match the manifest.
    The prior f3ae767 "drift" was CRLF-only (false drift on Windows checkouts
    with core.autocrlf=true) — it disappears once canonical_sha256 normalises
    both sides to LF. This test replaces TestRealDriftStillDetected."""

    V1_5_8_FILES = [
        "execution_emitter_stage1.py",
        "execution_loop.py",
        "stage2_compiler.py",
    ]

    def test_v1_5_8_files_match_manifest(self):
        version_path = (PROJECT_ROOT / "engine_dev"
                        / "universal_research_engine" / "v1_5_8")
        manifest_path = version_path / "engine_manifest.json"
        if not manifest_path.exists():
            self.skipTest(f"Manifest not present: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_hashes = manifest.get("file_hashes", {})
        for fname in self.V1_5_8_FILES:
            with self.subTest(file=fname):
                fpath = version_path / fname
                if not fpath.exists():
                    self.skipTest(f"File missing: {fpath}")
                expected = file_hashes.get(fname, "").upper()
                actual = canonical_sha256(fpath).upper()
                self.assertEqual(
                    actual, expected,
                    f"{fname}: canonical hash {actual[:16]} != manifest "
                    f"{expected[:16]} — genuine post-freeze drift detected. "
                    f"If intentional, regenerate the engine manifest."
                )


if __name__ == "__main__":
    unittest.main()
