
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
            
            # We only check completed runs or those with artifacts
            artifacts = manifest.get("artifacts", {})
            for name, expected_hash in artifacts.items():
                artifact_path = run_folder / "data" / name
                if not artifact_path.exists():
                    corrupted.append(f"{run_folder.name}: Missing artifact {name}")
                    continue
                
                # Check hash
                actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    corrupted.append(f"{run_folder.name}: Hash mismatch for {name}")
                    
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


def verify_directive_uniqueness_guard(directive_id: str):
    """Guardrail: Prevent reuse of already executed directive names."""
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
            if item.name.startswith("_"):
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

    Plan: H2_ENGINE_PROMOTION_PLAN.md Phase 5b (single-ABI on v1_5_9).
    """
    if provision_only:
        return False  # provision-only flow never dispatches basket execution

    path = _find_admitted_directive_path(directive_id)
    if path is None:
        return False  # caller will surface the missing-directive error

    from tools.basket_schema import is_basket_directive
    from tools.pipeline_utils import parse_directive

    try:
        parsed = parse_directive(path)
    except Exception:
        return False  # parsing problems surface in the existing flow
    if not is_basket_directive(parsed):
        return False

    # ---- Basket dispatch path ----
    from tools.basket_pipeline import run_basket_pipeline
    from tools.basket_vault import write_basket_vault
    from tools.portfolio_evaluator import append_basket_row_to_research_csv

    print(f"[BASKET] Phase 5b dispatch: {directive_id}")
    print(f"[BASKET] Directive: {path}")
    print(f"[BASKET] basket_id={parsed['basket']['basket_id']} "
          f"legs={[l['symbol'] for l in parsed['basket']['legs']]}")

    # Phase 5c: load real per-leg OHLC + USD_SYNTH compression_5d factor and
    # build ContinuousHoldStrategy per leg. Falls back to synthetic-mode
    # (passthrough strategy + zero-gate compression) if data loading fails
    # — useful for smoke testing without real RESEARCH layer access.
    leg_data, leg_strategies, data_mode = _load_basket_leg_inputs(parsed)
    print(f"[BASKET] Data mode: {data_mode}")
    registry_path = PROJECT_ROOT / "governance" / "recycle_rules" / "registry.yaml"

    result = run_basket_pipeline(
        parsed, leg_data, leg_strategies,
        recycle_registry_path=registry_path,
    )

    # Write basket vault snapshot (Phase 6 layout). Folder structure:
    #   DRY_RUN_VAULT/baskets/<directive_id>/<basket_id>/  (write_basket_vault adds the inner basket_id dir)
    from config.path_authority import DRY_RUN_VAULT as _DRY_RUN_VAULT
    from tools.basket_vault import BasketVaultPayload
    vault_parent = _DRY_RUN_VAULT / "baskets" / directive_id
    vault_parent.mkdir(parents=True, exist_ok=True)
    trades_total = sum(len(t) for t in result.per_leg_trades.values())

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
    vault_dir = None  # may stay None if vault write fails — Path B block handles it
    try:
        vault_dir = write_basket_vault(vault_parent, payload)
        print(f"[BASKET] Vault written: {vault_dir}")
    except Exception as exc:
        print(f"[BASKET] WARN vault write failed: {exc}")

    # ---- Path B / Phase 5b.2 — discoverable artifacts in the standard layout ----
    # Goal: a basket run shows up alongside per-symbol runs in:
    #   * TradeScan_State/runs/<run_id>/data/results_tradelevel.csv
    #   * TradeScan_State/backtests/<directive_id>_<basket_id>/raw/results_tradelevel.csv
    #   * TradeScan_State/registry/run_registry.json
    #   * Master_Portfolio_Sheet.xlsx (Baskets sheet)
    # Without this, basket runs hide in DRY_RUN_VAULT/baskets/ and a research-
    # only CSV — the user's principle: "results must be discoverable later,
    # not just produced." The legacy basket_runs.csv writer is preserved during
    # the transition (see header comment on that file).
    run_id = None
    try:
        from tools.basket_ledger import basket_result_to_tradelevel_df
        from tools.portfolio.basket_ledger_writer import append_basket_row_to_mps
        from tools.pipeline_utils import generate_run_id
        from config.path_authority import TRADE_SCAN_STATE
        from datetime import datetime, timezone

        basket_id = parsed["basket"]["basket_id"]
        run_id, _content_hash = generate_run_id(path, symbol=basket_id)
        backtests_dir = TRADE_SCAN_STATE / "backtests" / f"{directive_id}_{basket_id}" / "raw"
        backtests_dir.mkdir(parents=True, exist_ok=True)
        runs_dir = TRADE_SCAN_STATE / "runs" / run_id / "data"
        runs_dir.mkdir(parents=True, exist_ok=True)

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

        # Phase 5b.3a — fill the per-window report stack (results_standard,
        # results_risk, results_yearwise, results_basket, metrics_glossary,
        # bar_geometry, metadata/run_metadata, REPORT_<id>.md). Without
        # these, the basket backtests/ folder has only `raw/results_tradelevel.csv`
        # while per-symbol folders have ~7 files. This block closes that gap.
        try:
            from tools.basket_report import (
                write_per_window_report_artifacts,
                write_basket_strategy_card,
            )
            from engine_abi.v1_5_9 import ENGINE_VERSION as _engine_version
            stake = float(parsed.get("basket", {}).get("initial_stake_usd", 1000.0))
            written = write_per_window_report_artifacts(
                out_dir=backtests_dir.parent,  # parent of raw/ is the directive folder
                run_id=run_id,
                directive_id=directive_id,
                basket_result=result,
                df_trades=df_trades,
                parsed_directive=parsed,
                engine_version=str(_engine_version),
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
                engine_version=str(_engine_version),
            )
            print(f"[BASKET] STRATEGY_CARD.md: {card_path.name}")
        except Exception as exc:
            print(f"[BASKET] WARN per-window report emit failed: {exc}")

        # run_registry.json entry (basket-flavored). Direct write avoids
        # log_run_to_registry's run_state.json dependency, which doesn't
        # apply to the basket short-circuit path.
        from tools.system_registry import _load_registry, _save_registry_atomic
        reg = _load_registry()
        if run_id not in reg:
            reg[run_id] = {
                "run_id": run_id,
                "tier": "basket",
                "status": "BASKET_COMPLETE",
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "directive_id": directive_id,
                "directive_hash": _content_hash,
                "artifact_hash": "",  # basket vault hash not yet schematized; Phase 5b.3
                "basket_id": basket_id,
                "execution_mode": "basket",
            }
            _save_registry_atomic(reg)
            print(f"[BASKET] run_registry entry: {run_id}")

        # Append to MPS Baskets sheet (the actual MPS file users open).
        try:
            vault_path_str = ""
            if vault_dir is not None:
                try:
                    vault_path_str = str(vault_dir.relative_to(_DRY_RUN_VAULT.parent))
                except (ValueError, AttributeError):
                    vault_path_str = str(vault_dir)
            mps_path = append_basket_row_to_mps(
                result, run_id=run_id, directive_id=directive_id,
                backtests_path=str(backtests_csv.relative_to(TRADE_SCAN_STATE)),
                vault_path=vault_path_str,
                df_trades=df_trades,   # Phase 5d.1 fix: writer uses converter's
                                       # computed pnl_usd so force_close trades
                                       # contribute correctly to final_realized_usd
            )
            print(f"[BASKET] MPS Baskets row: {mps_path}")
        except Exception as exc:
            print(f"[BASKET] WARN MPS Baskets append failed: {exc}")

    except Exception as exc:
        # Path B failure must NOT swallow the run — log + continue. The
        # vault + research CSV still landed; future analysis can recover.
        import traceback
        print(f"[BASKET] WARN Path B (standard artifacts) failed: {exc}")
        print(f"[BASKET]   {traceback.format_exc().splitlines()[-1]}")

    # Append basket row to legacy research CSV (Phase 5b.1 — slated for
    # retirement after the Baskets MPS sheet stabilizes; review 2026-06-14).
    try:
        csv_path = append_basket_row_to_research_csv(result, directive_id=directive_id)
        print(f"[BASKET] Research row appended (LEGACY): {csv_path}")
    except Exception as exc:
        print(f"[BASKET] WARN legacy research CSV append failed: {exc}")

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
    try:
        from tools.basket_data_loader import load_basket_leg_data
        from tools.recycle_strategies import ContinuousHoldStrategy
        leg_data = load_basket_leg_data(symbols, start_date, end_date)
        leg_strategies = {
            leg["symbol"]: ContinuousHoldStrategy(
                symbol=leg["symbol"],
                direction=+1 if leg["direction"] == "long" else -1,
            )
            for leg in parsed["basket"]["legs"]
        }
        return leg_data, leg_strategies, "real"
    except Exception as exc:
        print(f"[BASKET] WARN real data load failed ({exc}); falling back to synthetic mode.")
        leg_data = _synthetic_leg_data(parsed)
        leg_strategies = {
            leg["symbol"]: _PassthroughStrategy(leg["symbol"])
            for leg in parsed["basket"]["legs"]
        }
        return leg_data, leg_strategies, "synthetic"


def run_single_directive(directive_id, provision_only=False):
    """Execution logic for a single directive."""
    ctx = None
    # 1.1 Uniqueness Check
    verify_directive_uniqueness_guard(directive_id)

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
    """Read freshness_index.json (via data_root symlink) and print stale-only report.
    Uses Path.exists() which follows symlinks — returns False for broken links.
    Never raises.
    """
    try:
        index_path = PROJECT_ROOT / "data_root" / "freshness_index.json"
        if not index_path.exists():
            print(
                "[WARN] freshness_index.json missing — "
                "data ingestion may have failed or not yet run. "
                "Run build_freshness_index in DATA_INGRESS to generate it."
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


def run_batch_mode(provision_only=False):
    """Sequential Batch Execution."""
    active_dir = PROJECT_ROOT / "backtest_directives" / "INBOX"
    completed_dir = PROJECT_ROOT / "backtest_directives" / "completed"
    
    _assert_pipeline_idle()

    if not active_dir.exists():
        print(f"[BATCH] Active directory not found: {active_dir}")
        return

    directives = prepare_batch_directives_for_execution(
        active_dir=active_dir,
        python_exe=PYTHON_EXE,
        run_command=run_command,
    )
    if not directives:
        print("[BATCH] No directives found in active/")
        return

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

    print(f"[BATCH] Admitted {len(admitted)} directive(s). Starting sequential execution...")

    # --- PHASE 2: EXECUTION (sequential — Invariant #26) ---
    # Direct loop — ProcessPoolExecutor(1) was pure overhead (subprocess spawn
    # + IPC for zero parallelism). Fail-fast on first error. A 15s cooldown
    # between directives (Invariant #26) gives ledger writers, Excel file
    # handles, and sweep-registry flushes time to settle before the next run.
    import time as _time

    INTER_DIRECTIVE_COOLDOWN_SECONDS = 15
    for idx, d_id in enumerate(admitted):
        if idx > 0:
            print(
                f"[BATCH] Cooldown: sleeping {INTER_DIRECTIVE_COOLDOWN_SECONDS}s "
                f"before next directive (Invariant #26)..."
            )
            _time.sleep(INTER_DIRECTIVE_COOLDOWN_SECONDS)
        try:
            run_single_directive(d_id, provision_only)
            print(f"[BATCH] Completed: {d_id}")
        except PipelineError:
            print(f"[BATCH] FAILED: {d_id}")
            print("[FAIL-FAST] Stopping batch execution.")
            raise
        except Exception as e:
            print(f"[BATCH] FAILED: {d_id} - {e}")
            print("[FAIL-FAST] Stopping batch execution.")
            raise PipelineExecutionError(
                f"Batch directive failed: {d_id}: {e}",
                directive_id=d_id,
            ) from e

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

    print("\n[BATCH] All directives processed successfully.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/run_pipeline.py <DIRECTIVE_ID> | --all")
        sys.exit(1)

    arg = sys.argv[1]
    provision_only = "--provision-only" in sys.argv[2:]

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
            run_batch_mode(provision_only=provision_only)
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
            run_single_directive(directive_id, provision_only=provision_only)

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