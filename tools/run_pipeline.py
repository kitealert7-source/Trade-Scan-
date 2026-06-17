
"""
run_pipeline.py -- Master Execution Pipeline Orchestrator (v3.2 - State Gated)

Usage:
  python tools/run_pipeline.py <DIRECTIVE_ID>
  python tools/run_pipeline.py --all

Purpose:
  Orchestrates the deterministic multi-asset execution flow:

  0. Preflight (Safety & Governance Checks)
  1. Directive Parsing (Concurrency + Symbol Detection)
  2. Stage-1: Generation (RESEARCH Data Only)
  3. Stage-1.5: Portfolio Risk Constraints (Conditional)
  4. Stage-2: Compilation
  5. Stage-3: Aggregation
  6. Stage-4: Portfolio Evaluation

Execution Model -- Mandatory Compliance:

  - All execution gated by run_state.json (Audit Phase 7)
  - All Stage-1 executions MUST use RESEARCH market data.
  - CLEAN or derived datasets are non-authoritative and prohibited.
  - Directive must contain executable conditions.
  - STRATEGY_PLUGIN_CONTRACT.md must be satisfied.
  - SOP_INDICATOR.md must be enforced (repository-only indicators).
  - No inline indicator logic permitted.

Authority:
  governance/SOP/SOP_TESTING.md
  governance/SOP/STRATEGY_PLUGIN_CONTRACT.md
  governance/SOP/SOP_INDICATOR.md

"""


import sys
import shutil
import os
import json
import hashlib
import re
import subprocess
from pathlib import Path

# --- ENCODING BOOTSTRAP ---
# Ensures UTF-8 I/O across the process and all spawned subprocesses.
# Must run before any subprocess calls or print statements.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


# Config
PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_EXE = sys.executable
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives"
ACTIVE_DIR = DIRECTIVES_DIR / "INBOX"
ACTIVE_BACKUP_DIR = DIRECTIVES_DIR / "active_backup"
COMPLETED_DIR = DIRECTIVES_DIR / "completed"

def admit_directive(directive_id: str) -> None:
    """Atomic admission of directive from INBOX/ to active_backup/ with marker."""
    d_path = find_directive_path(ACTIVE_DIR, directive_id)
    if not d_path:
        # Check if already admitted (authoritative)
        if find_directive_path(ACTIVE_BACKUP_DIR, directive_id):
            return
        raise PipelineExecutionError(f"Directive {directive_id} not found in {ACTIVE_DIR}")

    # Rule-binding gate (Task A, Phase A1). Runs BEFORE any state mutation:
    # a reject leaves the directive in INBOX/ for the operator to fix.
    from tools.rule_binding_gate import check_directive_rule_binding, RuleBindingGateError
    try:
        check_directive_rule_binding(d_path)
    except RuleBindingGateError as exc:
        raise PipelineExecutionError(str(exc)) from exc

    # Window-validity gate (Task B). Also pre-mutation. No-op unless the
    # directive declares basket.cointegration_join.lookback_days; rejects a
    # test window not fully inside a continuous cointegrated regime span.
    from tools.window_validity_gate import check_window_validity, WindowValidityGateError
    try:
        check_window_validity(d_path)
    except WindowValidityGateError as exc:
        raise PipelineExecutionError(str(exc)) from exc

    # Methodology-citation gate (Task D). Also pre-mutation. No-op unless the
    # directive declares methodology_citations; rejects citations of slugs
    # absent from the repo-local methodology registry.
    from tools.methodology_citation_gate import check_methodology_citations, MethodologyCitationGateError
    try:
        check_methodology_citations(d_path)
    except MethodologyCitationGateError as exc:
        raise PipelineExecutionError(str(exc)) from exc

    ACTIVE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target_path = ACTIVE_BACKUP_DIR / d_path.name

    # Atomic Move
    os.replace(str(d_path), str(target_path))
    
    # Create marker
    marker_path = target_path.with_suffix(target_path.suffix + ".admitted")
    marker_path.touch()
    print(f"[ORCHESTRATOR] Admitted: {d_path.name} -> {ACTIVE_BACKUP_DIR}")

def archive_completed_directive(directive_id: str) -> None:
    """Move directive and marker from active_backup/ to completed/."""
    # Source must be active_backup/
    d_path = find_directive_path(ACTIVE_BACKUP_DIR, directive_id)
    if not d_path:
        return

    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
    target_path = COMPLETED_DIR / d_path.name
    
    if target_path.exists():
        os.remove(target_path)
    
    os.replace(str(d_path), str(target_path))
    
    # Move marker if exists
    marker_path = d_path.with_suffix(d_path.suffix + ".admitted")
    if marker_path.exists():
        new_marker = target_path.with_suffix(target_path.suffix + ".admitted")
        os.replace(str(marker_path), str(new_marker))
        
    print(f"[ORCHESTRATOR] Archived: {d_path.name} -> {COMPLETED_DIR}")

def reconcile_active_backup() -> None:
    """
    Archive terminal directives and clean orphaned markers in active_backup/.

    Called on startup and at the end of every run so that fail-fast aborts
    never permanently strand directives in active_backup/.

    Terminal states (PORTFOLIO_COMPLETE, FAILED) -> move to completed/.
    Orphaned .admitted markers (no matching .txt) -> delete.
    """
    if not ACTIVE_BACKUP_DIR.exists():
        return

    TERMINAL_STATES = {"PORTFOLIO_COMPLETE", "FAILED"}

    # 1. Archive terminal directives (.txt files)
    for d_path in sorted(ACTIVE_BACKUP_DIR.glob("*.txt")):
        if d_path.name.endswith(".txt.admitted"):
            continue  # skip markers in this pass
        if not d_path.exists():
            continue
        directive_id = d_path.stem
        state = DirectiveStateManager(directive_id).get_state()
        if state in TERMINAL_STATES:
            try:
                archive_completed_directive(directive_id)
                print(f"[RECONCILE] Auto-archived {state} directive: {directive_id}")
            except Exception as e:
                print(f"[RECONCILE][WARN] Failed to archive {directive_id}: {e}")

    # 2. Clean orphaned .admitted markers (no matching .txt)
    for marker in sorted(ACTIVE_BACKUP_DIR.glob("*.txt.admitted")):
        txt_path = marker.with_suffix("")  # strip .admitted -> .txt
        if not txt_path.exists():
            marker.unlink()
            print(f"[RECONCILE] Removed orphaned marker: {marker.name}")


def recover_partially_admitted_directives() -> None:
    """On startup, recreate markers for directives in backup missing them."""
    if not ACTIVE_BACKUP_DIR.exists():
        return
        
    for item in ACTIVE_BACKUP_DIR.glob("*.txt"):
        marker = item.with_suffix(item.suffix + ".admitted")
        if not marker.exists():
            marker.touch()
            print(f"[RECOVERY] Recreated admission marker for: {item.name}")

# Governance Imports

sys.path.insert(0, str(PROJECT_ROOT))
from config.state_paths import initialize_state_directories, RUNS_DIR, STRATEGIES_DIR, QUARANTINE_DIR
from tools.pipeline_utils import (
    PipelineStateManager, 
    DirectiveStateManager,
)
from tools.orchestration.transition_service import (
    transition_directive_state,
    fail_run_best_effort,
    fail_directive_best_effort,
)
from tools.orchestration.pipeline_errors import (
    PipelineAdmissionPause,
    PipelineError,
    PipelineExecutionError,
)
from tools.orchestration.pipeline_stages import (
    run_preflight_semantic_checks,
    run_symbol_execution_stages,
)
from tools.orchestration.pre_execution import (
    find_directive_path,
    prepare_batch_directives_for_execution,
    prepare_single_directive_for_execution,
    enforce_signature_consistency,
)
from tools.orchestration.execution_adapter import run_command
from tools.system_registry import reconcile_registry, _load_registry, _save_registry_atomic
from tools.manifest_verification import verify_run_artifacts
from tools.pipeline_utils import PipelineContext, parse_directive
from tools.orchestration.bootstrap_controller import BootstrapController
from tools.orchestration.runner import StageRunner


def validate_inbox_directive_tokens():
    """
    Token Gate: validate MODEL token in all INBOX directives against
    token_dictionary.yaml before any pipeline work begins.
    Zero state changes on failure — nothing is provisioned, nothing is moved.
    Name format: {id}_{FAMILY}_{SYMBOL}_{TF}_{MODEL}[_{FILTER}]_{SWEEP}_{V#}_{P##}
    MODEL is always the 5th component (index 4).
    """
    import yaml
    token_dict_path = PROJECT_ROOT / "governance" / "namespace" / "token_dictionary.yaml"
    if not token_dict_path.exists():
        return

    try:
        token_data = yaml.safe_load(token_dict_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[TOKEN GATE] Could not read token_dictionary.yaml ({e}) — skipping token check.")
        return

    valid_models  = {t.upper() for t in token_data.get("model", [])}
    alias_keys    = {k.upper() for k in token_data.get("aliases", {}).get("model", {})}
    all_valid     = valid_models | alias_keys

    inbox = PROJECT_ROOT / "backtest_directives" / "INBOX"
    if not inbox.exists():
        return

    errors = []
    for directive_file in sorted(inbox.glob("*.txt")):
        parts = directive_file.stem.split("_")
        if len(parts) < 5:
            continue
        model_token = parts[4].upper()
        if model_token not in all_valid:
            errors.append(
                f"  {directive_file.name}\n"
                f"    MODEL='{model_token}' is not a valid token.\n"
                f"    Valid: {', '.join(sorted(valid_models))}\n"
                f"    Aliases: {', '.join(sorted(alias_keys)) or 'none'}"
            )

    if errors:
        print("[TOKEN GATE] INVALID MODEL TOKEN(S) — pipeline blocked before any state change:")
        for err in errors:
            print(err)
        raise PipelineAdmissionPause(
            "Invalid namespace token(s) in INBOX. Fix directive filename(s) and re-run."
        )

    print(f"[TOKEN GATE] All INBOX directive tokens valid.")


def enforce_run_schema(project_root: Path):
    """Guardrail: Verify every run container v2 structure."""
    runs_dir = RUNS_DIR
    quarantine_dir = QUARANTINE_DIR / "runs"
    
    if not runs_dir.exists():
        return

    invalid_found = []
    for run_folder in runs_dir.iterdir():
        if not run_folder.is_dir():
            continue
            
        # Standard v2 requirements apply only to run containers (24-char hex IDs)
        if len(run_folder.name) != 24:
            continue
            
        # [FIX] Do not delete freshly provisioned runs (no data yet) 
        # or runs currently in progress. 
        # A run is only "Abandoned" if it's been there a while WITHOUT activity.
        # For now, we only enforce manifest/data for runs that are COMPLETED.
        
        required = ["run_state.json"] # Only run_state is strictly required at startup
        missing = [req for req in required if not (run_folder / req).exists()]
        
        if missing:
            print(f"[GUARDRAIL] Corrupt run container: {run_folder.name} (Missing: {', '.join(missing)})")
            # Fallback to quarantine for corrupt runs
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dst = quarantine_dir / run_folder.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(run_folder), str(dst))
            invalid_found.append(run_folder.name)
            continue

        # If it has a run_state, check if it's old and abandoned
        try:
            from tools.pipeline_utils import PipelineStateManager
            mgr = PipelineStateManager(run_folder.name)
            state_data = mgr.get_state_data()
            current_state = state_data.get("current_state", "IDLE")
            
            # If it's COMPLETE but missing manifest/data, then it's a schema violation
            if current_state == "COMPLETE":
                manifest_exists = (run_folder / "manifest.json").exists()
                data_exists = (run_folder / "data").exists()
                if not manifest_exists or not data_exists:
                    print(f"[GUARDRAIL] Incomplete COMPLETED run: {run_folder.name} (Missing: manifest or data)")
                    # Quarantine...
                    quarantine_dir.mkdir(parents=True, exist_ok=True)
                    dst = quarantine_dir / run_folder.name
                    if dst.exists(): shutil.rmtree(dst)
                    shutil.move(str(run_folder), str(dst))
                    invalid_found.append(run_folder.name)
        except Exception:
            pass # Skip if state cannot be read

    if invalid_found:
        print(f"[FATAL] Schema enforcement failed for {len(invalid_found)} runs. Quarantined to {quarantine_dir}.")
        raise PipelineAdmissionPause(f"Run schema violation. Check {quarantine_dir}.")


