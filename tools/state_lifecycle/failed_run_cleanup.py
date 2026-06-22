"""Auto-cleanup of terminally-FAILED, zero-trade-artifact runs (Layer 1).

A run that crashes BEFORE Stage-1 completes produces no trade artifact, no
manifest, and no ledger row -- zero decision value (Invariant #3). Left on disk
it (a) gets counted as the directive's "first execution", tripping
EXPERIMENT_DISCIPLINE on a legitimate same-day bug-fix rerun, and (b) leaves an
orphan strategies/<id>/ dir the startup guardrail (detect_strategy_drift) blocks
on. We delete such runs at the failure handler, at the source.

Defense-in-depth: system_registry._get_directive_first_execution_timestamp
(Layer 2) independently ignores FAILED/ABORTED entries, covering any crash a hard
kill stopped us from cleaning here.

SAFETY PREDICATE -- is_zero_artifact_terminal_run(run_id), the single shared
classifier (Layer-1 cleanup, Layer-2 first-exec filter, and the future Idea Gate
all consume it, so the definition cannot drift). True IFF BOTH hold, else the run
is left untouched:
  1. runs/<run_id>/run_state.json exists and current_state in {FAILED, ABORTED}
  2. the run NEVER reached STAGE_1_COMPLETE (no history 'to' >= STAGE_1_COMPLETE)
     => it produced no trade artifact and no ledger row

Completed/successful runs (Invariant #4 immutability) and ANY run that reached
Stage-1 (trades worth auditing) are never deleted. Every deletion is audit-logged
to registry/auto_deleted_runs.jsonl -- nothing is dropped silently.

This is an AUTOMATED cleanup distinct from the operator-driven
repair_integrity.py --action drop path (Invariant #2): it only ever removes
zero-value crash debris, never a run that reached a ledger-bearing state.

SUCCESS-PATH COUNTERPART -- prune_completed_base_stubs() (startup self-heal).
A single-asset directive's real artifacts land in its variant dir
strategies/<id>__E###/, so the base dir strategies/<id>/ is left holding only
engine_resolution.json (a write-only audit breadcrumb -- no reader in the repo)
even on full success. detect_strategy_drift then flags that bare base dir on the
NEXT run and blocks the pipeline. prune_completed_base_stubs removes such stubs
at startup, BEFORE the drift guard, so the guard stays strict yet never trips on
a benign post-completion leftover. Same orphan-delete primitive + audit log;
stricter signature (engine_resolution.json-ONLY).
"""
import json
import shutil
from datetime import datetime, timezone

from config.state_paths import RUNS_DIR, REGISTRY_DIR, STRATEGIES_DIR
from config.status_enums import (
    RUN_FAILED,
    RUN_ABORTED,
    RUN_STAGE_1_COMPLETE,
    RUN_STAGE_2_COMPLETE,
    RUN_STAGE_3_COMPLETE,
    RUN_STAGE_3A_COMPLETE,
    RUN_COMPLETE,
)

# Terminal-FAILURE states (COMPLETE is terminal-success, excluded -- it always
# reached Stage-1 anyway).
_TERMINAL_FAILURE_STATES = frozenset({RUN_FAILED, RUN_ABORTED})

# Any of these in a run's history 'to' field => Stage-1 completed => a trade
# artifact (and eventually a ledger row) exist => the run has audit value and is
# NEVER deleted by this module.
_POST_STAGE1_STATES = frozenset({
    RUN_STAGE_1_COMPLETE,
    RUN_STAGE_2_COMPLETE,
    RUN_STAGE_3_COMPLETE,
    RUN_STAGE_3A_COMPLETE,
    RUN_COMPLETE,
})

_AUDIT_LOG = REGISTRY_DIR / "auto_deleted_runs.jsonl"


def _reached_stage1(run_state: dict) -> bool:
    """True if the run ever reached STAGE_1_COMPLETE or beyond (=> has a trade artifact)."""
    if run_state.get("current_state") in _POST_STAGE1_STATES:
        return True
    for h in run_state.get("history", []) or []:
        if h.get("to") in _POST_STAGE1_STATES:
            return True
    return False


