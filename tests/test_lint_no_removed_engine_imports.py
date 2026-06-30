"""The removed-engine import lint (tools/lint_no_removed_engine_imports.py) must
catch imports of the consolidation-removed engines v1.5.3-v1.5.9, while leaving the
kept engines (v1_5_10 rollback / v1_5_11 canonical) and historical references in
comments/strings/docstrings alone.

Locks the enforcement gate itself so the single-active-engine invariant
(ENGINE_VAULT_CONTRACT.md section 14) cannot silently decay — per
feedback_enforceable_mechanisms_only (test the enforcer, not just document it).
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from lint_no_removed_engine_imports import is_exempt, scan_file  # noqa: E402


def _write(tmp_path: Path, code: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(code, encoding="utf-8")
    return p


@pytest.mark.parametrize("code", [
    "from engine_dev.universal_research_engine.v1_5_3.main import run_engine",
    "from engine_dev.universal_research_engine.v1_5_6.execution_loop import ContextView",
    "import engine_dev.universal_research_engine.v1_5_8.stage2_compiler",
    "import engine_dev.universal_research_engine.v1_5_9",
])
def test_flags_removed_engine_imports(tmp_path, code):
    """A deliberately-introduced import of a removed engine MUST be flagged."""
    assert scan_file(_write(tmp_path, code)), f"lint must flag: {code!r}"


@pytest.mark.parametrize("code", [
    # Kept engines — never flagged (the v1_5_[3-9] regex excludes v1_5_10/11).
    "from engine_dev.universal_research_engine.v1_5_10 import execution_loop",
    "import engine_dev.universal_research_engine.v1_5_11.main",
    # Historical references that are NOT runtime imports — must NOT be flagged.
    "# originated in v1_5_8; see engine_dev/universal_research_engine/v1_5_8/main.py",
    'PATH = "engine_dev/universal_research_engine/v1_5_6/main.py"',
    '"""Docstring mentioning the since-removed v1_5_8 engine (f3ae767)."""',
])
def test_ignores_kept_engines_and_non_imports(tmp_path, code):
    assert not scan_file(_write(tmp_path, code)), f"lint must NOT flag: {code!r}"


def test_active_tree_has_no_removed_engine_imports():
    """The live repo is the consolidation end-state: zero removed-engine imports
    in non-exempt code (vault/archive/tmp/.claude are exempt)."""
    from lint_helpers import get_all_py_files

    files = [f for f in get_all_py_files(PROJECT_ROOT, is_exempt) if not is_exempt(f)]
    offenders = {}
    for f in files:
        hits = scan_file(f)
        if hits:
            offenders[str(f.relative_to(PROJECT_ROOT))] = hits
    assert not offenders, f"removed-engine imports in live code: {offenders}"
