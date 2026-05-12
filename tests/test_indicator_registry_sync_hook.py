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


# ---------------------------------------------------------------------------
# 10. Session-close drift check (Patch 1 from GOVERNANCE_DRIFT_PREVENTION_PLAN)
# ---------------------------------------------------------------------------
#
# `python tools/indicator_registry_sync.py --check` is wired into the
# session-close skill as Step 6b (NON-NEGOTIABLE) — non-zero exit blocks
# close. These tests pin:
#   - clean state returns 0 (the positive — also tested by the real-registry
#     case above, but we add the synthetic version here for completeness)
#   - drifted state returns 1 (the negative — the case Step 6b exists for)
#
# The drift check has two failure modes (`on_disk - registered` and
# `registered - on_disk`); both must return 1. Both are pinned below.


def _run_sync_check(repo: Path) -> subprocess.CompletedProcess:
    """Invoke the operator helper's --check mode against the fixture tree."""
    return subprocess.run(
        [sys.executable, "tools/indicator_registry_sync.py", "--check"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _seed_sync_helper_in(repo: Path) -> None:
    """Copy the sync helper into the fixture tree so its
    `Path(__file__).resolve().parent.parent` resolves to the fixture repo
    rather than the real Trade_Scan checkout.
    """
    (repo / "tools").mkdir(exist_ok=True)
    shutil.copy(SYNC_SCRIPT, repo / "tools" / "indicator_registry_sync.py")


def test_session_close_drift_check_passes_on_clean_state(fake_repo):
    """Step 6b PASS path — disk and registry in sync → exit 0, session-close
    proceeds. Establishes the positive baseline for the negative tests below.
    """
    _seed_sync_helper_in(fake_repo)
    cat_dir = fake_repo / "indicators" / "structure"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "clean_ind.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(["indicators.structure.clean_ind"]),
        encoding="utf-8",
    )
    result = _run_sync_check(fake_repo)
    assert result.returncode == 0, (
        f"Step 6b must PASS when disk and registry are in sync. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_session_close_drift_check_blocks_on_disk_only(fake_repo):
    """Step 6b BLOCK path #1 — indicator on disk, no registry entry.
    This is the hook-bypass scenario: author committed a `.py` with
    `--no-verify` so the pre-commit gate did not fire. Session-close
    must catch it.
    """
    _seed_sync_helper_in(fake_repo)
    cat_dir = fake_repo / "indicators" / "momentum"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "bypassed.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    # Registry deliberately empty — bypass scenario.
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )
    result = _run_sync_check(fake_repo)
    assert result.returncode == 1, (
        f"Step 6b must BLOCK when an indicator on disk is missing from "
        f"the registry. stdout:\n{result.stdout}"
    )
    assert "indicators.momentum.bypassed" in result.stdout
    assert "DRIFT DETECTED" in result.stdout


def test_session_close_drift_check_blocks_on_phantom_registry_entry(fake_repo):
    """Step 6b BLOCK path #2 — registry entry without a corresponding
    `.py` file. This is the manual-YAML-edit scenario the original
    NEWSBRK precedent fell into (14 directives importing modules whose
    `.py` files were never created). Session-close must catch it even
    though no `.py` diff exists for the pre-commit hook to inspect.
    """
    _seed_sync_helper_in(fake_repo)
    fake_repo_indicators = fake_repo / "indicators"
    # Registry asserts a module that does NOT exist on disk.
    (fake_repo_indicators / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(["indicators.macro.phantom_event_window"]),
        encoding="utf-8",
    )
    result = _run_sync_check(fake_repo)
    assert result.returncode == 1, (
        f"Step 6b must BLOCK on phantom registry entries — the NEWSBRK "
        f"precedent. stdout:\n{result.stdout}"
    )
    assert "indicators.macro.phantom_event_window" in result.stdout
    assert "DRIFT DETECTED" in result.stdout


def test_session_close_drift_check_message_names_remediation_command(fake_repo):
    """The BLOCK output must tell the operator how to fix it. Pin the
    explicit `--add-stubs` reference so a future refactor that changes
    the message doesn't strip the actionable remediation.
    """
    _seed_sync_helper_in(fake_repo)
    cat_dir = fake_repo / "indicators" / "trend"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "ghost.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )
    result = _run_sync_check(fake_repo)
    assert result.returncode == 1
    # Both pieces of the remediation must appear: the command name and
    # the flag.
    assert "indicator_registry_sync.py" in result.stdout
    assert "--add-stubs" in result.stdout


def test_session_close_skill_documents_step_6b():
    """The skill must actually contain the Step 6b instruction the
    runtime tests above pin. Document-level regression — guards against
    the skill being silently rewritten in a way that drops the gate.
    """
    skill_path = (
        PROJECT_ROOT / ".claude" / "skills" / "session-close" / "SKILL.md"
    )
    assert skill_path.exists(), (
        f"session-close skill missing at {skill_path} — this test cannot "
        "run without it."
    )
    text = skill_path.read_text(encoding="utf-8")
    assert "### 6b. Indicator Registry Drift Check" in text, (
        "Step 6b heading missing from session-close skill. Patch 1 of "
        "GOVERNANCE_DRIFT_PREVENTION_PLAN was either reverted or never "
        "applied."
    )
    assert "python tools/indicator_registry_sync.py --check" in text, (
        "Step 6b body must reference the actual check command."
    )
    # Quick Version copy-paste section must include the same gate.
    assert "# 4b. Indicator registry drift" in text, (
        "Quick Version section is missing the registry drift gate."
    )


# ---------------------------------------------------------------------------
# 11. Pre-push hook (Patch 2 from GOVERNANCE_DRIFT_PREVENTION_PLAN)
# ---------------------------------------------------------------------------
#
# Pre-commit is bypassable via `git commit --no-verify`. Pre-push catches
# that bypass at the network boundary before drift leaves the local clone.
#
# These tests pin two things:
#   - tools/hooks/install.sh actually installs the pre-push hook
#   - the installed hook blocks a `git push` when the registry has drift


PRE_PUSH_SCRIPT = PROJECT_ROOT / "tools" / "hooks" / "pre-push"
INSTALL_SCRIPT = PROJECT_ROOT / "tools" / "hooks" / "install.sh"


def _seed_hook_install_tree(repo: Path) -> None:
    """Copy the tools/hooks/ tree + sync helper + lint into the fixture
    repo so `install.sh` and the installed hook resolve correctly.
    """
    (repo / "tools" / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copy(PRE_PUSH_SCRIPT, repo / "tools" / "hooks" / "pre-push")
    shutil.copy(
        PROJECT_ROOT / "tools" / "hooks" / "pre-commit",
        repo / "tools" / "hooks" / "pre-commit",
    )
    shutil.copy(INSTALL_SCRIPT, repo / "tools" / "hooks" / "install.sh")
    os.chmod(repo / "tools" / "hooks" / "install.sh", 0o755)
    # The pre-push hook calls tools/indicator_registry_sync.py — copy it.
    shutil.copy(SYNC_SCRIPT, repo / "tools" / "indicator_registry_sync.py")


def test_install_sh_installs_pre_push_hook(fake_repo):
    """`tools/hooks/install.sh` extended in Patch 2 must install both
    pre-commit and pre-push. Document-level guard against the loop
    over `HOOK_NAMES` getting dropped by a future refactor.
    """
    _seed_hook_install_tree(fake_repo)

    install_path = fake_repo / "tools" / "hooks" / "install.sh"
    result = subprocess.run(
        ["sh", str(install_path)],
        cwd=str(fake_repo),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"install.sh failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # The git common dir is `<fake_repo>/.git` for a non-worktree clone.
    pre_push = fake_repo / ".git" / "hooks" / "pre-push"
    pre_commit = fake_repo / ".git" / "hooks" / "pre-commit"
    assert pre_push.exists(), "install.sh failed to install pre-push hook"
    assert pre_commit.exists(), "install.sh regressed on pre-commit hook"
    # On Windows the chmod is a no-op but should not fail; the hook still
    # works because git invokes via sh.
    assert pre_push.read_text(encoding="utf-8").startswith("#!/bin/sh")


def test_pre_push_hook_blocks_when_registry_drifts(fake_repo):
    """The installed pre-push hook exits 1 when indicator registry drift
    exists. We invoke the hook script directly (rather than running an
    actual `git push`) so the test is robust to Windows shell quirks and
    doesn't need a remote.
    """
    _seed_hook_install_tree(fake_repo)
    # Run install.sh first so the hook is in place.
    subprocess.run(
        ["sh", str(fake_repo / "tools" / "hooks" / "install.sh")],
        cwd=str(fake_repo), check=True,
        capture_output=True, text=True, encoding="utf-8",
    )

    # Introduce drift — an indicator file with no registry entry.
    cat_dir = fake_repo / "indicators" / "structure"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "drifted.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry([]), encoding="utf-8",
    )

    # Run the installed pre-push hook directly via sh.
    hook_path = fake_repo / ".git" / "hooks" / "pre-push"
    result = subprocess.run(
        ["sh", str(hook_path)],
        cwd=str(fake_repo),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1, (
        f"pre-push hook must BLOCK on drift. stdout:\n{result.stdout}"
    )
    # Operator guidance must be present in the failure message.
    assert "PUSH BLOCKED" in result.stdout
    assert "indicator_registry_sync.py" in result.stdout


def test_pre_push_hook_passes_when_registry_clean(fake_repo):
    """The installed pre-push hook exits 0 when disk and registry are in
    sync. Sanity check — without this the hook would block every push,
    not just drifted ones.
    """
    _seed_hook_install_tree(fake_repo)
    subprocess.run(
        ["sh", str(fake_repo / "tools" / "hooks" / "install.sh")],
        cwd=str(fake_repo), check=True,
        capture_output=True, text=True, encoding="utf-8",
    )

    cat_dir = fake_repo / "indicators" / "momentum"
    cat_dir.mkdir()
    (cat_dir / "__init__.py").write_text("", encoding="utf-8")
    (cat_dir / "clean.py").write_text(
        "def apply(df): return df\n", encoding="utf-8",
    )
    (fake_repo / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(["indicators.momentum.clean"]),
        encoding="utf-8",
    )

    hook_path = fake_repo / ".git" / "hooks" / "pre-push"
    result = subprocess.run(
        ["sh", str(hook_path)],
        cwd=str(fake_repo),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"pre-push hook must PASS when registry is clean. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 12. Runtime enforcement (Patch 3 from GOVERNANCE_DRIFT_PREVENTION_PLAN)
# ---------------------------------------------------------------------------
#
# Two runtime gates were added in Patch 3:
#   - `tools/run_pipeline.py::verify_indicator_registry_sync` — raises
#     PipelineAdmissionPause at pipeline startup. Halts the pipeline
#     before any directive admission attempt.
#   - `tools/verify_engine_integrity.py::verify_indicator_registry_sync` —
#     returns False at engine self-test. Caller (`run_check`) does
#     sys.exit(1) on False.
#
# Both shell out to `tools/indicator_registry_sync.py --check` so the
# check logic stays single-source. Tests below build a fixture tree
# containing the sync helper + a controlled indicators/ tree and
# invoke each gate against it.


def _seed_runtime_fixture(repo: Path, on_disk: list[str], registered: list[str]) -> None:
    """Lay out a synthetic project_root under `repo` containing the
    sync helper + a controlled indicators/ tree.

    `on_disk` is the list of dotted module paths to create as `.py` files.
    `registered` is the list of dotted module paths to register in
    INDICATOR_REGISTRY.yaml. Drift = a mismatch between the two.
    """
    (repo / "tools").mkdir(exist_ok=True)
    shutil.copy(SYNC_SCRIPT, repo / "tools" / "indicator_registry_sync.py")
    indicators = repo / "indicators"
    indicators.mkdir(exist_ok=True)
    (indicators / "__init__.py").write_text("", encoding="utf-8")
    for dotted in on_disk:
        parts = dotted.split(".")  # ['indicators', '<cat>', '<name>']
        cat_dir = repo / Path(*parts[:-1])
        cat_dir.mkdir(parents=True, exist_ok=True)
        init = cat_dir / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")
        (cat_dir / f"{parts[-1]}.py").write_text(
            "def apply(df): return df\n", encoding="utf-8",
        )
    (indicators / "INDICATOR_REGISTRY.yaml").write_text(
        _make_registry(registered), encoding="utf-8",
    )


def test_run_pipeline_verify_blocks_on_drift(tmp_path):
    """`verify_indicator_registry_sync(project_root)` raises
    PipelineAdmissionPause when the fixture tree has drift. This is the
    pipeline-start guardrail behavior.
    """
    from tools.run_pipeline import verify_indicator_registry_sync
    from tools.orchestration.pipeline_errors import PipelineAdmissionPause

    # On-disk module without a registry entry.
    _seed_runtime_fixture(
        tmp_path,
        on_disk=["indicators.fakecat.disk_only"],
        registered=[],
    )
    with pytest.raises(PipelineAdmissionPause) as excinfo:
        verify_indicator_registry_sync(tmp_path)
    assert "registry drift" in str(excinfo.value).lower()
    # Operator remediation must be in the message.
    assert "indicator_registry_sync.py" in str(excinfo.value)


def test_run_pipeline_verify_passes_on_clean_state(tmp_path, capsys):
    """`verify_indicator_registry_sync(project_root)` returns silently
    when disk and registry are in sync. No raise, "[GUARDRAIL]" log
    confirms the gate ran.
    """
    from tools.run_pipeline import verify_indicator_registry_sync

    _seed_runtime_fixture(
        tmp_path,
        on_disk=["indicators.fakecat.synced"],
        registered=["indicators.fakecat.synced"],
    )
    verify_indicator_registry_sync(tmp_path)  # must not raise
    out = capsys.readouterr().out
    assert "[GUARDRAIL] Indicator Registry: in sync." in out


def test_run_pipeline_verify_skips_when_helper_absent(tmp_path, capsys):
    """Defensive case: an older checkout that pre-dates 2026-05-12 does
    not have `tools/indicator_registry_sync.py` on disk. The guardrail
    must NOT block in that case — the going-forward defence is the
    pre-commit hook; pipeline runs on legacy clones should not regress.
    """
    from tools.run_pipeline import verify_indicator_registry_sync

    # No sync helper, no indicators/ tree.
    verify_indicator_registry_sync(tmp_path)
    out = capsys.readouterr().out
    assert "Sync helper not present" in out


def test_engine_integrity_check_returns_false_on_drift(tmp_path, monkeypatch):
    """`verify_engine_integrity.verify_indicator_registry_sync` returns
    False (not raise) when drift exists. The caller (`run_check`) is
    responsible for sys.exit(1). Mirrors `verify_hashes` /
    `verify_tools_integrity` shape.
    """
    import tools.verify_engine_integrity as vei

    _seed_runtime_fixture(
        tmp_path,
        on_disk=["indicators.fakecat.engine_drift"],
        registered=[],
    )
    monkeypatch.setattr(vei, "PROJECT_ROOT", tmp_path, raising=True)

    result = vei.verify_indicator_registry_sync()
    assert result is False, (
        "verify_indicator_registry_sync must return False on drift so "
        "the engine self-test can abort via sys.exit(1)."
    )


def test_engine_integrity_check_returns_true_on_clean_state(tmp_path, monkeypatch):
    """`verify_engine_integrity.verify_indicator_registry_sync` returns
    True when disk and registry are in sync.
    """
    import tools.verify_engine_integrity as vei

    _seed_runtime_fixture(
        tmp_path,
        on_disk=["indicators.fakecat.engine_synced"],
        registered=["indicators.fakecat.engine_synced"],
    )
    monkeypatch.setattr(vei, "PROJECT_ROOT", tmp_path, raising=True)

    assert vei.verify_indicator_registry_sync() is True


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