def gate_registry_consistency():
    """Guardrail: Detect registry/filesystem drift before execution."""
    print("[GUARDRAIL] Verifying Registry-Filesystem alignment...")
    try:
        results = reconcile_registry()
        
        drift_detected = False
        if results["orphaned_on_disk"]:
            # Auto-recovered by reconciler — not actionable drift, just a warning.
            print(f"[DRIFT] DISK_NOT_IN_REGISTRY (auto-recovered): {results['orphaned_on_disk']}")
        if results["missing_from_disk"]:
            print(f"[DRIFT] REGISTRY_RUN_MISSING_ON_DISK: {results['missing_from_disk']}")
            print("[AUTO-HEAL] Automatically purging orphaned registry keys...")
            reg = _load_registry()
            for run_id in results["missing_from_disk"]:
                if run_id in reg:
                    del reg[run_id]
            _save_registry_atomic(reg)
            
            # Re-run registry reconciliation
            results = reconcile_registry()
            # If still missing_from_disk, it will still set drift_detected = True below if not cleared
            if results["missing_from_disk"]:
                drift_detected = True
            
        if drift_detected:
            raise PipelineAdmissionPause("Registry drift detected. Manual reconciliation required.")
            
    except PipelineAdmissionPause:
        raise
    except Exception as e:
        print(f"[FATAL] Registry Consistency Gate: {e}")
        raise PipelineAdmissionPause(f"Registry drift detected: {e}")


def verify_manifest_integrity(project_root: Path):
    """Guardrail: Verify that manifest hashes match physical files at startup."""
    print("[GUARDRAIL] Verifying Manifest Integrity (Startup Hash Check)...")
    runs_dir = RUNS_DIR
    if not runs_dir.exists():
        return

    corrupted = []
    for run_folder in runs_dir.iterdir():
        if not run_folder.is_dir(): continue
        
        manifest_path = run_folder / "manifest.json"
        if not manifest_path.exists(): continue
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            # Per-artifact verification (basket_code vs data/ PATH + HASH
            # contract) lives in the single source of truth
            # tools.manifest_verification.verify_run_artifacts, shared with
            # system_preflight._check_runs so the two checkers can never
            # desync on the contract again (the 2026-06-02 false-RED class).
            artifacts = manifest.get("artifacts", {})
            for problem in verify_run_artifacts(run_folder, artifacts):
                corrupted.append(f"{run_folder.name}: {problem}")
        except Exception as e:
            corrupted.append(f"{run_folder.name}: Failed to read manifest ({e})")

    if corrupted:
        print("[FATAL] Manifest Integrity Violations Detected:")
        for err in corrupted:
            print(f"  !! {err}")
        raise PipelineAdmissionPause("Manifest integrity violation. Pipeline halted to prevent corrupt data propagation.")


