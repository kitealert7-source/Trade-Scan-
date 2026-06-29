# Vault snapshot — ID format, contents, invariants

> Reference for [`/promote`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

## Vault ID Format

```
DRY_RUN_{YYYY}_{MM}_{DD}__{run_id[:8]}
```

- **Date**: promotion date (not backtest date)
- **Run ID suffix**: first 8 chars of pipeline run_id hash
- **Deterministic**: same strategy + same run = same vault_id
- **Unique**: different runs on same day produce different vault_ids

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

## Vault Invariants (Never Violate)

1. **Outside all repos** -- `DRY_RUN_VAULT/` is not inside Trade_Scan or TS_Execution
2. **Immutable** -- once a strategy folder exists in a vault, never modify it
3. **Deterministic** -- same run_id always produces same vault_id
4. **No recomputation** -- every file is copied, never regenerated
5. **Git commit required** -- `meta.json` must have non-unknown git_commit
6. **Run ID required** -- `meta.json` must have non-unknown run_id
