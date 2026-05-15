# Skill Catalog — `.claude/skills/`

Hand-curated index of every project skill. Use this when picking a skill
to invoke. The system-reminder list at session start is alphabetical and
flat — this file is grouped by intent and pairs each skill with **when
to use** + **when NOT to use** + **related skills**.

> **Source of truth:** the actual `SKILL.md` frontmatter in each folder.
> When you rename, add, or delete a skill, update both that file AND
> this catalog in the same commit.

---

## Quick picker

| If you're about to ... | Reach for |
|---|---|
| Run a directive end-to-end | `/execute-directives` |
| Re-run a previously tested strategy | `/rerun-backtest` |
| Combine 2+ runs into a portfolio | `/run-composite-portfolio` |
| Build a new strategy or port from Pine | `/port-strategy` |
| Promote a strategy to LIVE | `/promote` |
| Snapshot the workspace as a vault entry | `/update-vault` |
| Add or remove a strategy from the active selection | `/portfolio-selection-add` / `/portfolio-selection-remove` |
| Analyze the candidate pool | `/portfolio-research` |
| Format the FSP/MPS spreadsheets | `/format-excel-ledgers` |
| Test a hypothesis on existing runs | `/hypothesis-testing` |
| Run capital wrappers at uniform risk | `/uniform-risk-capital-simulation` |
| End a work session cleanly | `/session-close` |
| Register a long-running Windows daemon | `/launch-windows-supervised-task` |
| Periodic repo hygiene + code DRY | `/repo-cleanup-refactor` |
| Cleanup of pipeline artifacts (runs/, backtests/, etc.) | `/pipeline-state-cleanup` |
| System health audit / governance maintenance | `/system-health-maintenance` |

---

## By category

### 1. Pipeline execution

| Skill | When | When NOT | Related |
|---|---|---|---|
| `execute-directives` | A directive (`.txt`) is sitting in `directives/active/` and you want to run it through the governed pipeline (Stages 0 → 4) | The directive is a re-test of a prior strategy → use `/rerun-backtest` instead | `port-strategy` (created the directive), `promote` (LIVE-ifies the result) |
| `rerun-backtest` | A previously-tested strategy needs re-execution due to data refresh, indicator change, engine update, parameter tweak, or bug fix | First run of a brand-new strategy → use `/execute-directives` after `/port-strategy` | `execute-directives`, `update-vault` |
| `run-composite-portfolio` | You have 2+ completed runs and want to combine them into a single composite portfolio with capital wrappers + robustness suite | Single-strategy run → not needed; portfolio_evaluator handles single-run portfolios automatically | `portfolio-research` (selecting which runs), `uniform-risk-capital-simulation` |

### 2. Strategy lifecycle

| Skill | When | When NOT | Related |
|---|---|---|---|
| `port-strategy` | Building a new `strategy.py` from scratch, including Pine→Trade_Scan ports | Re-running an existing strategy → use `/rerun-backtest` | `execute-directives` (next step) |
| `promote` | A strategy has reached `PIPELINE_COMPLETE` and you want it deployed to TS_Execution as LIVE | Pre-`PIPELINE_COMPLETE` → finish the pipeline first; PORTFOLIO_COMPLETE not yet granted by human → blocked | `update-vault`, `execute-directives` |
| `update-vault` | Need a frozen snapshot of the current workspace state (strategy + indicator + governance + engine versions) | Snapshot already exists for this commit | `promote` (auto-vaults on success), `port-strategy` |

### 3. Portfolio management

| Skill | When | When NOT | Related |
|---|---|---|---|
| `portfolio-research` | Looking at the candidate pool to decide which runs go into a composite | Single-strategy decision → no need | `portfolio-selection-add`, `run-composite-portfolio` |
| `portfolio-selection-add` | Marking one or more strategies as `IN_PORTFOLIO=1` in the master ledgers | Strategy isn't in `Filtered_Strategies_Passed.xlsx` yet | `portfolio-research`, `portfolio-selection-remove` |
| `portfolio-selection-remove` | Clearing the `IN_PORTFOLIO` flag on a strategy | Want to delete the strategy entirely → that's not allowed (append-only ledger) | `portfolio-selection-add` |
| `format-excel-ledgers` | Either spreadsheet (FSP / MPS) needs formatting refreshed (after manual edits or new rows) | DB has been updated but Excel not exported yet → run `tools/ledger_db.py --export` first | — |

