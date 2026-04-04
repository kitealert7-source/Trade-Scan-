import os
import json
import hashlib
import sys
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.state_paths import RUNS_DIR, REGISTRY_DIR, STRATEGIES_DIR, ARCHIVE_DIR, QUARANTINE_DIR, BACKTESTS_DIR, SELECTED_DIR, POOL_DIR, resolve_base_strategy_dir
from config.status_enums import PORTFOLIO_BLOCKED_STATUSES, RUN_ABORTED
STRICT_MODE = True # Any error makes overall status RED


def _build_quarantine_index():
    """Scan quarantine once, return {run_id: path} for all quarantined runs."""
    index = {}
    if not QUARANTINE_DIR.exists():
        return index
    for entry in QUARANTINE_DIR.iterdir():
        if not entry.is_dir():
            continue
        # quarantine/runs/{run_id} (permanent quarantine)
        if entry.name == "runs":
            for run_dir in entry.iterdir():
                if run_dir.is_dir():
                    index[run_dir.name] = run_dir
        else:
            # quarantine/{timestamp}_cleanup/runs/{run_id}
            runs_sub = entry / "runs"
            if runs_sub.exists():
                for run_dir in runs_sub.iterdir():
                    if run_dir.is_dir():
                        index.setdefault(run_dir.name, run_dir)
    return index


# Built once per preflight invocation (module-level lazy singleton)
_quarantine_index = None

def _get_quarantine_index():
    global _quarantine_index
    if _quarantine_index is None:
        _quarantine_index = _build_quarantine_index()
    return _quarantine_index


def resolve_run_location(run_id: str):
    """Returns (tier, path) for a run_id.

    Search order:
      1. RUNS_DIR      → ("runs", path)
      2. POOL_DIR      → ("sandbox", path)
      3. quarantine index → ("quarantine", path)
      4. not found      → (None, None)
    """
    p = RUNS_DIR / run_id
    if p.exists():
        return ("runs", p)
    p = POOL_DIR / run_id
    if p.exists():
        return ("sandbox", p)
    q_index = _get_quarantine_index()
    if run_id in q_index:
        return ("quarantine", q_index[run_id])
    return (None, None)


