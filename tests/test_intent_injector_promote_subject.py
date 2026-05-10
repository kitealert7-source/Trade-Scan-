"""S3 regression — promote_strategy intent must not fire on infrastructure
work (deletion, refactor, migration, doctrine cleanup) just because the
prompt happens to share vocabulary with the workflow.

Bug class:
  Pre-fix, the `promote_strategy` intent in INTENT_INDEX.yaml fired on
  any prompt where two semantic tags (e.g. `promote` + `portfolio_complete`,
  `promote` + `deployable`) appeared at word boundaries. Talking ABOUT the
  /promote tool — refactoring it, documenting it, deleting stale logic,
  migrating doctrine — would inject a MANDATORY ROUTING block routing the
  agent to /promote, which is meaningless and disruptive.

  Concrete misfires observed during the BURN_IN doctrine migration on
  2026-05-10:
    - "We removed the consumer-side BURN_IN scaffolding..." -> promote_strategy
    - "Decisions: Rename target..."                          -> promote_strategy
    - "TS_Execution rebuild commit ... retired BURN_IN..."   -> promote_strategy

Fix:
  1. Add `requires_subject: true` to the promote_strategy intent.
  2. Hook adds two post-score filters when this flag is set:
     a. Infra-action suppression: prompts containing infrastructure verbs
        (delete/refactor/migrate/cleanup/rename/...) suppress the injection
        unless a STRONG subject identifier (strategy_id, PF_id, vault_id)
        is also named.
     b. Fuzzy-no-subject suppression: fuzzy-fired matches require a strong
        subject. Regex hits bypass — the patterns themselves encode subject
        requirements, and idiomatic phrasal patterns rely on (a) for safety.
  3. Add idiomatic regex patterns covering "add X to portfolio",
     "deploy X strategy", "promote X to live" — these fire on workflow
     phrasing that lacks a strict identifier.
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
_spec = importlib.util.spec_from_file_location("intent_injector", _HOOK_PATH)
intent_injector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intent_injector)


def _run_hook(prompt: str) -> tuple[bool, str | None, dict | None]:
    """Invoke the hook as a subprocess; return (hard_fired, intent_id, log_record).

    Mirrors how Claude Code invokes the hook on UserPromptSubmit so the test
    catches integration-level regressions, not just unit-level scoring bugs.
    """
    payload = json.dumps({"prompt": prompt})
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
    )
    out = result.stdout or ""
    fired_hard = "MANDATORY ROUTING" in out
    intent_id: str | None = None
    if "intent_id=" in out:
        intent_id = out.split("intent_id=", 1)[1].split(")", 1)[0].strip()

    # Find the matching log record (most recent).
    log_path = PROJECT_ROOT / ".claude" / "logs" / "intent_matches.jsonl"
    record: dict | None = None
    if log_path.exists():
        for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("snippet", "").startswith(prompt[:60]):
                record = rec
                break
    return fired_hard, intent_id, record


# ---------------------------------------------------------------------------
# Schema assertions — INTENT_INDEX.yaml must declare the gate
# ---------------------------------------------------------------------------


class TestPromoteStrategyDeclaresRequiresSubject:

    def test_intent_yaml_has_requires_subject_true(self):
        index_path = PROJECT_ROOT / "outputs" / "system_reports" / "INTENT_INDEX.yaml"
        data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        promote = next(
            (i for i in data["intents"] if i["id"] == "promote_strategy"), None
        )
        assert promote is not None, "promote_strategy intent missing from INTENT_INDEX.yaml"
        assert promote.get("requires_subject") is True, (
            "promote_strategy must declare `requires_subject: true` so the hook "
            "applies infra-action and fuzzy-no-subject suppression. See S3 fix."
        )


# ---------------------------------------------------------------------------
# Unit tests for the helper functions
# ---------------------------------------------------------------------------


class TestInfraActionDetector:

    @pytest.mark.parametrize("prompt", [
        "delete burn-in tools",
        "Remove waiting lifecycle",
        "RETIRE the old workflow",
        "cleanup stale portfolio validators",
        "refactor strategy loader",
        "rename promote_to_burnin",
        "migrate promotion doctrine",
        "deprecate the deployable profile",
        "decommission the registry",
        "doctrine drift",
        "scaffolding cleanup",
    ])
    def test_detects_infra_verbs(self, prompt):
        assert intent_injector._is_infra_action(prompt), (
            f"Expected infra-action detection on: {prompt!r}"
        )

    @pytest.mark.parametrize("prompt", [
        "promote KALFLIP BTC H1 to live",
        "add vault strategy to portfolio",
        "deploy NAS100 M5 strategy",
        "promote 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02",
    ])
    def test_does_not_flag_workflow_prompts(self, prompt):
        assert not intent_injector._is_infra_action(prompt), (
            f"Expected NO infra-action detection on workflow prompt: {prompt!r}"
        )


class TestStrongSubjectEvidence:

    @pytest.mark.parametrize("prompt", [
        "promote VOLEXP_NAS100_S05_V1_P02 to live",
        "deploy 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05",
        "PF_04C5F80CB1E3 needs review",
        "vault DRY_RUN_2026_05_10 was created",
    ])
    def test_detects_strong_subject(self, prompt):
        assert intent_injector._has_strong_subject_evidence(prompt), (
            f"Expected strong subject evidence in: {prompt!r}"
        )

    @pytest.mark.parametrize("prompt", [
        "promote KALFLIP BTC H1 to live",   # informal, no _V<n>_P<n>
        "add vault strategy to portfolio",   # generic
        "deploy NAS100 M5 strategy",         # symbol+TF only
        "delete burn-in tools",              # no subject at all
    ])
    def test_does_not_flag_informal(self, prompt):
        assert not intent_injector._has_strong_subject_evidence(prompt), (
            f"Expected NO strong subject evidence in: {prompt!r}"
        )


# ---------------------------------------------------------------------------
# Integration tests — must NOT trigger promote_strategy
# ---------------------------------------------------------------------------


class TestMustNotTrigger:
    """User-supplied false-positive prompts. Each must NOT result in a
    promote_strategy MANDATORY ROUTING injection."""

    @pytest.mark.parametrize("prompt", [
        # User's literal must-not-trigger list
        "delete burn-in tools",
        "remove waiting lifecycle",
        "migrate promotion doctrine",
        "cleanup stale portfolio validators",
        "refactor strategy loader",
        # Real misfires from the BURN_IN migration session
        ("We removed the consumer-side BURN_IN scaffolding in commit c1f6d83, "
         "but two doctrine drifts remain. Clean them up. The /promote workflow "
         "needs to flip lifecycle from BURN_IN to LIVE."),
        ("Decisions 1. Rename target Use: promote_to_live.py Not deploy.py, "
         "not to_live.py. Reason: preserves mental continuity with /promote."),
        ("TS_Execution rebuild commit 191c8da deliberately retired the entire "
         "BURN_IN lifecycle: shadow infrastructure deleted, profile system "
         "deleted, ALLOWED_LIFECYCLES = {LIVE, RETIRED}."),
        # Meta-tooling on the /promote tool itself
        "Refactor the /promote tool and the portfolio_complete handler",
        "Document the /promote skill and deployable profile pipeline",
        "I want to delete the /promote stale logic that handles portfolio_complete",
        "Update the /promote docstring to reference deployable artifacts",
        # Doctrine work
        "fix promote_strategy hook false positives",
        "rename the promote skill",
        "remove all references to /promote and burn-in",
    ])
    def test_does_not_fire_promote_strategy(self, prompt):
        fired_hard, intent_id, _ = _run_hook(prompt)
        if fired_hard and intent_id == "promote_strategy":
            pytest.fail(
                f"promote_strategy false-positive on: {prompt[:120]!r}\n"
                f"  intent_id={intent_id} fired_hard={fired_hard}"
            )


# ---------------------------------------------------------------------------
# Integration tests — MUST trigger promote_strategy
# ---------------------------------------------------------------------------


class TestMustTrigger:
    """Genuine workflow prompts. Each must result in promote_strategy."""

    @pytest.mark.parametrize("prompt", [
        # User's literal must-trigger list
        "promote KALFLIP BTC H1 to live",
        "add vault strategy to portfolio",
        "deploy NAS100 M5 strategy",
        # Strong-subject canonical phrasings
        "promote VOLEXP_NAS100_S05_V1_P02",
        "promote 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02 --profile RAW_MIN_LOT_V1",
        "move 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05 to live",
    ])
    def test_fires_promote_strategy(self, prompt):
        fired_hard, intent_id, record = _run_hook(prompt)
        assert fired_hard and intent_id == "promote_strategy", (
            f"Expected promote_strategy MANDATORY ROUTING on: {prompt!r}\n"
            f"  fired_hard={fired_hard} intent_id={intent_id}\n"
            f"  log_record={record}"
        )


# ---------------------------------------------------------------------------
# Other intents — requires_subject / suppress_on_infra coverage
# ---------------------------------------------------------------------------
#
# After the promote_strategy fix, the same false-positive pattern was found
# on the soft intents (rerun_backtest, run_directive, session_close,
# portfolio_edit). Each got the same treatment:
#   - rerun_backtest, run_directive, portfolio_edit -> requires_subject: true
#   - session_close                                 -> suppress_on_infra: true
# These tests pin the new behavior so future regressions are caught.


_STATE_PATH = PROJECT_ROOT / ".claude" / "state" / "last_intent.json"


def _intent_id_for(prompt: str) -> str | None:
    """Return chosen_intent for a prompt, or None if nothing fired (hard or soft).

    Reads from .claude/state/last_intent.json which the hook writes on every
    invocation (regardless of enforcement). Hard injections include intent_id
    in stdout; soft hints don't, so the state file is the universal source.
    """
    payload = json.dumps({"prompt": prompt})
    subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
    )
    if not _STATE_PATH.exists():
        return None
    try:
        state = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return state.get("intent_id")


class TestSchemaAssertions:
    """INTENT_INDEX.yaml must declare the gate flags so future edits
    don't silently drop them."""

    @pytest.fixture(scope="class")
    def intents(self):
        index_path = PROJECT_ROOT / "outputs" / "system_reports" / "INTENT_INDEX.yaml"
        return {
            i["id"]: i for i in yaml.safe_load(
                index_path.read_text(encoding="utf-8")
            )["intents"]
        }

    @pytest.mark.parametrize("intent_id", [
        "promote_strategy",
        "rerun_backtest",
        "run_directive",
        "portfolio_edit",
    ])
    def test_intent_has_requires_subject(self, intents, intent_id):
        intent = intents.get(intent_id)
        assert intent is not None, f"{intent_id} missing from INTENT_INDEX.yaml"
        assert intent.get("requires_subject") is True, (
            f"{intent_id} must declare `requires_subject: true` so the hook "
            f"applies subject + infra gate. See S3 fix."
        )

    def test_session_close_has_suppress_on_infra(self, intents):
        intent = intents.get("session_close")
        assert intent is not None
        assert intent.get("suppress_on_infra") is True, (
            "session_close must declare `suppress_on_infra: true` so meta-"
            "tooling prompts about the skill itself don't fire the hint."
        )


