# `tools/resolve_baseline.py` — Specification (FINAL, v1.0)

**Status:** Approved for implementation (operator, 2026-06-12).
**Grounded by:** workflow `wf_1d70aee1-686` (8 agents, ~500K tokens) + targeted re-confirm of `strategies/`.
**Scope constraint:** preserve current operational behavior; do not remove directives; do not
redesign the pipeline; preserve `active/` recovery. Optimize for *research continuity*.

---

## 1. The research object (the reframe)

There is no single canonical artifact. There is one **canonical research object** distributed
across governed homes, each with a distinct, non-overlapping role:

```
PROJECT_ROOT/strategies/<strategy_id>/    =  EXECUTABLE INTENT  (strategy.py + directive.txt)      [repo source; symbol-agnostic]
STATE/backtests/<strategy_id>_<symbol>/   =  EMPIRICAL EVIDENCE (reports + metrics + raw outputs)  [per-symbol]
STATE/runs/<run_id>/                      =  PROVENANCE         (opaque execution snapshot)         [run-keyed]
```

> **NB (load-bearing, verified by build review 2026-06-12):** the executable-intent home is
> **`PROJECT_ROOT/strategies`** (`config.state_paths.REPO_STRATEGIES_DIR`) — this is where
> `strategy.py` + the governed `directive.txt` live. It is **NOT** `STATE_ROOT/strategies`
> (`STRATEGIES_DIR`), which holds *deployment/eval state* (`strategy_ref.json`, `deployables/`,
> robustness reports) and **no source code**. `state_paths.strategy_dir()` resolves to the REPO
> home; conflating the two silently breaks `code` resolution.

Supporting homes: `backtest_directives/completed/` (directive corpus + F19 history) and `git`
(deep recovery). The **ledger** (`master_filter`) is the spine that ties a handle to the
authoritative `run_id`/`strategy`/`symbol`.

`resolve_baseline` **unifies these homes** into one descriptor — a `BaselineReference` (not a
"capsule": the term is retired because the object spans `strategies/` *and* `backtests/`, not
just `backtests/`).

> **Two directive truths.** A directive snapshot exists in three places with different meanings:
> - **`backtests/.../DIRECTIVE_SOURCE.txt`** and **`runs/<run_id>/directive.txt`** = *exact
>   execution truth* (byte-exact to the run that produced these metrics).
> - **`strategies/<strategy_id>/directive.txt`** = *human-keyed continuity truth* (the
>   name-resolvable, governed, backfilled copy; present even for old runs).

---

## 2. Purpose & non-goals

**Purpose.** Given any handle to a prior experiment, return — in one read-only call — the
authoritative `is_current` run plus its **code**, **seed (directive)**, **baseline metrics**,
and **provenance paths**, unified from `strategies/` + `backtests/` + `runs/`. It ends the
"search multiple homes / reconstruct baselines by hand" friction and answers the two core
continuity questions: *"What exactly am I modifying?"* (code + seed) and *"What am I measuring
against?"* (metrics).

**Non-goals (hard).** No ledger mutation; no folder creation; no pipeline re-run; no backfill
(delegate to `backfill_run_directives.py`); no pruning/migration; not the cohort-comparison
engine (defer to `compare_cohorts.py`). **Read-only, side-effect-free.**

---

## 3. The invariant it exists to enforce

> **Authoritative = `is_current=1` (or `IS NULL` legacy), selected in SQL before any row is
> returned. The first-match path is never trusted.**

Verified failure mode: `find_run_id_for_directive` (`pipeline_utils.py:357`) returns the FIRST
match, and `read_master_filter()` (`ledger_db.py:978`) applies **no** `is_current` filter
(insertion-order rows). Real case — directive `22_CONT_FX_15M_RSIAVG_TRENDFILT_S07_V1_P02_EURUSD`:
first-match `7bdded9f…` is `is_current=0` (superseded); canonical is `80a6ef23…` (`is_current=1`).
`query_baskets` already filters `is_current=1` (`ledger_db.py:965`) — `master_filter` lacks the
equivalent; this spec adds it.

---

## 4. Interface

**Python**
```python
resolve_baseline(
    handle: str,                  # run_id | directive/strategy name | series tag
    *, symbol: str | None = None,     # disambiguate a multi-symbol directive
    require: str = "none",        # "none" | "seed" | "metrics" | "code" | "all"
) -> BaselineResult               # .references: list[BaselineReference]; len>1 = multi-symbol
```
**CLI**
```bash
python tools/resolve_baseline.py <handle> [--symbol SYM] [--all-symbols] \
       [--require seed|metrics|code|all] [--json]
```
Default output is a compact human summary (the token-saving lever for `hypothesis-testing`);
`--json` emits the `BaselineReference` schema in §6.

