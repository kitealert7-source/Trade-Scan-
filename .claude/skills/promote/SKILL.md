---
name: promote
description: Promote a strategy from PIPELINE_COMPLETE to BURN_IN -- vault snapshot, portfolio.yaml edit, execution-ready
---

# /promote -- Strategy Promotion to Burn-In

Single workflow that takes a strategy from PIPELINE_COMPLETE to live BURN_IN execution.
One command chains: run_id lookup -> quality gate -> full vault snapshot -> portfolio.yaml edit
with vault_id + profile + lifecycle fields.

> **Human-gated**: Only runs when explicitly triggered. No auto-promotion.

---

## Quick Reference

```bash
# 1. Check readiness first
python tools/promote_readiness.py              # full dashboard
python tools/promote_readiness.py --core-only  # CORE only

# 2. Single strategy
python tools/promote_to_burnin.py <ID> --profile <PROFILE> --dry-run
python tools/promote_to_burnin.py <ID> --profile <PROFILE>

# 3. Composite portfolio (PF_*)
python tools/promote_to_burnin.py <PF_ID> --composite --profile <PROFILE> --dry-run

# 4. Batch promote all ready CORE strategies
python tools/promote_to_burnin.py --batch --profile <PROFILE> --dry-run
python tools/promote_to_burnin.py --batch-all --profile <PROFILE> --dry-run  # includes WATCH
```

---

## Input

The human provides:
- **Strategy ID** (required for single/composite) -- e.g., `27_MR_XAUUSD_1H_PINBAR_S01_V1_P05` or `PF_04C5F80CB1E3`
- **Capital profile** (required) -- one of `RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1` (legacy institutional profiles retired 2026-04-16)
- **Description** (optional) -- one-line strategy summary for the burn-in comment block
- **Mode flag** (optional) -- `--composite`, `--batch`, `--batch-all`, `--skip-quality-gate`

---

## Pre-Conditions (verify ALL before proceeding)

// turbo

1. Strategy has reached **PORTFOLIO_COMPLETE** -- check `TradeScan_State/runs/{DIRECTIVE_ID}/directive_state.json`
   - At PORTFOLIO_COMPLETE, the system automatically sets `protected: true` and runs artifact verification
2. `strategies/{ID}/strategy.py` exists in Trade_Scan (or recoverable from run snapshot)
3. `TradeScan_State/strategies/{ID}/portfolio_evaluation/` exists
4. `TradeScan_State/strategies/{ID}/deployable/` exists with all 3 active capital profiles (`RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1`)
5. `TradeScan_State/backtests/{ID}_*/` exist (at least one symbol folder)
6. Strategy is **NOT** already in `TS_Execution/portfolio.yaml`
7. Trade_Scan git is clean -- commit any outstanding changes first

**Use the readiness dashboard to check all at once:**
```bash
python tools/promote_readiness.py --core-only
```
Strategies marked with `>>>` pass all checks and are ready to promote.

If ANY pre-condition fails, STOP and report which one failed.

---

## Automated Gates (enforced by the promote tool)

### Expectancy Gate
- FX: expectancy >= $0.15/trade
- XAU / BTC / INDEX: expectancy >= $0.50/trade
- Source: `config/asset_classification.py` -> `EXP_FAIL_GATES`
- Strategies below the floor are rejected automatically

### Per-Symbol Expectancy Gate (multi-symbol strategies)
- **All-or-nothing**: if ANY symbol fails the expectancy floor, the entire strategy is rejected
- The portfolio was backtested as a unit and must be promoted as a unit
- To override: use `--skip-quality-gate` (requires explicit justification)

### Quality Gate (6-metric edge check)
Computed automatically from trade-level CSV. No manual computation needed.

| # | Metric | HARD FAIL | WARN | Source |
|---|--------|-----------|------|--------|
| 1 | Remove top 5 trades -> PnL | Negative | < 30% of original | Man/AHL, Lopez de Prado |
| 2 | Top-5 trade concentration | > 70% of Net PnL | > 50% of Net PnL | CTA standard |
| 3 | Flat period as % of backtest | > 40% | > 30% | Kaufman |
| 4 | Edge ratio (avg MFE / avg MAE) | < 1.0 | < 1.2 | Van Tharp / Kaufman |
| 5 | Trade count | < 100 | < 200 | Pardo, Bailey |
| 6 | PF after removing top 5% of trades | < 1.0 | < 1.1 | Lopez de Prado |