### 4. Research workflows

| Skill | When | When NOT | Related |
|---|---|---|---|
| `hypothesis-testing` | An actionable insight from `hypothesis_tester.py` ranks high enough to deserve controlled re-testing | No actionable insights ranked → don't synthesize one | `rerun-backtest`, `execute-directives` |
| `uniform-risk-capital-simulation` | Need to compare capital profiles on a fixed dataset with `risk_per_trade` held uniform across all profiles | Default capital_wrapper run (per-profile risk varies) → use the standard `run-composite-portfolio` flow | `run-composite-portfolio` |

### 5. Maintenance & cleanup (periodic — see `session-close §8b`)

| Skill | When | When NOT | Related |
|---|---|---|---|
| `repo-cleanup-refactor` | Weekend before close, Monday before starting, or after major phase completion. Worktrees, stale branches, root-untracked files, cross-repo state orphans, code DRY (duplicate-function extraction) | Mid-task / mid-pipeline → too disruptive | `session-close` (calls this from §8b.i), `pipeline-state-cleanup` |
| `pipeline-state-cleanup` | Drift-triggered: large MPS delta (≳ 10 new entries), many backtests added (≳ 20), unusual `runs/` growth (≳ 50), or stale strategy folders noticed during work. Lineage-aware prune of `TradeScan_State/runs/`, `backtests/`, `sandbox/`, `strategies/` against the authoritative ledgers | No drift → calendar-running this wastes effort | `session-close` (calls this from §8b.ii), `system-health-maintenance` |
| `system-health-maintenance` | System health audit + workspace hygiene + recovery operations + vault management — non-authoritative governance tooling | Authoritative pipeline work → use `/execute-directives` instead | `pipeline-state-cleanup`, `repo-cleanup-refactor`, `session-close` |

### 6. Operational discipline

| Skill | When | When NOT | Related |
|---|---|---|---|
| `session-close` | Ending a work session — commit, push, document, regenerate `SYSTEM_STATE.md` snapshot, run periodic skills if it's the weekend | Mid-task pause (resuming same session) → skip; trivial read-only session → skip | All maintenance skills (called from §8b) |
| `launch-windows-supervised-task` | Registering a long-running Python daemon under Windows Task Scheduler — Phase 7a-H2 live runner, Stage-5-equivalent field stress, basket_pipeline live runner, TS_Execution H2 shim | One-shot scripts → just invoke directly | `repo-cleanup-refactor` (refactoring code that runs as scheduled task), `system-health-maintenance` (audits scheduled-task drift) |

---

## Distinguishing the three cleanup skills

Easy to confuse — the names were normalized in the 2026-05-15 catalog
introduction so the distinction is now lexical:

| Skill | Scope |
|---|---|
| **`repo-cleanup-refactor`** | The Trade_Scan repo + cross-repo state orphans + code DRY |
| **`pipeline-state-cleanup`** | TradeScan_State pipeline artifact lineage (runs/, backtests/, sandbox/, strategies/) |
| **`system-health-maintenance`** | System audit + recovery + vault — non-authoritative governance tools |

Cadence: `repo-cleanup-refactor` is calendar-weekly (weekend opt-in);
`pipeline-state-cleanup` is drift-triggered only; `system-health-maintenance`
is on-demand (with Phase 1 audit pulled into `session-close §8b.i` for
weekly health check).

---

## Maintenance

When adding a skill:
1. Create `.claude/skills/<slug>/SKILL.md` with `name:` matching the slug.
2. Add a row in the relevant section above + the Quick picker if it's
   a primary entry-point skill.
3. Cross-reference from any sibling skills' "Related skills" sections.
4. If the skill should be discoverable via natural-language routing,
   also add an `INTENT_INDEX.yaml` entry under `outputs/system_reports/`.

When renaming a skill:
1. `git mv .claude/skills/<old> .claude/skills/<new>`
2. Update the `name:` field in its `SKILL.md` frontmatter.
3. Grep for old slug across `.claude/skills/`, `outputs/system_reports/`,
   `CLAUDE.md`, `AGENT.md`, and update.
4. Update this catalog.
5. Run `python tools/audit_intent_index.py --all` (must exit 0).
