"""Regression coverage for tools/system_introspection.py porcelain parsing.

Replaces the brittle `l.strip().lstrip("?MA ")` path extraction — which deleted
leading characters until one fell outside the set {?, M, A, space} rather than
parsing porcelain, mangling `Makefile`->`akefile`, `Apptest.py`->`pptest.py`, and
failing on renames/deletions — with a positional parser. Self-generated artifacts
(SYSTEM_STATE.md, tools/TOOLS_INDEX.md, data_root/) are excluded from the
OPERATOR-FACING working-tree cleanliness metric only, never from git tracking.

Design discussion: session-close 2026-06-29 (two notions of "dirty" — raw git-tree
cleanliness vs. operator-actionable dirtiness; the metric wants the second).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import system_introspection as si


@pytest.mark.parametrize("line, expected", [
    (" M Makefile", "Makefile"),                  # formerly mangled -> 'akefile'
    ("A  Apptest.py", "Apptest.py"),              # formerly mangled -> 'pptest.py'
    (" D deleted.py", "deleted.py"),              # formerly leaked status -> 'D deleted.py'
    ("M  SYSTEM_STATE.md", "SYSTEM_STATE.md"),    # staged
    (" M data_root/x.parquet", "data_root/x.parquet"),
    ("?? tools/TOOLS_INDEX.md", "tools/TOOLS_INDEX.md"),  # untracked
    ("MM strategies/foo.py", "strategies/foo.py"),
    ("R  old.py -> new.py", "new.py"),            # rename -> destination
    ("RM a.py -> b.py", "b.py"),                  # rename+modify -> destination
])
def test_extract_porcelain_path(line, expected):
    assert si.extract_porcelain_path(line) == expected


@pytest.mark.parametrize("line", ["", "M", " M", "?"])
def test_extract_porcelain_path_malformed_returns_empty(line):
    assert si.extract_porcelain_path(line) == ""


@pytest.mark.parametrize("path, is_noise", [
    ("data_root/x.parquet", True),
    ("SYSTEM_STATE.md", True),
    ("tools/TOOLS_INDEX.md", True),
    ("strategies/foo.py", False),
    ("Makefile", False),
    ("tools/system_introspection.py", False),     # NOT over-broad on tools/
])
def test_is_status_noise(path, is_noise):
    assert si.is_status_noise(path) is is_noise


def test_self_generated_exclusions_is_a_named_concept():
    # Named tuple, not magic strings scattered through the dirty-check.
    assert isinstance(si.SELF_GENERATED_STATUS_EXCLUSIONS, tuple)
    for expected in ("data_root/", "SYSTEM_STATE.md", "tools/TOOLS_INDEX.md"):
        assert expected in si.SELF_GENERATED_STATUS_EXCLUSIONS


def test_self_count_does_not_trip_operator_dirtiness():
    """A working tree whose ONLY changes are self-generated artifacts must read
    as operator-clean (the bug this fix targets)."""
    self_only = [" M SYSTEM_STATE.md", "?? tools/TOOLS_INDEX.md",
                 " M data_root/freshness_index.json"]
    operator = [si.extract_porcelain_path(l) for l in self_only]
    assert [p for p in operator if p and not si.is_status_noise(p)] == []