def verify_indicator_registry_sync(project_root: Path):
    """Guardrail: indicators/INDICATOR_REGISTRY.yaml must match indicators/ tree.

    Catches drift that the pre-commit hook missed (--no-verify bypass,
    manual YAML edits introducing phantom registry entries, indicator
    deletions without corresponding registry cleanup). Stage-0.5 also
    rejects drifted directives at admission, but per-directive — this
    pipeline-start guard is loud once instead of per-run.

    Single source of truth: invokes tools/indicator_registry_sync.py
    --check via subprocess so the check logic lives in one place.

    Per outputs/GOVERNANCE_DRIFT_PREVENTION_PLAN.md Patch 3.
    """
    print("[GUARDRAIL] Verifying Indicator Registry Sync...")
    sync_script = project_root / "tools" / "indicator_registry_sync.py"
    if not sync_script.exists():
        # Defensive: the sync helper was added 2026-05-12; an older
        # checkout that pre-dates it should not be blocked from running.
        # The pre-commit hook covers the going-forward case.
        print("[GUARDRAIL] Sync helper not present; skipping registry check.")
        return

    result = subprocess.run(
        [sys.executable, str(sync_script), "--check"],
        cwd=str(project_root),
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        print("[FATAL] Indicator registry drift detected:")
        for line in (result.stdout or "").splitlines():
            print(f"  {line}")
        raise PipelineAdmissionPause(
            "Indicator registry drift. Pipeline halted to prevent "
            "Stage-0.5 ImportError-class bugs. Run `python "
            "tools/indicator_registry_sync.py --check` for detail, then "
            "`--add-stubs` (or restore missing .py files) and commit."
        )
    print("[GUARDRAIL] Indicator Registry: in sync.")


def _compute_manifest_file_hash(filepath: Path) -> str:
    """Compute sha256 of a file in the same canonical (LF-normalized) form
    as tools/generate_guard_manifest.py via verify_engine_integrity.canonical_sha256.
    Single source of truth for both manifest generation and runtime integrity
    check; eliminates Windows CRLF false-failures (autocrlf=true on Windows
    checks out files with CRLF, but the manifest stores LF-normalized hashes).
    Module-level so regression tests can compare deterministically."""
    from tools.verify_engine_integrity import canonical_sha256
    return canonical_sha256(filepath).upper()


def verify_tools_timestamp_guard(project_root: Path):
    """Guardrail: ensure protected tools match their recorded sha256 hashes
    in `tools/tools_manifest.json`. (Function name retained for backward
    compatibility, but content gate is now hash-based, not mtime-based — see
    INFRA-AUDIT C2 closure 2026-05-03.)

    Failure modes:
      * file present in manifest but missing on disk -> WARN (legacy behavior)
      * file present in both, hash mismatch          -> raise PipelineExecutionError
      * manifest unreadable                          -> WARN (legacy behavior)
    """
    manifest_path = project_root / "tools" / "tools_manifest.json"
    if not manifest_path.exists():
        return

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        file_hashes = manifest.get("file_hashes", {})
        for filename, recorded_hash in file_hashes.items():
            # Resolve relative to PROJECT_ROOT as per hardening scope
            filepath = project_root / filename
            # Fallback: maintain compatibility with current manifest (contained in 'tools/')
            if not filepath.exists():
                filepath = project_root / "tools" / filename

            if not filepath.exists():
                continue

            recorded = (recorded_hash or "").upper()
            actual = _compute_manifest_file_hash(filepath)
            if recorded and recorded != actual:
                raise PipelineExecutionError(
                    f"Tool content hash mismatch for {filename}: "
                    f"manifest=[{recorded[:16]}...] actual=[{actual[:16]}...]. "
                    "Run python tools/generate_guard_manifest.py",
                    fail_directive=False,
                    fail_runs=False
                )
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[WARN] Failed to parse tools manifest for timestamp check: {e}")
    except PipelineExecutionError:
        raise
    except Exception as e:
        print(f"[WARN] Tools timestamp guard encountered an error: {e}")


def verify_directive_uniqueness_guard(directive_id: str, refresh: bool = False):
    """Guardrail: Prevent reuse of already executed directive names.

    `refresh=True` (set only by the cointegration refresh entrypoint
    `tools/refresh_cointegration.py`, via the `--refresh` CLI flag) DELIBERATELY
    re-runs an existing directive in place: the uniqueness check is skipped so a
    declared refresh produces a new run_id for the SAME directive identity (no
    `__E###` variant). The only caller that passes `refresh=True` first validates
    the target is a cointegration directive, so this cannot relax uniqueness for
    a genuine new object.
    """
    if refresh:
        print(f"[REFRESH] re-running existing directive in place: {directive_id}")
        return
    registry = _load_registry()
    if not registry:
        return

    for entry in registry.values():
        if entry.get("directive_id") == directive_id:
            raise PipelineExecutionError(
                f"Directive already executed: {directive_id}. "
                "Create a new directive version before running the pipeline.",
                directive_id=directive_id,
                fail_directive=False,
                fail_runs=False
            )


_MULTISYM_NAME_RE = re.compile(r'^(\s*name\s*=\s*")[^"]*(")')


def _normalize_strategy_lines(lines: list) -> list:
    """Replace the name field value with a sentinel for content comparison."""
    return [_MULTISYM_NAME_RE.sub(r'\g<1>__NAME__\2', line) for line in lines]


def _multisymbol_drift_check(strat_dir: Path) -> None:
    """
    Detect logic divergence between base strategy.py and per-symbol copies.

    Detection rule:
      - A directory <BASE> exists with a strategy.py whose `name` field equals <BASE>
      - One or more sibling directories <BASE>_<SYM> exist
      → These are per-symbol deployment copies. They must be identical to the base
        except for the name field.

    Raises PipelineAdmissionPause if any divergence is found.
    Fix: python tools/sync_multisymbol_strategy.py <BASE> <SYM1> [<SYM2> ...]
    """
    dirs = {d.name: d for d in strat_dir.iterdir() if d.is_dir() and not d.name.startswith("_")}

    # Build map: base_id -> [symbol, ...] for all confirmed base+per-symbol sets
    bases: dict = {}
    for name, path in dirs.items():
        strat_py = path / "strategy.py"
        if not strat_py.exists():
            continue
        # Confirm this dir is genuinely a base: its name field must equal the folder name
        content = strat_py.read_text(encoding="utf-8")
        m = _MULTISYM_NAME_RE.search(content)
        if not m:
            continue
        declared_name = re.search(r'name\s*=\s*"([^"]+)"', content)
        if not declared_name or declared_name.group(1) != name:
            continue
        # Find all per-symbol siblings
        siblings = [
            sib_name[len(name) + 1:]
            for sib_name, sib_path in dirs.items()
            if sib_name.startswith(name + "_") and (sib_path / "strategy.py").exists()
        ]
        if siblings:
            bases[name] = siblings

    if not bases:
        return

    drift_found = []
    for base_id, symbols in bases.items():
        base_lines = (strat_dir / base_id / "strategy.py").read_text(encoding="utf-8").splitlines(keepends=True)
        base_norm = _normalize_strategy_lines(base_lines)
        for sym in symbols:
            target_path = strat_dir / f"{base_id}_{sym}" / "strategy.py"
            if not target_path.exists():
                drift_found.append(
                    f"MULTI_SYMBOL_DRIFT: {base_id}_{sym} missing strategy.py. "
                    f"Run: python tools/sync_multisymbol_strategy.py {base_id} {' '.join(symbols)}"
                )
                continue
            target_lines = target_path.read_text(encoding="utf-8").splitlines(keepends=True)
            if _normalize_strategy_lines(target_lines) != base_norm:
                drift_found.append(
                    f"MULTI_SYMBOL_DRIFT: {base_id}_{sym} differs from base {base_id}. "
                    f"Run: python tools/sync_multisymbol_strategy.py {base_id} {' '.join(symbols)}"
                )

    if drift_found:
        print("[GUARDRAIL] Multi-Symbol Strategy Drift Detected:")
        for msg in drift_found:
            print(f"  !! {msg}")
        raise PipelineAdmissionPause(
            "Multi-symbol strategy drift detected. Sync per-symbol copies before execution."
        )


def detect_strategy_drift(project_root: Path):
    """Guardrail: Detect untracked modification in strategies/."""
    strat_dir = STRATEGIES_DIR
    if not strat_dir.exists():
        return

    drift = []
    for item in strat_dir.iterdir():
        if item.is_file():
            # No files allowed in root of strategies/ except the portfolio sheet
            # and Office temp lock files (~$...) which are transient and harmless.
            if item.name != "Master_Portfolio_Sheet.xlsx" and not item.name.startswith("~$"):
                drift.append(f"Unexpected file: {item.name}")
        elif item.is_dir():
            if item.name.startswith(("_", ".")):
                continue
            has_portfolio = (item / "portfolio_evaluation" / "portfolio_metadata.json").exists()
            has_code = any(item.glob("*.py"))
            has_deployable = (item / "deployable").exists()
            if not has_portfolio and not has_code and not has_deployable:
                drift.append(f"Untracked directory: {item.name}")

    if drift:
        print("[GUARDRAIL] Strategy Directory Drift Detected:")
        for d in drift:
            print(f"  !! {d}")
        raise PipelineAdmissionPause("Strategy directory drift detected. Manual reconciliation required.")

    # --- Multi-symbol logic drift check ---
    # For every base+per-symbol folder set, verify all per-symbol copies match the base
    # (ignoring only the name line). Hard fail on any divergence.
    _multisymbol_drift_check(strat_dir)


def map_pipeline_error(err):
    """Single top-level mapper for pause/failure outcomes."""
    try:
        from tools.system_logging.pipeline_failure_logger import log_pipeline_failure as _log_failure
    except Exception:
        _log_failure = None

    if isinstance(err, PipelineAdmissionPause):
        print(f"[ORCHESTRATOR] Execution Paused: {err}")
        return err.exit_code

    if isinstance(err, PipelineExecutionError):
        print(f"[ORCHESTRATOR] Execution Failed: {err}")
        if _log_failure:
            _log_failure(
                directive_id=getattr(err, "directive_id", None) or "UNKNOWN",
                run_id=(getattr(err, "run_ids", None) or [None])[0],
                stage="ORCHESTRATOR",
                error_type="PIPELINE_ERROR",
                message=str(err),
            )
        if err.fail_directive and err.directive_id:
            fail_directive_best_effort(err.directive_id)

        if err.fail_runs and err.run_ids:
            print("[ORCHESTRATOR] Performing fail-safe state cleanup...")
            for rid in err.run_ids:
                try:
                    if fail_run_best_effort(rid):
                        print(f"[CLEANUP] Marking run {rid} as FAILED")
                except Exception as cleanup_err:
                    print(f"[WARN] Failed to cleanup run {rid}: {cleanup_err}")
        return err.exit_code

    print(f"[ORCHESTRATOR] Unhandled Error: {err}")
    return 1

_PARTIAL_CAPABLE_ENGINES = {"1.5.7", "1.5.8"}

def _announce_run_engine(directive_id: str) -> None:
    """Print the resolved engine version + an early warning when a strategy
    defines check_partial_exit but the engine pin is not partial-capable.

    Stage1 has a hard guard (tools/run_stage1.py) that fail-fasts if partial
    legs make it out of the engine under a non-partial emitter. This helper
    is the softer upstream counterpart: it fires before any stage runs, so
    operators see the mismatch immediately rather than deep into Stage1.

    Partial-capable engines: v1.5.7 (EXPERIMENTAL) and v1.5.8 (FROZEN). Any
    future engine that ships `check_partial_exit` support should be added
    to _PARTIAL_CAPABLE_ENGINES.
    """
    import os
    from tools.pipeline_utils import get_engine_version
    try:
        engine_ver = get_engine_version()
    except Exception as exc:
        print(f"[ENGINE] Version lookup failed: {exc}")
        return

    override = os.environ.get("ENGINE_VERSION_OVERRIDE", "").strip()
    label = f"v{engine_ver}" + (" (EXPERIMENTAL)" if engine_ver == "1.5.7" else "")
    suffix = f"  [override={override}]" if override else ""
    print(f"[ENGINE] Running {directive_id} on engine {label}{suffix}")

    # Authority copy lives in PROJECT_ROOT/strategies (not STRATEGIES_DIR which
    # resolves to TradeScan_State and holds only deployable/ref artifacts).
    strat_py = PROJECT_ROOT / "strategies" / directive_id / "strategy.py"
    if not strat_py.exists():
        return
    try:
        source = strat_py.read_text(encoding="utf-8")
    except Exception:
        return
    if "def check_partial_exit" in source and engine_ver not in _PARTIAL_CAPABLE_ENGINES:
        print(
            f"[WARN] Strategy {directive_id} defines check_partial_exit but "
            f"engine v{engine_ver} is not in the partial-capable set "
            f"({sorted(_PARTIAL_CAPABLE_ENGINES)}). Partial legs will be "
            f"blocked by the Stage1 fail-fast guard."
        )


def _find_admitted_directive_path(directive_id: str) -> Path | None:
    """Find the admitted directive .txt file in active_backup/ or completed/.

    Used by the basket dispatch path which needs to parse the directive YAML
    before BootstrapController fires (per-symbol provisioning is wrong for
    baskets).
    """
    candidate = ACTIVE_BACKUP_DIR / f"{directive_id}.txt"
    if candidate.is_file():
        return candidate
    candidate = COMPLETED_DIR / f"{directive_id}.txt"
    if candidate.is_file():
        return candidate
    return None


# ────────────────────────────────────────────────────────────────────────
# Basket dispatch — phase helpers (2026-06-01 decomposition, Backlog 1/4)
#
# `_try_basket_dispatch` was 358 LOC, the largest function in the file.
# Decomposed into six phase helpers + a slim orchestrator. Behavior is
# byte-equivalent: same print order, same try/except boundaries, same
# state-machine transitions, same artifact-write order.
# ────────────────────────────────────────────────────────────────────────


def _basket_early_dispatch_check(directive_id: str, provision_only: bool):
    """Run the four early-return gates and return (path, parsed) for a valid
    basket directive, or None to signal the caller to fall through to the
    per-symbol flow.

    Gates (in order):
      1. provision-only mode never dispatches basket execution
      2. directive file must be locatable in active_backup/ or completed/
      3. directive must parse cleanly (parse problems surface on per-symbol path)
      4. parsed directive must be a basket directive
    """
    if provision_only:
        return None  # provision-only flow never dispatches basket execution

    path = _find_admitted_directive_path(directive_id)
    if path is None:
        return None  # caller will surface the missing-directive error

    from tools.basket_schema import is_basket_directive
    from tools.pipeline_utils import parse_directive

    try:
        parsed = parse_directive(path)
    except Exception:
        return None  # parsing problems surface in the existing flow
    if not is_basket_directive(parsed):
        return None

    return path, parsed


def _basket_run_pipeline(directive_id: str, path, parsed):
    """Print the dispatch banner, load per-leg OHLC + leg strategies via the
    registry-driven dispatch, generate run_id BEFORE the rule executes (so
    the rule can thread it into per-bar ledger rows), and invoke
    run_basket_pipeline. Returns a dict bundling result + threading state
    that the downstream phase helpers consume.

    Phase 5c: real per-leg OHLC + USD_SYNTH compression_5d factor; falls
    back to synthetic-mode (passthrough strategy + closed-gate compression)
    when data loading fails — useful for smoke testing without real
    RESEARCH layer access.
    """
    from tools.basket_pipeline import run_basket_pipeline
    from tools.pipeline_utils import generate_run_id as _generate_run_id
    # Phase 5b.3 (2026-05-20): research/basket_runs.csv writer retired.
    # The legacy import (append_basket_row_to_research_csv) is gone; the
    # function remains in tools/portfolio_evaluator.py as dead code until
    # the next cleanup sweep.

    print(f"[BASKET] Phase 5b dispatch: {directive_id}")
    print(f"[BASKET] Directive: {path}")
    print(f"[BASKET] basket_id={parsed['basket']['basket_id']} "
          f"legs={[l['symbol'] for l in parsed['basket']['legs']]}")

    leg_data, leg_strategies, data_mode = _load_basket_leg_inputs(parsed)
    print(f"[BASKET] Data mode: {data_mode}")
    registry_path = PROJECT_ROOT / "governance" / "recycle_rules" / "registry.yaml"

    # 1.3.0-basket schema: generate run_id BEFORE the rule executes so the rule
    # can thread it into per-bar ledger rows. Path B (Phase 5b.2) reuses this
    # same run_id for the run_registry entry + tradelevel CSV pair.
    _basket_id_for_runid = parsed["basket"]["basket_id"]
    run_id, _content_hash = _generate_run_id(path, symbol=_basket_id_for_runid)

    result = run_basket_pipeline(
        parsed, leg_data, leg_strategies,
        recycle_registry_path=registry_path,
        run_id=run_id,
        directive_id=directive_id,
    )
    return {
        "result": result,
        "leg_data": leg_data,
        "leg_strategies": leg_strategies,  # for the per-run code provenance snapshot
        "directive_path": path,            # guaranteed source directive (mandatory snapshot)
        "data_mode": data_mode,
        "run_id": run_id,
        "content_hash": _content_hash,
    }


def _basket_write_vault_snapshot(directive_id: str, parsed, result):
    """Write the DRY_RUN_VAULT basket snapshot (Phase 6 layout). Folder:
    `DRY_RUN_VAULT/baskets/<directive_id>/<basket_id>/` (write_basket_vault
    adds the inner basket_id directory).

    Returns the vault directory path on success, or None if the write
    failed (logged but non-fatal — Path B / standard artifacts carries on
    without it; future analysis can recover from the run record alone)."""
    from config.path_authority import DRY_RUN_VAULT as _DRY_RUN_VAULT
    from tools.basket_vault import BasketVaultPayload, write_basket_vault

    vault_parent = _DRY_RUN_VAULT / "baskets" / directive_id
    vault_parent.mkdir(parents=True, exist_ok=True)

    payload = BasketVaultPayload(
        basket_id=parsed["basket"]["basket_id"],
        directive=parsed,
        rule_name=result.rule_name,
        rule_version=result.rule_version,
        harvested_total_usd=result.harvested_total_usd,
        legs=parsed["basket"]["legs"],
        leg_trades=dict(result.per_leg_trades),
        recycle_events=list(result.recycle_events),
    )
    try:
        vault_dir = write_basket_vault(vault_parent, payload)
        print(f"[BASKET] Vault written: {vault_dir}")
        return vault_dir
    except Exception as exc:
        print(f"[BASKET] WARN vault write failed: {exc}")
        return None


def _basket_compute_engine_version() -> str:
    """Authoritative engine identity for EVERY basket-run stamp.

    Baskets compute on the hardcoded ``engine_abi.v1_5_9`` ABI (basket_runner.py
    imports it directly; ``engine_abi/`` exposes only v1_5_9). A basket run's
    engine identity is therefore DEFINED by that module's ``ENGINE_VERSION`` and
    is INERT to ``ENGINE_VERSION_OVERRIDE`` (proven byte-identical compute under
    override 1.5.9 vs 1.5.10). Every basket stamp -- manifest/input_provenance,
    run_metadata.json, STRATEGY_CARD.md, the cointegration_sheet row -- MUST
    route through here, NEVER through ``get_engine_version()`` (which honors the
    override/registry and would mislabel a basket as an engine it never ran on).

    Single source so the four stamp sites cannot drift; locked by
    tests/test_engine_identity_convergence.py. Doctrine:
    memory ``engine_identity_is_compute_not_stamp``.

    Imports from ``tools.basket_runner`` (NOT directly from engine_abi) on
    purpose: basket_runner is the ONE module that imports the basket compute
    ABI, so the stamp reads the EXACT symbol the compute path uses. A future
    engine promotion that re-points basket_runner moves this stamp with it --
    there is no second independent ``from engine_abi.v1_5_X`` to forget.
    """
    from tools.basket_runner import ENGINE_VERSION
    return str(ENGINE_VERSION)


def _basket_engine_abi() -> str:
    """The ABI module path of the basket compute, from the same single source
    as ``_basket_compute_engine_version()``. The cointegration_sheet row carries
    BOTH engine_version and engine_abi; both must move together on an engine
    promotion, so both derive from ``tools.basket_runner``."""
    from tools.basket_runner import ENGINE_ABI
    return str(ENGINE_ABI)


def _basket_write_tradelevel_and_report(directive_id: str, parsed, run_ctx):
    """Path B / Phase 5b.2 first half: initialize PipelineStateManager, create
    the backtests/ + runs/ folders, write the dual-location tradelevel CSV,
    and emit the per-window report stack (results_standard/risk/yearwise/
    basket, metrics_glossary, bar_geometry, metadata/run_metadata,
    REPORT_<id>.md, STRATEGY_CARD.md).

    Result is a dict containing the state_mgr + paths the next phase helpers
    consume. The per-window report's inner try/except is preserved exactly so
    a per-window-report failure does not abort the run record write.
    """
    from tools.basket_ledger import basket_result_to_tradelevel_df
    from config.path_authority import TRADE_SCAN_STATE
    from tools.pipeline_utils import PipelineStateManager

    result = run_ctx["result"]
    leg_data = run_ctx["leg_data"]
    run_id = run_ctx["run_id"]
    basket_id = parsed["basket"]["basket_id"]

    backtests_dir = TRADE_SCAN_STATE / "backtests" / f"{directive_id}_{basket_id}" / "raw"
    backtests_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = TRADE_SCAN_STATE / "runs" / run_id / "data"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Per-run code provenance: snapshot the exact leg-strategy + recycle-rule
    # source files that executed into runs/<run_id>/basket_code/ (write-once).
    # Brings basket runs to parity with the single-strategy
    # runs/<run_id>/strategy.py snapshot. Non-fatal: a provenance hiccup must
    # not abort the run record write (mirrors the vault-write contract).
    code_snapshot = None
    try:
        from tools.basket_provenance import snapshot_basket_code
        from config.path_authority import REAL_REPO_ROOT
        code_snapshot = snapshot_basket_code(
            runs_dir.parent,
            rule_name=result.rule_name,
            rule_version=result.rule_version,
            leg_strategies=run_ctx.get("leg_strategies") or {},
            project_root=REAL_REPO_ROOT,
        )
        print(f"[BASKET] Code snapshot: basket_code/ "
              f"({len(code_snapshot['files'])} files, rule {code_snapshot['rule']})")
    except Exception as exc:
        print(f"[BASKET] WARN code snapshot failed: {exc}")

    # Reproducibility identity: engine version + per-leg input-data hash. With
    # the code hashes (above) this lets a re-run be compared to a prior run and
    # declared reproducible-or-new-truth (single-strategy parquet_sha256 model).
    input_provenance = None
    try:
        from tools.basket_provenance import basket_input_provenance
        input_provenance = basket_input_provenance(
            run_ctx.get("leg_data") or {}, _basket_compute_engine_version(),
        )
    except Exception as exc:
        print(f"[BASKET] WARN input provenance failed: {exc}")

    # Co-locate the SOURCE DIRECTIVE with the basket run, MANDATORY — parity
    # with the single-strategy strategy.py pairing; makes the run self-describing
    # and reproducible even if the directive is later cleaned out of completed/.
    # run_ctx["directive_path"] is the dispatched directive (guaranteed present),
    # so this is a guaranteed copy; a failure raises and the run is marked FAILED
    # — the rule is enforced, never silently skipped.
    from tools.run_directive_snapshot import require_directive_snapshot
    _dsnap = require_directive_snapshot(runs_dir.parent, run_ctx.get("directive_path"))
    print(f"[BASKET] Directive snapshot: {_dsnap['filename']}")

    # Phase 5b.4: emit run_state.json so the startup guardrail
    # (enforce_run_schema) does not quarantine basket runs on subsequent
    # pipeline invocations. Basket dispatch is monolithic but
    # ALLOWED_TRANSITIONS is linear — initialize as IDLE here and walk
    # through stages to COMPLETE at the end of the try block (or
    # transition to FAILED in the outer except).
    state_mgr = PipelineStateManager(run_id, directive_id=directive_id)
    state_mgr.initialize(metadata={
        "execution_mode": "basket",
        "basket_id": basket_id,
    })

    # Build per-symbol-shape tradelevel DataFrame and write to BOTH
    # locations (runs/ for the per-run snapshot, backtests/ for the
    # discovery-friendly per-directive folder).
    df_trades = basket_result_to_tradelevel_df(
        result, run_id=run_id, directive_id=directive_id, leg_data=leg_data,
    )
    runs_csv = runs_dir / "results_tradelevel.csv"
    backtests_csv = backtests_dir / "results_tradelevel.csv"
    df_trades.to_csv(runs_csv, index=False)
    df_trades.to_csv(backtests_csv, index=False)
    print(f"[BASKET] Tradelevel CSV: {backtests_csv} ({len(df_trades)} rows)")

    # Phase 5b.3a — fill the per-window report stack. Without this, the
    # basket backtests/ folder has only `raw/results_tradelevel.csv` while
    # per-symbol folders have ~7 files. This block closes that gap.
    try:
        from tools.basket_report import (
            write_per_window_report_artifacts,
            write_basket_strategy_card,
        )
        stake = float(parsed.get("basket", {}).get("initial_stake_usd", 1000.0))
        written = write_per_window_report_artifacts(
            out_dir=backtests_dir.parent,  # parent of raw/ is the directive folder
            run_id=run_id,
            directive_id=directive_id,
            basket_result=result,
            df_trades=df_trades,
            parsed_directive=parsed,
            engine_version=_basket_compute_engine_version(),
            starting_equity=stake,
        )
        print(f"[BASKET] Per-window report: {len(written)} files "
              f"(REPORT.md, results_standard/risk/yearwise/basket, glossary, bar_geometry, metadata)")

        # Phase 5b.3a — STRATEGY_CARD.md (basket-flavored counterpart to
        # tools/generate_strategy_card.py). Per-symbol generator assumes a
        # strategy.py with STRATEGY_SIGNATURE; baskets have no such file
        # (rule lives in tools/recycle_rules/), so we render the card
        # directly from the directive's basket block.
        card_path = write_basket_strategy_card(
            out_dir=backtests_dir.parent,
            directive_id=directive_id,
            run_id=run_id,
            parsed_directive=parsed,
            engine_version=_basket_compute_engine_version(),
        )
        print(f"[BASKET] STRATEGY_CARD.md: {card_path.name}")
    except Exception as exc:
        print(f"[BASKET] WARN per-window report emit failed: {exc}")

    return {
        "state_mgr": state_mgr,
        "backtests_dir": backtests_dir,
        "runs_dir": runs_dir,
        "code_snapshot": code_snapshot,
        "input_provenance": input_provenance,
        "basket_id": basket_id,
        "df_trades": df_trades,
        "runs_csv": runs_csv,
        "backtests_csv": backtests_csv,
    }


def _basket_persist_run_record(directive_id: str, path, parsed,
                               run_ctx, vault_dir, artifact_ctx):
    """Path B / Phase 5b.2 second half: write the basket run record to the
    authoritative ledger surfaces — run_registry.json (single chokepoint via
    record_run, shard-safe under --max-parallel), and EITHER the MPS Baskets
    sheet (operational basket runs) OR the cointegration_sheet ledger
    (research runs with basket.cointegration_join set, separate ontology).

    The Baskets writer is a dumb sink; canonical metrics are computed here so
    the writer never needs to read the per-bar parquet."""
    from tools.portfolio.basket_ledger_writer import append_basket_row_to_mps
    from config.path_authority import (
        TRADE_SCAN_STATE,
        DRY_RUN_VAULT as _DRY_RUN_VAULT,
    )
    from tools.system_registry import record_run
    from datetime import datetime, timezone

    result = run_ctx["result"]
    run_id = run_ctx["run_id"]
    _content_hash = run_ctx["content_hash"]
    basket_id = artifact_ctx["basket_id"]
    backtests_dir = artifact_ctx["backtests_dir"]
    backtests_csv = artifact_ctx["backtests_csv"]
    df_trades = artifact_ctx["df_trades"]

    # run_registry.json entry (basket-flavored) via the SINGLE chokepoint
    # record_run() -- shard in parallel-batch mode, locked merge sequentially.
    # This is the BASKET topology's authoritative run-state write; it must go
    # through record_run (topology guard enforces it). Previously an inline
    # _load_registry + _save_registry_atomic here raced under --max-parallel,
    # corrupting the registry AND (on WinError 5) aborting this block before
    # the cointegration dispatch below ran.
    record_run({
        "run_id": run_id,
        "tier": "basket",
        "status": "BASKET_COMPLETE",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "directive_id": directive_id,
        "directive_hash": _content_hash,
        "artifact_hash": "",  # basket vault hash not yet schematized; Phase 5b.3
        "basket_id": basket_id,
        "execution_mode": "basket",
    })
    print(f"[BASKET] run_registry entry: {run_id}")

    # Append to MPS Baskets sheet (the actual MPS file users open).
    try:
        vault_path_str = ""
        if vault_dir is not None:
            try:
                vault_path_str = str(vault_dir.relative_to(_DRY_RUN_VAULT.parent))
            except (ValueError, AttributeError):
                vault_path_str = str(vault_dir)
        # Phase 5d.2 (2026-05-17): also pass parquet_path + stake_usd so
        # the writer can populate the canonical_* / cycle_* columns from
        # tools.basket_hypothesis.canonical_metrics. For cycle-mechanic
        # rules (@4/@5+), these are the deployment-decision metrics; the
        # trade-level final_realized_usd column stays for back-compat.
        _basket_block = parsed.get("basket", {}) or {}
        _stake_usd = float(_basket_block.get("initial_stake_usd", 1000.0))
        _parquet_p = backtests_csv.parent / "results_basket_per_bar.parquet"
        mps_path = None
        if _basket_block.get("cointegration_join"):
            # Cointegration research run -> the dedicated regime-aware ledger
            # (separate ontology from operational baskets). The orchestrator
            # computes the canonical metrics + substrate hash here; the writer
            # stays a dumb, sink-only persister that never reads the screener.
            from tools.portfolio.cointegration_provenance import build_cointegration_row
            from tools.portfolio.cointegration_ledger_writer import append_cointegration_row
            from tools.basket_hypothesis.canonical_metrics import canonical_metrics
            import hashlib as _hl
            if not _parquet_p.is_file():
                print("[COINT] WARN no per-bar parquet; skipping cointegration ledger row")
            else:
                _cm = canonical_metrics(_parquet_p, _stake_usd)
                try:
                    import pandas as _pd
                    _n_obs = int(len(_pd.read_parquet(_parquet_p)))
                except Exception:
                    _n_obs = None
                _pq_sha = _hl.sha256(_parquet_p.read_bytes()).hexdigest()
                _trades_total = sum(len(t) for t in result.per_leg_trades.values())
                # Promote the existing per-leg DATA witness (the manifest's
                # leg_data_sha256, already computed for input_provenance) into the
                # authoritative ledger as ONE comparison scalar, so two rows answer
                # "same effective input data?" via WHERE effective_input_sha256=?
                # (DATA axis only; None-safe -> NULL, never aborts the row).
                from tools.basket_provenance import effective_input_sha256 as _eff_input_sha256
                _inp_prov = artifact_ctx.get("input_provenance") or {}
                _eff_input = _eff_input_sha256(_inp_prov.get("leg_data_sha256"))
                # R9 self-ID: a basket charges purely off the per-bar `spread`
                # column, so the row self-reports BOTH whether that column was
                # populated (measured min-across-legs coverage) and whether the
                # compute charges it at all (cost model DERIVED from the imported
                # ABI via the basket_runner SSOT -- override-inert, as honest as
                # engine_abi). Together: "genuinely charged on real-spread data".
                # None-safe -> NULL, never aborts the row.
                from tools.basket_provenance import (
                    min_spread_coverage_pct as _min_spread_cov,
                    execution_cost_model as _exec_cost_model,
                )
                _spread_cov = _min_spread_cov(_inp_prov.get("spread_coverage_pct"))
                _cost_model = _exec_cost_model(_basket_engine_abi())
                _coint_row = build_cointegration_row(
                    parsed=parsed, directive_path=path, run_id=run_id,
                    directive_id=directive_id, directive_hash=_content_hash,
                    backtests_path=str(backtests_dir.parent.relative_to(TRADE_SCAN_STATE)),
                    vault_path=vault_path_str, canonical=_cm,
                    trades_total=_trades_total,
                    completed_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    stake_usd=_stake_usd, n_obs=_n_obs, parquet_sha256=_pq_sha,
                    effective_input_sha256=_eff_input,
                    spread_coverage_pct=_spread_cov,
                    execution_cost_model=_cost_model,
                    engine_version=_basket_compute_engine_version(),
                    engine_abi=_basket_engine_abi(),
                )
                append_cointegration_row(_coint_row)
                # Writer is sink-only (DB, WAL-safe under parallel workers).
                # The MPS xlsx is a derived view: in batch mode the parent
                # renders it ONCE after all directives (TS_DEFER_MPS_EXPORT),
                # avoiding N redundant concurrent renders; a single-directive
                # run renders inline so its tab refreshes immediately.
                if os.environ.get("TS_DEFER_MPS_EXPORT") == "1":
                    print(f"[COINT] MPS render deferred to batch end: {run_id}")
                else:
                    try:
                        from tools.ledger_db import export_mps as _export_mps
                        _export_mps()
                    except Exception as _exc:
                        print(f"[COINT] WARN MPS export (Cointegration tab) failed: {_exc}")
                print(f"[COINT] Cointegration ledger row written: {run_id}")
        else:
            mps_path = append_basket_row_to_mps(
                result, run_id=run_id, directive_id=directive_id,
                backtests_path=str(backtests_csv.relative_to(TRADE_SCAN_STATE)),
                vault_path=vault_path_str,
                df_trades=df_trades,   # Phase 5d.1 fix: writer uses converter's
                                       # computed pnl_usd so force_close trades
                                       # contribute correctly to final_realized_usd
                parquet_path=_parquet_p if _parquet_p.is_file() else None,
                stake_usd=_stake_usd,
            )
            print(f"[BASKET] MPS Baskets row: {mps_path}")
    except Exception as exc:
        print(f"[BASKET] WARN MPS Baskets append failed: {exc}")


def _basket_finalize_state_machine(state_mgr, run_id: str, path,
                                   artifact_ctx):
    """Phase 5b.4: emit manifest.json (so the startup guardrail accepts this
    basket run on next pipeline invocation) and walk the PipelineStateManager
    through PREFLIGHT → STAGE_1..3A → COMPLETE.

    Schema mirrors the per-symbol manifest (stage_symbol_execution.py):
    run_id + strategy_hash (here: hash of directive file, since baskets have
    no strategy.py) + artifacts hash map + timestamp. Extra basket markers
    ('execution_mode', 'basket_id') aid future consumers."""
    import hashlib
    import json
    from datetime import datetime, timezone

    runs_csv = artifact_ctx["runs_csv"]
    basket_id = artifact_ctx["basket_id"]

    if state_mgr is not None:
        artifacts_manifest = {}
        if runs_csv.exists():
            artifacts_manifest["results_tradelevel.csv"] = hashlib.sha256(
                runs_csv.read_bytes()
            ).hexdigest()
        # Code provenance: fold the per-run basket_code/ snapshot hashes into
        # the run manifest so the run record references the exact leg-strategy
        # + recycle-rule code that executed (canonical LF sha256).
        _code_snap = artifact_ctx.get("code_snapshot") or {}
        for _rel, _h in (_code_snap.get("files") or {}).items():
            artifacts_manifest[f"basket_code/{_rel}"] = _h
        _input_prov = artifact_ctx.get("input_provenance") or {}
        manifest_payload = {
            "run_id": run_id,
            "strategy_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            # Engine stamp comes DIRECTLY from the compute source, NOT off the
            # (best-effort, can-be-None) input_provenance block -- a provenance
            # hashing hiccup must never yield engine_version: null in the
            # manifest (Fail-Fast / no silent mislabel). input_provenance still
            # carries its own copy alongside the data/broker-spec hashes.
            "engine_version": _basket_compute_engine_version(),
            "input_provenance": _input_prov,
            "artifacts": artifacts_manifest,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_mode": "basket",
            "basket_id": basket_id,
        }
        manifest_path = state_mgr.run_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=4)
        print(f"[BASKET] Manifest written: {manifest_path}")

    # Phase 5b.4: walk state machine to COMPLETE so the startup
    # guardrail accepts this basket run on next pipeline invocation.
    if state_mgr is not None:
        for _next_state in [
            "PREFLIGHT_COMPLETE",
            "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID",
            "STAGE_1_COMPLETE",
            "STAGE_2_COMPLETE",
            "STAGE_3_COMPLETE",
            "STAGE_3A_COMPLETE",
            "COMPLETE",
        ]:
            state_mgr.transition_to(_next_state)