**HARD FAIL on any metric = promotion aborted.** WARN = proceeds with warning logged.

> **Why this exists:** Composite portfolio metrics can mask individually weak strategies.
> PF_0C0C974A75F7 showed PF 1.73 / zero negative rolling windows, but two of three
> components had 96% and 51% top-5 concentration respectively. The composite looked
> strong only because the third strategy carried all the weight.

See also: `outputs/system_reports/11_deployment_and_burnin/CLASSIFICATION_REFERENCE.md` for full
CORE/WATCH/FAIL gate reference across all pipeline stages.

---

## Step 1: Promote

// turbo

### Single Strategy

```bash
python tools/promote_to_burnin.py <STRATEGY_ID> --profile <PROFILE> --dry-run
python tools/promote_to_burnin.py <STRATEGY_ID> --profile <PROFILE>
```

With description:
```bash
python tools/promote_to_burnin.py <STRATEGY_ID> --profile <PROFILE> --description "one-line summary"
```

### Composite Portfolio (PF_*)

Composites have no single strategy.py or run_id. The tool decomposes the portfolio into
constituent strategies, runs quality gates on each, and promotes passing constituents:

```bash
python tools/promote_to_burnin.py <PF_ID> --composite --profile <PROFILE> --dry-run
```

Decomposition reads constituent_run_ids from `portfolio_metadata.json` (primary) or
`Master_Portfolio_Sheet.xlsx` (fallback). If run_ids are missing from the Master Filter,
the tool falls back to reading `run_state.json` + `run_metadata.json` directly from run folders.

### Batch Promote

Promotes all ready CORE strategies in one session:

```bash
python tools/promote_to_burnin.py --batch --profile <PROFILE> --dry-run      # CORE only
python tools/promote_to_burnin.py --batch-all --profile <PROFILE> --dry-run   # CORE + WATCH
```

Uses `promote_readiness.py` internally to find candidates, then promotes each passing strategy
sequentially. Outputs a summary table with promoted/failed/skipped counts.

### What the promote tool does (in order)

1. Checks expectancy gate (asset-class floor)
2. Runs 6-metric quality gate on trade-level data
3. Per-symbol expectancy gate (multi-symbol: all-or-nothing)
4. Looks up `run_id` from `TradeScan_State/runs/*/run_state.json`
5. Generates deterministic vault_id: `DRY_RUN_YYYY_MM_DD__{run_id[:8]}`
6. Creates full vault snapshot via `backup_dryrun_strategies.py`
7. Verifies vault was created (meta.json + run_id present)
8. Appends YAML entries to `TS_Execution/portfolio.yaml`
9. Auto-chains: `sync_portfolio_flags.py --save` + `validate_portfolio_integrity.py`

**If any `[SKIP]` appears for directive.txt, strategy.py, or portfolio_evaluation**: STOP.
**If vault snapshot fails**: STOP. No portfolio.yaml edit happens.
**If `[ABORT]` appears**: quality gate or expectancy gate failed. Review output.

---

## Step 2: Auto-Chained (no manual action)

The promote tool automatically runs:
1. `sync_portfolio_flags.py --save` -- syncs IN_PORTFOLIO flags to candidates ledger + Master Filter
2. `validate_portfolio_integrity.py` -- audits portfolio.yaml for governance violations

Both are chained after successful portfolio.yaml edit. If either warns, review the output.

To verify flags manually: `python tools/sync_portfolio_flags.py --list`

---

## Step 3: Report

Report to the human:

| Item | Value |
|------|-------|
| Strategy | `<STRATEGY_ID>` |
| Run ID | `<run_id>` |
| Vault ID | `DRY_RUN_YYYY_MM_DD__{run_id[:8]}` |
| Profile | `<PROFILE>` |
| Lifecycle | BURN_IN |
| Symbols added | `<list>` |
| portfolio.yaml entries | N |
| Quality gate | PASS / WARN (N warnings) |
| IN_PORTFOLIO synced | Auto (check output) |
| Integrity check | Auto (check output) |

**Next steps for the human:**
1. Run Phase 0 smoke test: `cd ../TS_Execution && python src/main.py --phase 0`
2. Restart TS_Execution to pick up new strategies
3. Verify the strategy appears in execution logs after restart
4. Monitor via `python tools/burnin_monitor.py` (in TS_Execution, outputs to `TS_Execution/outputs/burnin/`)
5. When burn-in completes, use `/to-waiting` to transition