---

## 5. Resolution pipeline (the spine)

```
handle
  │ 5.1 classify: run_id (24-hex) | strategy/directive name | series tag
  ▼
5.2 ledger → query_master_filter_current(...)     ← NEW helper; is_current=1 OR NULL, IN SQL
  │   • run_id   → 1 row
  │   • strategy → N rows (one per symbol)         ← multi-symbol set (§11)
  │   • all superseded → follow superseded_by to the live successor; else resolved:false
  │   • >1 is_current for the same (strategy,symbol) → ERROR (append-only violation)
  │   • series tag → cointegration view, _classify_series; representative by ret_dd (§13.2)
  ▼
5.3 one ledger row (strategy, symbol, run_id) yields THREE homes:
       strategy_dir  = strategies/<strategy>                 (symbol-agnostic; may be ABSENT — §17)
       backtest_dir  = backtests/<strategy>_<symbol>
       run_dir       = runs/<run_id>
  ▼
5.4 resolve seed   (§7 ladder)
5.5 resolve code   (§8)
5.6 resolve metrics (§9 per run-type)
  ▼
BaselineResult (1 reference, or N for a bare multi-symbol directive handle)
```

---

## 6. Output schema (`BaselineReference`)

```jsonc
{
  "handle": "...", "resolved": true,
  "run_id": "80a6ef23...", "strategy": "...", "symbol": "EURUSD",
  "run_type": "basket | single_asset",
  "is_current": true,

  "homes": {
    "strategy_dir": "Trade_Scan/strategies/<strategy_id>            | null",   // executable intent
    "backtest_dir": "TradeScan_State/backtests/<strategy_id>_<symbol> | null", // empirical evidence
    "run_dir":      "TradeScan_State/runs/<run_id>                   | null"   // provenance
  },

  "code":   { "path": ".../strategy.py | .../RECYCLE_RULE_SOURCE.py | null",
              "source": "strategies_dir | capsule | git | ABSENT" },
  "seed":   { "path": "...",
              "source": "DIRECTIVE_SOURCE | run_directive_txt | strategy_directive_txt | completed | git | ABSENT",
              "truth": "exact_execution | human_keyed_continuity" },
  "metrics":{ /* §9, per run_type */ "source": "parquet_canonical | csv_stage1 | report_md | ABSENT" },
  "reports":{ "strategy_card": "…|null", "basket_report": "…|null", "report_md": "…|null" },

  "siblings": ["<strategy>_<otherSymbol>", ...],   // other symbols of the same directive
  "warnings": ["capsule predates DIRECTIVE_SOURCE; seed via strategies/<id>/directive.txt", ...]
}
```

---

## 7. Seed (directive) resolution ladder

Stop at the first hit; record `source` + `truth`. Exact-execution truth is preferred; human-keyed
continuity truth is the reliable fallback (and the only name-resolvable one for old runs):

| Tier | Source | Truth | Notes |
|---|---|---|---|
| 1 | `backtest_dir/DIRECTIVE_SOURCE.txt` | exact_execution | basket V3+ only; byte-exact to run |
| 2 | `run_dir/directive.txt` | exact_execution | run-keyed; present on most runs incl. recent + March-2026 |
| 3 | `strategy_dir/directive.txt` | human_keyed_continuity | governed, backfilled (2026-06-01); present for old runs |
| 4 | `backtest_directives/completed/<strategy>.txt` | human_keyed_continuity | corpus fallback |
| 5 | `recover_admitted_directive` → `recover_anypath_git` | human_keyed_continuity | git `--all` (verified: old `01_MR_FX…P02` from commit `7763514b`) |
| — | **ABSENT** | — | `warnings += provenance_gap`; block only if `require∈{seed,all}` |

`stake_usd` for basket metric recompute (§9) is parsed from the resolved seed's
`basket.initial_stake_usd`.

---

## 8. Code resolution

The executable artifact — *"what exactly am I modifying?"*:

| run_type | code source (priority) | field |
|---|---|---|
| single_asset | `strategy_dir/strategy.py` → git → ABSENT | `code.path` |
| basket | `backtest_dir/RECYCLE_RULE_SOURCE.py` (V3+) → git → ABSENT | `code.path` |

`strategy.py.bak` is ignored. `code.source=ABSENT` is reported, never assumed present (§17).

---

