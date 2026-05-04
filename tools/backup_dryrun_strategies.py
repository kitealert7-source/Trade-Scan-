"""
Dry-Run Strategy Backup -- copies backtest artifacts for strategies
into a uniquely identified folder inside DRY_RUN_VAULT (sibling to Trade_Scan).

Vault ID format:
    DRY_RUN_YYYY_MM_DD__{run_id[:8]}   (per-strategy, deterministic)
    DRY_RUN_YYYY_MM_DD                  (legacy batch mode, no --run-id)

What is saved per strategy (FULL snapshot -- no recomputation):
  - directive.txt              (entry/exit/filter spec + config)
  - strategy.py                (frozen code at dry-run start)
  - meta.json                  (git commit, config_hash, run_id, execution model)
  - selected_profile.json      (profile selection record)
  - portfolio_evaluation/      (full copy -- metrics, charts, trade log)
  - deployable/                (ALL profiles -- trade logs, equity, rejections, metrics)
  - broker_specs_snapshot/     (broker YAML for each symbol)
  - backtests/{ID}_{SYMBOL}/   (per-symbol raw results + metadata)
  - run_snapshot/              (full pipeline state from runs/{RUN_ID}/)

Usage:
    # Promote workflow: single strategy with run_id (deterministic vault_id)
    python tools/backup_dryrun_strategies.py --strategies ID --run-id HASH --profile PROF

    # Legacy batch mode: default cohort
    python tools/backup_dryrun_strategies.py

Output:
    DRY_RUN_VAULT/DRY_RUN_{DATE}__{run_id[:8]}/   (with --run-id)
    DRY_RUN_VAULT/DRY_RUN_{DATE}/                   (without --run-id)
"""

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Default cohort (used when --strategies not provided) ─────────────────────
DRY_RUN_STRATEGIES = [
    "03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02",
    "11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S03_V1_P00",
    "12_STR_FX_1H_BOS_REGFILT_S03_V1_P00",
    "17_REV_XAUUSD_1H_FAKEBREAK_S01_V1_P04",
    "18_REV_XAUUSD_1H_LIQSWEEP_S01_V1_P06",
    "23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12",
    "15_MR_FX_15M_ASRANGE_SESSFILT_S03_V1_P02",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(PROJECT_ROOT))
from tools.pipeline_utils import find_run_id_for_directive

from config.path_authority import TRADE_SCAN_STATE as STATE_ROOT, DRY_RUN_VAULT as VAULT_ROOT
BROKER_SPECS = PROJECT_ROOT / "data_access" / "broker_specs"

