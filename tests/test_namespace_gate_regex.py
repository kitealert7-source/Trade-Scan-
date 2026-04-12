"""
Unit tests for namespace_gate.py — regex pattern matching only, no I/O.

Covers:
  - NAME_PATTERN valid matches with all token combinations
  - Group extraction correctness
  - Rejection of malformed names (structural bugs, wrong order)
  - Run suffix handling
  - Clone prefix
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.namespace_gate import NAME_PATTERN, _RUN_SUFFIX_RE


class TestNamePattern:

    def test_full_name_with_filter(self):
        m = NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03")
        assert m is not None
        assert m.group("idea_id") == "22"
        assert m.group("family") == "CONT"
        assert m.group("symbol") == "FX"
        assert m.group("timeframe") == "30M"
        assert m.group("model") == "RSIAVG"
        assert m.group("filter") == "TRENDFILT"
        assert m.group("sweep") == "02"
        assert m.group("variant") == "1"
        assert m.group("parent") == "03"

    def test_name_without_filter(self):
        m = NAME_PATTERN.match("03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02")
        assert m is not None
        assert m.group("model") == "IMPULSE"
        assert m.group("filter") is None

    def test_run_suffix(self):
        m = NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03__E152")
        assert m is not None
        assert m.group("run_suffix") == "E152"

    def test_clone_prefix(self):
        m = NAME_PATTERN.match("C_22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03")
        assert m is not None
        assert m.group("clone") == "C_"
        assert m.group("model") == "RSIAVG"

    def test_index_symbol(self):
        m = NAME_PATTERN.match("35_PA_GER40_15M_DAYOC_S12_V1_P00")
        assert m is not None
        assert m.group("symbol") == "GER40"
        assert m.group("model") == "DAYOC"

    def test_crypto_symbol(self):
        m = NAME_PATTERN.match("33_TREND_BTCUSD_1H_IMPULSE_S03_V1_P02")
        assert m is not None
        assert m.group("symbol") == "BTCUSD"

    # --- Rejection cases ---

    def test_rejects_empty(self):
        assert NAME_PATTERN.match("") is None

    def test_rejects_garbage(self):
        assert NAME_PATTERN.match("hello_world") is None

    def test_rejects_partial(self):
        assert NAME_PATTERN.match("22_CONT_FX") is None

    def test_rejects_double_underscore_misplaced(self):
        """Structural bug: double underscore between model tokens."""
        assert NAME_PATTERN.match("22_CONT_FX_30M__RSIAVG_S02_V1_P03") is None

    def test_rejects_missing_sweep_prefix(self):
        """Missing 'S' before sweep number."""
        assert NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_02_V1_P03") is None

    def test_rejects_missing_parent_prefix(self):
        """Missing 'P' before parent number."""
        assert NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_03") is None

    def test_rejects_lowercase(self):
        assert NAME_PATTERN.match("22_cont_fx_30m_rsiavg_trendfilt_s02_v1_p03") is None

    def test_rejects_extra_trailing_text(self):
        """No unstructured trailing text allowed (only __SUFFIX)."""
        assert NAME_PATTERN.match("22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03_extra") is None


class TestRunSuffixPattern:

    def test_valid_suffixes(self):
        assert _RUN_SUFFIX_RE.match("__E152") is not None
        assert _RUN_SUFFIX_RE.match("__ROBUST") is not None
        assert _RUN_SUFFIX_RE.match("__MC1000") is not None

    def test_rejects_no_prefix(self):
        assert _RUN_SUFFIX_RE.match("E152") is None

    def test_rejects_lowercase(self):
        assert _RUN_SUFFIX_RE.match("__e152") is None

    def test_rejects_single_underscore(self):
        assert _RUN_SUFFIX_RE.match("_E152") is None
