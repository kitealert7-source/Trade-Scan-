"""Regression tests for INFRA-AUDIT H2 closure — encoding lint extension.

Before fix: `tools/lint_encoding.py` only caught bare `.read_text()`. It
missed `open(...)` without encoding= and `.write_text(...)` without encoding=.
The original audit found 8 instances of these patterns in production code
(watchdog state, audit snapshot writes, broker spec read, robustness loader).
All 8 are now patched. Linter must now block future regressions.

These tests run the linter as a black box against synthetic single-file
fixtures to verify the regex patterns hit (and don't false-positive) on
each class of construct.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LINT_PATH = PROJECT_ROOT / "tools" / "lint_encoding.py"

# Load the lint module as a library (it's a script).
_spec = importlib.util.spec_from_file_location("lint_encoding", LINT_PATH)
_lint = importlib.util.module_from_spec(_spec)
sys.modules["lint_encoding"] = _lint
_spec.loader.exec_module(_lint)


def _scan_text(tmp_path: Path, code: str) -> list[tuple[int, str, str]]:
    """Write `code` to a temp .py file, scan, return list of violations."""
    f = tmp_path / "fixture.py"
    f.write_text(code, encoding="utf-8")
    return _lint.scan_file(f)


# ---------------------------------------------------------------------------
# Pattern 1: bare .read_text() — original behavior preserved
# ---------------------------------------------------------------------------

def test_bare_read_text_flagged(tmp_path):
    code = 'data = path.read_text()\n'
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "read_text" for v in violations)


def test_read_text_with_encoding_passes(tmp_path):
    code = 'data = path.read_text(encoding="utf-8")\n'
    violations = _scan_text(tmp_path, code)
    assert not any(v[1] == "read_text" for v in violations)


# ---------------------------------------------------------------------------
# Pattern 2: .write_text() without encoding=
# ---------------------------------------------------------------------------

def test_bare_write_text_flagged(tmp_path):
    code = 'path.write_text("hello")\n'
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "write_text" for v in violations), \
        f"expected write_text violation, got {violations}"


def test_write_text_with_encoding_passes(tmp_path):
    code = 'path.write_text("hello", encoding="utf-8")\n'
    violations = _scan_text(tmp_path, code)
    assert not any(v[1] == "write_text" for v in violations)


def test_write_text_with_complex_arg_no_encoding_flagged(tmp_path):
    code = 'path.write_text(json.dumps(data, indent=2))\n'
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "write_text" for v in violations)


# ---------------------------------------------------------------------------
# Pattern 3: open() text-mode without encoding=
# ---------------------------------------------------------------------------

def test_bare_open_default_mode_flagged(tmp_path):
    """open(path) — default mode is 'r' (text), no encoding → VIOLATION."""
    code = 'with open("foo.txt") as f:\n    data = f.read()\n'
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "open" for v in violations), \
        f"expected open violation, got {violations}"


def test_open_explicit_text_mode_flagged(tmp_path):
    code = 'with open(path, "r") as f:\n    data = f.read()\n'
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "open" for v in violations)


def test_open_write_mode_flagged(tmp_path):
    code = 'with open(path, "w") as f:\n    f.write("hi")\n'
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "open" for v in violations)


def test_open_binary_mode_passes(tmp_path):
    """Binary mode never has encoding — must NOT be flagged."""
    for mode in ("rb", "wb", "ab", "rb+"):
        code = f'with open(path, "{mode}") as f:\n    pass\n'
        violations = _scan_text(tmp_path, code)
        assert not any(v[1] == "open" for v in violations), \
            f"binary mode {mode} should not be flagged"


def test_open_with_encoding_passes(tmp_path):
    code = 'with open(path, "r", encoding="utf-8") as f:\n    pass\n'
    violations = _scan_text(tmp_path, code)
    assert not any(v[1] == "open" for v in violations)


def test_open_with_encoding_kwarg_only_passes(tmp_path):
    code = 'with open(path, encoding="utf-8") as f:\n    pass\n'
    violations = _scan_text(tmp_path, code)
    assert not any(v[1] == "open" for v in violations)


def test_os_open_file_descriptor_not_flagged(tmp_path):
    """os.open() returns a file descriptor (int), not a stream — no encoding
    needed. Must NOT be flagged. This is what sweep_registry_gate.py and
    run_registry.py use for file locks."""
    code = 'fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)\n'
    violations = _scan_text(tmp_path, code)
    assert not any(v[1] == "open" for v in violations)


def test_open_with_path_call_inside_args_passes(tmp_path):
    """open(Path("foo"), "r", encoding="utf-8") — nested call should not
    confuse the parser."""
    code = 'with open(Path("foo.txt"), "r", encoding="utf-8") as f:\n    pass\n'
    violations = _scan_text(tmp_path, code)
    assert not any(v[1] == "open" for v in violations)


# ---------------------------------------------------------------------------
# Real-world examples that were the actual H2 bugs
# ---------------------------------------------------------------------------

def test_h2_watchdog_pattern_now_flagged(tmp_path):
    """Replicate the original watchdog_daemon.py:159 pattern."""
    code = (
        "if not EXEC_STATE.exists():\n"
        "    return None\n"
        "with open(EXEC_STATE) as f:\n"
        "    d = json.load(f)\n"
    )
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "open" for v in violations)


def test_h2_audit_snapshot_pattern_now_flagged(tmp_path):
    """Replicate the original create_audit_snapshot.py:105 pattern."""
    code = (
        'with open(TARGET_DIR / "AUDIT_METADATA.json", "w") as f:\n'
        "    json.dump(metadata, f, indent=4)\n"
    )
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "open" for v in violations)


def test_h2_broker_spec_pattern_now_flagged(tmp_path):
    """Replicate the original capital_broker_spec.py:87 pattern."""
    code = (
        'with open(spec_path, "r") as f:\n'
        "    return yaml.safe_load(f)\n"
    )
    violations = _scan_text(tmp_path, code)
    assert any(v[1] == "open" for v in violations)


# ---------------------------------------------------------------------------
# H2 patched files now lint clean
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relpath", [
    "tools/orchestration/watchdog_daemon.py",
    "tools/create_audit_snapshot.py",
    "tools/capital/capital_broker_spec.py",
    "tools/robustness/loader.py",
])
def test_originally_flagged_files_are_now_clean_at_h2_sites(relpath):
    """The 8 H2 sites are now fixed. The lint must NOT flag them anymore.

    Note: these files may still contain OTHER unencoded open() calls outside
    the original H2 audit scope — those are tracked separately. We just
    verify that the lines specifically called out in the audit report no
    longer trigger violations.
    """
    target = PROJECT_ROOT / relpath
    if not target.exists():
        pytest.skip(f"{relpath} not present")
    violations = _lint.scan_file(target)
    # Convert to set of (lineno, kind) for easy lookup
    violation_lines = {v[0] for v in violations}

    # H2 audit-flagged line numbers per file (1-based, post-fix expectation).
    # The lines we patched should NOT show up. Other lines might (out of
    # H2 scope; tracked under broader sweep follow-up).
    h2_lines_per_file = {
        "tools/orchestration/watchdog_daemon.py": [159, 175, 252, 263],
        "tools/create_audit_snapshot.py": [105, 109],
        "tools/capital/capital_broker_spec.py": [87],
        "tools/robustness/loader.py": [40, 54],
    }
    for lineno in h2_lines_per_file.get(relpath, []):
        assert lineno not in violation_lines, (
            f"H2 site {relpath}:{lineno} still flags as violation after fix"
        )


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