def _try_basket_dispatch(directive_id: str, provision_only: bool) -> bool:
    """Phase 5b minimal basket dispatch.

    Returns True if the directive was a basket and was dispatched via the
    basket adapter; False otherwise (caller continues with per-symbol flow).

    SCOPE (Phase 5b minimal): wires run_basket_pipeline + basket_vault into
    the orchestrator. Uses PASSTHROUGH strategies + SYNTHETIC OHLC data
    until Phase 5c plumbs real EUR+JPY 5m + USD_SYNTH features. Real-data
    parity vs basket_sim is the live-data gate (currently @pytest.mark.skip
    in tests/test_basket_directive_phase5.py).

    Per-symbol hot path is unchanged — this function early-returns False
    for non-basket directives.

    Decomposition (2026-06-01, Backlog Item 1/4): orchestrates six phase
    helpers (_basket_early_dispatch_check / _basket_run_pipeline /
    _basket_write_vault_snapshot / _basket_write_tradelevel_and_report /
    _basket_persist_run_record / _basket_finalize_state_machine). Path B
    (Phase 5b.2 — standard artifacts) try/except stays here so the failure
    handler can transition the run uniformly to FAILED regardless of which
    sub-phase raised.

    Plan: H2_ENGINE_PROMOTION_PLAN.md Phase 5b (single-ABI on v1_5_9).
    """
    dispatch = _basket_early_dispatch_check(directive_id, provision_only)
    if dispatch is None:
        return False
    path, parsed = dispatch

    # Run the basket through the recycle-rule pipeline.
    run_ctx = _basket_run_pipeline(directive_id, path, parsed)
    vault_dir = None  # DRY_RUN_VAULT/baskets/ auto-write removed 2026-06-07; data lives in TradeScan_State/runs/

    # ---- Path B / Phase 5b.2 — discoverable artifacts in the standard layout ----
    # Goal: a basket run shows up alongside per-symbol runs in:
    #   * TradeScan_State/runs/<run_id>/data/results_tradelevel.csv
    #   * TradeScan_State/backtests/<directive_id>_<basket_id>/raw/results_tradelevel.csv
    #   * TradeScan_State/registry/run_registry.json
    #   * Master_Portfolio_Sheet.xlsx (Baskets sheet)
    # Without this, basket runs hide in DRY_RUN_VAULT/baskets/ — the user's
    # principle: "results must be discoverable later, not just produced."
    # Phase 5b.3 (2026-05-20): writer now goes through ledger.db.basket_sheet;
    # the legacy research/basket_runs.csv writer is retired.
    state_mgr = None  # Phase 5b.4: emit run_state.json (startup-guardrail compliance)
    try:
        artifact_ctx = _basket_write_tradelevel_and_report(directive_id, parsed, run_ctx)
        state_mgr = artifact_ctx["state_mgr"]
        _basket_persist_run_record(
            directive_id, path, parsed, run_ctx, vault_dir, artifact_ctx,
        )
        _basket_finalize_state_machine(
            state_mgr, run_ctx["run_id"], path, artifact_ctx,
        )
    except Exception as exc:
        # Path B failure must NOT swallow the run — log + continue. The
        # research CSV still landed; future analysis can recover.
        import traceback
        print(f"[BASKET] WARN Path B (standard artifacts) failed: {exc}")
        print(f"[BASKET]   {traceback.format_exc().splitlines()[-1]}")
        # Phase 5b.4: mark run FAILED so it doesn't get quarantined as
        # "corrupt" (no run_state.json) on the next startup. Best-effort —
        # state_mgr may not yet exist if the exception fired pre-init.
        if state_mgr is not None:
            try:
                state_mgr.transition_to("FAILED")
            except Exception:
                pass

    # Phase 5b.3 (2026-05-20): the legacy research/basket_runs.csv writer is
    # retired. basket_sheet (ledger.db) is now the canonical store; the CSV
    # file remains on disk for historical reference (290 rows imported into
    # basket_sheet; 256 legacy pre-2026-05-18 rows have synthetic 'L'-prefixed
    # run_ids). The function append_basket_row_to_research_csv stays in
    # tools/portfolio_evaluator.py as dead code until the next cleanup sweep.

    result = run_ctx["result"]
    run_id = run_ctx["run_id"]
    data_mode = run_ctx["data_mode"]
    trades_total = sum(len(t) for t in result.per_leg_trades.values())
    print(f"[BASKET] Phase 5b.2 dispatch complete. "
          f"trades={trades_total}, recycles={len(result.recycle_events)}, "
          f"harvested_usd={result.harvested_total_usd:.2f}, "
          f"run_id={run_id or 'N/A'}")
    if data_mode == "synthetic":
        print("[BASKET] NOTE: synthetic-data mode — figures are placeholder. "
              "Confirm DATA_INGRESS has populated MASTER_DATA + SYSTEM_FACTORS "
              "for the basket symbols, then re-run.")
    else:
        print(f"[BASKET] Real RESEARCH data: {len(result.recycle_events)} recycle event(s); "
              f"10-window basket_sim parity gate remains skipped pending Phase 5d.1.")
    return True


