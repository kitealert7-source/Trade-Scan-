# Regression Harness

Minimal system-level PASS/FAIL safety net for capital / portfolio / report / promote layers.
Single command runs all scenarios in < 60s (currently ~0.04s, 7 artifacts).

See [PLAN.md](PLAN.md) for the full design rationale.

## Running

```bash
python -m tools.regression.cli                    # run everything
python -m tools.regression.cli --layer capital    # filter by scenario-name substring
```

Exit code `0` = all PASS, `1` = any regression.

On failure, a per-scenario diff file is written to `tmp/<scenario>/DIFF_<artifact>.txt`
and the first 10 failures are summarized on stdout.

## Layout

```
tools/regression/
  cli.py          # argparse entrypoint
  runner.py       # discovery + orchestration + summary
  compare.py      # json / csv / jsonl / md / yaml / sqlite comparators
  normalize.py    # path + timestamp + set-order normalization
  scenarios/      # one file per layer's choke-point
    capital_replay.py
    portfolio_select.py
    promote_gate.py
    report_project.py
  baselines/      # git-tracked goldens + REBASELINE_LOG.md
  tmp/            # gitignored — reset each run
```

## Adding a new scenario

1. Drop `tools/regression/scenarios/<name>.py`.
2. Export `run(tmp_dir, baseline_dir, budget) -> list[Result]`.
3. Write your outputs to `tmp_dir/<artifact>` for compare, AND to
   `tmp_dir/golden_candidate/<artifact>` so `--update-baseline` can stage it.
4. Use comparators from `tools.regression.compare`:
   `compare_json`, `compare_csv`, `compare_text`, `compare_jsonl`,
   `compare_yaml`, `compare_sqlite_table`.
5. Seed goldens with `python -m tools.regression.cli --update-baseline --force`
   (see next section).

The runner auto-discovers any module in `scenarios/` with a `run` callable —
no central registration.

### Choke-point principle

One scenario per layer, targeting its **authority function** (the single
write-point or projection where drift would silently corrupt downstream
behavior). Do not unit-test helpers here — those belong in `tests/`.

## Updating baselines

Rebaselining is **two-step** to prevent "green by overwrite":

```bash
# 1. Dry run — prints every artifact that would change, writes nothing.
python -m tools.regression.cli --update-baseline

# 2. After reviewing the diff, apply it.
python -m tools.regression.cli --update-baseline --force
```

`--force` copies `tmp/<scn>/golden_candidate/**` over
`baselines/<scn>/golden/**` and appends a record to
[baselines/REBASELINE_LOG.md](baselines/REBASELINE_LOG.md) (timestamp,
scenarios touched, whether pre-state was GREEN or HAD_FAILURES).

Only the `golden_candidate/` subtree is eligible — scenarios opt into
rebaselining by writing there.

## Failure cap

`MAX_FAILURES = 20` (in [runner.py](runner.py)). When the aggregate failure
count hits the cap, remaining scenarios are skipped with
`skipped: MAX_FAILURES reached in earlier scenarios`. This prevents a single
upstream break (e.g., a renamed field) from producing hundreds of noisy
diffs. Fix the first failures, then re-run.

## Determinism rules

- Strict compare: metric floats (`rtol=1e-9, atol=1e-12`), `signal_hash`,
  `deployed_profile`, gate booleans, ledger identity fields.
- Normalized: wall-clock timestamps → `<TS>`, absolute project paths →
  `<PROJECT_ROOT>`, set-like lists sorted before serialize.
- YAML compared parsed (via `yaml.safe_load`), never raw text.

If a field is non-deterministic, either normalize it consistently or
exclude it. Do not compare a flaky field without normalization.

## Usage Policy

Run the regression harness before:

- committing changes that touch any of:
  - `tools/capital/`
  - `tools/portfolio/`
  - `tools/report/`
  - `tools/promote/`
- pushing to remote

Command:

```bash
python -m tools.regression.cli
```

PASS is required before proceeding. The commit-time check is enforced
automatically by [.git/hooks/pre-commit](../../.git/hooks/pre-commit) — it
skips the harness when no relevant tool directory is staged. Push-time
enforcement lives in
[.github/workflows/regression.yml](../../.github/workflows/regression.yml)
and blocks the merge on a non-zero exit.

Neither the hook nor CI ever passes `--update-baseline`. Baseline changes
require a deliberate local `python -m tools.regression.cli
--update-baseline --force` followed by a separate review + commit.

### First-time setup

`.git/hooks/` is per-clone and not tracked. Install the hook once after
cloning:

```bash
./tools/hooks/install.sh
```

Re-run the same command whenever [tools/hooks/pre-commit](../hooks/pre-commit)
changes. The installer copies the tracked source into `.git/hooks/pre-commit`
and marks it executable — no framework, no auto-install.