## 9. Metric resolution — per run-type (verified sources)

| run_type | source (priority) | fields |
|---|---|---|
| **basket** | **recompute** `canonical_metrics(parquet, stake_usd)` from `backtest_dir/raw/results_basket_per_bar.parquet` (`canonical_metrics.py:304`) | net_pct, max_dd_pct, ret_dd, recycle_events, cycles_completed/won, exit_reason |
| basket (no parquet / legacy V2) | parse `BASKET_REPORT_*.md` (fallback) | same, rounded |
| **single_asset** | `raw/results_standard.csv` (`trade_count`, `profit_factor`, `net_pnl_usd`) + `raw/results_risk.csv` (`sharpe_ratio`, `max_drawdown_pct`); **derive** `top5_concentration` via `metrics_core.compute_concentration` (`metrics_core.py:384`) and `losing_years` from `results_yearwise.csv` (count `net_pnl_usd<0`) | the exact 7 metrics `hypothesis-testing` locks |
| **old single_asset** | same CSVs (best-available); `REPORT_*.md` aggregate if a CSV is missing | subset; flag derived/missing |

> **Correctness rule (verified divergence):** for baskets, **never** use `canonical_net_pct` /
> `final_realized_usd÷stake` from MPS — real case `EURUSDUSDJPYBEAR` (run `4c11610190393e4b549aac5a`)
> showed 33.5% vs 655% from a different denominator. The parquet `equity_total_usd` via
> `canonical_metrics()` is the sole truth. `STRATEGY_CARD.md` carries **config only, no metrics** —
> never read metrics from it.

---

## 10. Degradation matrix (what you get, by era) — incl. the old-run path

| Era | Seed | Code | Metrics | Result |
|---|---|---|---|---|
| basket V3+ | DIRECTIVE_SOURCE.txt | RECYCLE_RULE_SOURCE.py | parquet canonical | full |
| basket V2/legacy | run/strategy directive.txt → git | git / ABSENT | parquet (or REPORT parse) | full, warn |
| single-asset recent | run/strategy directive.txt | **strategies/strategy.py** | CSV + derive | full |
| **single-asset OLD** | **strategy_dir/directive.txt** (backfilled) | **strategy_dir/strategy.py** | CSV best-available | **full executable continuity + degraded metrics** |
| pre-governance / grandfathered | possibly ABSENT | git / ABSENT | CSV if present | metrics-only or `resolved:false` |

The resolver **always returns best-available** and names gaps in `warnings`; it never fails just
because a run is old.

---

## 11. Multi-symbol handling

A bare directive handle (e.g. `02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P00` → 10 runs;
`01_MR_FX…P02` → 6 FX runs) resolves to **N references — one per symbol** (never silently one).
`--symbol SYM` or a `run_id` handle collapses to a single reference. `siblings[]` always lists the
other symbols so a single-symbol result still advertises the set.

---

## 12. Edge-case / error model (from the red-team)

| Scenario (real example) | Behavior | Exit |
|---|---|---|
| first-match≠is_current (`22_CONT_FX…P02_EURUSD`) | return is_current row, never first-match | 0 |
| multi-symbol directive (`02_VOL_IDX…P00` → 10) | return the **set** (single if `--symbol`/run_id) | 0 |
| fully superseded, no is_current (488 found) | follow `superseded_by` to live successor; else `resolved:false` | 1 |
| ledger row but capsule pruned (`00a8e0b5…_AUDNZD`) | `resolved:true`, `backtest_dir:null`, warn; error only if `--require` unmet | 0/2 |
| capsule folder, no ledger row (orphan) | `resolved:false`, warn — **never** auto-register | 1 |
| `strategy_dir` absent (curated 230-subset) | `code.source` → git/ABSENT, warn — never assume present | 0 |
| >1 is_current for same (strategy,symbol) | hard error (append-only violation), list both | 2 |
| series tag (`GP_ZCRS_CXN1_Z25`) | representative (top `ret_dd`) + `note: cohort → compare_cohorts` | 0 |
| seed/code unrecoverable (old/grandfathered) | best-available + `provenance_gap` warning | 0 (1 if `require` unmet) |

---

## 13. Resolved open decisions

