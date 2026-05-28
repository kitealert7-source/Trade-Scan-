"""Tests for the memory_hint extension to intent_injector.

Plan: outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md Task C.

Covers:
  1. Emission format: soft intent with memory_hint emits "[Memory hint]" banner
     (not "[Skill hint]") and references the memory slug with [[..]] syntax.
  2. Validation: must declare either must_skill or memory_hint (or both).
  3. Validation: hard enforcement still requires must_skill (memory hints are
     advisory by design).
  4. The two new intents (test_window_signal_class, governance_as_evaluator)
     fire on representative prompts.
  5. The two new intents do NOT fire on meta-tooling phrases that just
     mention the relevant vocabulary.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_HOOK_PATH = PROJECT_ROOT / ".claude" / "hooks" / "intent_injector.py"
_INDEX_PATH = PROJECT_ROOT / "outputs" / "system_reports" / "INTENT_INDEX.yaml"

_spec = importlib.util.spec_from_file_location("intent_injector", _HOOK_PATH)
intent_injector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intent_injector)


def _run_hook(prompt: str) -> str:
    """Invoke the hook as a subprocess; return stdout (the injected text)."""
    payload = json.dumps({"prompt": prompt})
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
    )
    return result.stdout or ""


def _intent_id(stdout: str) -> str | None:
    if "intent_id=" in stdout:
        return stdout.split("intent_id=", 1)[1].split(")", 1)[0].strip()
    # Soft hints don't print intent_id; recover from log
    log_path = PROJECT_ROOT / ".claude" / "logs" / "intent_matches.jsonl"
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("level") == "WARN":
            continue
        chosen = rec.get("chosen") or {}
        if chosen.get("score", 0) > 0:
            return chosen.get("id")
        break
    return None


# --- emission format -------------------------------------------------------

def test_memory_hint_emits_memory_banner_not_skill_banner():
    intent = {
        "id": "x",
        "memory_hint": "feedback_test_window_must_match_signal_class",
        "enforcement": "soft",
        "reason": "test reason",
    }
    out = intent_injector._format_injection(intent)
    assert "[Memory hint]" in out
    assert "[Skill hint]" not in out
    assert "[[feedback_test_window_must_match_signal_class]]" in out
    assert "test reason" in out


def test_memory_hint_wins_when_both_fields_present():
    intent = {
        "id": "x",
        "must_skill": "rerun-backtest",
        "memory_hint": "feedback_test_window_must_match_signal_class",
        "enforcement": "soft",
        "reason": "test",
    }
    out = intent_injector._format_injection(intent)
    assert "[Memory hint]" in out
    assert "/rerun-backtest" not in out


def test_skill_hint_still_works_when_only_must_skill():
    intent = {
        "id": "x",
        "must_skill": "rerun-backtest",
        "enforcement": "soft",
        "reason": "test",
    }
    out = intent_injector._format_injection(intent)
    assert "[Skill hint]" in out
    assert "/rerun-backtest" in out


# --- validation ------------------------------------------------------------

def test_validation_requires_either_must_skill_or_memory_hint():
    intents = [{"id": "naked", "enforcement": "soft", "regex_patterns": []}]
    _, errors = intent_injector._validate_intents(intents)
    assert any("missing_target" in e["error"] for e in errors)


def test_validation_rejects_hard_intent_without_must_skill():
    intents = [{
        "id": "hard_memory",
        "enforcement": "hard",
        "memory_hint": "feedback_test_window_must_match_signal_class",
    }]
    _, errors = intent_injector._validate_intents(intents)
    assert any("hard_intent_needs_must_skill" in e["error"] for e in errors)


def test_validation_accepts_soft_memory_hint_only():
    intents = [{
        "id": "soft_memory",
        "enforcement": "soft",
        "memory_hint": "feedback_test_window_must_match_signal_class",
    }]
    _, errors = intent_injector._validate_intents(intents)
    # Only error allowed for this intent is missing_skill (already excluded since no must_skill).
    relevant = [e for e in errors if e["intent"] == "soft_memory"]
    assert not relevant, f"unexpected errors: {relevant}"


# --- live INTENT_INDEX.yaml: structure of the new intents -----------------

@pytest.fixture(scope="module")
def live_intents():
    data = yaml.safe_load(_INDEX_PATH.read_text(encoding="utf-8"))
    return {it["id"]: it for it in data["intents"]}


@pytest.mark.parametrize("intent_id,memory_slug", [
    ("test_window_signal_class", "feedback_test_window_must_match_signal_class"),
    ("governance_as_evaluator", "feedback_screening_rules_for_research"),
])
def test_new_intent_declared_with_memory_hint(live_intents, intent_id, memory_slug):
    intent = live_intents.get(intent_id)
    assert intent, f"intent {intent_id!r} not in INTENT_INDEX.yaml"
    assert intent.get("memory_hint") == memory_slug
    assert intent.get("enforcement") == "soft"
    assert intent.get("suppress_on_infra") is True, (
        "memory hints must declare a false-positive gate per the doctrine"
    )


# --- live behavior: positive cases ----------------------------------------

@pytest.mark.parametrize("prompt,expected_memory_slug", [
    ("use a 2-year test window with cointegrated pairs",
     "feedback_test_window_must_match_signal_class"),
    ("Should the backtest period for this cointegration screen be a calendar window?",
     "feedback_test_window_must_match_signal_class"),
    ("rank candidates by FAIL/CORE evaluator score",
     "feedback_screening_rules_for_research"),
    ("use the governance verdict as our research screen",
     "feedback_screening_rules_for_research"),
])
def test_new_intent_fires_on_trigger_phrase(prompt, expected_memory_slug):
    out = _run_hook(prompt)
    assert "[Memory hint]" in out, (
        f"Expected memory hint for prompt {prompt!r}; got stdout: {out[:200]!r}"
    )
    assert f"[[{expected_memory_slug}]]" in out, (
        f"Expected memory slug {expected_memory_slug!r} in hint; got: {out[:200]!r}"
    )


# --- live behavior: negative cases ----------------------------------------

_NEW_MEMORY_SLUGS = (
    "feedback_test_window_must_match_signal_class",
    "feedback_screening_rules_for_research",
)


@pytest.mark.parametrize("prompt", [
    # Meta-tooling about the intents themselves
    "delete the test_window_signal_class intent",
    "refactor the governance_as_evaluator hint",
    # Generic prompts that share vocabulary but aren't the workflow
    "rename the calendar widget",
    "remove the WATCH flag from this test fixture",
    # Pure infra discussion
    "refactor the governance directory layout",
])
def test_new_intent_suppressed_on_infra_phrasing(prompt):
    out = _run_hook(prompt)
    fired = [slug for slug in _NEW_MEMORY_SLUGS if f"[[{slug}]]" in out]
    assert not fired, (
        f"Memory-hint intent(s) {fired} false-fired on infra prompt: {prompt!r}"
    )
