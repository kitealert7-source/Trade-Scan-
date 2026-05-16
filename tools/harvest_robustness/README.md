# Harvest Robustness Harness

Orchestrator + collator for basket-recycle (harvest-oriented) strategy analyses.

This is the harvest-strategy counterpart to `tools/robustness/` — but built as a thin **harness** over independent analysis scripts in `tools/harvest_robustness/modules/`, not a from-scratch tool. Each section of the report is produced by an independent script; the harness runs them in order and concatenates their outputs into one report.

The harness is self-contained: all referenced scripts live under this package's `modules/` subdirectory. (Original scripts were authored in `tmp/` during research and migrated here on 2026-05-16; the harness no longer depends on `tmp/`.)

## Quick start

```bash
# Run all sections defined in sections.yaml
python tools/harvest_robustness/cli.py

# Run only specific sections
python tools/harvest_robustness/cli.py --sections intrabar_floating,realized_metrics

# Run only sections tagged with 'capital' or 'dd'
python tools/harvest_robustness/cli.py --tags capital,dd

# Custom label + output dir
python tools/harvest_robustness/cli.py --label E1_champion_review \
    --output outputs/harvest_robustness/E1_review/
```

Output: a single markdown report at `outputs/harvest_robustness/REPORT_<label>_<timestamp>.md`.

## Current sections (sections.yaml)

| id | what it does | source script |
|---|---|---|
| `realized_metrics` | Per-basket realized PnL, Max DD, PF, recycles, harvest outcome (USD-anchored 4×3 matrix) | `tools/harvest_robustness/modules/h2_s08_results_extract.py` |
| `composite_realized` | N-basket parallel composite rollup (realized DD basis) — all 2/3-of-3 harvester combos + E1 + E2 + bonus | `tools/harvest_robustness/modules/h2_harvesters_composite_analysis.py` |
| `at_event_floating` | Worst floating PnL at recycle event timestamps (lower-bound DD) | `tools/harvest_robustness/modules/h2_floating_dd_at_events.py` |
| `intrabar_floating` | TRUE per-bar floating Max DD reconstruction + composite intra-bar DD + real-capital model | `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` |

## Plug-in protocol (adding new sections)

### Option A — Existing standalone script (most common)

1. Drop your analysis script into `tools/harvest_robustness/modules/` (the canonical home). If the script computes `PROJECT_ROOT` for sys.path or imports, use `Path(__file__).resolve().parents[3]` to walk up `modules/ → harvest_robustness/ → tools/ → repo`.
2. Append an entry to `sections.yaml`:

```yaml
- id: my_new_section
  title: "5. My new analysis"
  description: >
    One sentence operator-facing context.
  script: tools/harvest_robustness/modules/h2_my_new_analysis.py
  kind: stdout_capture
  tags: [my_tag]
```

3. Run: `python tools/harvest_robustness/cli.py --sections my_new_section` to validate it works
4. Done — next full harness run will include it

(Research-stage scripts may live in `tmp/` while iterating, but they must be moved under `modules/` before being registered in `sections.yaml`. The harness must remain self-contained.)

### Option B — Python module under harvest_robustness/

If a section needs Python-level interop (shared config, dataframe passing between sections, etc.), drop a module in this package and extend `harness.py` to handle a `kind: python_callable` section type. Not implemented in MVP — design when needed.

## Why not rewrite the scripts into a proper tool?

Deliberate trade-off. The migrated scripts (now in `modules/`) work, are tested by direct invocation during research, and have hardcoded basket IDs that match the current data. Building a fully parameterised proper tool would:
- Duplicate logic that's already correct
- Require basket-set abstraction that we don't yet need (one current research dataset)
- Delay getting an orchestrated report into operator hands

If/when a section's parameterisation becomes useful (e.g., running on a different basket set), refactor THAT module alone — the harness contract doesn't change.

## Failure modes

- **Section script missing:** report shows `[harness] ERROR: script not found at ...`. Fix the path in sections.yaml.
- **Section times out (10 min limit):** report shows `[harness] TIMEOUT after Xs`. Either optimise the script or bump the timeout in `harness.py`.
- **Section non-zero exit:** report shows the stderr; subsequent sections still run.

## Versioning

`__version__` lives in `tools/harvest_robustness/__init__.py`. Bump when:
- Adding/removing a section in sections.yaml (minor)
- Changing harness.py contract (major)

Current version is in the report header.
