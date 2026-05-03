"""Regression tests for hook routing — engine_change false-positive fix.

Background: the engine_change intent was firing on every prompt mentioning
"engine v1.5.8a" or "engine_dev/" or "ENGINE_VERSION", regardless of which
files were actually being modified. This led to 10+ misfires during the
NEWS-execution work where the only changes were in mutable shared infra
(engines/filter_stack.py, tools/sweep_registry_gate.py).

After fix: engine_change has `frozen_path_only: true`, which gates the
intent on actual changed-file scope. The text classifier still scores; the
file-scope post-filter suppresses the injection unless at least one
pending change is in:
  - engine_dev/universal_research_engine/<version>/...
  - vault/engines/...
  - any *engine_manifest.json
  - any *contract.json

Mutable shared infra is explicitly excluded:
  - engines/...
  - tools/...
  - governance/...
  - tests/...
  - outputs/...

These tests exercise the helpers directly to avoid coupling to a live
git working tree.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = PROJECT_ROOT / ".claude" / "hooks" / "intent_injector.py"

# The hook lives under .claude/ which is gitignored by repo policy
# (machine-local). On this machine, the file MUST exist and carry the
# frozen-path helpers added 2026-05-03. If either is missing, mark the
# whole module skipped — the user is on a clean clone and needs to
# apply the local patch from outputs/HOOK_ROUTING_ENGINE_FALSE_POSITIVE.md.
if not HOOK_PATH.exists():
    pytest.skip(
        f"{HOOK_PATH} not present — apply local hook patch from "
        "outputs/HOOK_ROUTING_ENGINE_FALSE_POSITIVE.md before running.",
        allow_module_level=True,
    )

# Load the hook module directly (it's a script, not a package member).
_spec = importlib.util.spec_from_file_location("intent_injector", HOOK_PATH)
_intent_injector = importlib.util.module_from_spec(_spec)
sys.modules["intent_injector"] = _intent_injector
_spec.loader.exec_module(_intent_injector)

# Defensive: skip gracefully on a clean machine where the hook file
# exists but hasn't yet had the file-scope filter patch applied.
if not hasattr(_intent_injector, "_changes_touch_frozen_paths"):
    pytest.skip(
        ".claude/hooks/intent_injector.py is missing the frozen-path "
        "helpers (_get_changed_files / _changes_touch_frozen_paths). "
        "Apply local hook patch from "
        "outputs/HOOK_ROUTING_ENGINE_FALSE_POSITIVE.md.",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "engines/filter_stack.py",
    "engines/regime_state_machine.py",
    "tools/sweep_registry_gate.py",
    "tools/register_sweep_stub.py",
    "tools/run_pipeline.py",
    "governance/preflight.py",
    "governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md",
    "tests/test_filter_stack_session_bar_hour.py",
    "outputs/INFRA_CLOSURE_SPRINT_2026_05_03.md",
    "indicators/macro/news_event_window.py",
    "config/state_paths.py",
])
def test_mutable_infra_paths_do_not_match_frozen(path):
    """Mutable shared infrastructure must NOT trigger engine_change."""
    assert _intent_injector._changes_touch_frozen_paths([path]) is False, (
        f"Mutable infra path '{path}' incorrectly classified as frozen-engine"
    )


@pytest.mark.parametrize("path", [
    "engine_dev/universal_research_engine/v1_5_8a/main.py",
    "engine_dev/universal_research_engine/v1_5_8a/execution_loop.py",
    "engine_dev/universal_research_engine/v1_5_8/execution_loop.py",
    "engine_dev/universal_research_engine/v1_6_0/main.py",
    "vault/engines/Universal_Research_Engine/v1_5_8a/manifest.json",
    "vault/engines/Universal_Research_Engine/v1_5_8a/execution_loop.py",
    "engine_dev/universal_research_engine/v1_5_8a/engine_manifest.json",
    "vault/engines/Universal_Research_Engine/v1_5_8a/contract.json",
])
def test_frozen_engine_paths_do_match(path):
    """Frozen-engine and vault paths MUST trigger engine_change."""
    assert _intent_injector._changes_touch_frozen_paths([path]) is True, (
        f"Frozen-engine path '{path}' was not classified as frozen"
    )


def test_empty_change_set_returns_false():
    """No changed files → no frozen-path match → engine_change suppressed."""
    assert _intent_injector._changes_touch_frozen_paths([]) is False


def test_mixed_change_set_with_one_frozen_path_triggers():
    """If any single change is frozen, engine_change fires (correct behavior)."""
    changed = [
        "engines/filter_stack.py",                          # mutable
        "tools/sweep_registry_gate.py",                     # mutable
        "engine_dev/universal_research_engine/v1_5_8a/main.py",  # FROZEN
        "outputs/SOMETHING.md",                             # mutable
    ]
    assert _intent_injector._changes_touch_frozen_paths(changed) is True


def test_all_mutable_change_set_does_not_trigger():
    """Today's INFRA closure sprint changes — none of these touch frozen paths."""
    today_changes = [
        "engines/filter_stack.py",
        "tools/sweep_registry_gate.py",
        "tools/register_sweep_stub.py",
        "tests/test_filter_stack_session_bar_hour.py",
        "tests/test_sweep_collision_detection.py",
        "outputs/INFRA_CLOSURE_SPRINT_2026_05_03.md",
        "outputs/PORT_MACDX_DUPLICATION_DIAGNOSIS.md",
        "governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md",
    ]
    assert _intent_injector._changes_touch_frozen_paths(today_changes) is False


# ---------------------------------------------------------------------------
# Custom pattern override (intent-level frozen_paths)
# ---------------------------------------------------------------------------

def test_custom_pattern_list_overrides_default():
    """An intent that supplies its own frozen_paths regex list uses it
    instead of the default."""
    custom = (r"^my_special_dir/",)
    assert _intent_injector._changes_touch_frozen_paths(
        ["engine_dev/universal_research_engine/v1_5_8a/main.py"], patterns=custom
    ) is False
    assert _intent_injector._changes_touch_frozen_paths(
        ["my_special_dir/something.py"], patterns=custom
    ) is True


# ---------------------------------------------------------------------------
# Engine-change intent has frozen_path_only flag in INTENT_INDEX.yaml
# ---------------------------------------------------------------------------

def test_intent_index_engine_change_has_frozen_path_only():
    """Static check: the engine_change intent in INTENT_INDEX.yaml carries
    frozen_path_only=true. Without this flag the file-scope filter is a
    no-op for engine_change."""
    intents, errors = _intent_injector._load_intents()
    eng = next((i for i in intents if i.get("id") == "engine_change"), None)
    assert eng is not None, "engine_change intent missing from INTENT_INDEX.yaml"
    assert eng.get("frozen_path_only") is True, (
        "engine_change must carry frozen_path_only=true; otherwise the "
        "false-positive fix is bypassed."
    )


def test_intent_index_engine_change_default_paths_align():
    """The engine_change intent's explicit frozen_paths list (or default)
    must accept frozen-engine paths and reject mutable infra paths."""
    intents, _ = _intent_injector._load_intents()
    eng = next(i for i in intents if i.get("id") == "engine_change")
    patterns = tuple(eng.get("frozen_paths", _intent_injector._DEFAULT_FROZEN_PATTERNS))
    assert _intent_injector._changes_touch_frozen_paths(
        ["engine_dev/universal_research_engine/v1_5_8a/main.py"], patterns=patterns
    ) is True
    assert _intent_injector._changes_touch_frozen_paths(
        ["engines/filter_stack.py"], patterns=patterns
    ) is False


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
