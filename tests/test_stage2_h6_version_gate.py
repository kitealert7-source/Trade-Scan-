"""H6 (v1.5.11) — Stage-2 engine-version gate is now FAIL-CLOSED on a RELIABLE
runtime resolver.

Before H6: `get_runtime_engine_version()` read a `VALIDATED_ENGINE.manifest.json`
that never exists, on a dotted path that never matches the underscored engine
dirs, so it returned 'UNKNOWN' on every run and the strict-version check was
permanently dead (fail-OPEN). After H6 the runtime version resolves from the same
authority that stamped the run, and a metadata/runtime mismatch refuses to compile.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine_dev.universal_research_engine.v1_5_11.stage2_compiler import (
    get_runtime_engine_version,
    get_settings_df,
)


def _meta(**over):
    md = {"engine_version": get_runtime_engine_version(), "run_id": "r",
          "strategy_name": "s", "symbol": "X", "timeframe": "1h"}
    md.update(over)
    return md


def test_runtime_version_resolves_real_not_unknown():
    rv = get_runtime_engine_version()
    assert rv and rv != "UNKNOWN", f"runtime version must resolve, got {rv!r}"


def test_passes_when_metadata_matches_runtime():
    # Normal pipeline run: Stage-1 stamp == Stage-2 runtime -> compiles.
    df = get_settings_df(_meta())
    assert df is not None and len(df) > 0


def test_passes_on_equivalent_format_skew():
    # Underscored vs dotted must NOT false-raise (normalized compare).
    rv = get_runtime_engine_version()                       # dotted, e.g. "1.5.11"
    underscored = "v" + rv.replace(".", "_")                # "v1_5_11"
    df = get_settings_df(_meta(engine_version=underscored))
    assert df is not None


def test_raises_on_version_mismatch():
    with pytest.raises(ValueError, match="Mismatch"):
        get_settings_df(_meta(engine_version="0.0.1"))


def test_raises_on_missing_engine_version():
    md = _meta()
    md.pop("engine_version")
    with pytest.raises(ValueError, match="Unverifiable"):
        get_settings_df(md)


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
