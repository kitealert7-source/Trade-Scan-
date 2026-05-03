"""
Regression tests for the 2026-05-03 admission race stabilization.

Background
----------
The framework had a race condition between admission-time auto-consistency,
preflight-time provisioner rewrites, and EXPERIMENT_DISCIPLINE checks:

  1. Auto-consistency canonicalized strategy.py SIGNATURE block, then wrote
     a legacy timestamp-only approval marker (no sha256).
  2. Provisioner rewrote strategy.py during preflight (idempotent
     canonicalization), bumping mtime past the marker.
  3. EXPERIMENT_DISCIPLINE compared raw mtimes — falsely tripped because
     marker mtime < strategy.py mtime by milliseconds, even though content
     was unchanged.

Result: every batch sweep across multiple sweeps/architectures hit
EXPERIMENT_DISCIPLINE blocks within preflight, requiring manual marker
refreshes between admissions.

Stabilization
-------------
  • Auto-consistency now writes hash-based markers (sha256 of post-
    canonicalization strategy.py).
  • Provisioner refreshes the hash marker after writing strategy.py.
  • EXPERIMENT_DISCIPLINE checks (preflight + reset_directive) use
    is_approval_current() — content-equality via sha256, immune to mtime.
  • Legacy timestamp-only markers continue to work via internal mtime
    fallback in is_approval_current; auto-consistency upgrades them on
    the next admission pass.

These tests cover the contract directly:
  1. Hash-based marker round-trip
  2. Legacy timestamp-only marker mtime fallback
  3. Idempotent rewrite (byte-identical content) preserves approval
  4. Genuine content change invalidates approval
  5. Cross-process marker validity (file content, not in-memory state)
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.approval_marker import (
    compute_strategy_hash,
    is_approval_current,
    read_approved_marker,
    write_approved_marker,
)


class TestHashMarkerRoundtrip(unittest.TestCase):
    """1. Single-run scenario: write marker, validate, read back."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.strat = self.tmp / "strategy.py"
        self.marker = self.tmp / "strategy.py.approved"
        self.strat.write_text("class Strategy: pass\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_then_validate(self):
        sha = compute_strategy_hash(self.strat)
        write_approved_marker(self.marker, sha)
        self.assertTrue(is_approval_current(self.strat, self.marker))

    def test_marker_records_sha256(self):
        sha = compute_strategy_hash(self.strat)
        write_approved_marker(self.marker, sha)
        m = read_approved_marker(self.marker)
        self.assertIsNotNone(m)
        self.assertTrue(m.has_hash)
        self.assertEqual(m.strategy_sha256, sha)


class TestLegacyMarkerCompat(unittest.TestCase):
    """2. Legacy timestamp-only marker behavior (back-compat)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.strat = self.tmp / "strategy.py"
        self.marker = self.tmp / "strategy.py.approved"
        self.strat.write_text("class Strategy: pass\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_marker_mtime_pass(self):
        """Legacy marker (no sha) created AFTER strategy.py — passes mtime."""
        time.sleep(0.05)
        self.marker.write_text(
            "approved: 2026-01-01T00:00:00+00:00\n", encoding="utf-8"
        )
        self.assertTrue(is_approval_current(self.strat, self.marker))

    def test_legacy_marker_mtime_fail(self):
        """Legacy marker (no sha) created BEFORE strategy.py modification — fails."""
        self.marker.write_text(
            "approved: 2026-01-01T00:00:00+00:00\n", encoding="utf-8"
        )
        time.sleep(0.05)
        self.strat.write_text("class Strategy: pass  # modified\n", encoding="utf-8")
        self.assertFalse(is_approval_current(self.strat, self.marker))


class TestIdempotentRewriteContract(unittest.TestCase):
    """3. The race-condition fix: byte-identical rewrite preserves approval.

    This is the core regression — provisioner rewrites strategy.py to
    byte-identical content during preflight, bumping mtime. With the
    hash-based marker, this MUST be a no-op for is_approval_current.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.strat = self.tmp / "strategy.py"
        self.marker = self.tmp / "strategy.py.approved"
        self.original_content = (
            "# strategy module\nclass Strategy:\n    name = 'test'\n"
        )
        self.strat.write_text(self.original_content, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_byte_identical_rewrite_after_approval(self):
        """Approve, then rewrite identical content (provisioner-style),
        marker MUST still validate."""
        sha = compute_strategy_hash(self.strat)
        write_approved_marker(self.marker, sha)
        self.assertTrue(is_approval_current(self.strat, self.marker))

        # Simulate provisioner rewriting byte-identical content
        time.sleep(0.05)
        self.strat.write_text(self.original_content, encoding="utf-8")

        # mtime is now newer than marker, but content is identical → approval current
        self.assertGreater(
            self.strat.stat().st_mtime, self.marker.stat().st_mtime,
            "Test setup error: strategy.py mtime should be > marker mtime"
        )
        self.assertTrue(
            is_approval_current(self.strat, self.marker),
            "Hash-based marker must validate byte-identical content "
            "regardless of mtime drift (race-condition regression)"
        )


class TestGenuineContentChangeInvalidates(unittest.TestCase):
    """4. Re-approval after legitimate logic change."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.strat = self.tmp / "strategy.py"
        self.marker = self.tmp / "strategy.py.approved"
        self.strat.write_text(
            "class Strategy:\n    threshold = 0.5\n", encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_logic_change_invalidates_marker(self):
        sha_v1 = compute_strategy_hash(self.strat)
        write_approved_marker(self.marker, sha_v1)
        self.assertTrue(is_approval_current(self.strat, self.marker))

        # Genuine content change — different threshold value
        time.sleep(0.05)
        self.strat.write_text(
            "class Strategy:\n    threshold = 0.8\n", encoding="utf-8"
        )
        self.assertFalse(
            is_approval_current(self.strat, self.marker),
            "Genuine content change MUST invalidate hash-based marker"
        )

        # Re-approval restores validity
        sha_v2 = compute_strategy_hash(self.strat)
        write_approved_marker(self.marker, sha_v2)
        self.assertTrue(is_approval_current(self.strat, self.marker))
        self.assertNotEqual(sha_v1, sha_v2)


class TestCrossProcessMarkerValidity(unittest.TestCase):
    """5. Cross-process: marker file content is the only source of truth.

    The race involved the admission process writing strategy.py + marker,
    then a SUBPROCESS (preflight) reading them. mtime granularity could
    differ across subprocess boundaries on Windows. Hash-based markers
    are file-content-only and immune.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.strat = self.tmp / "strategy.py"
        self.marker = self.tmp / "strategy.py.approved"
        self.strat.write_text("class Strategy: pass\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_subprocess_validation_matches_in_process(self):
        """Validate the marker in-process AND via subprocess; both agree."""
        sha = compute_strategy_hash(self.strat)
        write_approved_marker(self.marker, sha)

        # In-process check
        in_proc = is_approval_current(self.strat, self.marker)
        self.assertTrue(in_proc)

        # Subprocess check via tools.approval_marker
        cmd = [
            sys.executable, "-c",
            f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}');"
            f"from tools.approval_marker import is_approval_current;"
            f"from pathlib import Path;"
            f"print(is_approval_current(Path(r'{self.strat}'), Path(r'{self.marker}')))",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0,
                         f"Subprocess failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "True",
                         "Subprocess validation must match in-process result")


class TestAutoConsistencyWritesHashMarker(unittest.TestCase):
    """6. enforce_signature_consistency writes hash-based markers
    (regression test for tools/orchestration/pre_execution.py fix)."""

    def test_inspect_pre_execution_uses_canonical_helper(self):
        """Static check: pre_execution.py imports + calls write_approved_marker."""
        src = (PROJECT_ROOT / "tools" / "orchestration" / "pre_execution.py"
               ).read_text(encoding="utf-8")
        self.assertIn("from tools.approval_marker import", src,
                      "pre_execution.py MUST import approval_marker helpers")
        self.assertIn("write_approved_marker", src,
                      "pre_execution.py MUST call write_approved_marker "
                      "(not raw write_text with timestamp-only format)")
        # Negative: no raw timestamp-only marker write should remain
        self.assertNotIn(
            'approved_marker.write_text(\n            f"approved:',
            src,
            "Legacy timestamp-only marker write must be removed",
        )

    def test_inspect_provisioner_refreshes_marker_after_write(self):
        """Static check: strategy_provisioner.py refreshes hash marker after
        writing strategy.py."""
        src = (PROJECT_ROOT / "tools" / "strategy_provisioner.py"
               ).read_text(encoding="utf-8")
        self.assertIn("write_approved_marker", src,
                      "strategy_provisioner.py MUST refresh hash marker "
                      "after rewriting strategy.py")

    def test_inspect_preflight_uses_is_approval_current(self):
        """Static check: governance/preflight.py uses is_approval_current
        for EXPERIMENT_DISCIPLINE check (not raw mtime comparison)."""
        src = (PROJECT_ROOT / "governance" / "preflight.py"
               ).read_text(encoding="utf-8")
        self.assertIn("is_approval_current", src,
                      "preflight.py EXPERIMENT_DISCIPLINE check MUST use "
                      "is_approval_current (hash-aware), not raw mtime")

    def test_inspect_reset_directive_uses_is_approval_current(self):
        """Static check: reset_directive.py uses is_approval_current."""
        src = (PROJECT_ROOT / "tools" / "reset_directive.py"
               ).read_text(encoding="utf-8")
        self.assertIn("is_approval_current", src,
                      "reset_directive.py MUST use is_approval_current "
                      "(hash-aware) instead of raw mtime")

    def test_inspect_reset_directive_handles_stranded_admission_ghost(self):
        """Static check: reset_directive.py recovers stranded admission ghosts
        (state==INITIALIZED + run IDLE) — closes the second race class where
        a directive was admitted but never advanced past Stage 0."""
        src = (PROJECT_ROOT / "tools" / "reset_directive.py"
               ).read_text(encoding="utf-8")
        self.assertIn("_is_stranded_admission_ghost", src,
                      "reset_directive.py MUST detect stranded admission ghosts")
        self.assertIn("INITIALIZED_STRANDED", src,
                      "reset_directive.py MUST audit stranded-ghost cleanup as "
                      "INITIALIZED_STRANDED (distinct from INITIALIZED_GHOST)")


if __name__ == "__main__":
    unittest.main()