class _PassthroughStrategy:
    """Stand-in strategy for synthetic-mode dispatch — never emits signals.

    Used only when the real RESEARCH data layer is unavailable. Production
    runs use tools.recycle_strategies.ContinuousHoldStrategy.
    """
    timeframe = "5m"

    def __init__(self, symbol: str) -> None:
        self.name = f"basket_passthrough_{symbol}"

    def prepare_indicators(self, df):  # noqa: D401
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


# ────────────────────────────────────────────────────────────────────────
# Leg-strategy dispatch — single source of truth
# (2026-06-01: replaces the inline if/elif chain that produced the ZBND
# silent-fallthrough bug. See SYSTEM_STATE.md [INVARIANT_PROPOSAL] entry
# 2026-06-01 and [[mechanism-port-integration-points]] memory.)
#
# Every recycle rule registered in governance/recycle_rules/registry.yaml
# MUST be in exactly ONE of:
#   - LEG_STRATEGY_DISPATCH : proposal-based legs (fire entry signals)
#   - CONTINUOUS_HOLD_RULES : always-open legs (rule handles the mechanic)
# A registered rule absent from BOTH raises LegDispatchError at dispatch
# time. tests/test_leg_strategy_dispatch.py also catches it at test time
# by enumerating the registry.
# ────────────────────────────────────────────────────────────────────────


class LegDispatchError(RuntimeError):
    """Raised when a recycle rule has no leg-strategy assignment.

    Distinct from generic RuntimeError so the synthetic-fallback
    try/except in _load_basket_leg_inputs does NOT mask the
    misconfiguration. ZBND 2026-06-01: a new rule wired into registry +
    basket_pipeline dispatch + __init__ exports but MISSED at the
    leg-strategy site silently ran with ContinuousHoldStrategy → no
    armed_state → no proposal mechanism → 24 episodes returned wrong
    synthesis before root-cause."""


def _build_spread_cross_legs(parsed, rule_block, bar_seconds):
    """H3_spread leg strategy: shared SpreadCrossArmedState, cross signals."""
    from tools.recycle_strategies import (
        SpreadCrossArmedState, SpreadCrossLegStrategy,
    )
    rule_params = rule_block.get("params", {}) or {}
    if bool(rule_params.get("bidirectional", False)):
        cross_watch = 0
    else:
        cross_watch = int(rule_params.get("entry_direction", +1))
    delay_bars = int(rule_params.get("entry_delay_bars", 12))
    shared_armed_state = SpreadCrossArmedState()
    return {
        leg["symbol"]: SpreadCrossLegStrategy(
            symbol=leg["symbol"],
            position_direction=+1 if leg["direction"] == "long" else -1,
            cross_watch_direction=cross_watch,
            armed_state=shared_armed_state,
            delay_bars=delay_bars,
            bar_seconds=bar_seconds,
        )
        for leg in parsed["basket"]["legs"]
    }


def _build_coint_trigger_legs(parsed, rule_block, bar_seconds):
    """cointegration_meanrev_v1_2 leg strategy: shared CointTriggerArmedState."""
    from tools.recycle_strategies import (
        CointTriggerArmedState, CointTriggerLegStrategy,
    )
    shared_armed_state = CointTriggerArmedState()
    return {
        leg["symbol"]: CointTriggerLegStrategy(
            symbol=leg["symbol"],
            position_direction=+1 if leg["direction"] == "long" else -1,
            armed_state=shared_armed_state,
        )
        for leg in parsed["basket"]["legs"]
    }


def _build_pine_zrev_legs(parsed, rule_block, bar_seconds):
    """pine_ratio_zrev_v1 family (incl. _zcross, _zband): shared PineZRevArmedState."""
    from tools.recycle_strategies import (
        PineZRevArmedState, PineZRevLegStrategy,
    )
    shared_armed_state = PineZRevArmedState()
    return {
        leg["symbol"]: PineZRevLegStrategy(
            symbol=leg["symbol"],
            position_direction=+1 if leg["direction"] == "long" else -1,
            armed_state=shared_armed_state,
        )
        for leg in parsed["basket"]["legs"]
    }