def get_hash(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()

class PreflightCheck:
    def __init__(self):
        self.stats = {"GREEN": 0, "YELLOW": 0, "RED": 0}
        self.results = {}

    def report(self, category, status, message):
        self.stats[status] += 1
        if category not in self.results: self.results[category] = []
        self.results[category].append((status, message))

    def run(self):
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print(f"TRADE_SCAN PREFLIGHT CHECK - {os.name.upper()} - {Path.cwd()}")
        print("-" * 26)

        # Step 1: Root Integrity
        self._check_root()
        # Step 2 & 3: Runs & Manifests
        self._check_runs()
        # Step 4: Registry
        self._check_registry()
        # Step 5: Portfolios
        self._check_portfolios()
        # Step 5b: Ledger Health (blocked statuses)
        self._check_ledger_health()
        # Step 5c: Stale ABORTED runs
        self._check_aborted_runs()
        # Step 6: Strategy Drift
        self._check_strategy_drift()
        # Step 7: Archive Sanity
        self._check_archives()
        # Step 8: Guardrails Presence
        self._check_guardrails()
        # Step 9: Execution Contract
        self._check_execution_contract()

        self._print_summary()

    def _check_root(self):
        required = [RUNS_DIR, STRATEGIES_DIR, REGISTRY_DIR, ARCHIVE_DIR, QUARANTINE_DIR]
        missing = [str(r) for r in required if not r.exists()]
        if missing:
            self.report("ROOT", "RED", f"Missing critical directories: {missing}")
        else:
            self.report("ROOT", "GREEN", "All critical directories present.")

    def _check_runs(self):
        if not RUNS_DIR.exists(): return
        
        red_count = 0
        corrupt_count = 0
        total = 0
        for run_folder in RUNS_DIR.iterdir():
            if not run_folder.is_dir(): continue
            if "_" in run_folder.name: continue
            total += 1
            
            # Step 2: Schema
            required = ["data", "manifest.json", "run_state.json"]
            missing = [r for r in required if not (run_folder / r).exists()]
            if missing:
                red_count += 1
                continue

            # Step 3: Manifest Hash
            m_path = run_folder / "manifest.json"
            try:
                manifest = json.loads(m_path.read_text(encoding="utf-8"))
                artifacts = manifest.get("artifacts", {})
                for name, expected in artifacts.items():
                    p = run_folder / "data" / name
                    if not p.exists() or get_hash(p) != expected:
                        corrupt_count += 1
                        break
            except Exception:
                corrupt_count += 1

        if red_count > 0:
            self.report("RUNS", "RED", f"{red_count} runs failed schema validation.")
        elif corrupt_count > 0:
            self.report("RUNS", "RED", f"{corrupt_count} runs failed manifest hash verification.")
        else:
            self.report("RUNS", "GREEN", f"All {total} run containers valid and verified.")

    def _check_registry(self):
        reg_path = REGISTRY_DIR / "run_registry.json"
        if not reg_path.exists():
            self.report("REGISTRY", "RED", "Registry file missing.")
            return

        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))

            # Disk scan — all physical locations where runs can exist
            runs_disk = set(p.name for p in RUNS_DIR.iterdir() if p.is_dir())
            sandbox_disk = set(p.name for p in POOL_DIR.iterdir() if p.is_dir()) if POOL_DIR.exists() else set()
            candidate_disk = set(p.name for p in SELECTED_DIR.iterdir() if p.is_dir())
            all_disk = runs_disk | sandbox_disk | candidate_disk

            reg_ids = set(reg.keys())

            # 1. Orphans (On disk but not in registry)
            # Filter out directive state folders (contain underscores) and known non-run dirs
            non_run_dirs = {"archive"}
            orphans = [o for o in (all_disk - reg_ids) if "_" not in o and o not in non_run_dirs]

            if orphans:
                self.report("REGISTRY", "RED", f"DISK_NOT_IN_REGISTRY: {orphans[:3]}...")

            # 2. Missing (In registry but not on disk — tier-aware resolution)
            missing = []
            quarantine_orphans = []
            for rid, entry in reg.items():
                status = entry.get("status")
                if status == "invalid":
                    continue

                tier, _path = resolve_run_location(rid)

                if status == "quarantined":
                    # Quarantined in registry — verify it actually exists in quarantine
                    if tier != "quarantine":
                        quarantine_orphans.append(rid)
                    continue

                if tier is None:
                    missing.append(rid)

            if missing:
                self.report("REGISTRY", "RED", f"REGISTRY_RUN_MISSING_ON_DISK: {missing[:3]}...")
            if quarantine_orphans:
                self.report("REGISTRY", "YELLOW", f"QUARANTINED_BUT_NOT_FOUND: {quarantine_orphans[:3]}...")

            if not orphans and not missing and not quarantine_orphans:
                self.report("REGISTRY", "GREEN", "Registry and disk are aligned per tier.")
        except Exception as e:
            self.report("REGISTRY", "RED", f"Error reading registry: {e}")

    def _check_portfolios(self):
        if not STRATEGIES_DIR.exists(): return

        missing_ids = set()
        quarantined_ids = set()
        portfolio_count = 0
        for p_file in STRATEGIES_DIR.rglob("portfolio_metadata.json"):
            portfolio_count += 1
            try:
                data = json.loads(p_file.read_text(encoding="utf-8"))
                for rid in data.get("constituent_run_ids", []):
                    tier, _path = resolve_run_location(rid)
                    if tier is None:
                        missing_ids.add(rid)
                    elif tier == "quarantine":
                        quarantined_ids.add(rid)
            except Exception: continue

        if missing_ids:
            self.report("PORTFOLIOS", "RED", f"Missing dependencies for {len(missing_ids)} runs.")
        if quarantined_ids:
            self.report("PORTFOLIOS", "YELLOW", f"{len(quarantined_ids)} portfolio deps in quarantine (degraded).")
        if not missing_ids and not quarantined_ids:
            self.report("PORTFOLIOS", "GREEN", f"{portfolio_count} portfolios verified for dependencies.")

    def _check_ledger_health(self):
        """Flag strategies with blocked portfolio_status (e.g. PROFILE_UNRESOLVED).

        Also fails RED if the ledger exists but cannot be read (locked, corrupt,
        partial write) — a readable authoritative ledger is a hard requirement.
        """
        ledger_path = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"
        if not ledger_path.exists():
            return  # No ledger yet — nothing to check
        try:
            import pandas as pd
            df = pd.read_excel(ledger_path)
        except PermissionError:
            self.report("LEDGER", "RED",
                        f"Ledger locked — cannot read: {ledger_path.name} (close Excel or wait for pipeline)")
            return
        except Exception as e:
            self.report("LEDGER", "RED",
                        f"Ledger unreadable (corrupt/partial write?): {type(e).__name__}: {e}")
            return
        if "portfolio_status" not in df.columns or "portfolio_id" not in df.columns:
            return
        blocked = df[df["portfolio_status"].astype(str).isin(PORTFOLIO_BLOCKED_STATUSES)]
        if not blocked.empty:
            ids = blocked["portfolio_id"].astype(str).tolist()
            statuses = blocked["portfolio_status"].astype(str).tolist()
            detail = ", ".join(f"{sid}={st}" for sid, st in zip(ids, statuses))
            self.report("LEDGER", "RED",
                        f"{len(blocked)} strategy(ies) in blocked status: {detail}")
        else:
            self.report("LEDGER", "GREEN", "All ledger entries have valid portfolio_status.")

    def _check_aborted_runs(self):
        """Flag ABORTED runs that need cleanup or investigation."""
        if not RUNS_DIR.exists():
            return
        aborted = []
        for run_folder in RUNS_DIR.iterdir():
            if not run_folder.is_dir():
                continue
            state_file = run_folder / "run_state.json"
            if not state_file.exists():
                continue
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if data.get("current_state") == RUN_ABORTED:
                    reason = data.get("abort_reason", "unknown")
                    aborted.append(f"{run_folder.name} (reason={reason})")
            except Exception:
                continue
        if aborted:
            self.report("RUNS", "YELLOW",
                        f"{len(aborted)} ABORTED run(s) pending cleanup: {aborted[:3]}{'...' if len(aborted) > 3 else ''}")

    def _check_strategy_drift(self):
        if not STRATEGIES_DIR.exists(): return
        
        drift = []
        for item in STRATEGIES_DIR.iterdir():
            if item.is_file() and item.name != "Master_Portfolio_Sheet.xlsx":
                drift.append(item.name)
            elif item.is_dir() and not item.name.startswith("_"):
                has_metadata = (item / "portfolio_metadata.json").exists() or (item / "portfolio_evaluation" / "portfolio_metadata.json").exists()
                if not has_metadata and not any(item.glob("*.py")):
                    drift.append(item.name)
                    
        if drift:
            self.report("STRATEGIES", "YELLOW", f"Unexpected content in strategies/: {drift[:3]}")
        else:
            self.report("STRATEGIES", "GREEN", "Strategy directory is clean.")

    def _check_archives(self):
        paths = {
            "legacy": ARCHIVE_DIR / "legacy_runs",
            "stale": ARCHIVE_DIR / "stale_portfolios",
            "invalid": ARCHIVE_DIR / "invalid_runs",
            "quarantine": QUARANTINE_DIR / "runs"
        }
        counts = {k: (len(list(v.iterdir())) if v.exists() else 0) for k, v in paths.items()}
        self.report("ARCHIVE", "GREEN", f"Archive Stats: {counts}")

    def _check_guardrails(self):
        pipeline_code = (PROJECT_ROOT / "tools" / "run_pipeline.py").read_text(encoding="utf-8")
        required_logic = ["enforce_run_schema", "gate_registry_consistency", "detect_strategy_drift", "verify_manifest_integrity"]
        missing = [r for r in required_logic if r not in pipeline_code]

        if missing:
            self.report("GUARDRAILS", "RED", f"Missing operational logic: {missing}")
        else:
            self.report("GUARDRAILS", "GREEN", "All primary guardrails detected in run_pipeline.py.")

    def _check_execution_contract(self):
        """Verify every strategy in TS_Execution/portfolio.yaml is deployment-ready.

        For each enabled strategy:
          1. strategy.py exists in Trade_Scan/strategies/{id}/
          2. portfolio_evaluation/ exists in TradeScan_State/strategies/{id}/
          3. _schema_sample() passes signal_schema.validate()
        """
        import yaml
        import importlib.util

        portfolio_path = PROJECT_ROOT.parent / "TS_Execution" / "portfolio.yaml"
        if not portfolio_path.exists():
            self.report("EXEC_CONTRACT", "YELLOW", "TS_Execution/portfolio.yaml not found — skipping.")
            return

        try:
            with open(portfolio_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            self.report("EXEC_CONTRACT", "RED", f"Failed to parse portfolio.yaml: {e}")
            return

        strategies = data.get("portfolio", {}).get("strategies", []) or []
        enabled = [s for s in strategies if s.get("enabled", False) and s.get("id")]
        if not enabled:
            self.report("EXEC_CONTRACT", "YELLOW", "No enabled strategies in portfolio.yaml.")
            return

        # Load signal_schema from TS_Execution
        schema_path = PROJECT_ROOT.parent / "TS_Execution" / "src" / "signal_schema.py"
        signal_schema = None
        if schema_path.exists():
            spec = importlib.util.spec_from_file_location("signal_schema", str(schema_path))
            signal_schema = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(signal_schema)
            except Exception:
                signal_schema = None

        state_root = PROJECT_ROOT.parent / "TradeScan_State"
        strategy_root = PROJECT_ROOT / "strategies"
        errors = []

        for entry in enabled:
            sid = entry["id"]

            # Check 1: strategy.py exists
            strat_dir = strategy_root / sid
            strat_py = strat_dir / "strategy.py"
            if not strat_py.exists():
                errors.append(f"{sid}: strategy.py MISSING at {strat_dir}")
                continue

            # Check 2: portfolio_evaluation exists (resolve per-symbol to base)
            pe_dir = resolve_base_strategy_dir(sid, "portfolio_evaluation")
            if pe_dir is None:
                errors.append(f"{sid}: portfolio_evaluation/ MISSING (checked base resolution)")
                continue

            # Check 3: _schema_sample passes signal_schema.validate
            if signal_schema is None:
                continue  # can't validate without schema module

            try:
                spec_strat = importlib.util.spec_from_file_location(
                    f"strategy_{sid}", str(strat_py),
                    submodule_search_locations=[str(strat_dir)]
                )
                mod = importlib.util.module_from_spec(spec_strat)
                # Add project root to sys.path temporarily for indicator imports
                _prev_path = sys.path[:]
                sys.path.insert(0, str(PROJECT_ROOT))
                try:
                    spec_strat.loader.exec_module(mod)
                finally:
                    sys.path[:] = _prev_path

                strat_cls = getattr(mod, "Strategy", None)
                if strat_cls is None:
                    errors.append(f"{sid}: no Strategy class found")
                    continue

                sample_fn = getattr(strat_cls, "_schema_sample", None)
                if sample_fn is None:
                    errors.append(f"{sid}: no _schema_sample() method")
                    continue

                sample = sample_fn()
                result = signal_schema.validate(sample, sid, "PREFLIGHT")
                if result is None:
                    errors.append(f"{sid}: _schema_sample() REJECTED by signal_schema")
            except Exception as e:
                errors.append(f"{sid}: import/validate error — {type(e).__name__}: {e}")

        if errors:
            self.report("EXEC_CONTRACT", "RED",
                        f"{len(errors)}/{len(enabled)} strategies failed execution contract:")
            for err in errors:
                self.report("EXEC_CONTRACT", "RED", f"  {err}")
        else:
            schema_note = " (schema validated)" if signal_schema else " (schema skipped — signal_schema.py not found)"
            self.report("EXEC_CONTRACT", "GREEN",
                        f"All {len(enabled)} deployed strategies pass execution contract{schema_note}.")

    def _print_summary(self):
        def get_color_tag(cat):
            stats = [r[0] for r in self.results.get(cat, [])]
            if "RED" in stats: return "\033[91mRED\033[0m"
            if "YELLOW" in stats: return "\033[93mYELLOW\033[0m"
            return "\033[92mGREEN\033[0m"

        print(f"{'RUNS':<12} {get_color_tag('RUNS')}")
        for status, msg in self.results.get("RUNS", []):
            if status != "GREEN": print(f"  - {msg}")
            
        print(f"{'REGISTRY':<12} {get_color_tag('REGISTRY')}")
        for status, msg in self.results.get("REGISTRY", []):
            if status != "GREEN": print(f"  - {msg}")
            
        print(f"{'PORTFOLIOS':<12} {get_color_tag('PORTFOLIOS')}")
        for status, msg in self.results.get("PORTFOLIOS", []):
            if status != "GREEN": print(f"  - {msg}")

        print(f"{'LEDGER':<12} {get_color_tag('LEDGER')}")
        for status, msg in self.results.get("LEDGER", []):
            if status != "GREEN": print(f"  - {msg}")

        print(f"{'STRATEGIES':<12} {get_color_tag('STRATEGIES')}")
        for status, msg in self.results.get("STRATEGIES", []):
            if status != "GREEN": print(f"  - {msg}")
            
        print(f"{'ARCHIVE':<12} {get_color_tag('ARCHIVE')}")
        print(f"{'GUARDRAILS':<12} {get_color_tag('GUARDRAILS')}")
        for status, msg in self.results.get("GUARDRAILS", []):
            if status != "GREEN": print(f"  - {msg}")

        print(f"{'EXEC_CONTRACT':<14} {get_color_tag('EXEC_CONTRACT')}")
        for status, msg in self.results.get("EXEC_CONTRACT", []):
            if status != "GREEN": print(f"  - {msg}")

        overall = "GREEN"
        if self.stats["RED"] > 0: overall = "RED"
        elif self.stats["YELLOW"] > 0: overall = "YELLOW"
        
        color_map = {"RED": "\033[91m", "YELLOW": "\033[93m", "GREEN": "\033[92m"}
        print("\nOVERALL STATUS: " + color_map[overall] + overall + "\033[0m")
        if overall == "RED":
            print("!! Execution must halt.")
            sys.exit(1)
        elif overall == "YELLOW":
            print("-- Warning but execution allowed.")
        else:
            print("++ Pipeline safe to run.")

if __name__ == "__main__":
    PreflightCheck().run()
