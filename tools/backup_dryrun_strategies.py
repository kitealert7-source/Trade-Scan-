"""
Dry-Run Strategy Backup — copies backtest artifacts for the 6 active dry-run strategies
into a timestamped folder inside C:\\Users\\faraw\\Documents\\DRY_RUN_VAULT\\.

What is saved per strategy:
  - directive.txt              (entry/exit/filter spec + config)
  - strategy.py                (frozen code at dry-run start)
  - portfolio_evaluation/      (full copy — metrics, charts, trade log)
  - deployable/
      profile_comparison.json  (capital model comparison)
      {PROFILE}/equity_curve.csv   (equity curve per bar, first profile only)
  - backtests/{ID}_{SYMBOL}/
      metadata/run_metadata.json
      raw/results_standard.csv
      raw/results_risk.csv
      raw/results_yearwise.csv
  - meta.json                  (git commit, config_hash, execution model, data signature)

What is excluded (too large, recoverable):
  - results_tradelevel.csv     (portfolio_tradelevel.csv in portfolio_evaluation/ covers this)
  - AK_Trade_Report_*.xlsx

Usage:
    cd C:\\Users\\faraw\\Documents\\Trade_Scan
    python tools/backup_dryrun_strategies.py

Output:
    C:\\Users\\faraw\\Documents\\DRY_RUN_VAULT\\DRY_RUN_{DATE}\\
"""

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Edit this list when the dry-run cohort changes ────────────────────────────
DRY_RUN_STRATEGIES = [
    "03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02",
    "11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S03_V1_P00",
    "12_STR_FX_1H_BOS_REGFILT_S03_V1_P00",
    "17_REV_XAUUSD_1H_FAKEBREAK_S01_V1_P04",
    "18_REV_XAUUSD_1H_LIQSWEEP_S01_V1_P06",
    "23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT   = PROJECT_ROOT.parent / "TradeScan_State"
VAULT_ROOT   = PROJECT_ROOT.parent / "DRY_RUN_VAULT"

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


def _copy_equity_curve_csv(strat_id: str, strat_backup: Path) -> bool:
    """Copy equity_curve.csv from the first deployable profile found."""
    deployable = STATE_ROOT / "strategies" / strat_id / "deployable"
    if not deployable.exists():
        return False
    for profile_dir in sorted(deployable.iterdir()):
        src = profile_dir / "equity_curve.csv"
        if src.exists():
            dst = strat_backup / "deployable" / profile_dir.name / "equity_curve.csv"
            _copy_if_exists(src, dst)
            return True
    return False


def main():
    date_str    = datetime.now().strftime("%Y_%m_%d")
    backup_root = VAULT_ROOT / f"DRY_RUN_{date_str}"

    if backup_root.exists():
        print(f"[ERROR] Backup already exists: {backup_root}")
        print("Remove it first or wait until tomorrow to create a new dated backup.")
        return

    backup_root.mkdir(parents=True)

    git_commit   = _git_commit(PROJECT_ROOT)
    completed    = []
    total_copied = 0
    index_strategies: dict = {}

    print(f"Git commit: {git_commit}")
    print(f"Output:     {backup_root}")
    print()

    for strat_id in DRY_RUN_STRATEGIES:
        print(f"  [{strat_id}]")
        strat_backup = backup_root / strat_id
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

        # 3. portfolio_evaluation/ (full copy — includes trade log + charts)
        pe_src = STATE_ROOT / "strategies" / strat_id / "portfolio_evaluation"
        if pe_src.exists():
            shutil.copytree(pe_src, strat_backup / "portfolio_evaluation")
            n = sum(1 for _ in pe_src.rglob("*") if _.is_file())
            copied += n
            print(f"    portfolio_evaluation/  {n} files  OK")
        else:
            print(f"    [SKIP] portfolio_evaluation not found in TradeScan_State")

        # 4. deployable/profile_comparison.json
        pc_src = STATE_ROOT / "strategies" / strat_id / "deployable" / "profile_comparison.json"
        if _copy_if_exists(pc_src, strat_backup / "deployable" / "profile_comparison.json"):
            copied += 1
            print(f"    deployable/profile_comparison.json  OK")
        else:
            print(f"    [SKIP] profile_comparison.json not found")

        # 5. equity_curve.csv (first deployable profile — per-bar equity)
        if _copy_equity_curve_csv(strat_id, strat_backup):
            copied += 1
            print(f"    deployable/{strat_id}/equity_curve.csv  OK")
        else:
            print(f"    [SKIP] equity_curve.csv not found in any deployable profile")

        # 6. Per-symbol raw summary CSVs + run metadata (no tradelevel — covered above)
        bt_dirs = sorted((STATE_ROOT / "backtests").glob(f"{strat_id}_*"))
        if not bt_dirs:
            print(f"    [SKIP] no backtest folders found in TradeScan_State/backtests/")
        for bt_dir in bt_dirs:
            symbol_tag = bt_dir.name
            raw_dst    = strat_backup / "backtests" / symbol_tag / "raw"
            raw_dst.mkdir(parents=True, exist_ok=True)
            for fname in RAW_SUMMARY_FILES:
                if _copy_if_exists(bt_dir / "raw" / fname, raw_dst / fname):
                    copied += 1
            meta_dst = strat_backup / "backtests" / symbol_tag / "metadata" / "run_metadata.json"
            if _copy_if_exists(bt_dir / "metadata" / "run_metadata.json", meta_dst):
                copied += 1
        if bt_dirs:
            print(f"    backtests/  {len(bt_dirs)} symbol folder(s)  OK")

        # 7. meta.json — git commit + config_hash + execution model + data signature
        c_hash  = _config_hash(strat_backup / "directive.txt")
        rm      = _read_run_meta(strat_backup)
        metrics = _read_standard_metrics(strat_backup)
        max_dd  = _read_max_dd(strat_backup)
        meta = {
            "strategy_id":        strat_id,
            "backup_created_utc": datetime.now(timezone.utc).isoformat(),
            "code_version": {
                "git_commit": git_commit,
                "git_repo":   "Trade_Scan",
            },
            "config_hash": c_hash,
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
                "timeframe":      rm.get("timeframe", ""),
                "broker":         rm.get("broker", ""),
                "date_start":     rm.get("date_range", {}).get("start", ""),
                "date_end":       rm.get("date_range", {}).get("end", ""),
                "engine_version": rm.get("engine_version", ""),
            },
        }
        (strat_backup / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        copied += 1

        print(f"    meta.json  config_hash={c_hash}  git={git_commit[:10]}...")
        print(f"    {copied} files copied")
        total_copied += copied
        completed.append(strat_id)

        index_strategies[strat_id] = {
            "pf":          metrics["pf"],
            "max_dd_pct":  max_dd,
            "trades":      metrics["trades"],
            "win_rate":    metrics["win_rate"],
            "date_start":  rm.get("date_range", {}).get("start", ""),
            "date_end":    rm.get("date_range", {}).get("end", ""),
            "config_hash": c_hash,
        }

    # Write enriched index at backup root
    index = {
        "created_utc":  datetime.now(timezone.utc).isoformat(),
        "backup_folder": str(backup_root),
        "git_commit":   git_commit,
        "strategies":   index_strategies,
        "total_files":  total_copied,
        "excluded":     ["results_tradelevel.csv", "AK_Trade_Report_*.xlsx"],
        "note":         "Backtest baseline snapshot at dry-run start.",
    }
    with open(backup_root / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    print()
    print("=" * 60)
    print(f"Backup complete:  {backup_root}")
    print(f"Strategies:       {len(completed)}")
    print(f"Total files:      {total_copied}")
    print(f"Git commit:       {git_commit}")
    print(f"Index:            {backup_root / 'index.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
