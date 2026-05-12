"""Regression — `tools/system_introspection.py` must preserve the
`### Manual (deferred TDs, operational context)` subsection across regen.

Background (2026-05-12)
-----------------------
The session-close `SKILL.md` documents that the Manual subsection of
`## Known Issues` is operator-editable and persists across regen. The
collect_known_issues() docstring says the same. But the renderer wrote
a fresh default template every run, silently destroying any operator
notes added during the session. The fix introduces
`_preserve_manual_section()` which reads the existing file, extracts
the verbatim Manual block, and substitutes it into the regenerated
markdown before write_text.

This test file pins the four cases the user's spec called out:
  1. Manual section exists -> survives byte-for-byte
  2. No prior file -> no change; default template emitted
  3. Two Manual sections -> RuntimeError (fail closed)
  4. Non-Manual sections of the snapshot -> untouched by the fix
"""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from tools.system_introspection import (
    _find_manual_blocks,
    _preserve_manual_section,
    _MANUAL_SECTION_HEADER,
)


# ---------------------------------------------------------------------------
# Helpers — small markdown fixtures resembling SYSTEM_STATE.md shape
# ---------------------------------------------------------------------------

_REGEN_TEMPLATE = textwrap.dedent("""\
    # SYSTEM STATE

    ## SESSION STATUS: OK

    > Generated: 2026-05-12T13:00:00Z

    ## Engine
    - **Version:** 1.5.8 | **Status:** FROZEN

    ## Known Issues
    ### Auto-detected (regenerated each run)
    - **Post-merge watch CLOSED_OK:** 5/5 runs clean.

    ### Manual (deferred TDs, operational context)
    <!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
""")


_PRIOR_WITH_MANUAL_NOTES = textwrap.dedent("""\
    # SYSTEM STATE

    ## SESSION STATUS: OK

    > Generated: 2026-05-12T12:00:00Z

    ## Engine
    - **Version:** 1.5.8 | **Status:** FROZEN

    ## Known Issues
    ### Auto-detected (regenerated each run)
    - **Some prior auto-detected entry** — should NOT survive regen.

    ### Manual (deferred TDs, operational context)
    <!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

    - **Operator note 1:** A real piece of deferred work that must survive regen.
    - **Operator note 2:** Another piece of context with `code` and ## a nested heading.
""")


# ---------------------------------------------------------------------------
# Case 1 — Manual section survives byte-for-byte
# ---------------------------------------------------------------------------

def test_case1_manual_section_survives_byte_for_byte(tmp_path):
    target = tmp_path / "SYSTEM_STATE.md"
    target.write_text(_PRIOR_WITH_MANUAL_NOTES, encoding="utf-8")

    result = _preserve_manual_section(target, _REGEN_TEMPLATE)

    # The operator's bullet-content must be present, verbatim.
    assert "**Operator note 1:**" in result
    assert "**Operator note 2:**" in result
    assert "A real piece of deferred work that must survive regen." in result
    assert "Another piece of context with `code` and ## a nested heading." in result

    # The default template's empty-Manual line must NOT survive.
    # (the regen template's HTML comment is identical to the prior's, so
    # checking *that* doesn't distinguish — assert via the operator content
    # above. But also assert there is exactly one Manual header in the result.)
    assert result.count(_MANUAL_SECTION_HEADER) == 1


def test_case1_auto_detected_section_is_NOT_preserved(tmp_path):
    """Companion check: only the Manual block is preserved. The
    Auto-detected section above it must come from the regen (latest
    signals), not from the prior file. Otherwise stale auto-detected
    entries would persist forever.
    """
    target = tmp_path / "SYSTEM_STATE.md"
    target.write_text(_PRIOR_WITH_MANUAL_NOTES, encoding="utf-8")

    result = _preserve_manual_section(target, _REGEN_TEMPLATE)

    assert "**Some prior auto-detected entry**" not in result
    assert "**Post-merge watch CLOSED_OK:** 5/5 runs clean." in result


# ---------------------------------------------------------------------------
# Case 2 — No prior file -> no change
# ---------------------------------------------------------------------------

def test_case2_no_prior_file_returns_regen_unchanged(tmp_path):
    target = tmp_path / "SYSTEM_STATE.md"  # never created
    assert not target.exists()

    result = _preserve_manual_section(target, _REGEN_TEMPLATE)
    assert result == _REGEN_TEMPLATE


