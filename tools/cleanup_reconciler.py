import sys
import shutil
import argparse
import time
import json
from datetime import datetime, timezone
from pathlib import Path

# Project Paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import (
    RUNS_DIR,
    BACKTESTS_DIR,
    STRATEGIES_DIR,
    SELECTED_DIR,
    POOL_DIR,
    CANDIDATE_FILTER_PATH,
    MASTER_FILTER_PATH,
    RUN_DIRS_IN_LOOKUP_ORDER,
    resolve_run_dir,
)

RUNS_ROOT = RUNS_DIR
BACKTESTS_ROOT = BACKTESTS_DIR
STRATEGIES_ROOT = STRATEGIES_DIR
CANDIDATES_ROOT = SELECTED_DIR

from tools.system_registry import _load_registry, get_active_portfolio_runs, reconcile_registry

def get_run_ui_folder(run_id: str) -> Path:
    """Read run_metadata.json to find the corresponding UI view in backtests/"""
    meta_path = RUNS_ROOT / run_id / "data" / "run_metadata.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            strat = data.get("strategy_name")
            if strat:
                return BACKTESTS_ROOT / strat
        except Exception:
            pass
    return None

def main():
    parser = argparse.ArgumentParser(description="Extremely Safe Cleanup Sweep")
    parser.add_argument("--execute", action="store_true", help="Execute planned deletions")
    args = parser.parse_args()

    print("--- STARTING REGISTRY-GOVERNED CLEANUP ---")
    
    # 1. Startup Reconciliation (Always enforce state alignment before cleanup)
    reconcile_registry()
    
    reg_data = _load_registry()
    active_portfolios = get_active_portfolio_runs()
    
    runs_to_delete = []
    ui_views_to_delete = []

    # Load protected run_ids from the append-only ledgers.
    #
    # Previously this guard only protected candidate_status == "BURN_IN", which
    # silently stepped past canonical is_current=1 WATCH/CORE/RESERVE/
    # PROFILE_UNRESOLVED runs that had not yet been promoted into
    # portfolio.yaml. During the 2026-04-21 parallel __E158 re-run window the
    # reconciler flagged five is_current=1 runs for deletion (four 54-series
    # MACDX_S22 P01..P04 variants plus the 05_PORT v1.5.8 baseline). Every
    # sweep test and every __Exxx re-run re-creates that scenario.
    #
    # Protection rules (either alone is sufficient):
    #   1. is_current == 1 in FSP or SMF — the ledger's canonical flag.
    #   2. candidate_status in the non-terminal set — defence in depth for
    #      write-lag windows and pre-supersede rows where is_current is NaN.
    #
    # Fail-closed: if the guard cannot be loaded we refuse to proceed. A
    # silent unguarded cleanup would orphan ledger pointers.
    _PROTECTED_STATUSES = {
        "CORE",
        "BURN_IN",
        "WATCH",
        "RESERVE",
        "PROFILE_UNRESOLVED",
    }
    _protected_run_ids: set[str] = set()
    for _lpath, _label in [
        (CANDIDATE_FILTER_PATH, "FSP"),
        (MASTER_FILTER_PATH, "SMF"),
    ]:
        if not _lpath.exists():
            continue
        try:
            import pandas as _pd
            _df = _pd.read_excel(_lpath)
            if "run_id" not in _df.columns:
                continue
            _rid = _df["run_id"].astype(str)
            if "is_current" in _df.columns:
                _cur_mask = _df["is_current"].fillna(0).astype(int) == 1
                _protected_run_ids.update(_rid[_cur_mask].tolist())
            if "candidate_status" in _df.columns:
                _stat_mask = (
                    _df["candidate_status"].astype(str).str.strip().isin(_PROTECTED_STATUSES)
                )
                _protected_run_ids.update(_rid[_stat_mask].tolist())
        except Exception as _e:
            raise RuntimeError(
                f"[GUARD] Could not load protection ledger {_label} at {_lpath}: {_e}\n"
                f"Refusing to proceed — running cleanup without the canonical-run "
                f"guard would delete is_current=1 rows and orphan ledger pointers. "
                f"Fix the ledger and rerun."
            )

    # Drop any sentinel / blank run_ids that slipped in from NaN cells.
    _protected_run_ids.discard("")
    _protected_run_ids.discard("nan")
    print(f"[GUARD] {len(_protected_run_ids)} canonical run(s) protected from cleanup")

    # 2. Identify deletable runs based STRICTLY on the plan logic:
    # IF tier == "sandbox" AND status in {complete, aborted, failed} AND run_id not referenced
    # AND run_id is not ledger-protected (is_current=1 or non-terminal candidate_status)
    # ABORTED/failed runs are eligible but must be >1 hour old (forensic cool-down).
    # This prevents deleting runs the watchdog just marked or that need investigation.
    _deletable_statuses = {"complete", "aborted", "failed"}
    _cooldown_statuses = {"aborted", "failed"}  # require age check
    _COOLDOWN_SECONDS = 3600  # 1 hour
    _now_ts = datetime.now(timezone.utc).timestamp()

    for run_id, record in reg_data.items():
        status = record.get("status", "")
        if record.get("tier") == "sandbox" and status in _deletable_statuses:
            if run_id not in active_portfolios:
                if run_id in _protected_run_ids:
                    print(f"  [PROTECTED] {run_id} — ledger-canonical (is_current or non-terminal status), skipping")
                    continue
                # Cool-down guard for aborted/failed: check run_state.json timestamp
                if status in _cooldown_statuses:
                    state_file = RUNS_ROOT / run_id / "run_state.json"
                    if state_file.exists():
                        try:
                            sd = json.loads(state_file.read_text(encoding="utf-8"))
                            last_ts = sd.get("last_transition", "")
                            if last_ts:
                                run_age = _now_ts - datetime.fromisoformat(
                                    last_ts.replace("Z", "+00:00")
                                ).timestamp()
                                if run_age < _COOLDOWN_SECONDS:
                                    print(f"  [COOLDOWN] {run_id} — {status} {run_age:.0f}s ago, skipping (min {_COOLDOWN_SECONDS}s)")
                                    continue
                        except Exception:
                            pass  # Can't parse timestamp — allow deletion
                runs_to_delete.append(run_id)
                ui_folder = get_run_ui_folder(run_id)
                if ui_folder and ui_folder.exists() and str(ui_folder) not in ui_views_to_delete:
                    ui_views_to_delete.append(str(ui_folder))
                    
    # 3. Execution
    if not runs_to_delete:
        print("[PASS] No sandbox runs eligible for deletion.")
        sys.exit(0)
        
    # Resolve each flagged run to its current physical location. A sandbox-tier
    # run can live in RUNS_DIR (fresh) or POOL_DIR (migrated post-Master-Filter)
    # — hardcoding RUNS_DIR here caused silent no-op deletions where the
    # registry row was purged but the on-disk folder stayed. resolve_run_dir
    # is the single source of truth for "where does this run live now".
    resolved_run_paths: dict[str, Path] = {}
    for r_id in runs_to_delete:
        try:
            resolved_run_paths[r_id] = resolve_run_dir(r_id, require_data=False)
        except FileNotFoundError:
            resolved_run_paths[r_id] = None  # on-disk folder already gone

    print(f"[PLAN] {len(runs_to_delete)} atomic runs flagged for deletion.")
    for r_id in runs_to_delete:
        target = resolved_run_paths[r_id]
        if target is None:
            print(f"  - DELETE <registry-only> {r_id} (no on-disk folder)")
        else:
            try:
                rel = target.relative_to(PROJECT_ROOT.parent)
            except ValueError:
                rel = target
            print(f"  - DELETE {rel}/")

    for ui_view in ui_views_to_delete:
        try:
            rel_view = Path(ui_view).relative_to(PROJECT_ROOT)
        except ValueError:
            rel_view = ui_view
        print(f"  - DELETE {rel_view}/ (Disposable UI View)")

    def is_path_safe(p: Path) -> bool:
        """Strict physical guardrail for filesystem deletions."""
        p_abs = p.resolve()

        # 1. Must NOT be a system-critical folder
        forbidden = ["strategies", "candidates", "registry", "tools", "data_access", "waiting"]
        for part in p_abs.parts:
            if part.lower() in forbidden:
                return False

        # 2. Must be inside an allowed cleanup scope.
        #    RUN_DIRS_IN_LOOKUP_ORDER covers every location a sandbox-tier run
        #    can physically reside (runs/, sandbox/, candidates/); BACKTESTS_ROOT
        #    covers disposable UI views.
        allowed_scopes = [d.resolve() for d in RUN_DIRS_IN_LOOKUP_ORDER]
        allowed_scopes.append(BACKTESTS_ROOT.resolve())
        in_scope = any(scope in p_abs.parents for scope in allowed_scopes)

        return in_scope

    if args.execute:
        print("\n[EXECUTE] Removing files...")

        for r_id in runs_to_delete:
            r_path = resolved_run_paths[r_id]

            if r_path is None:
                # Nothing on disk — just drop the registry row.
                reg_data.pop(r_id, None)
                print(f"  [REGISTRY-ONLY] {r_id} (no folder found)")
                continue

            if not is_path_safe(r_path):
                print(f"  [ABORT] Boundary violation detected for {r_path}")
                raise RuntimeError(f"CRITICAL BOUNDARY VIOLATION: {r_path}")

            if r_path.exists():
                shutil.rmtree(r_path)
                try:
                    rel = r_path.relative_to(PROJECT_ROOT.parent)
                except ValueError:
                    rel = r_path
                print(f"  [DELETED] {rel}/")

            # Pop from registry to keep it clean
            reg_data.pop(r_id, None)
            
        for ui_view in ui_views_to_delete:
            ui_path = Path(ui_view)
            
            if not is_path_safe(ui_path):
                print(f"  [SKIP] Boundary violation for disposable view: {ui_path}")
                continue

            if ui_path.exists():
                shutil.rmtree(ui_path)
                try:
                    disp = ui_path.relative_to(PROJECT_ROOT)
                except ValueError:
                    disp = ui_path
                print(f"  [DELETED] {disp}/")
                
        # Persist cleaned registry
        from tools.system_registry import _save_registry_atomic
        _save_registry_atomic(reg_data)
        print("[SUCCESS] Cleanup and Registry Purge Complete.")
    else:
        print("\n[INFO] Dry-run complete. Use --execute to apply.")

if __name__ == "__main__":
    main()
