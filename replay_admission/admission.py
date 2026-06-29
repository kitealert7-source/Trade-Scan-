"""Replay Admission — admission providers (Phase 2a).

Two ways to build the immutable `PipelineContext` (today's name for the design's
`ExperimentContext`) that the SINGLE downstream `StageRunner` consumes — selected once at
the entry point, after which there is zero difference:

    provider = select_admission_provider(source)     # DirectiveAdmission | ReplayAdmission
    ctx = provider.prepare_context(source)
    StageRunner(ctx).run()                            # the one execution pipeline

* `DirectiveAdmission` wraps today's `BootstrapController.prepare_context` UNCHANGED — the
  directive path keeps doing exactly what it does (canonicalize → provision → plan).
* `ReplayAdmission` builds the equivalent pre-Stage-1 context from an ExperimentBundle,
  SKIPPING canonicalize/provision-from-directive (the schema-drift wall): it materializes the
  experiment directive, provisions `strategy.py` (+ indicator snapshot) from the bundle, plans
  run_ids + registry (reusing `plan_runs_for_directive`), creates per-run `run_state` at
  `PREFLIGHT_COMPLETE_SEMANTICALLY_VALID`, and pre-marks `completed_stages={"PREFLIGHT"}` so
  `StageRunner` runs ONLY the execution stages (Stage-1 → Portfolio), unchanged.

Materialization invariant: neither provider hands raw source artifacts to `StageRunner` — both
produce a complete context first. Design: REPLAY_ADMISSION_DESIGN_2026-06-29.md (FROZEN v1).

Phase 2a = this module (new; *uses* the orchestrator machinery, does not modify it). Phase 2b
wires the `run_pipeline.py` entry branch (the one Protected-Infra touch) + the end-to-end
byte-identical break-test.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from replay_admission.bundle import ExperimentBundle, load_bundle, verify_bundle
from replay_admission.contract import REPO_ROOT

_PRE_STAGE1_STATE = "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID"
_ADMISSION_STAGE_ID = "PREFLIGHT"


class ReplayAdmissionError(RuntimeError):
    """The bundle failed the Admission Contract, or replay state setup could not complete."""


@runtime_checkable
class AdmissionProvider(Protocol):
    """Both admission paths implement this. `prepare_context` returns a fully-materialized
    `PipelineContext` ready for `StageRunner` — the single seam between admission and execution."""

    def prepare_context(self, source):  # -> PipelineContext
        ...


class DirectiveAdmission:
    """The existing directive front door, wrapped UNCHANGED (canonicalize + provision + plan).

    A pure delegation to `BootstrapController` — no behavior change to the directive path
    (the global 'directive path byte-identical' regression gate must stay green by construction)."""

    def __init__(self, project_root: Path = REPO_ROOT):
        self.project_root = Path(project_root)

    def prepare_context(self, directive_id: str, *, provision_only: bool = False):
        from tools.orchestration.bootstrap_controller import BootstrapController

        return BootstrapController(self.project_root).prepare_context(
            directive_id, provision_only=provision_only
        )


# --------------------------------------------------------------------------- #
# Replay admission helpers (pure / file-local — unit-testable in isolation)
# --------------------------------------------------------------------------- #
def resolve_strategy_id(strategy_py: Path, fallback: str) -> str:
    """The strategy's own identity = the `name = "..."` class attribute in strategy.py
    (what `strategies/<id>/` keys on). Falls back to `fallback` (the bundle dir name)."""
    try:
        text = Path(strategy_py).read_text(encoding="utf-8")
    except OSError:
        return fallback
    m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else fallback


def materialize_replay_directive(dest_dir, directive_id: str, strategy_id: str, experiment,
                                 *, reason: str = "") -> Path:
    """Write the experiment-config as a minimal directive YAML the execution stages read
    (symbols + test block: name/strategy/broker/timeframe/window). This is NOT a re-authored
    signature directive — `strategy.py` is the compiled authority, already provisioned; the
    execution path only parses this for symbols/dates/broker. Returns the written path."""
    import yaml

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "symbols": list(experiment.symbols),
        "test": {
            "name": directive_id,
            "strategy": strategy_id,
            "broker": experiment.broker,
            "timeframe": experiment.timeframe,
            "start_date": experiment.start_date,
            "end_date": experiment.end_date,
            "admission_kind": "REPLAY",
            "replay_reason": reason or f"replay of {strategy_id}",
        },
    }
    path = dest_dir / f"{directive_id}.txt"
    path.write_text(yaml.safe_dump(doc, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return path


class ReplayAdmission:
    """Second admission path: ExperimentBundle -> pre-Stage-1 PipelineContext.

    `prepare_context` verifies the bundle (Admission Contract), then materializes the same
    pre-Stage-1 state a directive run reaches — minus canonicalize/provision-from-directive —
    so the unchanged `StageRunner` executes only Stages 1-4 (+ reports / FSP / ledger)."""

    def __init__(self, project_root: Path = REPO_ROOT):
        self.project_root = Path(project_root)

    def prepare_context(self, source, *, cli: Optional[dict] = None, reason: str = ""):
        from config.state_paths import REPO_STRATEGIES_DIR
        from tools.orchestration.run_planner import plan_runs_for_directive
        from tools.pipeline_utils import (
            DirectiveStateManager,
            PipelineContext,
            PipelineStateManager,
        )
        from tools.run_indicator_snapshot import require_indicator_snapshot

        bundle = source if isinstance(source, ExperimentBundle) else load_bundle(source)

        # 1. Admission Contract (strategy.py valid + experiment resolvable + indicators verified).
        result = verify_bundle(bundle, cli=cli, repo_root=self.project_root)
        if not result.ok:
            raise ReplayAdmissionError(
                "bundle failed the Admission Contract:\n  " + "\n  ".join(result.errors)
            )
        experiment = result.experiment
        strategy_id = resolve_strategy_id(bundle.strategy_py, fallback=bundle.root.name)
        directive_id = strategy_id  # replay reuses the strategy's identity as the directive id

        # 2. Provision strategy.py (the compiled authority) into the repo strategies dir Stage-1
        #    loads from, then snapshot its indicators there (chip task_0abbf64c, refresh).
        strat_dir = Path(REPO_STRATEGIES_DIR) / strategy_id
        strat_dir.mkdir(parents=True, exist_ok=True)
        dest_strategy = strat_dir / "strategy.py"
        dest_strategy.write_text(bundle.strategy_py.read_text(encoding="utf-8"), encoding="utf-8")
        require_indicator_snapshot(strat_dir, dest_strategy, self.project_root, write_once=False)

        # 3. Materialize the execution directive where run_stage1 reads it (active_backup).
        active_backup = self.project_root / "backtest_directives" / "active_backup"
        directive_path = materialize_replay_directive(
            active_backup, directive_id, strategy_id, experiment, reason=reason
        )

        # 4. Plan run_ids + registry (reuse the directive-path machinery, no canonicalize).
        dsm = DirectiveStateManager(directive_id)
        dsm.initialize()
        planned_runs, registry_path = plan_runs_for_directive(
            directive_id=directive_id,
            directive_path=directive_path,
            strategy_id=strategy_id,
            symbols=list(experiment.symbols),
            project_root=self.project_root,
        )
        run_ids = [r["run_id"] for r in planned_runs]
        symbols = [r["symbol"] for r in planned_runs]

        # 5. Create per-run state at the pre-Stage-1 level (what PREFLIGHT would have set).
        for rid in run_ids:
            sm = PipelineStateManager(rid, directive_id)
            sm.initialize()
            sm.transition_to("PREFLIGHT_COMPLETE")
            sm.transition_to(_PRE_STAGE1_STATE)

        # 6. Build the context; pre-mark PREFLIGHT complete so StageRunner runs ONLY Stages 1-4.
        ctx = PipelineContext(
            directive_id=directive_id,
            directive_path=directive_path,
            project_root=self.project_root,
            python_exe=sys.executable,
        )
        ctx.directive_config = {"symbols": symbols, "strategy": strategy_id,
                                "broker": experiment.broker, "timeframe": experiment.timeframe,
                                "start_date": experiment.start_date, "end_date": experiment.end_date}
        ctx.planned_runs = planned_runs
        ctx.run_ids = run_ids
        ctx.symbols = symbols
        ctx.registry_path = registry_path
        ctx.directive_state_manager = dsm
        ctx.current_state = dsm.get_state()
        ctx.completed_stages = {_ADMISSION_STAGE_ID}
        return ctx


def select_admission_provider(source, project_root: Path = REPO_ROOT) -> AdmissionProvider:
    """Pick the provider for `source`: an ExperimentBundle / bundle-dir → ReplayAdmission;
    a directive id (str that is not a bundle dir) → DirectiveAdmission."""
    from replay_admission.bundle import is_bundle

    if isinstance(source, ExperimentBundle):
        return ReplayAdmission(project_root)
    p = Path(source)
    if p.is_dir() and is_bundle(p):
        return ReplayAdmission(project_root)
    return DirectiveAdmission(project_root)
