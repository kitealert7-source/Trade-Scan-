"""Regression — Stage-0.5 indicator allowlist enforcement (Invariant 9).

The 2026-05-12 governance sync wired `indicators/INDICATOR_REGISTRY.yaml`
into `tools/semantic_validator.py` as the authoritative allowlist. Before
that, the check was structural-only: any import path starting with
``indicators.`` passed, regardless of whether the file existed on disk
(audit caught 14 NEWSBRK strategy folders importing non-existent modules
that ImportError'd at runtime instead of failing admission).

These tests pin the four-case enforcement matrix on the underlying
helper. They do NOT exercise the full `validate_semantic_signature`
end-to-end (which requires a full strategy.py + directive fixture) —
the helper is the layer that owns the allowlist policy, and isolating
the test here keeps signal clear and the failure messages legible.

| Case | Disk | Registry | Expected |
|---|---|---|---|
| Pass     | ✓ | ✓ | no raise |
| Fail-1   | ✗ | ✓ | raise: not on disk |
| Fail-2   | ✓ | ✗ | raise: not in registry |
| Fail-3   | ✗ | ✗ | raise: not on disk (disk check fires first) |
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixture — controlled registry + controlled disk tree
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_allowlist(tmp_path, monkeypatch):
    """Build a tiny indicators/ tree + INDICATOR_REGISTRY.yaml under tmp_path,
    then redirect the semantic_validator's module-level paths to it.

    Two modules are 'good' (on disk AND registered):
      - indicators.fake_cat.indicator_ok_one
      - indicators.fake_cat.indicator_ok_two

    One module is on disk but NOT in the registry:
      - indicators.fake_cat.disk_only

    One module is in the registry but NOT on disk:
      - indicators.fake_cat.registry_only
    """
    project_root = tmp_path
    indicators_root = project_root / "indicators"
    fake_cat = indicators_root / "fake_cat"
    fake_cat.mkdir(parents=True)
    (indicators_root / "__init__.py").write_text("", encoding="utf-8")
    (fake_cat / "__init__.py").write_text("", encoding="utf-8")

    # On-disk files
    (fake_cat / "indicator_ok_one.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_cat / "indicator_ok_two.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_cat / "disk_only.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    # `registry_only` deliberately has NO file.

    # Registry — three entries: two genuine + one phantom (registry_only).
    registry = {
        "registry_version": 99,
        "generated_at": "2026-05-12T00:00:00+05:30",
        "indicators": {
            "indicator_ok_one": {
                "module_path": "indicators.fake_cat.indicator_ok_one",
                "category": "fake_cat",
            },
            "indicator_ok_two": {
                "module_path": "indicators.fake_cat.indicator_ok_two",
                "category": "fake_cat",
            },
            "registry_only": {
                "module_path": "indicators.fake_cat.registry_only",
                "category": "fake_cat",
            },
        },
    }
    registry_path = indicators_root / "INDICATOR_REGISTRY.yaml"
    with open(registry_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(registry, f, sort_keys=False)

    # Redirect semantic_validator's module-level paths to the fixture tree.
    # Use the module object so monkeypatch.setattr targets the right symbol.
    import tools.semantic_validator as sv
    monkeypatch.setattr(sv, "PROJECT_ROOT", project_root, raising=True)
    monkeypatch.setattr(sv, "INDICATORS_ROOT", indicators_root, raising=True)
    monkeypatch.setattr(sv, "INDICATOR_REGISTRY_PATH", registry_path, raising=True)
    return {
        "project_root": project_root,
        "indicators_root": indicators_root,
        "registry_path": registry_path,
    }


# ---------------------------------------------------------------------------
# 1. Pass — valid import + on disk + in registry
# ---------------------------------------------------------------------------

def test_allowlist_passes_when_module_on_disk_and_registered(isolated_allowlist):
    from tools.semantic_validator import _enforce_indicator_allowlist
    # Two valid modules — must not raise.
    _enforce_indicator_allowlist({
        "indicators.fake_cat.indicator_ok_one",
        "indicators.fake_cat.indicator_ok_two",
    })


def test_allowlist_passes_when_set_is_empty(isolated_allowlist):
    """No declared indicators → nothing to check → pass. Strategies that
    don't import anything from `indicators/` (rare but legal) must not
    trip the allowlist.
    """
    from tools.semantic_validator import _enforce_indicator_allowlist
    _enforce_indicator_allowlist(set())


# ---------------------------------------------------------------------------
# 2. Fail — registered but not on disk (the NEWSBRK case)
# ---------------------------------------------------------------------------

def test_allowlist_fails_when_module_registered_but_missing_on_disk(
    isolated_allowlist,
):
    """The fixture's `indicators.fake_cat.registry_only` has a registry
    entry but no .py file. This mirrors the real-world NEWSBRK case
    where strategies imported `indicators.macro.news_event_window` which
    doesn't exist on disk — caught at admission instead of at runtime.
    """
    from tools.semantic_validator import _enforce_indicator_allowlist
    with pytest.raises(ValueError) as exc:
        _enforce_indicator_allowlist({"indicators.fake_cat.registry_only"})
    msg = str(exc.value)
    assert "do not exist on disk" in msg
    assert "indicators.fake_cat.registry_only" in msg
    # Operator guidance: the message must name the remediation paths
    # (restore file OR remove import + directive entry).
    assert "restore" in msg.lower() or "remove" in msg.lower()


# ---------------------------------------------------------------------------
# 3. Fail — on disk but not in registry
# ---------------------------------------------------------------------------

def test_allowlist_fails_when_module_on_disk_but_not_registered(
    isolated_allowlist,
):
    """The fixture's `indicators.fake_cat.disk_only` has a .py file but
    is NOT registered. The 2026-05-12 sync promoted the registry to the
    allowlist authority — disk presence alone is no longer sufficient.
    """
    from tools.semantic_validator import _enforce_indicator_allowlist
    with pytest.raises(ValueError) as exc:
        _enforce_indicator_allowlist({"indicators.fake_cat.disk_only"})
    msg = str(exc.value)
    assert "not registered" in msg.lower() or "registry" in msg.lower()
    assert "indicators.fake_cat.disk_only" in msg


# ---------------------------------------------------------------------------
# 4. Fail — completely unknown (neither disk nor registry)
# ---------------------------------------------------------------------------

def test_allowlist_fails_when_module_unknown_to_both_disk_and_registry(
    isolated_allowlist,
):
    """A typo'd import (`indicators.fake_cat.nonexistent`) is in neither
    the disk tree nor the registry. The disk-existence check fires first
    — that's the user-facing remediation path with the cheapest fix
    (restore the file or correct the typo).
    """
    from tools.semantic_validator import _enforce_indicator_allowlist
    with pytest.raises(ValueError) as exc:
        _enforce_indicator_allowlist({"indicators.fake_cat.nonexistent"})
    msg = str(exc.value)
    assert "do not exist on disk" in msg
    assert "indicators.fake_cat.nonexistent" in msg


# ---------------------------------------------------------------------------
# 5. Mixed-failure aggregation — multiple bad modules surfaced together
# ---------------------------------------------------------------------------

def test_allowlist_surfaces_all_disk_failures_in_one_error(isolated_allowlist):
    """When several modules fail the disk check, the operator should see
    every bad module in the same error message — not just the first one.
    Pin this so a future refactor doesn't accidentally short-circuit on
    the first failure.
    """
    from tools.semantic_validator import _enforce_indicator_allowlist
    with pytest.raises(ValueError) as exc:
        _enforce_indicator_allowlist({
            "indicators.fake_cat.indicator_ok_one",   # valid
            "indicators.fake_cat.registry_only",      # missing on disk
            "indicators.fake_cat.nonexistent",        # missing on disk
        })
    msg = str(exc.value)
    assert "indicators.fake_cat.registry_only" in msg
    assert "indicators.fake_cat.nonexistent" in msg


def test_disk_check_fires_before_registry_check(isolated_allowlist):
    """When a module is missing from BOTH disk and registry, the disk
    failure is the one surfaced — registry failures are only reported
    when the file actually exists. This is intentional: a missing file
    is the operator-actionable failure with the simplest remediation.
    """
    from tools.semantic_validator import _enforce_indicator_allowlist
    with pytest.raises(ValueError) as exc:
        _enforce_indicator_allowlist({"indicators.fake_cat.nonexistent"})
    msg = str(exc.value)
    assert "do not exist on disk" in msg
    # Registry error message uses the literal "not registered" wording —
    # confirm it's NOT what surfaces here.
    assert "not registered" not in msg.lower()


# ---------------------------------------------------------------------------
# 6. Real-registry sanity — disk and registry are in sync after the sync
# ---------------------------------------------------------------------------

def test_real_registry_resolves_every_entry_to_disk():
    """After the 2026-05-12 governance sync, every module_path in the
    real `indicators/INDICATOR_REGISTRY.yaml` must resolve to a file on
    disk under `indicators/`. Drift in either direction (registry entry
    without file, or file without registry entry) is a sync regression.
    """
    from tools.semantic_validator import (
        _load_registered_indicator_paths,
        INDICATORS_ROOT,
        PROJECT_ROOT,
    )

    registered = _load_registered_indicator_paths()
    assert registered, "Registry returned empty set — fixture / parse drift?"

    # Every registered module must have a file on disk.
    missing_files = []
    for mp in sorted(registered):
        path = PROJECT_ROOT / Path(*mp.split(".")).with_suffix(".py")
        if not path.exists():
            missing_files.append(mp)
    assert not missing_files, (
        "INDICATOR_REGISTRY.yaml references module(s) that do not exist on "
        f"disk: {missing_files}. Either restore the file or remove the "
        f"registry entry."
    )

    # Every disk module must have a registry entry (reverse direction).
    disk_modules = set()
    for p in INDICATORS_ROOT.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        rel = p.relative_to(PROJECT_ROOT).with_suffix("")
        disk_modules.add(".".join(rel.parts))

    unregistered = sorted(disk_modules - registered)
    assert not unregistered, (
        f"{len(unregistered)} indicator module(s) on disk are NOT registered "
        f"in INDICATOR_REGISTRY.yaml: {unregistered}. Add a registry entry "
        "for each (governance sync stub at minimum)."
    )
