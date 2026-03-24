---
description: Capture, store, and verify backtest artifacts for strategies entering live dry-run
---

# /dry-run-vault — Dry-Run Artifact Vault Workflow

Creates a point-in-time snapshot of all backtest artifacts for the active dry-run
cohort into `C:\Users\faraw\Documents\DRY_RUN_VAULT\` — isolated outside all repos,
immutable, never touched by any pipeline process.

> **IMPORTANT**: Run this BEFORE starting a dry-run, not after.
> The backup captures the baseline state. If you run it later, the baseline is ambiguous.

---

## When to Run

| Trigger | Action |
|---|---|
| New strategies approved for dry-run | Run this workflow BEFORE burn-in starts |
| Dry-run cohort changes (add/remove) | Update list in script, then re-run |
| Dry-run completed, moving to real account | Run again to freeze end-of-dry-run state |
| Strategy degradation detected in live | Go to **Emergency Retrieval** section |

---

## Pre-Conditions

Before running:

1. Backtest pipeline has completed for all strategies in the cohort.
2. `TradeScan_State/strategies/{ID}/portfolio_evaluation/` exists for each strategy.
3. `TradeScan_State/backtests/{ID}_*/` folders exist with raw CSVs.
4. Trade_Scan git is clean — commit any outstanding changes first.

---

## Step 1: Confirm Strategy List

// turbo

Open `tools/backup_dryrun_strategies.py` and verify `DRY_RUN_STRATEGIES` matches
the current cohort. If the list needs updating, edit it and commit to git BEFORE
running the backup — the git commit hash captured in the backup must reflect the
correct code state.

Current cohort (as of 2026-03-24):
```
03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02
11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S03_V1_P00
12_STR_FX_1H_BOS_REGFILT_S03_V1_P00
17_REV_XAUUSD_1H_FAKEBREAK_S01_V1_P04
18_REV_XAUUSD_1H_LIQSWEEP_S01_V1_P06
23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12
```

---

## Step 2: Run the Backup

// turbo

```bash
cd C:\Users\faraw\Documents\Trade_Scan
python tools/backup_dryrun_strategies.py
```

Expected output (abbreviated):
```
Git commit: 4a82d75b906e90dc...
Output:     C:\Users\faraw\Documents\DRY_RUN_VAULT\DRY_RUN_YYYY_MM_DD\

  [03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P02]
    portfolio_evaluation/  11 files  OK
    deployable/profile_comparison.json  OK
    backtests/  1 symbol folder(s)  OK
    meta.json  config_hash=17fcdbd1...  git=4a82d75b90...
    18 files copied
  ...
============================================================
Backup complete:  ...\DRY_RUN_VAULT\DRY_RUN_2026_03_24\
Strategies:       6
Total files:      108
Git commit:       4a82d75b906e90dc967c4ab2ce2f71754e559d85
============================================================
```

**If you see** `[ERROR] Backup already exists`:
The dated folder already exists. Do not overwrite it. If it was a failed test run,
delete the folder manually then re-run. Otherwise today's backup is already done.

---

## Step 3: Verify the Backup

// turbo

```bash
python - << 'EOF'
import json
from pathlib import Path

VAULT = Path(r"C:\Users\faraw\Documents\DRY_RUN_VAULT")
latest = sorted(VAULT.iterdir())[-1]
print(f"Latest backup: {latest.name}")
print()

idx = json.loads((latest / "index.json").read_text())
print(f"Git commit: {idx['git_commit'][:20]}...")
print()

for sid, v in idx["strategies"].items():
    meta = json.loads((latest / sid / "meta.json").read_text())
    git_ok  = meta["code_version"]["git_commit"] != "unknown"
    hash_ok = meta["config_hash"] != "unknown"
    print(f"  {'OK' if git_ok and hash_ok else 'FAIL'}  {sid}")
    print(f"       pf={v['pf']}  trades={v['trades']}  dd={v['max_dd_pct']}%")
    print(f"       git={'OK' if git_ok else 'MISSING'}  config_hash={'OK' if hash_ok else 'MISSING'}")
