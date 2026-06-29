# Execution Capsule Contract

**Status: ACTIVE contract.** Established 2026-06-16 (untrack commit `a0a1bccc`).
Authority: artifact-provenance + git-tracking policy. Read this before re-adding
`backtest_directives/completed/` to git on a "reproducibility was lost" argument —
it was not. This contract is the answer to that exact question.

---

## The contract

> A completed backtest run folder that contains **`DIRECTIVE_SOURCE.txt`** and
> **`RECYCLE_RULE_SOURCE.py`** constitutes an **immutable execution capsule** and is the
> **authoritative byte-level home of the executed specification**.

The capsule is self-contained *as a provenance record*: the spec *and* the code that executed
it travel with the results, so reproduction starts from the capsule and needs nothing further
**from git or the corpus**. What the capsule guarantees is **spec provenance and execution
provenance** — *what* was run and *how* — not eternal executability under arbitrary future
environments. Actually re-running the capsule still depends on the runtime environment, engine
compatibility, and market-data availability; those are environmental preconditions, not
something the capsule is meant to pin.

### What a capsule contains

Emitted by `tools/basket_report.py` (since commit `60862b4c`) into
`TradeScan_State/backtests/<run>/`:

| File | Role |
|---|---|
| `DIRECTIVE_SOURCE.txt` | the executed directive spec — **byte-identical** to the `backtest_directives/completed/<id>.txt` that would otherwise be tracked in git |
| `RECYCLE_RULE_SOURCE.py` | the exact rule code that computed the run (e.g. `pine_ratio_zrev_v1_zcross.py`) |
| `indicators_manifest.json` | the indicator modules the rule imports — module id + content-hash (sha256) + registry version; the **third behavioral determinant** alongside the directive spec + rule code (added 2026-06-29) |
| `indicators_snapshot/` | byte copies of those indicator source files — bit-exact reproduction even after a live indicator's logic/params change (added 2026-06-29) |
| `metadata/run_metadata.json` | `run_id`, `engine_version`, `date_range`, `leg_symbols`, `broker` — the provenance keys |
| `raw/` | results (`results_basket_per_bar.parquet` + the `results_*.csv` family) |
| `STRATEGY_CARD.md`, `BASKET_REPORT_*.md` | human-readable run summaries |

> **Indicator provenance (2026-06-29).** `indicators_manifest.json` + `indicators_snapshot/` make the
> capsule the **complete** basket reproduction unit: spec + rule code + indicators all travel with the
> results. Basket reproduction/replay sources from the **capsule** (this folder), not from
> `runs/<run_id>/` — so basket run folders intentionally do **not** carry the indicator manifest (it
> would be redundant). The mirror-image holds for single-asset runs, whose authoritative home is
> `runs/<run_id>/` (no `DIRECTIVE_SOURCE.txt` capsule); they carry the manifest there. Verify with
> `tools/run_indicator_snapshot.py verify <capsule_dir>` (fails loud on drift). Emitter:
> `tools/basket_report.py`; rationale: `outputs/system_reports/08_pipeline_audit/INDICATOR_SNAPSHOT_GAP_2026-06-29.md`.

## The decision rule

```
Is this directive embedded in an execution capsule?
(DIRECTIVE_SOURCE.txt + RECYCLE_RULE_SOURCE.py present in a retained run folder)
                         |
              +----------+----------+
              | YES                 | NO
              v                     v
   The git corpus copy is   git is the ONLY byte-level
   redundant -> the         home -> the directive MUST
   directive MAY be         remain tracked in git.
   untracked.
```

Both directions are binding. The "YES" branch is why `backtest_directives/completed/` is
gitignored (`a0a1bccc`). The "NO" branch is why these stayed tracked at the same time:

- **`90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt`** — a legacy directive with no surviving run
  folder (no capsule). Negated in `.gitignore`; git is its only spec copy.
- **`backtest_directives/archive/`** (366 legacy `v1_raw_adf` directives) — 0% capsule
  coverage (all pre-`60862b4c`). Kept tracked.

## Why reproducibility is NOT lost (read before re-adding the corpus)

Untracking the directive corpus does **not** lose reproducibility, because the spec is not
gone — it has simply moved to its authoritative home, the capsule. A future auditor will be
tempted to think "the directives left git, so we can no longer reproduce these runs." That
reasoning is wrong on three independently-verified points:

1. **The capsule is byte-faithful.** `DIRECTIVE_SOURCE.txt` was verified `diff`-identical to
   the git-tracked directive (2026-06-16; e.g. `90_PORT_UK100XAUUSD_..._BBK20__E260401`,
   2233 bytes, byte-for-byte). At the untrack, **1,491 of 1,492** tracked directives had a
   matching capsule.
2. **The DB is NOT a spec home.** `cointegration_sheet` stores only an **8-character
   truncated fingerprint** (mislabeled `directive_sha256`) + leg/window metadata — it can
   *verify* a directive but cannot *reconstruct* one. Do not cite the DB as the provenance
   home; it isn't.
3. **No history was rewritten.** The untrack used `git rm --cached`, so every directive ever
   committed remains reachable in git history. For *new* cohorts generated under the ignore
   rule (never committed), the capsule is the **sole** byte-level home — which is exactly why
   the capsule's existence is the gate, not an afterthought.

## Durability boundary

A capsule lives in the artifact store (`TradeScan_State`), which is lineage-pruned: the
`/pipeline-state-cleanup` skill removes only run folders **absent from the authoritative
ledgers** (`Master_Portfolio_Sheet`, `Filtered_Strategies_Passed`, `portfolio.yaml`). So a
capsule is retained exactly as long as its run is ledger-referenced. A pruned run is one no
ledger points to — its spec has no decision riding on it and does not need preserving. The
capsule's authority is therefore **lineage-bound, not eternal**, and that is the intended
contract: spec durability tracks run relevance.

## Cross-references

- `.gitignore` — `backtest_directives/completed/*` rule (points back here).
- Untrack commit `a0a1bccc`; emitter commit `60862b4c`.
- Snapshot Immutability (AGENT.md invariant #4) — the capsule is the per-run analogue.
- `outputs/system_reports/08_pipeline_audit/ARTIFACT_STORAGE_AUDIT_2026_03_24.md` — broader artifact-storage map.
- Sibling contracts in this folder: `ENGINE_VAULT_CONTRACT.md`, `ORCHESTRATION_CONTRACT.md`, `STRATEGY_PLUGIN_CONTRACT.md`.
