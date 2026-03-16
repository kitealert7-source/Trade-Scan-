import os
import json
import hashlib
import sys
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.state_paths import RUNS_DIR, REGISTRY_DIR, STRATEGIES_DIR, ARCHIVE_DIR, QUARANTINE_DIR, BACKTESTS_DIR, CANDIDATES_DIR
STRICT_MODE = True # Any error makes overall status RED

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
        # Step 6: Strategy Drift
        self._check_strategy_drift()
        # Step 7: Archive Sanity
        self._check_archives()
        # Step 8: Guardrails Presence
        self._check_guardrails()

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
                manifest = json.loads(m_path.read_text())
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
            reg = json.loads(reg_path.read_text())
            
            # Disk scan (Combined Sandbox and Candidates)
            sandbox_disk = set(p.name for p in RUNS_DIR.iterdir() if p.is_dir())
            candidate_disk = set(p.name for p in CANDIDATES_DIR.iterdir() if p.is_dir())
            all_disk = sandbox_disk | candidate_disk
            
            reg_ids = set(reg.keys())

            # 1. Orphans (On disk but not in registry)
            # Filter out directive state folders (they contain underscores, run IDs are hex)
            orphans = [o for o in (all_disk - reg_ids) if not ("_" in o)]
            
            if orphans:
                self.report("REGISTRY", "RED", f"DISK_NOT_IN_REGISTRY: {orphans[:3]}...")

            # 2. Missing (In registry but not on disk)
            missing = []
            for rid, entry in reg.items():
                if entry.get("status") == "invalid": continue
                
                target_dir = RUNS_DIR if entry.get("tier") == "sandbox" else CANDIDATES_DIR
                if not (target_dir / rid).exists():
                    missing.append(rid)
            
            if missing:
                self.report("REGISTRY", "RED", f"REGISTRY_RUN_MISSING_ON_DISK: {missing[:3]}...")
            
            if not orphans and not missing:
                self.report("REGISTRY", "GREEN", "Registry and disk are aligned per tier.")
        except Exception as e:
            self.report("REGISTRY", "RED", f"Error reading registry: {e}")

    def _check_portfolios(self):
        if not STRATEGIES_DIR.exists(): return
        
        missing_ids = set()
        portfolio_count = 0
        for p_file in STRATEGIES_DIR.rglob("portfolio_metadata.json"):
            portfolio_count += 1
            try:
                data = json.loads(p_file.read_text())
                for rid in data.get("constituent_run_ids", []):
                    if not (RUNS_DIR / rid).exists():
                        missing_ids.add(rid)
            except Exception: continue
            
        if missing_ids:
            self.report("PORTFOLIOS", "RED", f"Missing dependencies for {len(missing_ids)} runs.")
        else:
            self.report("PORTFOLIOS", "GREEN", f"{portfolio_count} portfolios verified for dependencies.")

    def _check_strategy_drift(self):
        if not STRATEGIES_DIR.exists(): return
        
        drift = []
        for item in STRATEGIES_DIR.iterdir():
            if item.is_file() and item.name != "Master_Portfolio_Sheet.xlsx":
                drift.append(item.name)
            elif item.is_dir() and not item.name.startswith("_"):
                if not (item / "portfolio_metadata.json").exists() and not any(item.glob("*.py")):
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
        pipeline_code = (PROJECT_ROOT / "tools" / "run_pipeline.py").read_text()
        required_logic = ["enforce_run_schema", "gate_registry_consistency", "detect_strategy_drift", "verify_manifest_integrity"]
        missing = [r for r in required_logic if r not in pipeline_code]
        
        if missing:
            self.report("GUARDRAILS", "RED", f"Missing operational logic: {missing}")
        else:
            self.report("GUARDRAILS", "GREEN", "All primary guardrails detected in run_pipeline.py.")

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
            
        print(f"{'STRATEGIES':<12} {get_color_tag('STRATEGIES')}")
        for status, msg in self.results.get("STRATEGIES", []):
            if status != "GREEN": print(f"  - {msg}")
            
        print(f"{'ARCHIVE':<12} {get_color_tag('ARCHIVE')}")
        print(f"{'GUARDRAILS':<12} {get_color_tag('GUARDRAILS')}")
        for status, msg in self.results.get("GUARDRAILS", []):
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