def test_case2_prior_file_without_manual_section_returns_regen_unchanged(tmp_path):
    """If the prior file exists but somehow lacks a Manual section
    (e.g., manually trimmed), the fix must not invent one and must not
    crash. Regen takes over with the default template.
    """
    target = tmp_path / "SYSTEM_STATE.md"
    # Prior file: no `### Manual` heading at all.
    prior = _PRIOR_WITH_MANUAL_NOTES.split("### Manual")[0]
    target.write_text(prior, encoding="utf-8")

    result = _preserve_manual_section(target, _REGEN_TEMPLATE)
    assert result == _REGEN_TEMPLATE


# ---------------------------------------------------------------------------
# Case 3 — Two Manual sections -> RuntimeError, fail closed
# ---------------------------------------------------------------------------

def test_case3_two_manual_sections_raise_runtime_error(tmp_path):
    target = tmp_path / "SYSTEM_STATE.md"
    # Two Manual sections — corrupted state. The fix must REFUSE to
    # pick one, since either choice could lose operator-deferred work.
    corrupted = _PRIOR_WITH_MANUAL_NOTES + textwrap.dedent("""\

        ### Manual (deferred TDs, operational context)
        - **Second manual block:** This must not be silently dropped.
    """)
    target.write_text(corrupted, encoding="utf-8")

    with pytest.raises(RuntimeError) as exc:
        _preserve_manual_section(target, _REGEN_TEMPLATE)
    msg = str(exc.value)
    assert "Manual" in msg
    assert "2" in msg  # the count must be in the message for operator triage


# ---------------------------------------------------------------------------
# Case 4 — Snapshot fields outside Known Issues are untouched
# ---------------------------------------------------------------------------

def test_case4_non_manual_sections_unchanged_by_preservation(tmp_path):
    """The fix only touches the Manual block. SESSION STATUS, Engine,
    Git Sync etc. must be exactly what the regen produced — never
    pulled forward from the prior file.
    """
    target = tmp_path / "SYSTEM_STATE.md"
    # Prior file has a STALE SESSION STATUS that must NOT survive.
    stale_prior = _PRIOR_WITH_MANUAL_NOTES.replace(
        "## SESSION STATUS: OK", "## SESSION STATUS: BROKEN"
    )
    stale_prior = stale_prior.replace(
        "**Version:** 1.5.8", "**Version:** 1.5.0"
    )
    target.write_text(stale_prior, encoding="utf-8")

    result = _preserve_manual_section(target, _REGEN_TEMPLATE)

    # The CURRENT regen's SESSION STATUS and Engine version must win.
    assert "## SESSION STATUS: OK" in result
    assert "## SESSION STATUS: BROKEN" not in result
    assert "**Version:** 1.5.8" in result
    assert "**Version:** 1.5.0" not in result
    # Manual content from prior still survives.
    assert "**Operator note 1:**" in result


# ---------------------------------------------------------------------------
# _find_manual_blocks — direct unit coverage
# ---------------------------------------------------------------------------

def test_find_manual_blocks_extracts_to_eof_when_last_section():
    """When the Manual section is the last `##`-level block in the
    file (current real-world layout), extraction must run to EOF.
    """
    blocks = _find_manual_blocks(_PRIOR_WITH_MANUAL_NOTES)
    assert len(blocks) == 1
    assert blocks[0].startswith(_MANUAL_SECTION_HEADER)
    assert "**Operator note 2:**" in blocks[0]


def test_find_manual_blocks_stops_at_next_section_heading():
    """Hypothetical: if a future renderer places another `## `-level
    section after Manual, the extractor must stop at that boundary,
    not bleed into the next section.
    """
    md = (
        _PRIOR_WITH_MANUAL_NOTES
        + "\n## A Future Section\n- this must NOT be inside the Manual block.\n"
    )
    blocks = _find_manual_blocks(md)
    assert len(blocks) == 1
    assert "this must NOT be inside the Manual block" not in blocks[0]
    assert "**Operator note 1:**" in blocks[0]


def test_find_manual_blocks_returns_empty_when_absent():
    md = "## Some Section\n- nothing here\n\n## Another\n- still nothing\n"
    assert _find_manual_blocks(md) == []


def test_find_manual_blocks_detects_multiple_for_fail_closed():
    md = (
        _PRIOR_WITH_MANUAL_NOTES
        + "\n### Manual (deferred TDs, operational context)\n- second\n"
    )
    blocks = _find_manual_blocks(md)
    assert len(blocks) == 2
