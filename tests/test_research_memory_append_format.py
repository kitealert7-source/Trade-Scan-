"""
Round-trip regression: research_memory_append.build_entry output MUST parse
cleanly through BOTH RESEARCH_MEMORY parsers.

The pre-commit gate (tools/generate_research_memory_index.py) only accepts a
single-line pipe header wrapped in '---'. On 2026-05-28 build_entry emitted a
multi-line header that the validator rejected as "MALFORMED ENTRY", blocking
the documented /session-close append step. This test pins the writer to the
validator's accepted format so the two tools cannot silently drift apart again.

It also confirms the labeled body survives the *other* parser
(compact_research_memory.parse_entry), which routes Finding/Evidence/
Conclusion/Implication labels into structured buckets.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.research_memory_append import (
    append_entry,
    build_entry,
    ensure_memory_file,
)
from tools.generate_research_memory_index import HEADER_A, parse_research_memory
from tools.compact_research_memory import parse_entry as compact_parse_entry


SAMPLE = dict(
    tags=["alpha_family", "zrev_model", "roundtrip_theme"],
    strategy="90_PORT_EURUSDUSDJPY_15M_PAIRX_S21_V1_P06",
    run_ids="abc123, def456",
    finding="Sample finding sentence describing the observed behavior.",
    evidence="Net% 198.36 -> 190.59 (-7.77pp), DD flat at 23.2.",
    conclusion="Sample conclusion drawn from the finding and evidence.",
    implication="Sample actionable implication to apply in future research.",
)

PREAMBLE = "# RESEARCH MEMORY\n\nTHIS FILE IS APPEND-ONLY.\n"


def _build(**overrides) -> str:
    return build_entry(**{**SAMPLE, **overrides})


class TestBuildEntryHeader:

    def test_wrapped_in_delimiters(self):
        lines = _build().splitlines()
        assert lines[0] == "---"
        assert lines[-1] == "---"

    def test_header_matches_validator_regex(self):
        header = _build().splitlines()[1]
        assert HEADER_A.match(header) is not None

    def test_header_field_order_and_content(self):
        m = HEADER_A.match(_build().splitlines()[1])
        assert m is not None
        assert m.group(1) == datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert m.group(2).strip() == "alpha_family, zrev_model, roundtrip_theme"
        assert m.group(3).strip() == SAMPLE["strategy"]
        assert m.group(4).strip() == SAMPLE["run_ids"]

    def test_optional_strategy_omitted_still_valid(self):
        header = _build(strategy="").splitlines()[1]
        m = HEADER_A.match(header)
        assert m is not None
        assert (m.group(3) or "") == ""              # no Strategy segment
        assert m.group(4).strip() == SAMPLE["run_ids"]

    def test_header_is_a_single_line(self):
        # The historical bug was a multi-line header. Body starts at line 3.
        lines = _build().splitlines()
        assert lines[2].startswith("Finding:")


class TestValidatorRoundTrip:

    def test_parses_with_zero_warnings(self):
        entries, warnings = parse_research_memory(PREAMBLE + _build(), "scratch.md")
        assert warnings == []
        assert len(entries) == 1

    def test_parsed_fields_match(self):
        entries, warnings = parse_research_memory(PREAMBLE + _build(), "scratch.md")
        assert warnings == []
        e = entries[0]
        assert e["tags"] == "alpha_family, zrev_model, roundtrip_theme"
        assert e["strategy"] == SAMPLE["strategy"]
        assert e["run_ids"] == SAMPLE["run_ids"]
        assert SAMPLE["finding"] in e["body"]
        assert SAMPLE["implication"] in e["body"]

    def test_full_append_path_round_trips(self, tmp_path):
        # Exercise the real append flow end to end, then re-validate.
        mem = tmp_path / "RESEARCH_MEMORY.md"
        ensure_memory_file(mem)
        append_entry(mem, _build())
        text = mem.read_text(encoding="utf-8")
        entries, warnings = parse_research_memory(text, "RESEARCH_MEMORY.md")
        assert warnings == []
        assert len(entries) == 1

    def test_two_consecutive_appends_round_trip(self, tmp_path):
        mem = tmp_path / "RESEARCH_MEMORY.md"
        ensure_memory_file(mem)
        append_entry(mem, _build())
        append_entry(mem, _build(strategy="", run_ids="zzz999"))
        text = mem.read_text(encoding="utf-8")
        entries, warnings = parse_research_memory(text, "RESEARCH_MEMORY.md")
        assert warnings == []
        assert len(entries) == 2


class TestCompactorRoundTrip:
    """The labeled body must also parse through the compactor's parser."""

    def test_compactor_extracts_all_fields(self):
        lines = _build().splitlines()
        content = "\n".join(lines[1:-1])          # strip wrapping '---' lines
        parsed = compact_parse_entry(content)
        assert parsed["date"]
        assert parsed["tags"] == ["alpha_family", "zrev_model", "roundtrip_theme"]
        assert parsed["strategy"] == SAMPLE["strategy"]
        assert parsed["run_ids"] == SAMPLE["run_ids"]
        assert SAMPLE["finding"] in parsed["finding"]
        assert SAMPLE["evidence"] in parsed["evidence"]
        assert SAMPLE["conclusion"] in parsed["conclusion"]
        assert SAMPLE["implication"] in parsed["implication"]