RAW_SUMMARY_FILES = [
    "results_standard.csv",
    "results_risk.csv",
    "results_yearwise.csv",
]


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _git_commit(repo: Path) -> str:
    """Return current HEAD commit hash, or 'unknown' on failure."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _config_hash(directive_path: Path) -> str:
    """SHA-256[:16] fingerprint of the directive file content."""
    if not directive_path.exists():
        return "unknown"
    return hashlib.sha256(directive_path.read_bytes()).hexdigest()[:16]


def _read_standard_metrics(strat_backup: Path) -> dict:
    """Read PF / win_rate / trades from first results_standard.csv found."""
    for csv_path in strat_backup.glob("backtests/*/raw/results_standard.csv"):
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
        if rows:
            r = rows[0]
            return {
                "pf":       float(r.get("profit_factor", 0)),
                "win_rate": float(r.get("win_rate", 0)),
                "trades":   int(float(r.get("trade_count", 0))),
            }
    return {"pf": None, "win_rate": None, "trades": None}


def _read_max_dd(strat_backup: Path) -> float | None:
    """Read max_drawdown_pct from profile_comparison.json (first profile)."""
    pc = strat_backup / "deployable" / "profile_comparison.json"
    if not pc.exists():
        return None
    profiles = json.loads(pc.read_text(encoding="utf-8")).get("profiles", {})
    if not profiles:
        return None
    return round(next(iter(profiles.values())).get("max_drawdown_pct", 0), 4)


def _read_run_meta(strat_backup: Path) -> dict:
    """Return first run_metadata.json contents found under backtests/."""
    for p in strat_backup.glob("backtests/*/metadata/run_metadata.json"):
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _find_run_id(directive_id: str) -> str:
    """Thin wrapper — delegates to shared find_run_id_for_directive().

    Returns 'unknown' (legacy contract) when not found.
    """
    result = find_run_id_for_directive(directive_id)
    return result if result else "unknown"


def _copy_full_deployable(strat_id: str, strat_backup: Path) -> int:
    """Copy ALL deployable profiles (not just one equity_curve.csv).

    Returns number of files copied.
    """
    src_root = STATE_ROOT / "strategies" / strat_id / "deployable"
    if not src_root.exists():
        return 0
    dst_root = strat_backup / "deployable"
    copied = 0
    for src_file in src_root.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(src_root)
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)
            copied += 1
    return copied


def _copy_run_snapshot(run_id: str, strat_backup: Path) -> int:
    """Copy full pipeline run context to run_snapshot/.

    Returns number of files copied.
    """
    if run_id == "unknown":
        return 0
    src = STATE_ROOT / "runs" / run_id
    if not src.exists():
        return 0
    dst = strat_backup / "run_snapshot"
    copied = 0
    for src_file in src.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(src)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst / rel)
            copied += 1
    return copied


def _copy_broker_specs(strat_backup: Path, symbols: list[str], broker: str) -> int:
    """Copy broker spec YAMLs for each symbol.

    Returns number of files copied.
    """
    if not broker:
        return 0
    # Normalize broker name for directory lookup (e.g., "OctaFX" -> try common forms)
    broker_dir = None
    for candidate in [broker, broker.replace("FX", "Fx"), broker.title()]:
        d = BROKER_SPECS / candidate
        if d.exists():
            broker_dir = d
            break
    if not broker_dir:
        # Try case-insensitive search
        for d in BROKER_SPECS.iterdir():
            if d.name.lower() == broker.lower():
                broker_dir = d
                break
    if not broker_dir:
        return 0

    dst = strat_backup / "broker_specs_snapshot"
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for sym in symbols:
        src = broker_dir / f"{sym}.yaml"
        if src.exists():
            shutil.copy2(src, dst / f"{sym}.yaml")
            copied += 1
    return copied


def _write_selected_profile(strat_id: str, profile: str, vault_id: str,
                            strat_backup: Path) -> None:
    """Write selected_profile.json -- records which profile was chosen."""
    data = {
        "strategy_id": strat_id,
        "selected_profile": profile,
        "selected_by": "human",
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "vault_id": vault_id,
    }
    (strat_backup / "selected_profile.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def backup_strategy(strat_id: str, backup_root: Path, git_commit: str,
                    run_id: str = "unknown", profile: str = "",
                    vault_id: str = "") -> dict:
    """Backup a single strategy. Returns index entry dict."""
    print(f"  [{strat_id}]")
    strat_backup = backup_root / strat_id
    if strat_backup.exists():
        print(f"    [SKIP] Already exists in vault: {strat_backup.name}")
        return {}
    strat_backup.mkdir()
    copied = 0

    # 1. Directive .txt
    directive = PROJECT_ROOT / "backtest_directives" / "completed" / f"{strat_id}.txt"
    if _copy_if_exists(directive, strat_backup / "directive.txt"):
        copied += 1
    else:
        print(f"    [SKIP] directive not found: {directive.name}")

    # 2. strategy.py
    spy = PROJECT_ROOT / "strategies" / strat_id / "strategy.py"
    if _copy_if_exists(spy, strat_backup / "strategy.py"):
        copied += 1
    else:
        print(f"    [SKIP] strategy.py not found")

    # 3. portfolio_evaluation/ (full copy -- includes trade log + charts)
    pe_src = STATE_ROOT / "strategies" / strat_id / "portfolio_evaluation"
    if pe_src.exists():
        shutil.copytree(pe_src, strat_backup / "portfolio_evaluation")
        n = sum(1 for _ in pe_src.rglob("*") if _.is_file())
        copied += n
        print(f"    portfolio_evaluation/  {n} files  OK")
    else:
        print(f"    [SKIP] portfolio_evaluation not found in TradeScan_State")

    # 4. deployable/ -- ALL profiles (trade logs, equity, rejections, metrics)
    deploy_n = _copy_full_deployable(strat_id, strat_backup)
    if deploy_n > 0:
        print(f"    deployable/  {deploy_n} files (all profiles)  OK")
    else:
        print(f"    [SKIP] deployable/ not found or empty")
    copied += deploy_n

    # 5. Per-symbol raw summary CSVs + run metadata
    bt_dirs = sorted((STATE_ROOT / "backtests").glob(f"{strat_id}_*"))
    symbols_found: list[str] = []
    if not bt_dirs:
        print(f"    [SKIP] no backtest folders found in TradeScan_State/backtests/")
    for bt_dir in bt_dirs:
        symbol_tag = bt_dir.name
        # Extract symbol: strip strategy_id prefix + underscore
        sym = symbol_tag[len(strat_id) + 1:]
        symbols_found.append(sym)
        raw_dst = strat_backup / "backtests" / symbol_tag / "raw"
        raw_dst.mkdir(parents=True, exist_ok=True)
        for fname in RAW_SUMMARY_FILES:
            if _copy_if_exists(bt_dir / "raw" / fname, raw_dst / fname):
                copied += 1
        meta_dst = strat_backup / "backtests" / symbol_tag / "metadata" / "run_metadata.json"
        if _copy_if_exists(bt_dir / "metadata" / "run_metadata.json", meta_dst):
            copied += 1
    if bt_dirs:
        print(f"    backtests/  {len(bt_dirs)} symbol folder(s)  OK")

    # 6. run_snapshot/ -- full pipeline run context
    actual_run_id = run_id
    if actual_run_id == "unknown":
        actual_run_id = _find_run_id(strat_id)
    snap_n = _copy_run_snapshot(actual_run_id, strat_backup)
    if snap_n > 0:
        print(f"    run_snapshot/  {snap_n} files (run_id={actual_run_id[:12]}...)  OK")
    else:
        print(f"    [SKIP] run_snapshot not found (run_id={actual_run_id})")
    copied += snap_n

    # 7. broker_specs_snapshot/ -- broker YAMLs for each symbol
    rm = _read_run_meta(strat_backup)
    broker = rm.get("broker", "")
    if not symbols_found and rm.get("symbol"):
        symbols_found = [rm["symbol"]]
    broker_n = _copy_broker_specs(strat_backup, symbols_found, broker)
    if broker_n > 0:
        print(f"    broker_specs_snapshot/  {broker_n} file(s)  OK")
    else:
        print(f"    [SKIP] broker specs not found (broker={broker})")
    copied += broker_n

    # 8. selected_profile.json
    if profile:
        _write_selected_profile(strat_id, profile, vault_id, strat_backup)
        copied += 1
        print(f"    selected_profile.json  profile={profile}  OK")

    # 9. meta.json -- git commit + config_hash + run_id + execution model + data sig
    c_hash = _config_hash(strat_backup / "directive.txt")
    metrics = _read_standard_metrics(strat_backup)
    max_dd = _read_max_dd(strat_backup)
    meta = {
        "strategy_id":        strat_id,
        "run_id":             actual_run_id,
        "vault_id":           vault_id,
        "backup_created_utc": datetime.now(timezone.utc).isoformat(),
        "code_version": {
            "git_commit": git_commit,
            "git_repo":   "Trade_Scan",
        },
        "config_hash": c_hash,
        "selected_profile":   profile or "unspecified",
        "execution_model": {
            "order_type":          "market",
            "execution_timing":    "next_bar_open",
            "spread_model":        "broker_live_spread",
            "slippage_model":      "none_assumed",
            "fill_assumption":     "full_fill_at_open",
            "latency_assumption":  "ignored",
        },
        "data_signature": {
            "symbol":         rm.get("symbol", ""),
            "symbols":        symbols_found,
            "timeframe":      rm.get("timeframe", ""),
            "broker":         broker,
            "date_start":     rm.get("date_range", {}).get("start", ""),
            "date_end":       rm.get("date_range", {}).get("end", ""),
            "engine_version": rm.get("engine_version", ""),
        },
    }
    (strat_backup / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    copied += 1

    print(f"    meta.json  run_id={actual_run_id[:12]}  config_hash={c_hash}  git={git_commit[:10]}...")
    print(f"    {copied} files copied")

    index_entry = {
        "pf":          metrics["pf"],
        "max_dd_pct":  max_dd,
        "trades":      metrics["trades"],
        "win_rate":    metrics["win_rate"],
        "date_start":  rm.get("date_range", {}).get("start", ""),
        "date_end":    rm.get("date_range", {}).get("end", ""),
        "config_hash": c_hash,
        "run_id":      actual_run_id,
        "profile":     profile or "unspecified",
    }
    return index_entry, copied


def main():
    parser = argparse.ArgumentParser(
        description="Backup strategy artifacts to DRY_RUN_VAULT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--strategies", nargs="+", metavar="ID",
        help="Strategy IDs to backup (overrides default cohort list)",
    )
    parser.add_argument(
        "--run-id", metavar="HASH",
        help="Pipeline run_id for vault_id generation (DRY_RUN_DATE__hash[:8])",
    )
    parser.add_argument(
        "--profile", metavar="NAME", default="",
        help="Selected capital profile (written to selected_profile.json + meta.json)",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Allow appending to an existing vault folder",
    )
    args = parser.parse_args()

    strategy_list = args.strategies if args.strategies else DRY_RUN_STRATEGIES

    # Build vault_id: date + run_id suffix (if provided)
    date_str = datetime.now().strftime("%Y_%m_%d")
    if args.run_id:
        vault_id = f"DRY_RUN_{date_str}__{args.run_id[:8]}"
    else:
        vault_id = f"DRY_RUN_{date_str}"

    backup_root = VAULT_ROOT / vault_id

    if backup_root.exists() and not args.append:
        print(f"[ERROR] Backup already exists: {backup_root}")
        print("Use --append to add strategies, or remove the folder.")
        return

    backup_root.mkdir(parents=True, exist_ok=True)

    # Load existing index if appending
    existing_index: dict = {}
    index_path = backup_root / "index.json"
    if index_path.exists():
        existing_index = json.loads(index_path.read_text(encoding="utf-8"))

    git_commit = _git_commit(PROJECT_ROOT)
    completed: list[str] = []
    total_copied = 0
    index_strategies: dict = existing_index.get("strategies", {})

    print(f"Vault ID:   {vault_id}")
    print(f"Git commit: {git_commit}")
    print(f"Output:     {backup_root}")
    if args.run_id:
        print(f"Run ID:     {args.run_id}")
    if args.profile:
        print(f"Profile:    {args.profile}")
    if args.append and existing_index:
        print(f"Mode:       APPEND (existing vault has {len(index_strategies)} strategies)")
    print()

    for strat_id in strategy_list:
        result = backup_strategy(
            strat_id, backup_root, git_commit,
            run_id=args.run_id or "unknown",
            profile=args.profile,
            vault_id=vault_id,
        )
        if not result:
            continue
        index_entry, copied = result
        index_strategies[strat_id] = index_entry
        total_copied += copied
        completed.append(strat_id)

    # Write enriched index at backup root
    prev_files = existing_index.get("total_files", 0) if existing_index else 0
    index = {
        "vault_id":     vault_id,
        "created_utc":  existing_index.get("created_utc", datetime.now(timezone.utc).isoformat()),
        "updated_utc":  datetime.now(timezone.utc).isoformat(),
        "backup_folder": str(backup_root),
        "git_commit":   git_commit,
        "strategies":   index_strategies,
        "total_files":  prev_files + total_copied,
        "note":         "Full strategy snapshot at promotion to burn-in.",
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    print()
    print("=" * 60)
    print(f"Backup complete:  {backup_root}")
    print(f"Vault ID:         {vault_id}")
    print(f"Strategies:       {len(completed)}")
    print(f"Total files:      {prev_files + total_copied}")
    print(f"Git commit:       {git_commit}")
    print("=" * 60)

    # Return vault_id for caller (promote_to_burnin.py)
    return vault_id


if __name__ == "__main__":
    main()