def _build_continuous_hold_legs(parsed, rule_block, bar_seconds):
    """ContinuousHoldStrategy: legs hold unconditionally; rule manages cycle."""
    from tools.recycle_strategies import ContinuousHoldStrategy
    return {
        leg["symbol"]: ContinuousHoldStrategy(
            symbol=leg["symbol"],
            direction=+1 if leg["direction"] == "long" else -1,
        )
        for leg in parsed["basket"]["legs"]
    }


LEG_STRATEGY_DISPATCH = {
    "H3_spread":                  _build_spread_cross_legs,
    "cointegration_meanrev_v1_2": _build_coint_trigger_legs,
    "pine_ratio_zrev_v1":         _build_pine_zrev_legs,
    "pine_ratio_zrev_v1_zcross":  _build_pine_zrev_legs,
    "pine_ratio_zrev_v1_zband":   _build_pine_zrev_legs,
    "pine_ratio_zrev_v1_zopp":    _build_pine_zrev_legs,
}

CONTINUOUS_HOLD_RULES = frozenset({
    "H2_recycle",         # v1, v2, v3, v4, v5 — all registry-tracked variants
    "H2_v7_compression",  # DEPRECATED but admitted for audit replay
})


def _dispatch_leg_strategies(parsed, rule_block, bar_seconds):
    """Resolve recycle_rule.name -> {symbol: leg_strategy_instance}.

    Loud-fail invariant: a rule name absent from BOTH
    LEG_STRATEGY_DISPATCH and CONTINUOUS_HOLD_RULES raises LegDispatchError.
    Empty rule_name (non-basket directive) routes to continuous-hold for
    legacy compatibility — basket detection happens upstream.
    """
    rule_name = rule_block.get("name", "") if rule_block else ""
    if rule_name in LEG_STRATEGY_DISPATCH:
        return LEG_STRATEGY_DISPATCH[rule_name](parsed, rule_block, bar_seconds)
    if rule_name in CONTINUOUS_HOLD_RULES or not rule_name:
        return _build_continuous_hold_legs(parsed, rule_block, bar_seconds)
    raise LegDispatchError(
        f"recycle_rule.name={rule_name!r} is not in LEG_STRATEGY_DISPATCH "
        f"(proposal-based legs) or CONTINUOUS_HOLD_RULES (always-open "
        f"legs). Every recycle rule registered in "
        f"governance/recycle_rules/registry.yaml MUST be in exactly one "
        f"of those collections in tools/run_pipeline.py. This raises "
        f"explicitly to prevent the silent-fallthrough bug from "
        f"2026-06-01 (ZBND ran in degraded mode across 24 episodes "
        f"before root-cause)."
    )


def _synthetic_leg_data(parsed: dict) -> dict:
    """Generate synthetic OHLC + compression_5d=5.0 (gate closed) for each leg.

    Phase 5c fallback used only when real data loading fails. Production
    path uses tools.basket_data_loader.load_basket_leg_data.
    """
    import numpy as np
    import pandas as pd
    n_bars = 240
    out: dict = {}
    for i, leg in enumerate(parsed["basket"]["legs"]):
        rng = np.random.default_rng(seed=hash(leg["symbol"]) & 0xFFFFFFFF)
        idx = pd.date_range("2024-09-02", periods=n_bars, freq="5min")
        base = 1.10 + np.cumsum(rng.normal(0.0, 0.0005, n_bars))
        out[leg["symbol"]] = pd.DataFrame(
            {"open": base, "high": base, "low": base, "close": base,
             "volume": 1000.0, "compression_5d": 5.0},
            index=idx,
        )
    return out


def _load_basket_leg_inputs(parsed: dict) -> tuple[dict, dict, str]:
    """Phase 5c: load real OHLC + factor + strategies; fall back to synthetic.

    Returns (leg_data, leg_strategies, mode) where mode is either
    'real' (RESEARCH layer + ContinuousHoldStrategy) or 'synthetic'
    (passthrough + closed-gate).

    The fallback is intentional — keeps the dispatcher resilient to
    missing/temporarily-unavailable data so the orchestrator pipeline
    test surfaces a clear "synthetic-mode" banner instead of a hard
    crash. Production runs MUST show 'real' mode to be meaningful.
    """
    symbols = [leg["symbol"] for leg in parsed["basket"]["legs"]]
    test_block = parsed.get("test", {})
    start_date = str(test_block.get("start_date", "2024-09-02"))
    end_date = str(test_block.get("end_date", "2026-05-09"))
    # S12 (2026-05-16): factor_column is read from the recycle rule's params
    # so alternative USD_SYNTH features (vol_5d, autocorr_5d, etc.) flow
    # through to the loader. Default 'compression_5d' preserves all
    # pre-S12 behaviour.
    _rule_params = (
        parsed.get("basket", {}).get("recycle_rule", {}).get("params", {}) or {}
    )
    factor_column = str(_rule_params.get("factor_column", "compression_5d"))
    # Bar timeframe — drives the underlying CSV series + cross-signal window
    # scaling. Default "5m" matches the historical default; 15m / 30m / 1h
    # are supported per the 2026-05 DATA_INGRESS ingest.
    bar_timeframe = str(parsed.get("test", {}).get("timeframe", "5m"))
    _BAR_SECONDS_MAP = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
                         "4h": 14400, "1d": 86400}
    bar_seconds = _BAR_SECONDS_MAP.get(bar_timeframe, 300)
    # Macro-direction filter (2026-05-19). When set, the loader computes
    # the spread cross at this higher native broker timeframe and uses it
    # to gate entry-TF cross_event entries. cross_side (exit signal) stays
    # untouched. None = no macro filter (byte-equivalent to legacy).
    macro_direction_timeframe = _rule_params.get("macro_direction_timeframe", None)
    if macro_direction_timeframe is not None:
        macro_direction_timeframe = str(macro_direction_timeframe)
    macro_warmup_days = int(_rule_params.get("macro_warmup_days", 120))
    # Indicator-window overrides for the macro filter. Defaults match
    # daily-calendar conventions (z=60, sma=5); override to scale 4h or
    # 1h macro signals to the same calendar lookback.
    macro_z_window = int(_rule_params.get("macro_z_window", 60))
    macro_sma_window = int(_rule_params.get("macro_sma_window", 5))
    # Correlation-health filter (2026-05-19). When set, the loader computes
    # rolling daily-log-return correlation between the two basket legs and
    # gates entry-TF cross_event entries on it being at-or-below
    # macro_correlation_threshold (strongly inverse = USD-direction thesis
    # holds). None = no filter (legacy behavior preserved).
    macro_correlation_window = _rule_params.get("macro_correlation_window", None)
    if macro_correlation_window is not None:
        macro_correlation_window = int(macro_correlation_window)
    macro_correlation_threshold = float(
        _rule_params.get("macro_correlation_threshold", -0.5)
    )
    # Regime gate (2026-05-23, charter h3_spread_window_c_regime_detector).
    # When both lookback and threshold are set, the loader computes a rolling
    # count of cross_side flips and zeros out cross_event where the count
    # exceeds the threshold (cycle-init suppression). Pyramid suppression on
    # already-open cycles is the v3 rule's responsibility. Default None on
    # either param preserves byte-equivalence with pre-2026-05-23 behavior.
    regime_gate_lookback_bars = _rule_params.get("regime_gate_lookback_bars", None)
    if regime_gate_lookback_bars is not None:
        regime_gate_lookback_bars = int(regime_gate_lookback_bars)
    regime_gate_flip_threshold = _rule_params.get("regime_gate_flip_threshold", None)
    if regime_gate_flip_threshold is not None:
        regime_gate_flip_threshold = float(regime_gate_flip_threshold)
    # Cointegration auto-join (COINTREV v1.2, 2026-05-24). When the directive
    # declares `basket.cointegration_join.lookback_days`, the loader joins
    # cointegration_daily + cointegration_triggers onto each 2-leg basket
    # from cointegration.db. Default None preserves byte-equivalence with
    # pre-v1.2 directives that don't reference cointegration columns.
    _coint_join = parsed.get("basket", {}).get("cointegration_join", {}) or {}
    cointegration_join_lookback_days = _coint_join.get("lookback_days", None)
    if cointegration_join_lookback_days is not None:
        cointegration_join_lookback_days = int(cointegration_join_lookback_days)
    try:
        from tools.basket_data_loader import load_basket_leg_data
        # Note: recycle_strategies symbols (CointTriggerLegStrategy,
        # PineZRevLegStrategy, SpreadCrossLegStrategy, ContinuousHoldStrategy,
        # and their armed-state companions) are imported lazily inside the
        # _build_*_legs helpers used by _dispatch_leg_strategies. Keeping
        # imports local to the helpers means the dispatch dict can live at
        # module scope and be exported for tests (test_leg_strategy_dispatch.py).
        # Leg-warmup probe (2026-05-30): the rule is the single source of truth
        # for how many bars of pre-start_date data its indicators need. We
        # temp-instantiate the rule with identity dummies (required_warmup_bars
        # only reads param fields, not run_id/directive_id/basket_id) and read
        # the count. The real rule instance is re-created by basket_pipeline's
        # _instantiate_rule later with real identity; both share the same
        # param values, so the warmup count is deterministic and identical.
        # Pipeline stays generic — no rule-specific formula lives here.
        rule_warmup_bars = 0
        if parsed.get("basket", {}).get("recycle_rule"):
            try:
                from tools.basket_pipeline import _instantiate_rule as _probe_rule_init
                _probe = _probe_rule_init(
                    parsed["basket"]["recycle_rule"],
                    run_id="__warmup_probe__",
                    directive_id="__warmup_probe__",
                    basket_id=parsed["basket"].get("basket_id", "__probe__"),
                )
                rule_warmup_bars = int(
                    getattr(_probe, "required_warmup_bars", lambda: 0)()
                )
            except Exception as exc:
                # Probe-failure is non-blocking — warmup defaults to 0, which
                # preserves pre-2026-05-30 behavior (rule may still hit its
                # own min-bars assertion at run time, surfaced as a real error
                # instead of silenced by hidden warmup).
                print(
                    f"[BASKET] WARN: warmup probe failed ({exc!r}); "
                    f"leg_warmup_bars=0 (pre-2026-05-30 default)."
                )
        leg_data = load_basket_leg_data(
            symbols, start_date, end_date,
            factor_column=factor_column, timeframe=bar_timeframe,
            macro_direction_timeframe=macro_direction_timeframe,
            macro_warmup_days=macro_warmup_days,
            macro_z_window=macro_z_window,
            macro_sma_window=macro_sma_window,
            macro_correlation_window=macro_correlation_window,
            macro_correlation_threshold=macro_correlation_threshold,
            regime_gate_lookback_bars=regime_gate_lookback_bars,
            regime_gate_flip_threshold=regime_gate_flip_threshold,
            cointegration_join_lookback_days=cointegration_join_lookback_days,
            leg_warmup_bars=rule_warmup_bars,
        )
        # Leg-strategy dispatch by recycle rule name. Delegated to the
        # module-scope _dispatch_leg_strategies / LEG_STRATEGY_DISPATCH /
        # CONTINUOUS_HOLD_RULES (2026-06-01 refactor; replaces inline
        # if/elif that produced the ZBND silent-fallthrough bug). The
        # shared armed-state instance(s) are constructed inside the helper
        # so BOTH legs of the basket reference the same instance (required
        # for per-bar atomicity).
        rule_block = parsed.get("basket", {}).get("recycle_rule", {}) or {}
        leg_strategies = _dispatch_leg_strategies(parsed, rule_block, bar_seconds)
        return leg_data, leg_strategies, "real"
    except LegDispatchError:
        # NEVER mask leg-dispatch wiring errors with the synthetic fallback.
        # The whole point of the loud-fail invariant is to surface a
        # silent-fallthrough at the construction site, not bury it under a
        # WARN that lets the directive complete in degraded mode.
        raise
    except Exception as exc:
        print(f"[BASKET] WARN real data load failed ({exc}); falling back to synthetic mode.")
        leg_data = _synthetic_leg_data(parsed)
        leg_strategies = {
            leg["symbol"]: _PassthroughStrategy(leg["symbol"])
            for leg in parsed["basket"]["legs"]
        }
        return leg_data, leg_strategies, "synthetic"


