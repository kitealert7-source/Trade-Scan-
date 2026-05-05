"""Regression coverage for the integrity / infra bugs surfaced during the
FVG idea-64 research session (2026-05-04).

Each test corresponds to one bug class. If any of these regressions reappear,
the corresponding test fails — preventing silent re-introduction.

Bugs covered:
  R1 — Hash-function divergence across the four hashing sites.
       run_pipeline.py:_compute_manifest_file_hash, generate_guard_manifest.py,
       generate_engine_manifest.py, and governance/preflight.py must all
       delegate to verify_engine_integrity.canonical_sha256 (LF-normalized).
       Pre-fix: at least one used raw hashlib.sha256(read_bytes()), causing
       Windows CRLF false-failures and root-of-trust violation loops
       (governance/reset_audit_log.csv 2026-05-03 entries).

  R2 — verify_engine_integrity.py hardcoded engine version.
       Pre-fix: line 34 loaded ENGINE_VERSION from a hardcoded
       v1_5_6/main.py path. The integrity check verified the wrong engine
       after each FROZEN promotion. Post-fix: uses
       tools.pipeline_utils.get_engine_version() (registry-driven, same
       resolver the orchestrator uses).

  R3 — Dummy test strategies in verify_engine_integrity.py returned None
       from check_exit. Engine v1.5.8 contract v1.3 rejects None
       (must be bool | str). Pre-fix: SessionLimitStrategy2,
       UnlimitedSessionStrategy, DiagnosticsStrategy returned None.

  R4 — Session filter signal-time vs fill-time clock semantics.
       FilterStack.session_filter matches against the SIGNAL bar's
       bar_hour. Under signal_bar_idx == fill_bar_idx - 1
       ("next_bar_open"), the FILL lands one hour later. exclude_hours_utc
       must be SHIFTED LEFT to keep fills out of an intended window.
       Documented in engines/filter_stack.py per FVG S04→S05 audit.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.verify_engine_integrity import canonical_sha256  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class R1_HashUnification(unittest.TestCase):
    """All four hashing sites must produce identical canonical hashes for the
    same input. Catches re-introduction of raw hashlib.sha256 anywhere in
    the manifest pipeline."""

    def setUp(self):
        # A representative tools/ file with mixed content (varies on Windows
        # vs Linux line-endings). Use run_pipeline.py itself.
        self.target = PROJECT_ROOT / "tools" / "run_pipeline.py"
        self.assertTrue(self.target.exists())

    def test_run_pipeline_compute_manifest_file_hash_uses_canonical(self):
        """tools/run_pipeline.py:_compute_manifest_file_hash agrees with
        canonical_sha256."""
        from tools.run_pipeline import _compute_manifest_file_hash
        actual = _compute_manifest_file_hash(self.target).upper()
        expected = canonical_sha256(self.target).upper()
        self.assertEqual(actual, expected,
            "run_pipeline._compute_manifest_file_hash diverged from canonical_sha256. "
            "Did someone re-introduce raw hashlib.sha256(read_bytes())?")

    def test_generate_guard_manifest_uses_canonical(self):
        """tools/generate_guard_manifest.py:compute_sha256 agrees with
        canonical_sha256."""
        mod = _load_module(
            "_ggm", PROJECT_ROOT / "tools" / "generate_guard_manifest.py"
        )
        actual = mod.compute_sha256(self.target).upper()
        expected = canonical_sha256(self.target).upper()
        self.assertEqual(actual, expected,
            "generate_guard_manifest.compute_sha256 diverged from canonical_sha256.")

    def test_generate_engine_manifest_uses_canonical(self):
        """tools/generate_engine_manifest.py:compute_sha256 agrees with
        canonical_sha256."""
        mod = _load_module(
            "_gem", PROJECT_ROOT / "tools" / "generate_engine_manifest.py"
        )
        actual = mod.compute_sha256(self.target).upper()
        expected = canonical_sha256(self.target).upper()
        self.assertEqual(actual, expected,
            "generate_engine_manifest.compute_sha256 diverged from canonical_sha256.")

    def test_preflight_root_of_trust_uses_canonical(self):
        """governance/preflight.py:check_engine_integrity must compute
        verify_engine_integrity.py's hash with canonical_sha256, NOT raw
        hashlib.sha256(file.read()) (the pre-9c1d4f4 bug)."""
        src = (PROJECT_ROOT / "governance" / "preflight.py").read_text(encoding="utf-8")
        # The fix imports canonical_sha256 inside the integrity check.
        self.assertIn("from tools.verify_engine_integrity import canonical_sha256", src,
            "governance/preflight.py is missing canonical_sha256 import. "
            "Did someone revert the fix?")
        # And the raw hashlib loop the bug used must NOT be present in the
        # root-of-trust block.
        self.assertNotIn(
            "for _chunk in iter(lambda: _f.read(8192), b\"\")",
            src,
            "governance/preflight.py is using the raw chunked-read pattern "
            "from the pre-fix root-of-trust check. Restore canonical_sha256.",
        )

    def test_engine_resolver_sha256_file_uses_canonical(self):
        """tools/engine_resolver.py:_sha256_file must delegate to
        canonical_sha256. This was the FIFTH hashing site missed in the
        original R1 unification — its raw-bytes hashing was the root cause
        of TD-002 (engine v1_5_6/v1_5_7/v1_5_8 contract_id mismatch on
        Windows CRLF contract.json files, blocking all backtests)."""
        from tools.engine_resolver import _sha256_file
        actual = _sha256_file(self.target)
        expected = "sha256:" + canonical_sha256(self.target)
        self.assertEqual(actual, expected,
            "engine_resolver._sha256_file diverged from canonical_sha256. "
            "Did someone re-introduce raw hashlib.sha256(read_bytes())? "
            "This is the TD-002 regression vector.")

    def test_engine_resolver_matches_canonical_on_crlf_and_lf_variants(self):
        """For both CRLF and LF variants of the same logical content, the
        resolver hash and the canonical hash must agree, AND the resolver
        hashes for LF vs CRLF must be equal (canonical strips CR, so the
        same logical content always produces the same hash regardless of
        line-ending convention). This is the property that lets
        contract.json travel across platforms without contract_id drift."""
        import tempfile
        from tools.engine_resolver import _sha256_file

        payload_lf = b"line1\nline2\nline3\n"
        payload_crlf = b"line1\r\nline2\r\nline3\r\n"

        paths_to_clean = []
        try:
            # Per-variant: resolver hash matches canonical hash.
            for variant_name, payload in [("LF", payload_lf), ("CRLF", payload_crlf)]:
                with tempfile.NamedTemporaryFile(
                    "wb", delete=False, suffix=".json"
                ) as fh:
                    fh.write(payload)
                    tmp = Path(fh.name)
                paths_to_clean.append(tmp)
                resolver_h = _sha256_file(tmp)
                canonical_h = "sha256:" + canonical_sha256(tmp)
                self.assertEqual(resolver_h, canonical_h,
                    f"variant={variant_name}: resolver hash != canonical hash. "
                    f"resolver={resolver_h}, canonical={canonical_h}")

            # Cross-variant: resolver hashes for LF and CRLF must be equal
            # because canonical_sha256 normalizes CRLF -> LF before hashing.
            lf_path, crlf_path = paths_to_clean[0], paths_to_clean[1]
            self.assertEqual(_sha256_file(lf_path), _sha256_file(crlf_path),
                "Resolver hashes differ for LF vs CRLF variants of identical "
                "logical content. Either canonical_sha256 stopped normalizing "
                "CR or _sha256_file is no longer delegating to it.")
        finally:
            for p in paths_to_clean:
                try:
                    p.unlink()
                except OSError:
                    pass

    def test_raw_vs_canonical_differ_on_crlf_file(self):
        """Sanity: on a file with CRLF endings, raw and canonical hashes
        differ. This is the property that made the bug invisible-on-Linux
        and broken-on-Windows."""
        with __import__("tempfile").NamedTemporaryFile(
            "wb", delete=False, suffix=".txt"
        ) as fh:
            fh.write(b"line1\r\nline2\r\n")
            tmp = Path(fh.name)
        try:
            raw = hashlib.sha256(tmp.read_bytes()).hexdigest().upper()
            canon = canonical_sha256(tmp).upper()
            self.assertNotEqual(raw, canon,
                "raw vs canonical hashes match on CRLF — the canonical "
                "normalization isn't actually stripping CR. Test fixture "
                "broken or canonical_sha256 regressed.")
        finally:
            tmp.unlink(missing_ok=True)


class R2_EngineResolverNotHardcoded(unittest.TestCase):
    """verify_engine_integrity.py must resolve the active engine via the
    registry, not via a hardcoded engine version path."""

    def test_uses_get_engine_version(self):
        from tools.verify_engine_integrity import ENGINE_VERSION
        from tools.pipeline_utils import get_engine_version
        self.assertEqual(ENGINE_VERSION, get_engine_version(),
            "verify_engine_integrity.ENGINE_VERSION diverged from "
            "tools.pipeline_utils.get_engine_version(). Did the v1_5_6 "
            "(or any other version) hardcode get reintroduced?")

    def test_no_hardcoded_engine_main_lookup(self):
        """The pre-fix code loaded ENGINE_VERSION from a hardcoded engine
        main.py path (`engine_dev/.../v1_5_6/main.py`). Catch any version
        reappearing as a hardcoded loader."""
        src = (PROJECT_ROOT / "tools" / "verify_engine_integrity.py").read_text(encoding="utf-8")
        import re
        # Forbid: literal vN_N_N path in a spec_from_file_location call for ENGINE_VERSION
        # The only legitimate reference to v1_5_X strings should be inside test
        # fixture comments / docstrings, not in import-time code paths.
        bad = re.findall(
            r'spec_from_file_location\([^)]*v\d+_\d+_\d+[^)]*\)',
            src,
        )
        self.assertEqual(bad, [],
            f"Found hardcoded engine path(s) in spec_from_file_location call: {bad}. "
            "Use tools.pipeline_utils.get_engine_version() instead.")


class R3_DummyStrategyContract(unittest.TestCase):
    """The three contract-v1.3 dummy strategies inside verify_engine_integrity.py
    must return False (not None) from check_exit when no exit fires."""

    def setUp(self):
        self.mod = _load_module(
            "_vei", PROJECT_ROOT / "tools" / "verify_engine_integrity.py"
        )

    def _assert_check_exit_returns_bool_when_no_exit(self, cls):
        """Construct a minimal ctx where the strategy's exit conditions are
        NOT met. check_exit must return a bool (False), not None."""
        strat = cls()

        class _Ctx:
            def __init__(self, idx, direction):
                self.index = idx
                self.direction = direction
            def get(self, k, default=None):
                return getattr(self, k, default)

        # Pick an index/direction that the strategy's exit logic does NOT match.
        ctx = _Ctx(idx=999, direction=1)
        result = strat.check_exit(ctx)
        self.assertIsInstance(result, bool,
            f"{cls.__name__}.check_exit returned {type(result).__name__} "
            f"({result!r}); contract v1.3 requires bool | str.")
        self.assertEqual(result, False,
            f"{cls.__name__}.check_exit non-exit path returned {result!r}; "
            "expected False.")

    def test_session_limit_strategy2(self):
        self._assert_check_exit_returns_bool_when_no_exit(self.mod.SessionLimitStrategy2)

    def test_unlimited_session_strategy(self):
        self._assert_check_exit_returns_bool_when_no_exit(self.mod.UnlimitedSessionStrategy)

    def test_diagnostics_strategy(self):
        self._assert_check_exit_returns_bool_when_no_exit(self.mod.DiagnosticsStrategy)


class R4_SessionFilterClockSemantics(unittest.TestCase):
    """FilterStack.session_filter matches against signal-bar hour. The clock-
    semantics docstring in engines/filter_stack.py exists to prevent users
    from forgetting that fills land one bar later under next_bar_open. If
    the docstring disappears, this test fails — protecting the convention."""

    def test_filter_stack_documents_signal_time_semantics(self):
        src = (PROJECT_ROOT / "engines" / "filter_stack.py").read_text(encoding="utf-8")
        # Look for the key terms from the documentation block.
        required_terms = [
            "CLOCK SEMANTICS",
            "SIGNAL bar",
            "next_bar_open",
            "FILL lands",
            "shifted left",
        ]
        for term in required_terms:
            self.assertIn(term.lower(), src.lower(),
                f"engines/filter_stack.py session_filter section missing "
                f"'{term}' from clock-semantics docstring. Restore it — "
                f"this comment exists to prevent the FVG S04→S05 leak class.")

    def test_session_filter_matches_signal_bar_hour(self):
        """The filter must consult ctx.bar_hour (signal-bar hour), not
        ctx.fill_bar_hour or similar. Checking the source for the call
        site."""
        src = (PROJECT_ROOT / "engines" / "filter_stack.py").read_text(encoding="utf-8")
        # The signal-time check uses ctx.require("bar_hour").
        self.assertIn('ctx.require("bar_hour")', src,
            "session_filter no longer matches against ctx.bar_hour. "
            "If the convention has intentionally changed (e.g., fill_bar_hour), "
            "update this test AND the docstring describing the new clock.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
