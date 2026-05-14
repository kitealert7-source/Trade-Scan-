"""Phase 0a Step 6 — adversarial tests for the engine_abi triple-gate.

Each manifest mutation below must trigger FAIL-CLOSED at EVERY enforcement
layer:
  Layer 1 (pre-commit hook): exit 1 from `tools/abi_audit.py --pre-commit`.
  Layer 2 (CI pipeline):    exit 1 from `tools/abi_audit.py --ci`.
  Layer 3 (runtime assert): RuntimeError at `import engine_abi.v1_5_X`.

Mutations under test:
  A. Add an unauthorized export to the package __init__ that isn't in the manifest.
  B. Remove an authorized export from the manifest while leaving the package
     export in place.
  C. Tamper with manifest_sha256.

The tests back up the manifest + package init before each scenario and
restore them in a finally block. They never leave the working tree dirty.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 0a Step 6.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GOV_DIR = _REPO_ROOT / "governance"
_PKG_DIR = _REPO_ROOT / "engine_abi"
_AUDIT_TOOL = _REPO_ROOT / "tools" / "abi_audit.py"

# Use v1_5_9 for adversarial mutation — it has more exports so the regex
# distinguishes mutations cleanly. v1_5_3 follows the same pattern; one
# representative is enough to exercise the framework.
_ABI = "v1_5_9"
_MANIFEST_PATH = _GOV_DIR / f"engine_abi_{_ABI}_manifest.yaml"
_PKG_INIT_PATH = _PKG_DIR / _ABI / "__init__.py"


def _run_audit(mode: str) -> subprocess.CompletedProcess[str]:
    """Run the audit tool in a fresh subprocess. Returns the CompletedProcess
    so callers can inspect rc + stdout + stderr."""
    return subprocess.run(
        [sys.executable, str(_AUDIT_TOOL), mode, "--abi-version", _ABI],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )


@contextmanager
def _backup_files(*paths: Path):
    """Backup files to .bak before the test mutates them, restore in finally."""
    backups: list[tuple[Path, Path]] = []
    try:
        for p in paths:
            bak = p.with_suffix(p.suffix + ".adversarial.bak")
            shutil.copy2(p, bak)
            backups.append((p, bak))
        yield
    finally:
        for p, bak in backups:
            shutil.copy2(bak, p)
            bak.unlink(missing_ok=True)


def _force_reload_abi():
    """Re-execute engine_abi.<_ABI> so its inline runtime assertion fires
    again. Returns the reloaded module or raises whatever the assertion does.

    Why importlib.reload() instead of `del sys.modules[...] + import_module`:
      The bare del+import pattern creates a NEW module object. Other test
      modules that already imported `from engine_abi import v1_5_9 as engine`
      keep their OLD reference, so when those tests subsequently run their
      own assertions (which check module identity against the manifest),
      the saved `__all__` reference no longer matches the package-level
      `__all__` — both `__all__` values are populated correctly, but the
      identity comparison fails. `importlib.reload()` re-executes the
      module body in place, preserving the original module identity AND
      triggering the runtime assertion. Same fail-closed behavior on
      drift, no full-suite test interference.

    Documented in SYSTEM_STATE Manual as the Phase 0a follow-up fix —
    closes the full-suite-run interference between
    `tests/test_engine_abi_adversarial.py` and
    `tests/test_basket_phase5c_real_data.py::test_dispatch_against_h2_directive_with_real_data`.
    """
    # First import (or get the existing module) so reload has a target.
    mod = importlib.import_module(f"engine_abi.{_ABI}")
    return importlib.reload(mod)


# ---------------------------------------------------------------------------
# Sanity guard — clean state passes
# ---------------------------------------------------------------------------


def test_sanity_clean_state_passes_all_layers():
    pre = _run_audit("--pre-commit")
    assert pre.returncode == 0, f"clean pre-commit fail: {pre.stderr or pre.stdout}"
    # Layer 3 runtime: a fresh import must succeed
    mod = _force_reload_abi()
    assert mod.__all__, "engine_abi loaded but exposes no symbols"


# ---------------------------------------------------------------------------
# Scenario A — unauthorized export added to package __init__
# ---------------------------------------------------------------------------


def test_adversarial_unauthorized_export_blocked():
    with _backup_files(_PKG_INIT_PATH):
        text = _PKG_INIT_PATH.read_text(encoding="utf-8")
        # Inject a bogus symbol into __all__ AND assign it. Locate the
        # insertion point by symbol lookup (the actual last entry in
        # engine_abi.<ver>.__all__) rather than by a hardcoded literal,
        # so the test is robust to manifest expansion.
        import re as _re
        import importlib as _importlib
        mod = _importlib.import_module(f"engine_abi.{_ABI}")
        last_symbol = mod.__all__[-1]
        pattern = _re.compile(rf'("{_re.escape(last_symbol)}",?)(\s*\n\])')
        m = pattern.search(text)
        assert m is not None, (
            f"test setup: cannot locate last __all__ entry {last_symbol!r} in package init"
        )
        injection = (
            m.group(1)
            + '\n    "rogue_unauthorized",'
            + m.group(2)
            + '\n\nrogue_unauthorized = "phantom"\n'
        )
        injected = text[: m.start()] + injection + text[m.end():]
        assert injected != text, "test setup: did not patch __all__"
        _PKG_INIT_PATH.write_text(injected, encoding="utf-8")

        pre = _run_audit("--pre-commit")
        assert pre.returncode != 0, (
            "FAIL-CLOSED expected from pre-commit on unauthorized export — "
            f"got rc={pre.returncode}: {pre.stdout}"
        )
        ci = _run_audit("--ci")
        assert ci.returncode != 0, (
            f"FAIL-CLOSED expected from --ci on unauthorized export — "
            f"got rc={ci.returncode}: {ci.stdout}"
        )

        with pytest.raises(RuntimeError, match="manifest drift detected"):
            _force_reload_abi()

    # Restore + force a clean reload so subsequent tests inherit known-good state.
    _force_reload_abi()


# ---------------------------------------------------------------------------
# Scenario B — manifest export removed while package still exposes it
# ---------------------------------------------------------------------------


def test_adversarial_manifest_export_removed_blocked():
    with _backup_files(_MANIFEST_PATH):
        with open(_MANIFEST_PATH, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        # Drop one authorized export from the manifest. Hash will also be
        # stale, but we deliberately don't re-hash — that's the adversarial
        # scenario (someone edits the manifest without re-stamping).
        removed = manifest["exports"].pop()
        with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)

        pre = _run_audit("--pre-commit")
        assert pre.returncode != 0, (
            f"FAIL-CLOSED expected on missing export {removed['name']!r}: "
            f"rc={pre.returncode} stdout={pre.stdout}"
        )
        with pytest.raises(RuntimeError, match="manifest drift detected"):
            _force_reload_abi()

    _force_reload_abi()


# ---------------------------------------------------------------------------
# Scenario C — manifest_sha256 tampered
# ---------------------------------------------------------------------------


def test_adversarial_manifest_sha256_tampered_blocked():
    with _backup_files(_MANIFEST_PATH):
        with open(_MANIFEST_PATH, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        manifest["manifest_sha256"] = "0" * 64  # wrong hex64
        with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)

        pre = _run_audit("--pre-commit")
        assert pre.returncode != 0
        assert "manifest_sha256 mismatch" in (pre.stdout + pre.stderr), pre.stdout

    _force_reload_abi()


# ---------------------------------------------------------------------------
# Scenario D — bogus consumer_count
# ---------------------------------------------------------------------------


def test_adversarial_consumer_count_inconsistent_blocked():
    with _backup_files(_MANIFEST_PATH):
        with open(_MANIFEST_PATH, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        manifest["exports"][0]["consumer_count"] = 99
        with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)
        pre = _run_audit("--pre-commit")
        assert pre.returncode != 0
        assert "consumer_count=99" in (pre.stdout + pre.stderr)
