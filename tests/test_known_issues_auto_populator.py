"""S2 regression — Known Issues section is auto-populated by
system_introspection so the file is honest by default.

Bug class:
  Pre-fix, the Known Issues section defaulted to `- (none)` and
  required manual edit at session-close. The truthfulness gate caught
  empty-while-broken state but couldn't catch the inverse: real
  failures the operator forgot to write down. By 2026-05-04 the gate
  was a chronic friction point because every session-close required
  re-deriving what was already in pytest/audit signals.

Fix:
  collect_known_issues() runs the same checks the gate runs (gate-
  suite pytest, intent-index audit, sweep_registry drift) and the
  renderer surfaces them in an auto-detected subsection. Manual
  subsection persists for deferred TDs and operational notes that
  automated signals don't see.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import system_introspection as si


# ---------------------------------------------------------------------------
# collect_known_issues structure
# ---------------------------------------------------------------------------


class TestCollectKnownIssuesStructure:

    def test_returns_expected_keys(self):
        """The shape must be stable — the renderer reads specific keys."""
        result = si.collect_known_issues()
        for key in (
            "pytest_failed",
            "pytest_skipped",
            "pytest_passed",
            "pytest_error",
            "intent_index_errors",
            "sweep_registry_errors",
        ):
            assert key in result, f"collect_known_issues missing key {key!r}"

    def test_counts_are_ints(self):
        result = si.collect_known_issues()
        assert isinstance(result["pytest_failed"], int)
        assert isinstance(result["pytest_skipped"], int)
        assert isinstance(result["pytest_passed"], int)


# ---------------------------------------------------------------------------
# Renderer behavior — auto-detected entries surface, manual section
# always present
# ---------------------------------------------------------------------------


def _render_with(known: dict) -> str:
    """Run render_markdown with stub upstream sections + the given
    known_issues dict, return the rendered markdown."""
    return si.render_markdown(
        engine={"version": "1.5.8", "version_raw": "v1_5_8", "status": "FROZEN", "manifest": "VALID"},
        directives={"inbox": [], "active": [], "completed_count": 0},
        ledgers={"master_filter": {"missing": True}, "mps": {"missing": True}, "candidates": {"missing": True}},
        portfolio={"missing": True},
        vault={"missing": True},
        freshness={"latest_bar": "?", "symbols_tracked": 0, "stale_symbols": 0},
        runs={"total": 0},
        git={"commits_ahead": 0, "working_tree": "clean", "last_commit": ""},
        session_status=("OK", []),
        known_issues=known,
    )


class TestRenderer:

    def _empty_known(self) -> dict:
        return {
            "pytest_failed": 0,
            "pytest_skipped": 0,
            "pytest_passed": 0,
            "pytest_error": None,
            "intent_index_errors": [],
            "sweep_registry_errors": [],
        }

    def test_clean_state_shows_none_in_manual_section(self):
        out = _render_with(self._empty_known())
        # No auto-detected subsection should appear (nothing to surface).
        assert "### Auto-detected" not in out
        # Manual section always present, with placeholder.
        assert "### Manual" in out
        assert "- (none)" in out

    def test_pytest_failure_surfaces_in_auto_section(self):
        k = self._empty_known()
        k["pytest_failed"] = 3
        k["pytest_passed"] = 80
        out = _render_with(k)
        assert "### Auto-detected" in out
        assert "Gate suite: 3 failing test(s)" in out
        # Manual subsection still present, but no "(none)" since auto
        # has surfaced something.
        assert "### Manual" in out
        manual_section = out.split("### Manual", 1)[1]
        assert "- (none)" not in manual_section

    def test_intent_index_hard_error_surfaces(self):
        k = self._empty_known()
        k["intent_index_errors"] = ["engine_change: bad_regex:invalid pattern"]
        out = _render_with(k)
        assert "Intent-index hard error" in out
        assert "engine_change: bad_regex" in out

    def test_sweep_registry_caveat_surfaces(self):
        k = self._empty_known()
        k["sweep_registry_errors"] = ["idea 64 / S03: short/full hash mismatch"]
        out = _render_with(k)
        assert "Sweep registry caveat" in out
        assert "idea 64 / S03" in out

    def test_pytest_error_path_surfaces(self):
        """If pytest itself can't run, surface the error rather than
        report 0/0/0 (a silent-success false-clean result)."""
        k = self._empty_known()
        k["pytest_error"] = "command not found"
        out = _render_with(k)
        assert "error running pytest" in out
        assert "command not found" in out

    def test_skipped_only_is_informational_not_blocker(self):
        """Skips alone shouldn't be presented as failures; they signal
        quarantines worth reviewing but aren't necessarily blockers."""
        k = self._empty_known()
        k["pytest_skipped"] = 5
        k["pytest_passed"] = 80
        out = _render_with(k)
        # Surfaces the count without bolding (no '**' around the line)
        # and without "failing" language.
        auto_section = out.split("### Auto-detected", 1)[1].split("### Manual", 1)[0]
        assert "5 skipped" in auto_section
        assert "failing" not in auto_section

    def test_manual_subsection_always_present(self):
        """Even with auto-populated entries, the manual subsection
        must remain so deferred TDs / operational context have a home."""
        k = self._empty_known()
        k["intent_index_errors"] = ["engine_change: bad_regex:invalid pattern"]
        out = _render_with(k)
        assert "### Manual" in out
        assert "<!-- Add tech-debt items" in out


# ---------------------------------------------------------------------------
# Backward compat — calling render_markdown without known_issues must
# still work (defaults to empty / no auto section).
# ---------------------------------------------------------------------------


class TestBackwardCompat:

    def test_render_without_known_issues_kwarg(self):
        """Old callers passing only the original positional args (now
        9 after burnin removal) must still work."""
        out = si.render_markdown(
            engine={"version": "1.5.8", "version_raw": "v1_5_8", "status": "FROZEN", "manifest": "VALID"},
            directives={"inbox": [], "active": [], "completed_count": 0},
            ledgers={"master_filter": {"missing": True}, "mps": {"missing": True}, "candidates": {"missing": True}},
            portfolio={"missing": True},
            vault={"missing": True},
            freshness={"latest_bar": "?", "symbols_tracked": 0, "stale_symbols": 0},
            runs={"total": 0},
            git={"commits_ahead": 0, "working_tree": "clean", "last_commit": ""},
            session_status=("OK", []),
        )
        assert "## Known Issues" in out
        assert "### Manual" in out
        assert "- (none)" in out
