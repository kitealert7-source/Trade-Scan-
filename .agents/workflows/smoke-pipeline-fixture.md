---
description: Run the pipeline smoke fixture regression test
---

# /smoke-pipeline-fixture - Pipeline Smoke Workflow

Runs the end-to-end smoke fixture regression that validates:

1. Stage-4 portfolio ledger append path
2. Step 8 capital wrapper artifact emission
3. Step 8.5 profile selector enrichment from `profile_comparison.json`

Fixture source of truth:

- `tests/fixtures/pipeline_smoke/`
- Runner: `tools/tests/run_pipeline_smoke_fixture.py`

---

## Step 1: Run Standard Smoke Fixture

```bash
python tools/tests/run_pipeline_smoke_fixture.py
```

Expected result:

- Exit code `0`
- Final log line: `[DONE] Pipeline smoke fixture PASSED.`

Default behavior cleans staged runtime artifacts and removes inserted
fixture rows from:

- `backtests/Strategy_Master_Filter.xlsx`
- `strategies/Master_Portfolio_Sheet.xlsx`

---

## Step 2: Debug Mode (Optional)

Use this only when the standard smoke run fails and you need artifacts
left in place for inspection.

```bash
python tools/tests/run_pipeline_smoke_fixture.py --keep-artifacts
```

---

## Step 3: Report Outcome

Report:

1. Pass/fail status
2. Failing stage (if any)
3. Any warnings seen during Step 9 deployable verification

If debug mode was used, include key artifact paths retained in runtime.