def run_single_directive(directive_id, provision_only=False, refresh=False):
    """Execution logic for a single directive.

    `refresh=True` permits an identity-preserving re-run of an existing directive
    (cointegration pilot) -- see `verify_directive_uniqueness_guard`.
    """
    ctx = None
    # 1.1 Uniqueness Check (skipped for a declared refresh)
    verify_directive_uniqueness_guard(directive_id, refresh=refresh)

    # Phase 5b: basket dispatch (early-return for RECYCLE basket directives;
    # per-symbol flow unchanged below).
    if _try_basket_dispatch(directive_id, provision_only):
        return

    # 1.2 Bootstrap
    bootstrap = BootstrapController(PROJECT_ROOT)

    try:
        ctx = bootstrap.prepare_context(
            directive_id=directive_id,
            provision_only=provision_only
        )
    except PipelineExecutionError as e:
        if "already COMPLETE" in str(e):
            return  # Clean exit if already done
        raise

    _announce_run_engine(directive_id)

    try:
        # StageRunner iterates STAGE_REGISTRY, skipping completed_stages on resume.
        StageRunner(ctx).run()
        print("[ORCHESTRATOR] Pipeline complete.")
        return
    except PipelineError as e:
        if "PREFLIGHT" in str(e) or "Unhandled orchestration failure" in str(e):
            from tools.orchestration.run_cleanup import cleanup_provisioned_runs
            if getattr(ctx, 'run_ids', []):
                cleanup_provisioned_runs(ctx.run_ids)
        raise
    except Exception as e:
        from tools.orchestration.run_cleanup import cleanup_provisioned_runs
        if getattr(ctx, 'run_ids', []):
            cleanup_provisioned_runs(ctx.run_ids)
        import traceback
        traceback.print_exc()
        raise PipelineExecutionError(
            f"Unhandled orchestration failure: {e}",
            directive_id=directive_id,
            run_ids=getattr(ctx, 'run_ids', []),
        ) from e


def _report_data_freshness() -> None:
    """Read freshness_index.json and print stale-only report.

    Path source: config.path_authority.FRESHNESS_INDEX (canonical = MASTER_DATA/
    freshness_index.json). Predecessor read from PROJECT_ROOT/data_root/
    freshness_index.json which diverged from path_authority and from the
    DATA_INGRESS writer contract; the divergence left this reader pointed at
    a stale 1-entry file even when the canonical index was fully populated.

    Never raises.
    """
    try:
        from config.path_authority import FRESHNESS_INDEX as index_path
        if not index_path.exists():
            print(
                "[WARN] freshness_index.json missing — "
                "data ingestion may have failed or not yet run. "
                "Run tools/refresh_freshness_index.py "
                "or build_freshness_index in DATA_INGRESS to generate it."
            )
            return
        index  = json.loads(index_path.read_text(encoding="utf-8"))
        buffer = index.get("buffer_days", 3)
        gen    = index.get("generated_at", "")[:10]
        stale  = {
            k: v for k, v in index.get("entries", {}).items()
            if v.get("days_behind", 0) > buffer
        }
        if not stale:
            return
        print(f"\n{'='*60}")
        print(f"DATA FRESHNESS WARNING  (index: {gen}, buffer: {buffer}d)")
        for key, v in sorted(stale.items(), key=lambda x: -x[1]["days_behind"]):
            print(f"  {key:<32}  last: {v['latest_date']}   {v['days_behind']}d stale")
            print(f"    source: {v['source_file']}")
        print(f"  → Data ingress may have failed for these symbols.")
        print(f"  → Run build_freshness_index in DATA_INGRESS to verify.")
        print(f"{'='*60}")
    except Exception as exc:
        print(f"[WARN] Data freshness check failed: {exc}")


