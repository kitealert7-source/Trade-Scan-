"""
Dry-Run Strategy Backup — copies backtest artifacts for the 6 active dry-run strategies
into a timestamped backup folder inside Trade_Scan/dry_run_backups/.

What is copied per strategy:
  - backtest_directives/completed/{ID}.txt  (entry/exit/filter spec)
  - strategies/{ID}/strategy.py             (frozen code at dry-run start)
  - TradeScan_State/strategies/{ID}/portfolio_evaluation/  (metrics + charts, full copy)
  - TradeScan_State/strategies/{ID}/deployable/profile_comparison.json
  - TradeScan_State/backtests/{ID}_*/raw/results_{standard,risk,yearwise}.csv
  - TradeScan_State/backtests/{ID}_*/metadata/run_metadata.json

What is excluded (too large, recoverable from pipeline):
  - results_tradelevel.csv
  - AK_Trade_Report_*.xlsx
  - deployable/{PROFILE}/ (individual capital model files)

Usage:
    cd C:\\Users\\faraw\\Documents\\Trade_Scan
    python tools/backup_dryrun_strategies.py
"""

import json
import shutil
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


def main():
    date_str    = datetime.now().strftime("%Y_%m_%d")
    backup_root = PROJECT_ROOT / "dry_run_backups" / f"DRY_RUN_{date_str}"

    if backup_root.exists():
        print(f"[ERROR] Backup already exists: {backup_root}")
        print("Remove it first or wait until tomorrow to create a new dated backup.")
        return

    backup_root.mkdir(parents=True)
    completed    = []
    total_copied = 0

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

        # 3. portfolio_evaluation/ (full copy — includes PNGs and CSVs)
        pe_src = STATE_ROOT / "strategies" / strat_id / "portfolio_evaluation"
        if pe_src.exists():
            shutil.copytree(pe_src, strat_backup / "portfolio_evaluation")
            copied += sum(1 for _ in pe_src.rglob("*") if _.is_file())
            print(f"    portfolio_evaluation/  OK")
        else:
            print(f"    [SKIP] portfolio_evaluation not found in TradeScan_State")

        # 4. deployable/profile_comparison.json only
        pc_src = STATE_ROOT / "strategies" / strat_id / "deployable" / "profile_comparison.json"
        if _copy_if_exists(pc_src, strat_backup / "deployable" / "profile_comparison.json"):
            copied += 1
            print(f"    deployable/profile_comparison.json  OK")
        else:
            print(f"    [SKIP] profile_comparison.json not found")

        # 5. Per-symbol raw summary CSVs + run metadata
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

        print(f"    {copied} files copied")
        total_copied += copied
        completed.append(strat_id)

    # Write a simple index at backup root
    index = {
        "created_utc"    : datetime.now(timezone.utc).isoformat(),
        "backup_folder"  : str(backup_root),
        "strategies"     : completed,
        "total_files"    : total_copied,
        "excluded"       : ["results_tradelevel.csv", "AK_Trade_Report_*.xlsx",
                            "deployable/{PROFILE}/equity_curve.csv"],
        "note"           : "Backtest baseline snapshot at dry-run start.",
    }
    with open(backup_root / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    print()
    print("=" * 60)
    print(f"Backup complete:  {backup_root}")
    print(f"Strategies:       {len(completed)}")
    print(f"Total files:      {total_copied}")
    print(f"Index:            {backup_root / 'index.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