class TestRerunBacktestFalsePositives:
    """Soft hint /rerun-backtest must not fire on meta-tooling prompts
    that just mention the intent or skill name."""

    @pytest.mark.parametrize("prompt", [
        "Look for other intents using fuzzy-only scoring. Likely candidates: engine_change session_close rerun_backtest",
        "delete the rerun-backtest skill",
        "refactor the rerun-backtest workflow",
        "document how rerun handling works",
        "fix the rerun_backtest fuzzy regex",
    ])
    def test_does_not_fire(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent != "rerun_backtest", (
            f"rerun_backtest false-positive on: {prompt[:120]!r} (got {intent!r})"
        )


class TestRerunBacktestTruePositives:

    @pytest.mark.parametrize("prompt", [
        "rerun 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02",
        "re-run the directive after data refresh",
        "reset_directive.py for VOLEXP_NAS100_S05_V1_P02",
        "run __E158 on the existing directive",
    ])
    def test_fires(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent == "rerun_backtest", (
            f"Expected rerun_backtest on: {prompt!r} (got {intent!r})"
        )


class TestRunDirectiveFalsePositives:

    @pytest.mark.parametrize("prompt", [
        "delete the directive parser",
        "refactor the pipeline orchestrator",
        "rename stage1 to stage_one",
        "remove the backtest harness",
    ])
    def test_does_not_fire(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent != "run_directive", (
            f"run_directive false-positive on: {prompt[:120]!r} (got {intent!r})"
        )


class TestRunDirectiveTruePositives:

    @pytest.mark.parametrize("prompt", [
        "python tools/run_pipeline.py 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05",
        "run the directive 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02",
        "execute backtest for VOLEXP_NAS100",
        "run 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02",
    ])
    def test_fires(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent == "run_directive", (
            f"Expected run_directive on: {prompt!r} (got {intent!r})"
        )


class TestSessionCloseFalsePositives:

    @pytest.mark.parametrize("prompt", [
        "delete the session_close skill",
        "refactor session-close steps",
        "rename the session-close workflow",
        "remove the wrap_up tag",
        "migrate session_close logic",
    ])
    def test_does_not_fire(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent != "session_close", (
            f"session_close false-positive on: {prompt[:120]!r} (got {intent!r})"
        )


class TestSessionCloseTruePositives:

    @pytest.mark.parametrize("prompt", [
        "wrap up the session",
        "close the session",
        "end session and push",
        "/session-close",
    ])
    def test_fires(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent == "session_close", (
            f"Expected session_close on: {prompt!r} (got {intent!r})"
        )


class TestPortfolioEditFalsePositives:
    """portfolio_edit must not fire on meta-tooling prompts about portfolio
    code. Generic "add X to portfolio" routes to promote_strategy (higher
    priority), so we don't test that overlap here."""

    @pytest.mark.parametrize("prompt", [
        "add comments to the portfolio loader file",
        "add a docstring to portfolio_evaluator",
        "delete the portfolio_interpreter and portfolio_validator",
        "refactor the master_portfolio_sheet writer",
        "look at portfolio_interpreter then add a TODO",
    ])
    def test_does_not_fire(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent != "portfolio_edit", (
            f"portfolio_edit false-positive on: {prompt[:120]!r} (got {intent!r})"
        )


class TestPortfolioEditTruePositives:
    """portfolio_edit fires on IN_PORTFOLIO flag changes + control_panel CLI."""

    @pytest.mark.parametrize("prompt", [
        "set IN_PORTFOLIO=1 for 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02",
        "control_panel.py --select 02_VOL_NAS100_1D_VOLEXP_S05_V1_P02",
        "control_panel.py --deselect 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05",
        "flag VOLEXP_NAS100 for portfolio analysis",
    ])
    def test_fires(self, prompt):
        intent = _intent_id_for(prompt)
        assert intent == "portfolio_edit", (
            f"Expected portfolio_edit on: {prompt!r} (got {intent!r})"
        )


class TestEngineChangeStillProtected:
    """engine_change is already gated by frozen_path_only (S1 fix). Confirm
    the new requires_subject / suppress_on_infra additions didn't break it."""

    @pytest.mark.parametrize("prompt", [
        "engine v1.5.8 needs a vault push",
        "freeze the engine",
        "promote the engine to vault",
    ])
    def test_does_not_fire_without_engine_files(self, prompt):
        # Without engine_dev/<v>/ or vault/engines/ files in the change set,
        # engine_change must NOT fire.
        intent = _intent_id_for(prompt)
        assert intent != "engine_change", (
            f"engine_change false-positive on: {prompt!r} (got {intent!r})"
        )
