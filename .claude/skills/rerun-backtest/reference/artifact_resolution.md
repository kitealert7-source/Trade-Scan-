# Authentic artifact source — look in `backtests/` first, then `runs/`

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

A rerun's source directive (and the code that ran) is recovered from the per-run artifact
snapshots — **not** by mtime-scanning `completed/`. Look in this order (the same ladder
`resolve_baseline` walks); recent runs' source artifacts increasingly land in `backtests/`, so
**look there first** — it is the most complete and the most natural to hit, since it is keyed
by the directive name (the usual rerun target).

**1 — `backtests/<directive_name>/` — look here first.** Keyed by **directive name**; the
recent-vintage canonical artifact home.

| File | Contents |
|---|---|
| `DIRECTIVE_SOURCE.txt` | byte-exact directive that produced the run — the config to clone (resolver's top rung) |
| `RECYCLE_RULE_SOURCE.py` *(basket)* | the exact leg-rule code that ran |
| `STRATEGY_CARD.md`, `BASKET_REPORT_*.md` / `REPORT_*.md` | human-readable run summary |
| `metadata/`, `raw/` | results (`raw/results_tradelevel.csv`, …) |

**2 — `runs/<run_id>/` — run_id-keyed companion.** When you hold the `run_id` hash, this carries
the same directive plus full sha256 provenance.

| File | Contents |
|---|---|
| `directive.txt` | byte-exact directive snapshot |
| `strategy.py` *(single-asset)* | exact strategy code — write-once (Invariant #4) |
| `basket_code/` *(basket)* | `recycle_strategies.py` + `recycle_rules/*.py` + `code_manifest.json` |
| `manifest.json` | sha256 provenance: `strategy_hash`, `engine_version`, per-leg data + broker-spec sha256, artifact sha256, `execution_mode`, `basket_id` |

**3 — fallback:** `strategies/<id>/directive.txt` → `completed/` → git.

**Why this beats the `completed/` mtime-scan:** these snapshots are keyed to the **exact run**
(by directive name or run_id — the provenance a `run_id`-targeted rerun otherwise discards),
**immutable**, and **sha256-verified** (`runs/.../manifest.json`). You recover the directive
*and* the code that actually ran — not a most-recent-mtime guess that may have landed on a
superseded `__E###` variant.

**`resolve_baseline` walks this exact ladder** — prefer it over hand-scanning:

// turbo

```bash
python tools/resolve_baseline.py <run_id | directive_name | series_tag> --json
# ladder: backtests/<name>/DIRECTIVE_SOURCE.txt → runs/<run_id>/directive.txt
#         → strategies/<id>/directive.txt → completed/ → git   (selects the is_current run)
```

**Coverage caveat:** source capture is recent-vintage — `DIRECTIVE_SOURCE.txt` +
`RECYCLE_RULE_SOURCE.py` are present for ~83% of `backtests/` entries (7,302 / 8,845): basket +
recent runs. Older single-asset `backtests/` entries are **report-only** (no source capture) —
for those the strategy code is in `runs/<run_id>/strategy.py` and the directive falls back to
`completed/`. The captured set grows as new runs land in `backtests/`.

> **Resolution (F1 landed 2026-06-14):** `prepare` resolves the source via `resolve_baseline`
> (`is_current` + the exact per-run seed) **first**, falling back to the mtime scan of `completed/`
> only when the resolver can't pin a single seed. A bare-name target now also captures the
> resolved `is_current` run_id as the `rerun_of` breadcrumb.
> **Baskets (F1b landed 2026-06-14):** baskets live in `cointegration_sheet` / `basket_sheet`,
> not `master_filter`, so `resolve_baseline` can't reach them — `prepare` resolves baskets via a
> dedicated basket-sheet tier (`_resolve_basket_source`): match the `is_current` row by
> `directive_id` / `run_id`, then read the seed from `runs/<run_id>/directive.txt` →
> `<backtests_path>/DIRECTIVE_SOURCE.txt` → `completed/`. Both a basket **name** and an
> **`is_current` run_id** resolve (a basket run_id, absent from `master_filter`, maps to its
> directive via the sheets too). A **superseded** basket run_id is not matched — use the
> directive name or the current run_id; it otherwise falls through to the mtime scan.
