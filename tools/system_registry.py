import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
import hashlib
from filelock import FileLock

from config.state_paths import RUNS_DIR, REGISTRY_DIR, STRATEGIES_DIR, SELECTED_DIR, POOL_DIR, QUARANTINE_DIR

PROJECT_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = REGISTRY_DIR / "run_registry.json"
LOCK_PATH = REGISTRY_PATH.with_suffix(".lock")

def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_registry_atomic(data: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    
    # Atomic rename (replace existing)
    if os.name == 'nt':
        if REGISTRY_PATH.exists():
            os.replace(tmp_path, REGISTRY_PATH)
        else:
            tmp_path.rename(REGISTRY_PATH)
    else:
        tmp_path.rename(REGISTRY_PATH)

def log_run_to_registry(run_id: str, status: str, directive_id: str):
    """
    Log a run into the master lifecycle ledger.
    Extracts the artifact_hash from the run_state.json if available.
    """
    # Try to extract the computed artifact_hash from run_state
    state_file = RUNS_DIR / run_id / "run_state.json"
    artifact_hash = None
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                artifact_hash = state_data.get("artifact_hash")
        except Exception:
            pass

    with FileLock(str(LOCK_PATH)):
        reg = _load_registry()

        # If the run already exists, update status and possibly hash. Otherwise create new tier: sandbox.
        if status == "complete":
            # Verification Guard: Ensure core artifacts exist physically
            run_dir = RUNS_DIR / run_id
            required = [
                run_dir / "manifest.json",
                run_dir / "data" / "results_tradelevel.csv",
                run_dir / "data" / "results_standard.csv",
                run_dir / "data" / "equity_curve.csv"
            ]
            if not all(p.exists() for p in required):
                print(f"[INTEGRITY] Run {run_id} missing core artifacts. Downgrading status to 'failed'.")
                status = "failed"

        if run_id in reg:
            reg[run_id]["status"] = status
            if artifact_hash and not reg[run_id].get("artifact_hash"):
                reg[run_id]["artifact_hash"] = artifact_hash
        else:
            reg[run_id] = {
                "run_id": run_id,
                "tier": "sandbox",
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "directive_hash": directive_id,
                "artifact_hash": artifact_hash
            }

        _save_registry_atomic(reg)

def get_active_portfolio_runs() -> set:
    """Scan strategies/ for portfolio_composition.json files and collect active dependencies."""
    strategies_dir = STRATEGIES_DIR
    if not strategies_dir.exists():
        return set()
        
    active_runs = set()
    for fname in ["portfolio_composition.json", "portfolio_metadata.json"]:
        for comp_file in strategies_dir.rglob(fname):
            try:
                with open(comp_file, "r") as f:
                    data = json.load(f)
                    run_ids = data.get("constituent_run_ids", [])
                    if isinstance(run_ids, list):
                        active_runs.update(run_ids)
            except Exception:
                continue

    # Also shield manually grouped static selections
    static_selections_path = POOL_DIR / "in_portfolio_selections.json"
    if static_selections_path.exists():
        try:
            with open(static_selections_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            selections = data.get("selections", [])
            if isinstance(selections, list):
                active_runs.update(selections)
        except Exception as e:
            print(f"[WARN] Could not parse static portfolio selections: {e}")

    return active_runs

def reconcile_registry() -> dict:
    """
    Startup sweep to ensure consistency between registry and physical disk.
    - Physical folder but missing from registry -> inject as sandbox.
    - In registry but physical folder missing -> mark invalid.
    - Portfolio requires missing dependency -> hard crash.
    
    Returns:
        dict: Mismatch details for callers (e.g., gates).
    """
    runs_dir = RUNS_DIR

    results = {
        "orphaned_on_disk": [],
        "missing_from_disk": [],
        "invalid_in_registry": []
    }

    # 1. Physical vs Registry (Across sandbox, candidate, and pool boundaries)
    physical_runs = set()
    for directory in [RUNS_DIR, SELECTED_DIR, POOL_DIR]: # Also check pool (completed/migrated runs)
        if directory.exists():
            for item in directory.iterdir():
                if item.is_dir() and (item / "data").exists():
                    physical_runs.add(item.name)
        elif directory == RUNS_DIR:
             # Runs dir must exist or we have no sandbox
             pass

    # 2. Load registry, compute mutations, and save — all under lock to prevent TOCTOU race.
    #    Filesystem moves (step 3) happen outside the lock since they don't touch the registry file.
    with FileLock(str(LOCK_PATH)):
        reg = _load_registry()
        dirty = False

        # Missing from registry
        for phys_id in physical_runs:
            if phys_id not in reg:
                print(f"[RECONCILE] Recovered orphaned physical run {phys_id} -> sandbox.")
                results["orphaned_on_disk"].append(phys_id)
                reg[phys_id] = {
                    "run_id": phys_id,
                    "tier": "sandbox",
                    "status": "complete", # Assume complete if it has a data folder
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "directive_hash": "recovered",
                    "artifact_hash": None
                }
                dirty = True

        # Build quarantine index once — runs intentionally archived by lifecycle cleanup.
        quarantine_runs_dir = QUARANTINE_DIR / "runs"
        quarantined_on_disk = set()
        if quarantine_runs_dir.exists():
            quarantined_on_disk = {p.name for p in quarantine_runs_dir.iterdir() if p.is_dir()}

        # Physically missing but in registry
        for run_id, data in list(reg.items()):
            if run_id not in physical_runs:
                current_status = data.get("status")

                # Run is in quarantine — intentionally archived, not broken.
                if run_id in quarantined_on_disk:
                    if current_status != "quarantined":
                        print(f"[RECONCILE] Registry entry {run_id} found in quarantine -> status corrected to quarantined.")
                        reg[run_id]["status"] = "quarantined"
                        dirty = True
                    results["invalid_in_registry"].append(run_id)
                    continue

                if current_status in ("invalid", "quarantined"):
                    results["invalid_in_registry"].append(run_id)
                    continue

                if not (runs_dir / run_id).exists():
                    print(f"[RECONCILE] Registry entry {run_id} missing physical folder -> marked invalid.")
                    results["missing_from_disk"].append(run_id)
                    reg[run_id]["status"] = "invalid"
                    dirty = True
            else:
                # Run IS physically present but registry says invalid — stale flag, restore it.
                if data.get("status") == "invalid":
                    print(f"[RECONCILE] Run {run_id} is physically present but marked invalid -> restored to complete.")
                    reg[run_id]["status"] = "complete"
                    dirty = True

        # Commit — still under lock, load + mutate + save is now atomic
        if dirty:
            _save_registry_atomic(reg)

    # 3. Candidate Location Alignment (Auto-Repair) — filesystem moves, no registry lock needed
    for run_id, data in reg.items():
        if data.get("tier") == "candidate" and data.get("status") == "complete":
            src = RUNS_DIR / run_id
            dst = SELECTED_DIR / run_id
            if src.exists() and not dst.exists():
                print(f"[RECONCILE] Detected candidate {run_id} in sandbox. Auto-repairing physical location...")
                try:
                    SELECTED_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                except Exception as e:
                    print(f"[ERROR] Auto-repair migration failed for {run_id}: {e}")

    # AUTO-CLEAN: remove newly-invalid AND quarantined run_ids from portfolio_metadata.json files.
    # Quarantined runs are permanently absent — any portfolio reference to them is stale.
    newly_invalid = set(results["missing_from_disk"])
    quarantined_run_ids = {r for r, d in reg.items() if d.get("status") == "quarantined"}
    runs_to_purge_from_metadata = newly_invalid | quarantined_run_ids
    if runs_to_purge_from_metadata:
        newly_invalid = runs_to_purge_from_metadata  # reuse variable for block below
    if newly_invalid:
        for meta_file in STRATEGIES_DIR.rglob("portfolio_metadata.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                original = meta.get("constituent_run_ids", [])
                cleaned = [r for r in original if r not in newly_invalid]
                if len(cleaned) != len(original):
                    meta["constituent_run_ids"] = cleaned
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=4)
                    removed = set(original) - set(cleaned)
                    print(f"[RECONCILE] Auto-cleaned stale run_ids {removed} from {meta_file}")
            except Exception as e:
                print(f"[RECONCILE] Warning: could not clean {meta_file}: {e}")

    # 2. Portfolio Dependency Check
    # Runs with status "quarantined" are intentionally archived by the lifecycle cleanup.
    # They are permanently absent from runs/ but their portfolio data is already captured
    # in portfolio artifacts (tradelevel.csv, equity_curve.csv). Not a consistency violation.
    active_portfolio_runs = get_active_portfolio_runs()
    for dep_id in active_portfolio_runs:
        dep_status = reg.get(dep_id, {}).get("status")
        if dep_status == "quarantined":
            continue  # intentionally archived — portfolio data already captured
        if dep_id not in physical_runs or dep_status == "invalid":
            raise RuntimeError(f"[FATAL] Consistency Violation: Portfolio heavily depends on missing/invalid run {dep_id}.")
            
    print("[RECONCILE] Registry alignment complete.")
    return results


def _get_directive_first_execution_timestamp(directive_id: str):
    """
    Return the earliest run creation timestamp for a directive.

    Primary source: run_registry.json
      - Filter entries where directive_hash == directive_id
      - Parse created_at, return the minimum

    Fallback (registry missing / empty / no matching entries):
      - Scan RUNS_DIR for run_state.json files with matching directive_id
      - Extract timestamp with priority:
          a) history[0]['timestamp']  — definitively the run creation time
          b) last_updated             — set at initialization
          c) run_state.json mtime     — last resort
      - Return the minimum across all matching runs

    Returns None if no runs found → treated as new directive, reset allowed.
    All exceptions are caught safely; missing data is skipped, never crashes.
    """
    # --- PRIMARY: run_registry.json ---
    registry_ts = None
    if REGISTRY_PATH.exists():
        try:
            reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            for entry in reg.values():
                if entry.get("directive_hash") != directive_id:
                    continue
                raw = entry.get("created_at", "")
                if not raw:
                    continue
                try:
                    ts = datetime.fromisoformat(raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if registry_ts is None or ts < registry_ts:
                        registry_ts = ts
                except Exception:
                    continue
        except Exception:
            pass

    if registry_ts is not None:
        return registry_ts

    # --- FALLBACK: scan RUNS_DIR for run_state.json ---
    fallback_ts = None
    if not RUNS_DIR.exists():
        return None

    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        rs_file = run_dir / "run_state.json"
        if not rs_file.exists():
            continue
        try:
            rs = json.loads(rs_file.read_text(encoding="utf-8"))
            if rs.get("directive_id") != directive_id:
                continue

            ts = None

            # Priority a: first history entry timestamp (run creation)
            history = rs.get("history", [])
            if history:
                raw = history[0].get("timestamp", "")
                if raw:
                    try:
                        raw = raw.rstrip("Z")
                        if "+" not in raw:
                            raw += "+00:00"
                        ts = datetime.fromisoformat(raw)
                    except Exception:
                        pass

            # Priority b: last_updated (set at initialization)
            if ts is None:
                raw = rs.get("last_updated", "")
                if raw:
                    try:
                        raw = raw.rstrip("Z")
                        if "+" not in raw:
                            raw += "+00:00"
                        ts = datetime.fromisoformat(raw)
                    except Exception:
                        pass

            # Priority c: filesystem mtime of run_state.json
            if ts is None:
                ts = datetime.fromtimestamp(rs_file.stat().st_mtime, tz=timezone.utc)

            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if fallback_ts is None or ts < fallback_ts:
                    fallback_ts = ts

        except Exception:
            continue

    return fallback_ts
