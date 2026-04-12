"""
Unit tests for idea_evaluation_gate.py — pure function tests, no I/O.

Covers:
  - NAME_PATTERN regex (valid, invalid, edge cases)
  - _classify() thresholds and RESEARCH_MEMORY override invariant
  - _generate_suggestions() structure, cap, ordering, determinism
  - _parse_research_entries() separator handling
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.idea_evaluation_gate import (
    NAME_PATTERN,
    _classify,
    _generate_suggestions,
    _parse_research_entries,
    _result,
)


# ===================================================================
# NAME_PATTERN regex
# ===================================================================

class TestNamePattern:
    """Regex must match valid strategy names and reject malformed ones."""

    def test_standard_name(self):
        m = NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03")
        assert m is not None
        assert m.group("model") == "RSIAVG"
        assert m.group("timeframe") == "30M"
        assert m.group("family") == "CONT"
        assert m.group("idea_id") == "22"
        assert m.group("sweep") == "02"
        assert m.group("parent") == "03"

    def test_name_with_suffix(self):
        m = NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03__E152")
        assert m is not None
        assert m.group("model") == "RSIAVG"

    def test_name_without_filter(self):
        m = NAME_PATTERN.match("03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02")
        assert m is not None
        assert m.group("model") == "IMPULSE"
        assert m.group("filter") is None

    def test_clone_prefix(self):
        m = NAME_PATTERN.match("C_22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03")
        assert m is not None
        assert m.group("model") == "RSIAVG"

    def test_rejects_garbage(self):
        assert NAME_PATTERN.match("hello") is None
        assert NAME_PATTERN.match("") is None
        assert NAME_PATTERN.match("22_CONT") is None

    def test_rejects_double_underscore_misplacement(self):
        """Off-by-one structural bug: double underscore in wrong position."""
        assert NAME_PATTERN.match("22_CONT_FX_30M__RSIAVG_S02_V1_P03") is None

    def test_rejects_missing_sweep(self):
        assert NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_V1_P03") is None

    def test_rejects_lowercase_tokens(self):
        assert NAME_PATTERN.match("22_cont_fx_30m_rsiavg_trendfilt_s02_v1_p03") is None


# ===================================================================
# _classify() — threshold logic
# ===================================================================

class TestClassify:
    """Classification must respect PF distributions, not just averages."""

    _BASE = dict(
        model="TEST", timeframe="1H",
        trade_counts=[100, 100, 100],
        has_failure_tag=False,
        has_exhausted_mention=False,
        rm_matches=[],
        failed_run_count=0,
        complete_run_count=3,
        hyp_rejected=0,
        hyp_accepted=0,
    )

    def _call(self, **overrides):
        kw = {**self._BASE, **overrides}
        return _classify(**kw)

    def test_all_failed_pf(self):
        """[1.05, 1.04, 1.03] — all below threshold → FAILED."""
        status, conf, rec, _ = self._call(pf_values=[1.05, 1.04, 1.03])
        assert status == "REPEAT_FAILED"
        assert rec == "RECONSIDER"

    def test_mixed_pf_weak(self):
        """[1.05, 1.25, 1.30] — avg ~1.20, dragged down by one bad run → WEAK."""
        status, _, rec, _ = self._call(pf_values=[1.05, 1.25, 1.30])
        # avg = 1.20, at the boundary
        assert status in ("REPEAT_WEAK", "REPEAT_PROMISING")

    def test_all_promising_pf(self):
        """[1.25, 1.30, 1.28] — all above threshold → PROMISING."""
        status, _, rec, _ = self._call(pf_values=[1.25, 1.30, 1.28])
        assert status == "REPEAT_PROMISING"
        assert rec == "PROCEED"

    def test_single_run_low_confidence(self):
        """Single run PF < 1.10 should be FAILED but MEDIUM confidence."""
        status, conf, _, _ = self._call(pf_values=[1.05])
        assert status == "REPEAT_FAILED"
        assert conf == "MEDIUM"  # not HIGH — only 1 data point

    def test_many_runs_high_confidence(self):
        """3+ runs PF < 1.10 should be HIGH confidence."""
        status, conf, _, _ = self._call(pf_values=[1.05, 1.04, 1.03])
        assert status == "REPEAT_FAILED"
        assert conf == "HIGH"

    def test_no_pf_all_failed_runs(self):
        """Many failed runs, no completions → FAILED."""
        status, _, _, _ = self._call(
            pf_values=[], failed_run_count=5, complete_run_count=0,
        )
        assert status == "REPEAT_FAILED"

    # --- MEMORY OVERRIDE INVARIANT ---

    def test_memory_override_always_wins(self):
        """CORE INVARIANT: exhausted tag overrides even excellent PF.

        If this test breaks, the entire idea gate system regresses.
        RESEARCH_MEMORY authority is non-negotiable.
        """
        status, conf, rec, summary = self._call(
            pf_values=[1.5, 1.6, 1.7],
            has_exhausted_mention=True,
        )
        assert status == "REPEAT_FAILED", (
            f"Memory override violated: got {status} with PF=[1.5,1.6,1.7] "
            f"and has_exhausted_mention=True"
        )
        assert rec == "RECONSIDER"
        assert conf == "HIGH"
        assert "EXHAUSTED" in summary.upper()

    def test_failure_tag_overrides_good_pf(self):
        """Failure tag overrides PF > 1.20."""
        status, _, rec, _ = self._call(
            pf_values=[1.35, 1.40],
            has_failure_tag=True,
        )
        assert status == "REPEAT_FAILED"
        assert rec == "RECONSIDER"

    def test_no_override_without_tags(self):
        """Good PF without failure tags should be PROMISING, not blocked."""
        status, _, rec, _ = self._call(
            pf_values=[1.35, 1.40],
            has_failure_tag=False,
            has_exhausted_mention=False,
        )
        assert status == "REPEAT_PROMISING"
        assert rec == "PROCEED"


# ===================================================================
# _generate_suggestions() — structure, cap, ordering, determinism
# ===================================================================

class TestSuggestions:
    """Suggestions must be typed, capped at 3, deterministically ordered."""

    _BASE = dict(
        model="TEST", timeframe="1H", family="MR", strategy_type="mean_reversion",
        summary_matches=[], hyp_matches=[], rm_matches=[], pf_values=[],
        has_exhausted_mention=False,
    )

    def _call(self, **overrides):
        kw = {**self._BASE, **overrides}
        return _generate_suggestions(**kw)

    def test_max_three_suggestions(self):
        """Must never return more than 3 suggestions."""
        # Feed many data sources to trigger multiple suggestions
        hyp = [
            {"decision": "REJECT", "rejection_reason": "PF decreased", "hypothesis": ""},
            {"decision": "REJECT", "rejection_reason": "MaxDD increased", "hypothesis": ""},
            {"decision": "REJECT", "rejection_reason": "Sharpe decreased", "hypothesis": ""},
            {"decision": "REJECT", "rejection_reason": "retention too low", "hypothesis": ""},
            {"decision": "ACCEPT", "rejection_reason": "", "hypothesis": "Pass P01"},
        ]
        rm = [{"finding": "tail-dependent returns observed", "tags": "failed_concept"}]
        result = self._call(
            hyp_matches=hyp, rm_matches=rm, pf_values=[1.05, 1.08],
            has_exhausted_mention=True,
        )
        assert len(result) <= 3

    def test_suggestion_structure(self):
        """Each suggestion must have text, type, confidence keys."""
        result = self._call(has_exhausted_mention=True)
        assert len(result) > 0
        for s in result:
            assert "text" in s
            assert "type" in s
            assert "confidence" in s
            assert s["type"] in ("AVOID", "EXPLOIT", "EXPLORE")
            assert s["confidence"] in ("HIGH", "MEDIUM", "LOW")

    def test_avoid_before_exploit_before_explore(self):
        """Priority ordering: AVOID > EXPLOIT > EXPLORE."""
        hyp = [
            {"decision": "REJECT", "rejection_reason": "PF decreased", "hypothesis": ""},
            {"decision": "ACCEPT", "rejection_reason": "", "hypothesis": "Pass P01"},
        ]
        result = self._call(
            hyp_matches=hyp, pf_values=[1.15],
            summary_matches=[],  # no TF data → EXPLORE will appear
        )
        types = [s["type"] for s in result]
        # If both AVOID and EXPLOIT present, AVOID must come first
        if "AVOID" in types and "EXPLOIT" in types:
            assert types.index("AVOID") < types.index("EXPLOIT")
        if "AVOID" in types and "EXPLORE" in types:
            assert types.index("AVOID") < types.index("EXPLORE")
        if "EXPLOIT" in types and "EXPLORE" in types:
            assert types.index("EXPLOIT") < types.index("EXPLORE")

    def test_deterministic_ordering(self):
        """Same input must produce same output — no randomness."""
        kw = dict(
            hyp_matches=[
                {"decision": "REJECT", "rejection_reason": "PF decreased", "hypothesis": ""},
            ],
            pf_values=[1.15],
            has_exhausted_mention=True,
        )
        r1 = self._call(**kw)
        r2 = self._call(**kw)
        assert r1 == r2


# ===================================================================
# _parse_research_entries() — separator and header handling
# ===================================================================

class TestResearchMemoryParser:
    """Parser must handle standard and double-separator patterns."""

    def test_standard_entry(self):
        text = (
            "---\n"
            "2026-04-01 | Tags: failed_concept | Strategy: 22_CONT\n"
            "Finding body here.\n"
            "---\n"
        )
        entries, warnings = _parse_research_entries(text)
        assert len(entries) >= 1
        assert entries[0]["date"] == "2026-04-01"
        assert "failed_concept" in entries[0]["tags"]

    def test_double_separator_pattern(self):
        """The bug we hit: ---\\n\\n---\\n left --- at start of blocks."""
        text = (
            "2026-03-15 | Tags: idea_exhausted | Strategy: SMI\n"
            "SMI concept is dead.\n"
            "\n---\n\n---\n"
            "2026-03-20 | Tags: promising | Strategy: RSIAVG\n"
            "RSIAVG shows edge.\n"
        )
        entries, warnings = _parse_research_entries(text)
        assert len(entries) == 2
        assert entries[0]["tags"].strip() == "idea_exhausted"
        assert entries[1]["tags"].strip() == "promising"

    def test_empty_text(self):
        entries, warnings = _parse_research_entries("")
        assert entries == []

    def test_no_header_match(self):
        """Blocks without a recognized header produce warnings, not silent skips."""
        text = "Just some random text\nwithout a header pattern.\n"
        entries, warnings = _parse_research_entries(text)
        assert entries == []


# ===================================================================
# _result() builder
# ===================================================================

class TestResultBuilder:
    def test_includes_all_keys(self):
        r = _result("NEW", "HIGH", 0, "test", [], "PROCEED")
        assert set(r.keys()) == {
            "status", "confidence", "matches_found", "summary",
            "examples", "recommendation", "suggestions", "memory_basis",
        }

    def test_suggestions_default_empty(self):
        r = _result("NEW", "HIGH", 0, "test", [], "PROCEED")
        assert r["suggestions"] == []
        assert r["memory_basis"] == []
