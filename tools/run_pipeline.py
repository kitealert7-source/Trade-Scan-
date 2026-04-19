
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


def verify_tools_timestamp_guard(project_root: Path):
    """Guardrail: Ensure no protected tools were modified after manifest generation."""
    manifest_path = project_root / "tools" / "tools_manifest.json"
    if not manifest_path.exists():
        return

    manifest_mtime = manifest_path.stat().st_mtime
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            
        file_hashes = manifest.get("file_hashes", {})
        for filename in file_hashes:
            # Resolve relative to PROJECT_ROOT as per hardening scope
            filepath = project_root / filename
            # Fallback: maintain compatibility with current manifest (contained in 'tools/')
            if not filepath.exists():
                filepath = project_root / "tools" / filename
                
            if filepath.exists():
                if filepath.stat().st_mtime > manifest_mtime:
                    raise PipelineExecutionError(
                        f"Tool modified after manifest generation: {filename}. "
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

def _announce_run_engine(directive_id: str) -> None:
    """Print the resolved engine version + an early warning when a strategy
    defines check_partial_exit but the engine pin is not v1.5.7.

    Stage1 has a hard guard (tools/run_stage1.py) that fail-fasts if partial
    legs make it out of the engine under a non-partial emitter. This helper
    is the softer upstream counterpart: it fires before any stage runs, so
    operators see the mismatch immediately rather than deep into Stage1.
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
    if "def check_partial_exit" in source and engine_ver != "1.5.7":
        print(
            f"[WARN] Strategy {directive_id} defines check_partial_exit but "
            f"engine is v{engine_ver} (not v1.5.7). Partial legs will be "
            f"blocked by the Stage1 fail-fast guard. "
            f"Re-run with ENGINE_VERSION_OVERRIDE=v1_5_7 to enable partials."
        )


def run_single_directive(directive_id, provision_only=False):
    """Execution logic for a single directive."""
    ctx = None
    # 1.1 Uniqueness Check
    verify_directive_uniqueness_guard(directive_id)

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