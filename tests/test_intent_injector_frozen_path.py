"""S1 regression — engine_change intent must not fire on conversational
keywords alone; the change set must actually touch a frozen-scope path.

Bug class:
  Pre-fix, the `engine_change` intent in INTENT_INDEX.yaml fired purely
  on regex/fuzzy matches against the prompt text. Every session
  involving the word "engine" — session-close discussions, infra
  audits, path-resolution work — produced violations. By 2026-05-04
  the same session had accumulated 12+ violations in 24h, all from
  prompts that touched zero engine artifacts.

Fix:
  Set `frozen_path_only: true` on the engine_change intent. The hook's
  `_changes_touch_frozen_paths` mechanism (already implemented) then
  gates the injection on actual changed-file scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import the hook module by path since it lives outside the canonical
# package layout (.claude/hooks/).
import importlib.util

_HOOK_PATH = PROJECT_ROOT / ".claude" / "hooks" / "intent_injector.py"
_spec = importlib.util.spec_from_file_location("intent_injector", _HOOK_PATH)
intent_injector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intent_injector)


# ---------------------------------------------------------------------------
# Intent index assertion — the YAML must declare frozen_path_only on the
# engine_change intent. If a future edit removes it, this test catches.
# ---------------------------------------------------------------------------


class TestEngineChangeIntentDeclaresFrozenPathOnly:

    def test_intent_yaml_has_frozen_path_only_true(self):
        index_path = PROJECT_ROOT / "outputs" / "system_reports" / "INTENT_INDEX.yaml"
        data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        engine_change = next(
            (i for i in data["intents"] if i["id"] == "engine_change"), None
        )
        assert engine_change is not None, "engine_change intent missing from INTENT_INDEX.yaml"
        assert engine_change.get("frozen_path_only") is True, (
            "engine_change must declare `frozen_path_only: true` so the hook "
            "gates injection on actual file scope, not conversational "
            "keywords. See S1 fix in INTENT_INDEX.yaml."
        )


# ---------------------------------------------------------------------------
# Hook behavior — frozen-path filter suppresses engine_change when the
# change set has no engine-scope file.
# ---------------------------------------------------------------------------


class TestFrozenPathFilter:

    def test_changes_touch_frozen_paths_engine_dev(self):
        """File under engine_dev/<version>/ matches the default frozen
        patterns -> engine_change intent should fire."""
        files = ["engine_dev/universal_research_engine/v1_5_8/execution_loop.py"]
        assert intent_injector._changes_touch_frozen_paths(files) is True

    def test_changes_touch_frozen_paths_vault_engine(self):
        """vault/engines/... is a vaulted engine snapshot -> in scope."""
        files = ["vault/engines/Universal_Research_Engine/v1_5_8/contract.json"]
        assert intent_injector._changes_touch_frozen_paths(files) is True

    def test_changes_touch_frozen_paths_engine_manifest(self):
        """Any engine_manifest.json (regardless of directory) is in scope."""
        files = ["some/random/dir/engine_manifest.json"]
        assert intent_injector._changes_touch_frozen_paths(files) is True

    def test_changes_outside_frozen_scope_do_not_match(self):
        """Tools/path_authority + indicator + governance edits — typical
        of a non-engine session — must NOT trigger the filter."""
        files = [
            "config/path_authority.py",
            "tools/system_introspection.py",
            "tools/lint_no_hardcoded_paths.py",
            "indicators/price/candle_state.py",
            "governance/namespace/sweep_registry.yaml",
            "tests/test_path_authority_worktree_compat.py",
        ]
        assert intent_injector._changes_touch_frozen_paths(files) is False, (
            "Path-resolution / indicator / governance / test work must not "
            "trigger engine_change. The frozen scope is engine_dev/<v>/, "
            "vault/engines/, engine_manifest.json, contract.json — nothing "
            "else."
        )

    def test_empty_changes_do_not_match(self):
        """No changes -> nothing in scope -> intent suppressed."""
        assert intent_injector._changes_touch_frozen_paths([]) is False

    def test_engines_filter_stack_is_NOT_frozen_scope(self):
        """engines/ (mutable shared infra) is deliberately distinct from
        engine_dev/ (versioned snapshots) and vault/engines/ (vaulted).
        Editing engines/filter_stack.py during research is normal and
        must not require a vault push."""
        files = ["engines/filter_stack.py"]
        assert intent_injector._changes_touch_frozen_paths(files) is False
