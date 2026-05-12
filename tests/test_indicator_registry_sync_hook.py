"""Regression — pre-commit indicator-registry-sync hook.

The 2026-05-12 governance follow-up added a forcing function: adding an
`indicators/<cat>/<name>.py` file without a matching entry in
`indicators/INDICATOR_REGISTRY.yaml` must block the commit. Without it,
disk-vs-registry drift can creep back in and Stage-0.5 admission gates
become unreliable.

Two layers are tested:

  1. `tools/lint_indicator_registry_sync.py` — the actual hook step.
     Mode `--staged` reads `git diff --cached --diff-filter=A` and
     `git show :indicators/INDICATOR_REGISTRY.yaml`.

  2. `tools/indicator_registry_sync.py` — the operator helper. Tests
     focus on the bits the hook depends on (parsing, drift detection,
     `--add-stub` behavior).

The `--staged` mode requires a real git index, so those tests build a
tmp_path repo, stage controlled file content, and run the lint as a
subprocess.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LINT_SCRIPT = PROJECT_ROOT / "tools" / "lint_indicator_registry_sync.py"
SYNC_SCRIPT = PROJECT_ROOT / "tools" / "indicator_registry_sync.py"


# ---------------------------------------------------------------------------
# Fixture — synthetic git repo with indicators/ + registry
# ---------------------------------------------------------------------------

def _run(cwd: Path, *cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        encoding="utf-8",
    )


def _make_registry(paths: list[str]) -> str:
    """Produce a minimal valid INDICATOR_REGISTRY.yaml string with the
    given module_paths registered as stubs.
    """
    entries: dict = {}
    for mp in paths:
        name = mp.split(".")[-1]
        entries[name] = {"module_path": mp, "category": mp.split(".")[1]}
    data = {
        "registry_version": 1,
        "generated_at": "2026-05-12T00:00:00",
        "indicators": entries,
    }
    return yaml.safe_dump(data, sort_keys=False)


@pytest.fixture()
def fake_repo(tmp_path):
    """Initialize a git repo at tmp_path, copy the lint script in,
    return the path. The lint script needs PROJECT_ROOT to resolve to
    the repo's worktree to find `indicators/INDICATOR_REGISTRY.yaml`
    via `PROJECT_ROOT/REGISTRY_PATH_REL`. We achieve this by copying
    `tools/lint_indicator_registry_sync.py` into `<tmp>/tools/` and
    invoking it from `<tmp>` so its `Path(__file__).parent.parent`
    resolves to <tmp>.
    """
    _run(tmp_path, "git", "init", "-q")
    _run(tmp_path, "git", "config", "user.email", "ci@local")
    _run(tmp_path, "git", "config", "user.name", "ci")
    (tmp_path / "tools").mkdir()
    shutil.copy(LINT_SCRIPT, tmp_path / "tools" / "lint_indicator_registry_sync.py")
    (tmp_path / "indicators").mkdir()
    (tmp_path / "indicators" / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def _run_lint_staged(repo: Path) -> subprocess.CompletedProcess:
    """Invoke the lint in --staged mode from inside the fake repo."""
    return subprocess.run(
        [sys.executable, "tools/lint_indicator_registry_sync.py", "--staged"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. Hook — pass case: indicator + registry entry staged together
# ---------------------------------------------------------------------------

def test_hook_passes_when_new_indicator_and_registry_staged_together(fake_repo):
    """The expected good path: author stages both the new .py and the
    registry update in the same commit."""
    cat_dir = fake_repo / "indicators" / "momentum"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "new_ind.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(["indicators.momentum.new_ind"]),
        encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "-A")

    result = _run_lint_staged(fake_repo)
    assert result.returncode == 0, (
        f"Expected lint to PASS. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 2. Hook — block case: indicator staged but registry NOT updated
# ---------------------------------------------------------------------------

def test_hook_blocks_when_new_indicator_added_but_registry_unchanged(fake_repo):
    """The bug we are preventing: author adds a new indicator file but
    forgets the registry entry. Hook must block.
    """
    # Step 1: commit an empty registry baseline so a later modification
    # is visible to `git diff --cached`.
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "-A")
    _run(fake_repo, "git", "commit", "-q", "-m", "baseline")

    # Step 2: add a new indicator file but DO NOT update the registry.
    cat_dir = fake_repo / "indicators" / "structure"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "rogue.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "indicators/structure/")

    result = _run_lint_staged(fake_repo)
    assert result.returncode == 1, (
        f"Expected lint to BLOCK. stdout:\n{result.stdout}"
    )
    assert "indicators/structure/rogue.py" in result.stdout
    assert "indicators.structure.rogue" in result.stdout
    # The fix-it message must name both the helper and the registry path.
    assert "indicator_registry_sync.py" in result.stdout
    assert "INDICATOR_REGISTRY.yaml" in result.stdout


# ---------------------------------------------------------------------------
# 3. Hook — only ADDED files are checked (modifications pass through)
# ---------------------------------------------------------------------------

def test_hook_ignores_modifications_to_already_registered_modules(fake_repo):
    """Modifying a registered indicator's body must NOT trigger the
    hook. Bug fixes / refactors should not require a registry change.
    """
    cat_dir = fake_repo / "indicators" / "trend"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "ema_cross.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(["indicators.trend.ema_cross"]),
        encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "-A")
    _run(fake_repo, "git", "commit", "-q", "-m", "baseline with ema_cross")

    # Modify the existing file — registry unchanged.
    (cat_dir / "ema_cross.py").write_text(
        "def apply(df):\n    # tweaked implementation\n    return df\n",
        encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "indicators/trend/ema_cross.py")

    result = _run_lint_staged(fake_repo)
    assert result.returncode == 0, (
        f"Modifications to registered indicators must pass. stdout:\n"
        f"{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 4. Hook — __init__.py additions are not policed
# ---------------------------------------------------------------------------

def test_hook_ignores_init_py_additions(fake_repo):
    """Adding a new `indicators/<cat>/__init__.py` (e.g., when creating
    a new category directory) must not block the commit — `__init__.py`
    is not an indicator module.
    """
    cat_dir = fake_repo / "indicators" / "newcat"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "-A")

    result = _run_lint_staged(fake_repo)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# 5. Hook — non-indicators/ files are not policed
# ---------------------------------------------------------------------------

def test_hook_ignores_files_outside_indicators_tree(fake_repo):
    """Adding e.g. `tools/foo.py` must not trigger the indicator hook.
    Scope discipline.
    """
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )
    (fake_repo / "tools" / "foo.py").write_text(
        "def foo(): pass\n", encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "-A")

    result = _run_lint_staged(fake_repo)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# 6. Hook — staged registry blob (not working-tree) is the authority
# ---------------------------------------------------------------------------

def test_hook_reads_staged_registry_not_working_tree(fake_repo):
    """If the operator updated the registry on disk but forgot to
    `git add` it, the staged blob is still the OLD registry. The hook
    must read the staged blob, not the working tree, and block.
    """
    cat_dir = fake_repo / "indicators" / "volatility"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "-A")
    _run(fake_repo, "git", "commit", "-q", "-m", "baseline empty registry")

    # Add the indicator file AND update the registry on disk — but only
    # `git add` the .py, leaving the registry update unstaged.
    (cat_dir / "stealth.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(["indicators.volatility.stealth"]),
        encoding="utf-8",
    )
    _run(fake_repo, "git", "add", "indicators/volatility/stealth.py")
    # NOTE: registry NOT staged.

    result = _run_lint_staged(fake_repo)
    assert result.returncode == 1, (
        "Hook must read the STAGED registry blob, not the working tree. "
        "Working tree has the entry, but the index does not — commit "
        "would land the new file with no registry entry in the same "
        f"commit. stdout:\n{result.stdout}"
    )
    assert "indicators.volatility.stealth" in result.stdout


# ---------------------------------------------------------------------------
# 7. Helper — drift report
# ---------------------------------------------------------------------------

def test_sync_helper_check_passes_on_real_registry():
    """Sanity: the real repo's disk vs registry should be in sync after
    today's governance work. If this breaks, run
    `python tools/indicator_registry_sync.py --check` to see what
    drifted.
    """
    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"Real repo has drift. stdout:\n{result.stdout}"
    )


def test_sync_helper_add_stub_appends_minimal_entry(tmp_path, monkeypatch):
    """`--add-stub indicators.foo.bar` must create the .py file's
    registry entry as a stub, bump version, and be idempotent.
    """
    import importlib
    import tools.indicator_registry_sync as sync_mod

    fake_root = tmp_path
    fake_indicators = fake_root / "indicators"
    fake_cat = fake_indicators / "fakecat"
    fake_cat.mkdir(parents=True)
    (fake_cat / "myind.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_indicators / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )

    monkeypatch.setattr(sync_mod, "PROJECT_ROOT", fake_root, raising=True)
    monkeypatch.setattr(sync_mod, "INDICATORS_ROOT", fake_indicators, raising=True)
    monkeypatch.setattr(
        sync_mod, "REGISTRY_PATH",
        fake_indicators / "INDICATOR_REGISTRY.yaml", raising=True,
    )
    importlib.reload(sync_mod)  # ensure constants pick up patches if needed
    # `reload` resets module-level constants — re-apply patches after.
    monkeypatch.setattr(sync_mod, "PROJECT_ROOT", fake_root, raising=True)
    monkeypatch.setattr(sync_mod, "INDICATORS_ROOT", fake_indicators, raising=True)
    monkeypatch.setattr(
        sync_mod, "REGISTRY_PATH",
        fake_indicators / "INDICATOR_REGISTRY.yaml", raising=True,
    )

    rc = sync_mod.cmd_add_stub("indicators.fakecat.myind")
    assert rc == 0

    reg = yaml.safe_load(
        (fake_indicators / "INDICATOR_REGISTRY.yaml").read_text(encoding="utf-8")
    )
    paths = {
        e["module_path"] for e in reg["indicators"].values()
        if isinstance(e, dict) and e.get("module_path")
    }
    assert "indicators.fakecat.myind" in paths

    # Idempotent — running again is a no-op.
    rc2 = sync_mod.cmd_add_stub("indicators.fakecat.myind")
    assert rc2 == 0


def test_sync_helper_add_stub_refuses_phantom_paths(tmp_path, monkeypatch):
    """Cannot register a module that does not exist on disk — guards
    against typos and against accidentally re-creating the
    NEWSBRK-style phantom-registry-entry problem.
    """
    import tools.indicator_registry_sync as sync_mod

    fake_root = tmp_path
    fake_indicators = fake_root / "indicators"
    fake_indicators.mkdir()
    (fake_indicators / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )

    monkeypatch.setattr(sync_mod, "PROJECT_ROOT", fake_root, raising=True)
    monkeypatch.setattr(sync_mod, "INDICATORS_ROOT", fake_indicators, raising=True)
    monkeypatch.setattr(
        sync_mod, "REGISTRY_PATH",
        fake_indicators / "INDICATOR_REGISTRY.yaml", raising=True,
    )

    rc = sync_mod.cmd_add_stub("indicators.nowhere.phantom")
    assert rc == 2, "Must reject paths with no file on disk."