EOF
```

Pass criteria — every strategy must show:
- `git = OK` (non-empty commit hash)
- `config_hash = OK` (non-empty fingerprint)
- No `[SKIP]` lines for directive.txt, strategy.py, or portfolio_evaluation in Step 2 output

---

## Step 4: Report

Report to the human:

- Vault folder name (e.g. `DRY_RUN_2026_03_24`)
- Total files captured
- Git commit hash captured
- Any `[SKIP]` warnings and which strategies were affected

---

## What Is Saved Per Strategy

```
DRY_RUN_VAULT\DRY_RUN_{DATE}\{STRATEGY_ID}\
├── directive.txt                        ← full config: entry/exit/filters/order type
├── strategy.py                          ← frozen code snapshot
├── meta.json                            ← git commit, config_hash, execution model,
│                                           data signature (symbol/tf/broker/dates)
├── portfolio_evaluation\                ← full copy
│   ├── portfolio_summary.json
│   ├── portfolio_metrics.csv
│   ├── portfolio_tradelevel.csv         ← full trade log
│   ├── equity_curve.png
│   ├── drawdown_curve.png
│   └── ...
├── deployable\
│   ├── profile_comparison.json          ← capital model comparison (all profiles)
│   └── {PROFILE}\equity_curve.csv      ← per-bar equity (first profile)
└── backtests\{STRATEGY_ID}_{SYMBOL}\
    ├── metadata\run_metadata.json       ← engine version, run_id, date range
    └── raw\
        ├── results_standard.csv
        ├── results_risk.csv
        └── results_yearwise.csv

DRY_RUN_VAULT\DRY_RUN_{DATE}\
└── index.json   ← git commit + PF/DD/trades/win_rate/config_hash per strategy
```

---

## Emergency Retrieval

If a strategy degrades in live and you need the baseline:

```
C:\Users\faraw\Documents\DRY_RUN_VAULT\DRY_RUN_2026_03_24\{STRATEGY_ID}\
```

Key files:
- `meta.json` → confirm git commit + config_hash match current state
- `portfolio_evaluation\portfolio_summary.json` → baseline metrics
- `portfolio_evaluation\portfolio_tradelevel.csv` → baseline trade distribution
- `deployable\profile_comparison.json` → expected PF/DD per capital model

To detect strategy.py drift from baseline:
```python
import hashlib
baseline = hashlib.sha256(
    open(r"DRY_RUN_VAULT\DRY_RUN_{DATE}\{ID}\strategy.py", "rb").read()
).hexdigest()[:16]
current = hashlib.sha256(
    open(r"Trade_Scan\strategies\{ID}\strategy.py", "rb").read()
).hexdigest()[:16]
print("MATCH" if baseline == current else f"DRIFT  {baseline} -> {current}")
```

---

## Vault Invariants (Never Violate)

1. **Outside all repos** — `DRY_RUN_VAULT\` is not inside Trade_Scan or TS_Execution
2. **Immutable** — once a dated folder exists, never modify its contents
3. **Append-only** — add new dated folders; never reuse or overwrite existing ones
4. **Run before dry-run** — captures baseline, not current state
5. **Git commit required** — if `meta.json` shows `git_commit: unknown`, backup is incomplete

---

## Related Workflows

| Workflow | Purpose |
|---|---|
| `/update-vault` | Workspace snapshot into `vault/snapshots/` (engine + research state) |
| `/system-maintenance` | General repo health checks |

## Related Files

| File | Location |
|---|---|
| Backup script | `tools/backup_dryrun_strategies.py` |
| Burn-in plan | `TS_Execution\BURNIN_PLAN.md` |
| Execution spec | `TS_Execution\EXECUTION_SPEC.md` |
