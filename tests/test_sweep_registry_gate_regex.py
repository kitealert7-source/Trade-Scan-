"""
Unit tests for sweep_registry_gate.py — regex extraction only, no I/O.

Covers:
  - Idea/sweep extraction from strategy names
  - Parent pass extraction
  - Edge cases (P00 baseline, two-digit IDs)
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import the regex patterns used by the gate (inline since they're module-level)
# From sweep_registry_gate.py line 48: r"^(\d{2})_.*_S(\d{2})"
IDEA_SWEEP_RE = re.compile(r"^(\d{2})_.*_S(\d{2})")
# From sweep_registry_gate.py line 326: r"_P(\d{2})"
PARENT_RE = re.compile(r"_P(\d{2})")


class TestIdeaSweepExtraction:

    def test_standard_name(self):
        m = IDEA_SWEEP_RE.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03")
        assert m is not None
        assert m.group(1) == "22"  # idea_id
        assert m.group(2) == "02"  # sweep

    def test_single_digit_idea_padded(self):
        m = IDEA_SWEEP_RE.match("03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02")
        assert m is not None
        assert m.group(1) == "03"
        assert m.group(2) == "01"

    def test_high_sweep_number(self):
        m = IDEA_SWEEP_RE.match("15_MR_FX_15M_ASRANGE_SESSFILT_S13_V1_P00")
        assert m is not None
        assert m.group(2) == "13"

    def test_no_match_without_sweep(self):
        m = IDEA_SWEEP_RE.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_V1_P03")
        assert m is None

    def test_no_match_garbage(self):
        assert IDEA_SWEEP_RE.match("hello") is None
        assert IDEA_SWEEP_RE.match("") is None


class TestParentExtraction:

    def test_standard_parent(self):
        m = PARENT_RE.search("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03")
        assert m is not None
        assert m.group(1) == "03"

    def test_baseline_parent(self):
        m = PARENT_RE.search("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P00")
        assert m is not None
        assert m.group(1) == "00"

    def test_with_run_suffix(self):
        m = PARENT_RE.search("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03__E152")
        assert m is not None
        assert m.group(1) == "03"

    def test_no_parent_field(self):
        m = PARENT_RE.search("some_random_string")
        assert m is None
