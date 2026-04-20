---
name: uniform-risk-capital-simulation
description: Run capital_wrapper on a fixed backtest dataset with uniform risk_per_trade across all applicable profiles, isolate outputs, restore wrapper, and extract raw metrics
---

## Uniform Risk Capital Simulation Workflow

This workflow re-simulates the capital layer only (no pipeline rerun) on an already completed backtest dataset.

## Scope

- Uses existing backtest artifacts under `TradeScan_State/backtests/`
- Runs `tools/capital_wrapper.py` only
- Applies one uniform `risk_per_trade` value to all profiles that define `risk_per_trade`
- Isolates each run output immediately to avoid overwrite loss
- Restores `tools/capital_wrapper.py` exactly after each run

## Fixed Dataset (Current Validated Prefix)

- `STRATEGY_PREFIX = PF_7FCF1D2EB158_R05_EXEC_PROFILES`

## Paths

- Inputs (discovered by wrapper): `TradeScan_State/backtests/<prefix>_<symbol>/raw/results_tradelevel.csv`
- Active output (overwritten every run): `TradeScan_State/strategies/<prefix>/deployable/`
- Isolated outputs:
  - `deployable_R05`
  - `deployable_UNIFORM_R10_ALL_PROFILES`
  - `deployable_R15`
  - `deployable_R20`

## Constraints

- Do not modify strategy/filter/regime logic
- Do not modify wrapper logic/flow
- Do not change anything except `risk_per_trade` values
- Do not rerun pipeline
- Do not regenerate backtests
- Keep seed unchanged

---

## Step 0: Preflight

1. Verify prefix folders exist:
```powershell
Get-ChildItem "C:\Users\faraw\Documents\TradeScan_State\backtests" -Directory |
  Where-Object { $_.Name -like "PF_7FCF1D2EB158_R05_EXEC_PROFILES*" } |
  Select-Object Name
```
2. Verify `raw/results_tradelevel.csv` exists in each folder before proceeding.

## Step 1: Backup Wrapper

Create a timestamped backup before any mutation:

```powershell
$ts=Get-Date -Format 'yyyyMMdd_HHmmss'
Copy-Item tools\capital_wrapper.py "tools\capital_wrapper.py.uniform_backup_$ts" -Force
```

## Step 2: Apply Uniform Risk to Applicable Profiles

Update `risk_per_trade` in `tools/capital_wrapper.py` for all profiles that have this key:

- `FIXED_USD_V1` (fallback field still set for uniformity via `fixed_risk_usd_floor`)
- `REAL_MODEL_V1` (base `risk_per_trade` — ignore `tier_base_pct`/`tier_step_pct` for the uniform variant; disable `tier_ramp` if you want pure flat behaviour)

Do not add keys to profiles that do not currently define `risk_per_trade`.
`RAW_MIN_LOT_V1` is intentionally excluded — it's the 0.01-lot diagnostic baseline
and has `raw_lot_mode: True`, no `risk_per_trade`.

> **Retired profiles (do not apply — no longer present in `PROFILES` dict):**
> `DYNAMIC_V1`, `CONSERVATIVE_V1`, `MIN_LOT_FALLBACK_V1`, `MIN_LOT_FALLBACK_UNCAPPED_V1`,
> `BOUNDED_MIN_LOT_V1`.

## Step 3: Run Wrapper

```powershell
python -m tools.capital_wrapper PF_7FCF1D2EB158_R05_EXEC_PROFILES
```

## Step 4: Isolate Output Immediately

Copy `deployable/` to the target folder right after each run:

```powershell
$base="C:\Users\faraw\Documents\TradeScan_State\strategies\PF_7FCF1D2EB158_R05_EXEC_PROFILES"
Copy-Item "$base\deployable" "$base\<TARGET_FOLDER>" -Recurse -Force
```

If replacing an existing target:

```powershell
Remove-Item "$base\<TARGET_FOLDER>" -Recurse -Force
Copy-Item "$base\deployable" "$base\<TARGET_FOLDER>" -Recurse -Force
```

## Step 5: Restore Wrapper

Restore exact pre-run file and verify hash match:

```powershell
Copy-Item "tools\capital_wrapper.py.uniform_backup_<TIMESTAMP>" tools\capital_wrapper.py -Force
(Get-FileHash tools\capital_wrapper.py -Algorithm SHA256).Hash
(Get-FileHash "tools\capital_wrapper.py.uniform_backup_<TIMESTAMP>" -Algorithm SHA256).Hash
```

---

## Standard Variant Map

Use this mapping when refreshing the saved uniform runs:

| Variant | Uniform risk_per_trade | Target folder |
|---|---:|---|
| R05 | 0.005 | `deployable_R05` |
| R10 | 0.010 | `deployable_UNIFORM_R10_ALL_PROFILES` |
| R15 | 0.015 | `deployable_R15` |
| R20 | 0.020 | `deployable_R20` |

For each row:

1. Set uniform risk
2. Run wrapper
3. Copy `deployable/` to mapped target folder immediately
4. Continue to next row
5. Restore wrapper at the end

---

## Raw Metrics Extraction (Per Profile)

`summary_metrics.json` does not include PF directly, so compute PF from `deployable_trade_log.csv`.

```powershell
$root="C:\Users\faraw\Documents\TradeScan_State\strategies\PF_7FCF1D2EB158_R05_EXEC_PROFILES\<TARGET_FOLDER>"
$profiles=Get-ChildItem $root -Directory | Select-Object -ExpandProperty Name
foreach($name in $profiles){
  $sum=Get-Content "$root\$name\summary_metrics.json" -Raw | ConvertFrom-Json
  $csv=Import-Csv "$root\$name\deployable_trade_log.csv"
  $pnl=$csv | ForEach-Object { [double]$_.pnl_usd }
  $gp=($pnl | Where-Object { $_ -gt 0 } | Measure-Object -Sum).Sum
  $gl=($pnl | Where-Object { $_ -lt 0 } | Measure-Object -Sum).Sum
  $pf=if($gl -eq 0){ if($gp -gt 0){ [double]::PositiveInfinity } else {0.0} } else { $gp / [math]::Abs($gl)}
  [PSCustomObject]@{
    Profile=$name
    ProfitFactor=[math]::Round($pf,4)
    NetPnL=[double]$sum.realized_pnl
    MaxDrawdownPct=[double]$sum.max_drawdown_pct
    Accepted=[int]$sum.total_accepted
    Rejected=[int]$sum.total_rejected
  }
}
```

---

## Failure Handling

1. If wrapper execution fails, do not copy `deployable/`; inspect failure and rerun only after fixing the immediate issue.
2. If output copy fails, rerun wrapper for that variant (output may be overwritten by next pass).
3. If restore hash mismatch occurs, stop and manually restore from backup before any further run.
4. Never continue to next variant without successful output isolation.

