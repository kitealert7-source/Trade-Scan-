"""Strategy-file validation + recovery + vault snapshot.

Owns:
  - _validate_strategy_files  — verify strategy.py + portfolio_evaluation/ + per-symbol dirs
  - _recover_strategy_py      — restore strategy.py from run snapshot
  - _snapshot_to_vault        — subprocess vault_snapshot + meta verification + hard gate
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import STRATEGIES_DIR, RUNS_DIR
from tools.pipeline_utils import find_run_id_for_directive
from tools.promote.yaml_writer import PROJECT_ROOT, VAULT_ROOT


def _recover_strategy_py(strategy_id: str, target_path: Path) -> bool:
    """Attempt to recover strategy.py from run snapshot if authority copy is missing.

    Searches TradeScan_State/runs/{run_id}/strategy.py using the fallback chain.
    If found, copies to the authority location and returns True.
    """
    run_id = find_run_id_for_directive(strategy_id)
    if not run_id:
        return False
    snapshot = RUNS_DIR / run_id / "strategy.py"
    if snapshot.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(snapshot), str(target_path))
        print(f"  [RECOVERED] strategy.py from run snapshot: {run_id}")
        return True
    return False


def _validate_strategy_files(strategy_id: str, symbols: list[dict]) -> None:
    """Verify all required files exist before modifying portfolio.yaml.

    If the authority strategy.py is missing, attempts auto-recovery from
    the run snapshot in TradeScan_State/runs/{run_id}/strategy.py.
    For multi-symbol strategies, auto-syncs per-symbol folders if the base
    strategy.py exists but per-symbol copies are missing.
    """
    base_spy = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if not base_spy.exists():
        if not _recover_strategy_py(strategy_id, base_spy):
            print(f"[ABORT] strategy.py not found: {base_spy}")
            print(f"  Not in authority location and no run snapshot found.")
            sys.exit(1)
    pe = STRATEGIES_DIR / strategy_id / "portfolio_evaluation"
    if not pe.exists():
        if len(symbols) <= 1:
            print(f"  [WARN] portfolio_evaluation/ not found (expected for single-symbol): {pe}")
        else:
            print(f"[ABORT] portfolio_evaluation/ not found: {pe}")
            sys.exit(1)
    if len(symbols) > 1:
        missing_syms = []
        for sym_info in symbols:
            sym_id = f"{strategy_id}_{sym_info['symbol']}"
            sym_spy = PROJECT_ROOT / "strategies" / sym_id / "strategy.py"
            if not sym_spy.exists():
                missing_syms.append(sym_info["symbol"])
        if missing_syms:
            # Auto-sync: copy base strategy.py to per-symbol folders
            print(f"  [AUTO-SYNC] Creating per-symbol strategy.py for: {missing_syms}")
            for sym in missing_syms:
                sym_id = f"{strategy_id}_{sym}"
                sym_dir = PROJECT_ROOT / "strategies" / sym_id
                sym_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(base_spy), str(sym_dir / "strategy.py"))
                print(f"    Created: strategies/{sym_id}/strategy.py")
            print(f"  [AUTO-SYNC] {len(missing_syms)} per-symbol folder(s) created")


def _snapshot_to_vault(strategy_id: str, run_id: str, profile: str,
                       vault_id: str, dry_run: bool) -> None:
    """Run vault snapshot subprocess + meta verification + hard gate.

    Aborts via sys.exit if snapshot fails or required files are missing.
    For dry_run: prints the would-be path and returns without side effects.
    """
    # 7. Run vault snapshot
    print(f"\n  --- Vault Snapshot ---")
    if dry_run:
        print(f"  [DRY RUN] Would create vault: {VAULT_ROOT / vault_id}")
    else:
        cmd = [
            sys.executable, str(PROJECT_ROOT / "tools" / "backup_dryrun_strategies.py"),
            "--strategies", strategy_id,
            "--run-id", run_id,
            "--profile", profile,
        ]
        # Check if vault already exists (idempotent)
        vault_path = VAULT_ROOT / vault_id
        if vault_path.exists():
            cmd.append("--append")
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=False)
        if result.returncode != 0:
            print(f"[ABORT] Vault snapshot failed (exit code {result.returncode})")
            sys.exit(1)

        # Verify vault was created
        if not (vault_path / strategy_id / "meta.json").exists():
            print(f"[ABORT] Vault verification failed: meta.json missing")
            sys.exit(1)

        # Verify run_id in meta.json
        meta = json.loads((vault_path / strategy_id / "meta.json").read_text(encoding="utf-8"))
        if meta.get("run_id", "unknown") == "unknown":
            print(f"[WARN] run_id not captured in vault meta.json")
        else:
            print(f"  Vault run_id verified: {meta['run_id'][:12]}...")

    # 8. HARD GATE: vault must exist before any portfolio.yaml mutation
    if not dry_run:
        vault_strat_path = VAULT_ROOT / vault_id / strategy_id
        required_files = ["meta.json", "strategy.py"]
        for rf in required_files:
            if not (vault_strat_path / rf).exists():
                print(f"[ABORT] Vault incomplete: {vault_strat_path / rf} missing")
                print(f"  Vault snapshot may have partially failed.")
                print(f"  portfolio.yaml was NOT modified.")
                sys.exit(1)
        print(f"  Vault gate PASSED: {vault_strat_path} verified")