def _assert_pipeline_idle():
    """PORTFOLIO_COMPLETE gate — Invariant #26.
    Hard fail if any directive is in a non-terminal state across all runs.
    Terminal states: PORTFOLIO_COMPLETE, FAILED.
    """
    from config.status_enums import DIRECTIVE_TERMINAL
    _TERMINAL = DIRECTIVE_TERMINAL
    if not RUNS_DIR.exists():
        return
    active = []
    for state_file in RUNS_DIR.glob("*/directive_state.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            latest = data.get("latest_attempt")
            if not latest:
                continue
            status = data["attempts"][latest]["status"]
            if status not in _TERMINAL:
                active.append(f"{data['directive_id']} ({status})")
        except Exception:
            continue  # corrupt/incomplete state file — do not block on it
    if active:
        msg = (
            f"\n{'='*60}\n"
            f"PIPELINE_BUSY\n"
            f"Previous directive still in progress: {active}\n"
            f"Complete or fail it before starting a new run.\n"
            f"{'='*60}"
        )
        print(msg)
        raise PipelineExecutionError("PIPELINE_BUSY", directive_id="BATCH")


# ────────────────────────────────────────────────────────────────────────
# Batch mode — phase helpers (2026-06-01 decomposition, Backlog 2/4)
#
# `run_batch_mode` was 226 LOC. Decomposed into three phase helpers plus a
# slim orchestrator. Behavior is byte-equivalent: same print order, same
# telemetry emit sequence, same try/finally semantics around the
# orchestrator.run_batch() call, same env-var lifecycle (TS_DEFER_MPS_EXPORT
# + TS_REGISTRY_SHARD_DIR set BEFORE workers spawn, popped after).
# ────────────────────────────────────────────────────────────────────────


def _batch_discover_and_admit(provision_only: bool):
    """Phase 1 — discovery + sequential admission.

    Discovers INBOX directives, asserts the pipeline is idle, runs the
    ACTIVE Bypass Guard, applies the Auto-Consistency Gate (hash alignment
    + approved marker) to every directive, then admits each via
    `admit_directive` (sequential — Invariant #26).

    Returns the list of admitted directive stems, or None for the two
    early-return short-circuits (active dir missing, no directives in
    INBOX). The caller treats None as "nothing to execute"."""
    active_dir = PROJECT_ROOT / "backtest_directives" / "INBOX"
    completed_dir = PROJECT_ROOT / "backtest_directives" / "completed"

    _assert_pipeline_idle()

    if not active_dir.exists():
        print(f"[BATCH] Active directory not found: {active_dir}")
        return None

    directives = prepare_batch_directives_for_execution(
        active_dir=active_dir,
        python_exe=PYTHON_EXE,
        run_command=run_command,
    )
    if not directives:
        print("[BATCH] No directives found in active/")
        return None

    print(f"[BATCH] Found {len(directives)} directives: {[d.name for d in directives]}")

    # Invariant #26 — Sequential Execution: multiple directives in INBOX are
    # permitted, but MUST be processed strictly sequentially with a cooldown
    # between runs. The Phase-2 loop below enforces this (one directive at a
    # time, 15s cooldown between iterations). No parallelism anywhere.

    # --- ACTIVE Bypass Guard ---
    try:
        from tools.sweep_registry_gate import (
            _load_yaml, SWEEP_REGISTRY_PATH, get_all_allocated_names,
        )
        registry_data = _load_yaml(SWEEP_REGISTRY_PATH)
        allocated_names = get_all_allocated_names(registry_data)
        for d_path in directives:
            if d_path.stem not in allocated_names:
                print(f"DIRECTIVE_NOT_ADMITTED | directive={d_path.name}")
    except Exception as e:
        print(f"[WARN] Failed to run ACTIVE Bypass Guard: {e}")
    # ---------------------------

    completed_dir.mkdir(parents=True, exist_ok=True)

    # Auto-Consistency Gate: hash alignment + approved marker (before admission)
    for d_path in directives:
        enforce_signature_consistency(
            directive_id=d_path.stem,
            project_root=PROJECT_ROOT,
            active_dir=ACTIVE_DIR,
        )

    # --- PHASE 1: ADMISSION (SEQUENTIAL) ---
    admitted = [d_path.stem for d_path in directives]
    if not provision_only:
        for d_id in admitted:
            admit_directive(d_id)

    print(f"[BATCH] Admitted {len(admitted)} directive(s).")
    return admitted


def _batch_execute_with_telemetry(admitted: list, provision_only: bool,
                                  max_parallel: int) -> None:
    """Phase 2 — telemetry-wrapped execution with optional registry sharding.

    Initializes the TelemetryWriter + batch_id, emits batch_start +
    directive_queued events, sets the TS_DEFER_MPS_EXPORT env var so the
    cointegration dispatch only touches the DB (parent renders xlsx once
    after the batch), sets up per-worker registry sharding when
    `max_parallel >= 2`, constructs the PipelineOrchestrator, runs the
    batch under a try/finally, and in the finally block: emits batch_end,
    prints the telemetry summary, merges shards (if any), and renders the
    deferred MPS exactly once from the (canonical) DB.

    Phase 3b (2026-05-27) — directive-level dispatch refactored into
    PipelineOrchestrator. Default `max_parallel=1` keeps pre-Phase-3
    sequential semantics (direct loop, no subprocess overhead) and is
    permanently first-class — debugging / safe-mode / reproducibility /
    emergency recovery. `--max-parallel >=2` enables ProcessPoolExecutor
    parallelism; Stage 3 + Stage 4 FileLocks (Phase 2) provide
    cross-directive write coordination.

    The 15s inter-directive cooldown is REMOVED — Stage 4 file lock
    (Phase 2b) now provides deterministic exclusivity around the shared
    ledger writes. Lock acquire is fast under no contention; lock
    release is bounded by Stage 4 wall time (~1-2s typical)."""
    from tools.pipeline_telemetry import (
        TelemetryWriter,
        batch_summary,
        generate_batch_id,
    )
    from tools.pipeline_orchestrator import PipelineOrchestrator

    _batch_id = generate_batch_id()
    _telemetry = TelemetryWriter(batch_id=_batch_id)
    _telemetry.emit(
        directive_id=None, stage_id=None, event="batch_start",
        n_directives=len(admitted),
        max_parallel=max_parallel,
    )
    print(f"[BATCH] telemetry batch_id={_batch_id} max_parallel={max_parallel}")

    # Emit directive_queued for every admitted directive upfront — even
    # in sequential mode, so the event stream shape is mode-invariant.
    for _d_id in admitted:
        _telemetry.queue_directive(_d_id)

    # Batch mode: defer the per-directive MPS render. The cointegration dispatch
    # writes only the (WAL-safe) DB during the run; the parent renders the xlsx
    # ONCE below, after all directives -- avoiding N redundant, concurrent renders
    # under --max-parallel. Set BEFORE workers spawn so they inherit the flag.
    os.environ["TS_DEFER_MPS_EXPORT"] = "1"

    # Parallel batch: shard the run-registry per worker, merge once in the parent.
    # run_registry.json is NOT safe under concurrent multi-process writes; sharding
    # confines each run's write to its own immutable file (SHARD_REGISTRY_PLAN.md).
    # Sequential (max_parallel==1) keeps the canonical direct-write path untouched.
    _shard_dir = None
    if max_parallel >= 2 and not provision_only:
        import yaml as _yaml
        from config.state_paths import REGISTRY_DIR as _REG_DIR
        from tools.orchestration.registry_merge import write_batch_manifest
        from tools.pipeline_utils import generate_run_id as _gen_rid
        _shard_dir = _REG_DIR / "batch_shards" / _batch_id
        _expected_run_ids = []
        for _d_id in admitted:
            _dpath = ACTIVE_BACKUP_DIR / f"{_d_id}.txt"
            try:
                _p = _yaml.safe_load(_dpath.read_text(encoding="utf-8")) or {}
                _bid = (_p.get("basket", {}) or {}).get("basket_id")
                if _bid:
                    _rid, _ = _gen_rid(_dpath, symbol=_bid)
                    _expected_run_ids.append(_rid)
            except Exception:
                pass
        write_batch_manifest(_shard_dir, batch_id=_batch_id,
                             expected_run_ids=_expected_run_ids,
                             worker_count=max_parallel, max_parallel=max_parallel)
        os.environ["TS_REGISTRY_SHARD_DIR"] = str(_shard_dir)
        print(f"[BATCH] registry sharding enabled ({len(_expected_run_ids)} expected) -> {_shard_dir}")

    _orchestrator = PipelineOrchestrator(
        batch_id=_batch_id,
        max_parallel=max_parallel,
        telemetry=_telemetry,
    )
    try:
        _orchestrator.run_batch(admitted, provision_only=provision_only)
    finally:
        _telemetry.emit(
            directive_id=None, stage_id=None, event="batch_end",
        )
        try:
            _summary = batch_summary(_batch_id)
            print(
                f"[BATCH] telemetry summary: started={_summary['n_directives_started']}, "
                f"completed={_summary['n_directives_completed']}, "
                f"failed={_summary['n_directives_failed']}"
            )
        except Exception as _summary_err:
            # Telemetry summary is diagnostic — never let a summary
            # failure mask the actual batch outcome.
            print(f"[BATCH] (telemetry summary unavailable: {_summary_err})")
        # Merge per-worker registry shards into the authoritative run_registry.json
        # (parent, single process). Idempotent + integrity-verified; shards are
        # preserved until a successful, verified merge (SHARD_REGISTRY_PLAN.md).
        os.environ.pop("TS_REGISTRY_SHARD_DIR", None)
        if _shard_dir is not None:
            try:
                from tools.orchestration.registry_merge import merge_shards
                _m = merge_shards(_shard_dir)
                print(f"[BATCH] registry shards merged: {_m.get('merged_run_count')} runs "
                      f"from {_m.get('shard_count')} shards.")
            except Exception as _exc:
                print(f"[BATCH] WARN registry shard merge failed — shards preserved at "
                      f"{_shard_dir} for recovery (re-run registry_merge.merge_shards): {_exc}")
        # Deferred single MPS render (parent process, no contention). Runs even
        # on a partial/failed batch so the xlsx reflects whatever the DB now
        # holds. The DB is canonical — a render failure is logged, never fatal.
        os.environ.pop("TS_DEFER_MPS_EXPORT", None)
        if not provision_only:
            try:
                from tools.ledger_db import export_mps as _export_mps
                _export_mps()
                print("[BATCH] MPS rendered once from DB after batch.")
            except Exception as _exc:
                print(f"[BATCH] WARN deferred MPS render failed (DB is canonical; "
                      f"run `python tools/ledger_db.py --export-mps` to refresh): {_exc}")


def _batch_archive_and_postprocess(admitted: list, provision_only: bool) -> None:
    """Phase 3 — archive completed directives + end-of-batch post-processing.

    Archives admitted directives via `archive_completed_directive` (or
    prints provision-only retention banners), then runs Candidate Promotion
    (`filter_strategies.py`), hyperlink restoration, and MPS/FSP Excel
    formatting. Each post-processing step is wrapped in its own try/except
    so a downstream failure (e.g., Excel file open locally → permission
    denied on the formatter) does not abort earlier sweeps."""
    # --- PHASE 3: ARCHIVE (SEQUENTIAL) ---
    # Only reached if all futures succeeded.
    if not provision_only:
        for d_id in admitted:
            archive_completed_directive(d_id)
    else:
        for d_id in admitted:
            print(f"[BATCH] Provision-only: {d_id} remains in INBOX/")

    if not provision_only:
        print("\n[BATCH] Running Candidate Promotion (filter_strategies.py)...")
        try:
            run_command([PYTHON_EXE, "tools/filter_strategies.py"], "Candidate Promotion")
        except Exception as e:
            print(f"[WARN] Candidate promotion failed: {e}")

        print("\n[BATCH] Restoring hyperlinks in Excel artifacts...")
        try:
            run_command([PYTHON_EXE, "tools/add_strategy_hyperlinks.py", "--target", "all"], "Hyperlinks")
        except Exception as e:
            print(f"[WARN] Hyperlink restoration failed: {e}")

        # Format MPS + FSP to the operator's preferred tab structure
        # (filters, dropdowns, hyperlinks, sort, hidden non-CORE rows).
        # Must run AFTER hyperlinks so column formatting doesn't lose
        # the link sweep. Warn-only: if MPS is open in Excel locally,
        # format will fail with permission-denied and the operator can
        # close + re-run `format-excel-ledgers` manually.
        from config.path_authority import TRADE_SCAN_STATE as _TS_STATE
        print("\n[BATCH] Formatting MPS (Master_Portfolio_Sheet.xlsx)...")
        try:
            run_command(
                [PYTHON_EXE, "tools/format_excel_artifact.py",
                 "--file", str(_TS_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"),
                 "--profile", "portfolio"],
                "Format MPS",
            )
        except Exception as e:
            print(f"[WARN] MPS formatting failed: {e}")
        print("\n[BATCH] Formatting FSP (Filtered_Strategies_Passed.xlsx)...")
        try:
            run_command(
                [PYTHON_EXE, "tools/format_excel_artifact.py",
                 "--file", str(_TS_STATE / "candidates" / "Filtered_Strategies_Passed.xlsx"),
                 "--profile", "strategy"],
                "Format FSP",
            )
        except Exception as e:
            print(f"[WARN] FSP formatting failed: {e}")

    print("\n[BATCH] All directives processed successfully.")


def run_batch_mode(provision_only=False, max_parallel=1):
    """Sequential Batch Execution.

    Three-phase batch dispatcher:
      1. Discover INBOX directives + admit them sequentially (Invariant #26).
      2. Execute through PipelineOrchestrator with telemetry + optional
         per-worker registry sharding (max_parallel >= 2 only).
      3. Archive completed directives + run end-of-batch post-processing
         (candidate promotion, hyperlinks, MPS/FSP formatting).

    Decomposition (2026-06-01, Backlog Item 2/4): each phase is a helper.
    Behavior is byte-equivalent: same print order, same telemetry emit
    sequence, same try/finally semantics around `orchestrator.run_batch()`,
    same TS_DEFER_MPS_EXPORT / TS_REGISTRY_SHARD_DIR env-var lifecycle,
    same exit codes."""
    admitted = _batch_discover_and_admit(provision_only)
    if admitted is None:
        return  # active dir missing or empty INBOX — discovery short-circuits
    _batch_execute_with_telemetry(admitted, provision_only, max_parallel)
    _batch_archive_and_postprocess(admitted, provision_only)

def _parse_max_parallel(argv: list[str]) -> int:
    """Extract --max-parallel N from argv. Default 1 (sequential fast-path).

    Permanent first-class operational mode per the Phase 3 plan: the
    default keeps pre-Phase-3 sequential semantics for debugging /
    safe-mode / reproducibility / emergency recovery. Operators opt in
    to parallelism by passing `--max-parallel 2` (or 3, 5, etc.).
    """
    for i, a in enumerate(argv):
        if a == "--max-parallel":
            if i + 1 >= len(argv):
                raise SystemExit("--max-parallel requires an integer argument")
            try:
                n = int(argv[i + 1])
            except ValueError:
                raise SystemExit(f"--max-parallel requires an integer, got {argv[i+1]!r}")
            if n < 1:
                raise SystemExit(f"--max-parallel must be >= 1, got {n}")
            return n
    return 1


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/run_pipeline.py <DIRECTIVE_ID> | --all [--max-parallel N] [--provision-only] [--refresh]")
        sys.exit(1)

    arg = sys.argv[1]
    provision_only = "--provision-only" in sys.argv[2:]
    # --refresh: identity-preserving re-run of an existing directive (cointegration
    # pilot). Single-directive only; set by tools/refresh_cointegration.py.
    refresh = "--refresh" in sys.argv[2:]
    max_parallel = _parse_max_parallel(sys.argv[2:])

    try:
        initialize_state_directories()
        print("[ORCHESTRATOR] Initializing Startup Guardrails...")
        validate_inbox_directive_tokens()
        verify_tools_timestamp_guard(PROJECT_ROOT)
        enforce_run_schema(PROJECT_ROOT)
        detect_strategy_drift(PROJECT_ROOT)
        gate_registry_consistency()
        
        # Phase 10: Watchdog integration
        from tools.orchestration.run_watchdog import recover_stale_runs
        recover_stale_runs()
        
        # Phase 11: Directive Admission Recovery + stale-backup reconcile
        recover_partially_admitted_directives()
        reconcile_active_backup()

        verify_manifest_integrity(PROJECT_ROOT)
        verify_indicator_registry_sync(PROJECT_ROOT)

        print("[ORCHESTRATOR] Performing authoritative registry reconciliation sweep...")
        reconcile_registry()
        
        if arg == "--all":
            run_batch_mode(provision_only=provision_only, max_parallel=max_parallel)
            _report_data_freshness()
            print("\n[SUCCESS] Batch Pipeline Completed Successfully.")
        else:
            directive_id = arg.replace(".txt", "")
            directive_id = prepare_single_directive_for_execution(
                directive_id=directive_id,
                active_dir=ACTIVE_DIR,
                python_exe=PYTHON_EXE,
                run_command=run_command,
            )

            # Auto-Consistency Gate: hash alignment + approved marker
            enforce_signature_consistency(
                directive_id=directive_id,
                project_root=PROJECT_ROOT,
                active_dir=ACTIVE_DIR,
            )

            # Phase 1: Admission (Move from INBOX/ -> active_backup/ + marker)
            if not provision_only:
                admit_directive(directive_id)

            print(f"MASTER PIPELINE EXECUTION -- {directive_id}")
            run_single_directive(directive_id, provision_only=provision_only, refresh=refresh)

            if not provision_only:
                # Phase 2: Archive (Move from active_backup/ -> completed/ + move marker)
                archive_completed_directive(directive_id)

                print("\n[PIPELINE] Running Candidate Promotion (filter_strategies.py)...")
                try:
                    run_command([PYTHON_EXE, "tools/filter_strategies.py"], "Candidate Promotion")
                except Exception as e:
                    print(f"[WARN] Candidate promotion failed: {e}")

                print("\n[PIPELINE] Restoring hyperlinks in Excel artifacts...")
                try:
                    run_command([PYTHON_EXE, "tools/add_strategy_hyperlinks.py", "--target", "all"], "Hyperlinks")
                except Exception as e:
                    print(f"[WARN] Hyperlink restoration failed: {e}")

                # Format MPS + FSP to the operator's preferred tab structure.
                # See batch-mode block above for rationale + behavior.
                from config.path_authority import TRADE_SCAN_STATE as _TS_STATE
                print("\n[PIPELINE] Formatting MPS (Master_Portfolio_Sheet.xlsx)...")
                try:
                    run_command(
                        [PYTHON_EXE, "tools/format_excel_artifact.py",
                         "--file", str(_TS_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"),
                         "--profile", "portfolio"],
                        "Format MPS",
                    )
                except Exception as e:
                    print(f"[WARN] MPS formatting failed: {e}")
                print("\n[PIPELINE] Formatting FSP (Filtered_Strategies_Passed.xlsx)...")
                try:
                    run_command(
                        [PYTHON_EXE, "tools/format_excel_artifact.py",
                         "--file", str(_TS_STATE / "candidates" / "Filtered_Strategies_Passed.xlsx"),
                         "--profile", "strategy"],
                        "Format FSP",
                    )
                except Exception as e:
                    print(f"[WARN] FSP formatting failed: {e}")

                print("\n[PIPELINE] Regenerating run summary view...")
                try:
                    run_command([PYTHON_EXE, "tools/generate_run_summary.py", "--quiet"], "Run Summary")
                    print("[PIPELINE] run_summary.csv updated.")
                except Exception as e:
                    print(f"[WARN] Run summary generation failed: {e}")

                # Phase 4: dual-age regime alignment audit (warn-only, never blocks).
                # Audits regime_age_signal/regime_age_fill structural invariants +
                # HTF-quantization sanity. See tools/regime_alignment_guard.py.
                try:
                    run_command(
                        [PYTHON_EXE, "tools/regime_alignment_guard.py", directive_id],
                        "Regime Alignment Guard (warn)",
                    )
                except Exception as e:
                    print(f"[WARN] Regime alignment guard failed: {e}")

            _report_data_freshness()
            print("\n[SUCCESS] Pipeline Completed Successfully.")
    except PipelineError as err:
        sys.exit(map_pipeline_error(err))
    except Exception as err:
        wrapped = PipelineExecutionError(f"Unhandled pipeline error: {err}")
        sys.exit(map_pipeline_error(wrapped))
    finally:
        # Post-run reconcile: archive any PORTFOLIO_COMPLETE directives that
        # were stranded in active_backup/ by a fail-fast abort or prior crash.
        if not provision_only:
            try:
                reconcile_active_backup()
            except Exception as e:
                print(f"[WARN] Post-run reconcile failed: {e}")

if __name__ == "__main__":
    main()