def is_zero_artifact_terminal_run(run_id) -> bool:
    """THE shared predicate: True iff run_id is a terminal-FAILURE run (FAILED or
    ABORTED) that never reached Stage-1 -- i.e. it produced no trade artifact and no
    ledger row. Single source of truth consumed by Layer-1 cleanup, Layer-2
    first-execution filtering, and (future) the Idea Gate, so the classification can
    never drift across call sites. Authority is the run's FSM (run_state.json).

    Conservative by construction: a missing/unreadable state file, a non-terminal
    (still-active) state, COMPLETE, or ANY run that reached Stage-1 all return False
    -- nothing with value, and nothing still in flight, is ever classified deletable."""
    if not run_id or not str(run_id).strip():
        return False
    rs_file = RUNS_DIR / str(run_id) / "run_state.json"
    if not rs_file.exists():
        return False
    try:
        rs = json.loads(rs_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    if rs.get("current_state") not in _TERMINAL_FAILURE_STATES:
        return False
    return not _reached_stage1(rs)


def _delete_orphan_strategy_dir(directive_id) -> bool:
    """Delete strategies/<directive_id>/ ONLY if it matches the orphan signature used
    by run_pipeline.detect_strategy_drift (no portfolio_evaluation, no code, no
    deployable). Never deletes a populated strategy dir. Returns True if removed."""
    if not directive_id:
        return False
    d = STRATEGIES_DIR / directive_id
    if not d.is_dir() or d.name.startswith(("_", ".")):
        return False
    has_portfolio = (d / "portfolio_evaluation" / "portfolio_metadata.json").exists()
    has_code = any(d.glob("*.py"))
    has_deployable = (d / "deployable").exists()
    if has_portfolio or has_code or has_deployable:
        return False  # populated -- not an orphan, never touch
    shutil.rmtree(d, ignore_errors=True)
    return True


def _audit(record: dict) -> None:
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[CLEANUP] WARN: could not write auto-delete audit record: {e}")


def delete_failed_run_if_safe(run_id: str, directive_id=None) -> bool:
    """Layer-1 auto-delete. If run_id is a terminally-FAILED zero-artifact run,
    remove its registry entry + run dir + orphan strategy dir, audit-logged first.
    Safe no-op (returns False) for anything with value. Never raises -- best-effort
    cleanup that must not mask the original failure."""
    try:
        if not is_zero_artifact_terminal_run(run_id):
            return False
        reason = "FAILED/ABORTED terminal run, never reached Stage-1 (zero-artifact crash debris)"

        rs_file = RUNS_DIR / run_id / "run_state.json"
        if directive_id is None:
            try:
                directive_id = json.loads(rs_file.read_text(encoding="utf-8")).get("directive_id")
            except Exception:
                directive_id = None

        # 1. Audit FIRST, so the record survives even if a later step is interrupted.
        _audit({
            "run_id": run_id,
            "directive_id": directive_id,
            "reason": reason,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        })

        # 2. Registry entry (system_registry chokepoint helper: locked + atomic).
        registry_removed = False
        try:
            from tools.system_registry import delete_run
            registry_removed = delete_run(run_id)
        except Exception as e:
            print(f"[CLEANUP] WARN: registry delete failed for {run_id}: {e}")

        # 3. Run dir.
        try:
            shutil.rmtree(RUNS_DIR / run_id, ignore_errors=True)
        except Exception as e:
            print(f"[CLEANUP] WARN: run-dir delete failed for {run_id}: {e}")

        # 4. Orphan strategy dir (two-birds: pre-empts the startup drift guardrail).
        orphan_removed = _delete_orphan_strategy_dir(directive_id)

        print(
            f"[CLEANUP] Auto-deleted failed zero-artifact run {run_id} "
            f"(registry={registry_removed}, orphan_dir={orphan_removed}) -- {reason}"
        )
        return True
    except Exception as e:
        print(f"[CLEANUP] WARN: delete_failed_run_if_safe({run_id}) errored: {e}")
        return False


def prune_completed_base_stubs() -> int:
    """Startup self-heal: prune COMPLETED single-asset base-dir stubs.

    Success-path counterpart to delete_failed_run_if_safe's orphan sweep. A
    single-asset directive's real artifacts (portfolio_evaluation/, *.py,
    deployable/) land in its variant dir strategies/<id>__E###/, so the base dir
    strategies/<id>/ is left holding only engine_resolution.json -- a write-only
    audit breadcrumb with no reader anywhere in the repo. detect_strategy_drift
    then flags that bare base dir as an "Untracked directory" on the NEXT run and
    raises PipelineAdmissionPause (FAILURE_PLAYBOOK: detect_strategy_drift
    DRIFT_ORPHAN).

    Called at startup, immediately BEFORE detect_strategy_drift, this removes every
    such bare stub so the guard stays strict yet never blocks on a benign
    post-completion leftover. Startup is the safe moment: no preflight is
    concurrently writing a fresh stub for an in-flight directive, and it covers
    every path that leaves one (single run, --all success, partially-failed batch,
    hard kill).

    STRICT signature -- a dir is pruned ONLY if its ENTIRE contents are exactly
    {engine_resolution.json}. A multi-symbol base (carries strategy.py), any dir
    holding a real artifact (deployable/, portfolio_evaluation/), and any dir with
    an unexpected extra file are all left untouched. The actual delete is delegated
    to _delete_orphan_strategy_dir, which re-checks the orphan signature (defense in
    depth). Every prune is audit-logged to auto_deleted_runs.jsonl FIRST -- nothing
    is dropped silently. Never raises -- best-effort startup hygiene that must not
    block a run. Returns the count of stubs pruned.
    """
    pruned = 0
    try:
        if not STRATEGIES_DIR.is_dir():
            return 0
        for d in STRATEGIES_DIR.iterdir():
            try:
                if not d.is_dir() or d.name.startswith(("_", ".")):
                    continue
                if {p.name for p in d.iterdir()} != {"engine_resolution.json"}:
                    continue
                # Audit FIRST so the record survives an interrupted delete.
                _audit({
                    "directive_id": d.name,
                    "reason": ("COMPLETED base stub -- engine_resolution.json-only; "
                               "artifacts in <id>__E### variant dir"),
                    "deleted_at": datetime.now(timezone.utc).isoformat(),
                })
                if _delete_orphan_strategy_dir(d.name):
                    pruned += 1
                    print(f"[CLEANUP] Pruned completed base stub strategies/{d.name}/ "
                          f"(engine_resolution.json-only)")
            except Exception as e:
                print(f"[CLEANUP] WARN: base-stub prune skipped for {d.name}: {e}")
    except Exception as e:
        print(f"[CLEANUP] WARN: prune_completed_base_stubs() errored: {e}")
    return pruned