1. **Multi-symbol default → return the SET.** A bare directive handle yields N references; `--symbol`/run_id collapses to one. Rationale: never silently drop symbols (the find_run_id data-loss trap).
2. **Series tag → representative + defer.** Return the top-`ret_dd` member as the representative reference, flag `is_cohort=true`, and point to `compare_cohorts.py` for matched-pairs analysis. Do not return the full cohort (that is `compare_cohorts`' job; "humans decide what to test, tooling decides how").
3. **Old-run-no-seed → warn + continue.** Return a metrics-only / code-only baseline with a `provenance_gap` warning; hard-fail only under `--require seed|all`. Rationale: continuity over purity — iteration can still proceed.

---

## 14. Supporting helpers (centralize the inline patterns)

1. `ledger_db.query_master_filter_current(strategy=None, run_id=None) -> DataFrame` — the
   `is_current=1 OR is_current IS NULL` filter `master_filter` lacks (mirrors `query_baskets`).
2. `state_paths.capsule_path(strategy, symbol)` and `state_paths.strategy_dir(strategy)` — one home
   for the `backtests/{strategy}_{symbol}` and `strategies/{strategy}` patterns (replaces 20+ inline
   f-strings). `find_run_id_for_directive` is **left untouched** — the resolver *wraps* it with the
   is_current filter rather than trusting it.

---

## 15. Skill integration (the two pointer edits — unchanged from the approved set)

- **`hypothesis-testing` → "Lock the reference run":** `resolve_baseline <ref> --json` → lock the
  returned `metrics` + record `homes`. The 7 single-asset fields map 1:1 to what it snapshots.
- **`generate-directives` → Method A step 1:** seed from `resolve_baseline(...).seed.path`;
  `completed/` retained as ladder tier 4 *inside* the resolver.

No skill edits land until the resolver is green.

---

## 16. Test plan (fixtures, before any wiring)

Fixture ledger + fixture homes covering each §10 row + each §12 scenario.
**Must-pass correctness test:** `resolve_baseline("22_CONT_FX…P02_EURUSD")` returns `80a6ef23`
(is_current), **not** `7bdded9f`. Plus: multi-symbol returns N; **old single-asset returns seed +
code from `strategies/<id>/`** with metrics degraded to CSV; basket metrics equal
`canonical_metrics()` and differ from the MPS `net_pct` trap; `strategy_dir` absent → `code` degrades
without error.

---

## 17. Coverage caveats (anti-drift — do not silently assume presence)

- `strategies/` holds **230** folders vs **5,959** backtests vs **11,127** completed directives —
  a *curated/recent* subset, not full history. `code`/`strategy_dir` may be ABSENT; report it.
- `DIRECTIVE_SOURCE.txt`/`RECYCLE_RULE_SOURCE.py` are **basket-V3+ only**.
- `STRATEGY_CARD.md` is a single-asset + basket artifact but **metrics-free** (config only).
- Old runs may be **grandfathered** (577 in `directive_provenance_baseline.json`) with no
  recoverable seed at all.

---

## 18. Verified-facts appendix (grounding)

| Fact | Evidence |
|---|---|
| capsule = `backtests/{strategy}_{symbol}` | `run_stage1.py:895`; 20+ inline sites |
| `read_master_filter` has no is_current filter; `query_baskets` does | `ledger_db.py:978` vs `:965` |
| is_current default 1; NULL treated as 1 | `ledger_db.py:290-296` |
| find_run_id_for_directive is first-match | `pipeline_utils.py:357` |
| `canonical_metrics(parquet, stake_usd, …)` | `canonical_metrics.py:304` |
| `compute_concentration` (top5) | `metrics_core.py:384` |
| single-asset metric files/cols | `results_standard.csv`, `results_risk.csv`, `results_tradelevel.csv`, `results_yearwise.csv` |
| `strategies/<id>/directive.txt` = human-keyed governed snapshot | `strategy_provisioner.py:336` |
| executable-intent home = `PROJECT_ROOT/strategies` (`REPO_STRATEGIES_DIR`), **not** `STATE_ROOT/strategies` (`STRATEGIES_DIR`) | `state_paths.py:109` (STATE) + added `REPO_STRATEGIES_DIR`; `01_MR…P02/strategy.py` present in repo, absent in STATE |
| `strategy_dir()` resolves to REPO home | `state_paths.py:strategy_dir`; smoke: `01_MR…P02` → `code.source=strategies_dir` |
| DIRECTIVE_SOURCE/RECYCLE_RULE_SOURCE writers (basket) | `basket_report.py:876-881`, `:810-811` |
| is_current trap real case | superseded `7bdded9f` vs canonical `80a6ef23` (`22_CONT_FX…P02_EURUSD`) |
| basket net_pct divergence real case | run `4c11610190393e4b549aac5a` (33.5% vs 655%) |
| home counts | strategies/ 230 · backtests/ 5,959 · completed/ 11,127 |