---

## Vault ID Format

```
DRY_RUN_{YYYY}_{MM}_{DD}__{run_id[:8]}
```

- **Date**: promotion date (not backtest date)
- **Run ID suffix**: first 8 chars of pipeline run_id hash
- **Deterministic**: same strategy + same run = same vault_id
- **Unique**: different runs on same day produce different vault_ids

---

## Vault Contents (Full Snapshot)

```
DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/
  strategy.py                          <- frozen code
  directive.txt                        <- execution spec
  meta.json                            <- git, hash, run_id, vault_id, profile
  selected_profile.json                <- profile selection record
  portfolio_evaluation/                <- full copy
  deployable/                          <- ALL active profiles
    profile_comparison.json
    RAW_MIN_LOT_V1/
      deployable_trade_log.csv
      equity_curve.csv
      equity_curve.png
      rejection_log.csv
      summary_metrics.json
    FIXED_USD_V1/...
    REAL_MODEL_V1/...
  broker_specs_snapshot/               <- broker YAML per symbol
    XAUUSD.yaml
  backtests/{ID}_{SYMBOL}/             <- per-symbol raw results
    metadata/run_metadata.json
    raw/results_standard.csv
    raw/results_risk.csv
    raw/results_yearwise.csv
  run_snapshot/                        <- full pipeline state
    audit.log
    manifest.json
    run_state.json
    strategy.py
    data/ (bar_geometry, batch_summary, equity_curve, metrics, results)
```

Every file is a **copy** from source. Nothing is recomputed.

---

## Multi-Symbol Strategies

Handled automatically:
- `backup_dryrun_strategies.py` captures base strategy + all `{ID}_{SYMBOL}` backtest folders
- Promote tool detects symbols from backtest folders and creates one portfolio.yaml entry per symbol
- All entries share the same `vault_id` and `profile`
- Per-symbol strategy copies must exist (`python tools/sync_multisymbol_strategy.py <ID>`)
- **All-or-nothing**: if any symbol fails per-symbol expectancy, the whole strategy is rejected

---

## Vault Invariants (Never Violate)

1. **Outside all repos** -- `DRY_RUN_VAULT/` is not inside Trade_Scan or TS_Execution
2. **Immutable** -- once a strategy folder exists in a vault, never modify it
3. **Deterministic** -- same run_id always produces same vault_id
4. **No recomputation** -- every file is copied, never regenerated
5. **Git commit required** -- `meta.json` must have non-unknown git_commit
6. **Run ID required** -- `meta.json` must have non-unknown run_id

---

## Emergency Retrieval

If a strategy degrades in live and you need the baseline:

1. Read `vault_id` from portfolio.yaml
2. Navigate to `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/`

Key files:
- `meta.json` -- git commit, run_id, config_hash
- `selected_profile.json` -- which profile was chosen
- `portfolio_evaluation/portfolio_summary.json` -- baseline metrics
- `run_snapshot/manifest.json` -- artifact hashes for tamper detection

---

## Related Workflows

| Workflow | Purpose |
|----------|---------|
| `/execute-directives` | Pipeline run that produces PORTFOLIO_COMPLETE (upstream) |
| `/to-waiting` | Downstream: BURN_IN -> WAITING after burn-in completes |
| `/portfolio-selection-add` | Manual IN_PORTFOLIO flag management |
| `/portfolio-selection-remove` | Remove strategy from portfolio |
| `/update-vault` | Workspace snapshot into `vault/snapshots/` (different scope) |

## Related Files

| File | Location |
|------|----------|
| Promote tool | `tools/promote_to_burnin.py` |
| Readiness dashboard | `tools/promote_readiness.py` |
| Portfolio integrity | `tools/validate_portfolio_integrity.py` |
| Vault backup | `tools/backup_dryrun_strategies.py` |
| Waiting transition | `tools/transition_to_waiting.py` |
| Portfolio flag sync | `tools/sync_portfolio_flags.py` (auto-chained by promote tool) |
| Portfolio YAML | `TS_Execution/portfolio.yaml` |
| Burn-in monitor | `TS_Execution/tools/burnin_monitor.py` (outputs to `TS_Execution/outputs/burnin/`) |
| Classification reference | `outputs/system_reports/11_deployment_and_burnin/CLASSIFICATION_REFERENCE.md` |
