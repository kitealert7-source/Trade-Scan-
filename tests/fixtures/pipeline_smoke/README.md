# Pipeline Smoke Fixture

This fixture is a regression smoke case for the end-to-end pipeline path:

1. `tools/portfolio_evaluator.py` writes the portfolio ledger row.
2. `tools/capital_wrapper.py` emits deployable profile artifacts.
3. `tools/profile_selector.py` enriches the ledger from `profile_comparison.json`.

Fixture ID:

- `C_XAUUSD_1H_VOL_EXP_L03_H2_SMOKE1`

Files:

- Directive: `tests/fixtures/pipeline_smoke/C_XAUUSD_1H_VOL_EXP_L03_H2_SMOKE1.txt`
- Strategy: `tests/fixtures/pipeline_smoke/strategies/C_XAUUSD_1H_VOL_EXP_L03_H2_SMOKE1/strategy.py`

Run command:

```powershell
python tools/tests/run_pipeline_smoke_fixture.py
```

Default behavior:

- Stages fixture into active runtime paths.
- Runs `tools/run_pipeline.py <fixture_id>`.
- Validates portfolio ledger/profile fields.
- Cleans fixture artifacts from production paths.

Use `--keep-artifacts` to keep generated artifacts for debugging.
