# REPORT_OWNERSHIP_AUDIT — Trade_Scan vs TradeScan_State boundary

**Date:** 2026-05-11
**Scope:** Read-only inventory of strategy-decision and family-analysis artifacts. Proposes canonical placement under the principle that `Trade_Scan/` is source/governance (tracked) and `TradeScan_State/` is generated artifacts (untracked, no .git).
**No file moves. No code changes. No wrapper creation.**

---

## 1. TL;DR

The biggest violation is `tools/family_report.py` writing auto-generated family reports to `outputs/family_reports/` inside the Trade_Scan repo (`tools/family_report.py:83`, `:152-156`) — these are rebuildable artifacts that belong in `TradeScan_State/`. They are not in git (covered by an `outputs/` exception for ad-hoc design docs alongside them), but they're physically on the source-code surface and grow on every invocation. Proposed fix: point `_OUTPUT_DIR` at `TRADE_SCAN_STATE / "reports" / "families"`; keep the existing four design docs and one-off decision memo in `outputs/` as governance. Migration headcount: 3 files to MOVE (today's two auto-generated family reports + today's promotion decision memo) plus 1 code-level follow-up (the `_OUTPUT_DIR` line in `tools/family_report.py`). Per-strategy `REPORT_*.md`, `AK_Trade_Report*.xlsx`, `STRATEGY_CARD.md`, and `PORTFOLIO_*.md` already live correctly under `TradeScan_State/` — no movement needed for those.

---

## 2. Part A — Current placement audit

`TradeScan_State/` is not a git repo (verified: no `.git` directory present; README explicitly forbids source code). Trade_Scan's `.gitignore` lines 71-72 also blanket-ignore the path. Anything written there is automatically off the source-control surface. Below, **Generated** = rebuildable runtime output; **Source/Governance** = hand-authored long-lived doc.

| # | Artifact | Current path | Kind | Boundary status |
|---|---|---|---|---|
| 1 | `psbrk_finalist_decision_2026_05_11.md` (promotion memo) | `Trade_Scan/outputs/` | Generated (one-off analysis) | VIOLATES — runtime artifact in Trade_Scan/ |
| 2 | `family_psbrk_24m_report.md` (hand-authored reference) | `Trade_Scan/outputs/` | Source/Governance (pre-tool reference) | OK (governance; effectively the spec for tool #3) |
| 3 | Auto-generated family reports `outputs/family_reports/<prefix>_<TS>.md` | `Trade_Scan/outputs/family_reports/` | Generated (every invocation) | VIOLATES — `tools/family_report.py:83` hardcodes destination |
| 4 | Per-strategy report `REPORT_<directive>.md` | `TradeScan_State/backtests/<dir>_<sym>/` | Generated | OK |
| 5 | `STRATEGY_CARD.md` (where present) | `TradeScan_State/backtests/<dir>_<sym>/` | Generated | OK |
| 6 | `AK_Trade_Report_*.xlsx` | `TradeScan_State/backtests/<dir>_<sym>/` | Generated | OK |
| 7 | Multi-asset `PORTFOLIO_<id>.md` | `TradeScan_State/strategies/<id>/` (e.g. PF_C1CEF8DD9C48) | Generated | OK (single-asset skipped per Phase A §4.10) |
| 8 | `portfolio_overview.md` per strategy | `TradeScan_State/strategies/<id>/portfolio_evaluation/` | Generated | OK |
| 9 | Design doc `REPORT_AUDIT.md` | `Trade_Scan/outputs/` | Source/Governance | OK (tracked, long-lived) |
| 10 | Design doc `REPORT_UPGRADE_PLAN.md` | `Trade_Scan/outputs/` | Source/Governance | OK (tracked) |
| 11 | Design doc `FAMILY_REPORT_DESIGN.md` | `Trade_Scan/outputs/` | Source/Governance | OK (tracked) |
| 12 | Design doc `FAMILY_REPORT_IMPLEMENTATION_PLAN.md` | `Trade_Scan/outputs/` | Source/Governance | OK (tracked) |
| 13 | `CODE_REVIEW_ISSUES_CONSOLIDATED.md` | `Trade_Scan/outputs/` | Source/Governance | OK (tracked) |
| 14 | `NEWS_CALENDAR_INGESTION_PLAN.md` | `Trade_Scan/outputs/` | Source/Governance | OK (tracked) |
| 15 | System reports `outputs/system_reports/**/*` | `Trade_Scan/outputs/system_reports/` | Source/Governance | OK (tracked) |
| 16 | `outputs/v158_probe/**/*` (CSV + JSON) | `Trade_Scan/outputs/v158_probe/` | Generated (engine-probe artifacts) | VIOLATES — runtime artifact under outputs/. CSVs are gitignored by `*.csv`, JSON is not |
| 17 | `governance/idea_gate_overrides.csv` | `Trade_Scan/governance/` | Generated (runtime audit log) | OK (gitignored via `*.csv`; lives next to governance source) |
| 18 | `governance/reset_audit_log.csv` | `Trade_Scan/governance/` | Generated | OK (gitignored via `*.csv`) |
| 19 | `governance/events.jsonl` | `Trade_Scan/governance/` | Generated | OK (explicitly gitignored line 119) |
| 20 | `governance/stop_contract_audit.jsonl` | `Trade_Scan/governance/` | Generated | MINOR — not gitignored, currently untracked, but no rule excludes future commits |
| 21 | `TradeScan_State/research/run_summary.csv` | `TradeScan_State/research/` | Generated | OK |
| 22 | `TradeScan_State/hypothesis_log.json` | `TradeScan_State/` | Generated | OK |
| 23 | `outputs/*.docx` (Code_Review trio) | `Trade_Scan/outputs/` | Source/Governance (deliverable artifacts) | OK (gitignored by `outputs/*.docx` line 124 but committed earlier) |

**Summary:** 3 paths physically violate the boundary today (#1, #3, #16). #20 is a latent ignore-rule gap. Everything else either correctly lives in `TradeScan_State/` or is a tracked governance document under `outputs/`.

---

## 3. Part B — Recommended canonical structure

```
TradeScan_State/
  backtests/<dir>_<sym>/
    REPORT_<directive>.md          # KEEP — already correct (Stage-2 owner)
    STRATEGY_CARD.md               # KEEP — Stage-2 owner
    AK_Trade_Report_*.xlsx         # KEEP
    raw/, metadata/                # KEEP — engine raw output
  strategies/<id>/
    PORTFOLIO_<id>.md              # KEEP — multi-asset only
    portfolio_evaluation/...       # KEEP
    deployable/...                 # KEEP
  reports/                         # NEW — root for cross-strategy / decision artifacts
    families/                      # auto-generated family analyses (family_report.py target)
    decisions/                     # one-off promotion / finalist memos
    archive/                       # frozen historical decisions
  research/                        # KEEP — run_summary.csv, indices
  ledgers/, runs/, registry/...    # KEEP — unchanged
```

### Rationale per branch

- **Per-strategy `REPORT_<directive>.md` stays co-located with raw artifacts** under `TradeScan_State/backtests/<dir>_<sym>/`. Stage-2 + report-tooling assumes that path (`tools/orchestration/stage_portfolio.py:169` reads `BACKTESTS_DIR` from `config/state_paths.py:112` → `STATE_ROOT/backtests`). Moving them would force a Stage-2 path rewrite, break `tools/report/report_strategy_portfolio.py:26-32` (navigates `strategies/<name>/portfolio_evaluation`), and break hyperlinks in existing `STRATEGY_CARD.md` files. The current co-location IS canonical — the per-strategy report is part of the per-run artifact bundle, not a separate "report" surface.
- **New `TradeScan_State/reports/families/`** for `tools/family_report.py` output. Family reports are cross-variant analyses that don't belong inside any single `backtests/<dir>_<sym>/` bundle — they're naturally a sibling directory. Mirrors how `family_report.py` already invents its own folder, just relocated to State.
- **New `TradeScan_State/reports/decisions/`** for one-off promotion memos like `psbrk_finalist_decision_2026_05_11.md`. These are runtime decision evidence, not source. They will accumulate — `decisions/` keeps them out of `families/` (which is tool-owned and timestamp-keyed) while still grouping them semantically.
- **New `TradeScan_State/reports/archive/`** for explicitly frozen historical decisions. Optional today; useful when a decision is superseded but worth retaining for lineage. Could be skipped initially and added when first needed.
- **Design docs stay in `Trade_Scan/outputs/`** (NOT moved to `outputs/system_reports/`):
  - `REPORT_AUDIT.md`, `REPORT_UPGRADE_PLAN.md`, `FAMILY_REPORT_DESIGN.md`, `FAMILY_REPORT_IMPLEMENTATION_PLAN.md` are active workstream documents, not finalized architecture audits.
  - `outputs/system_reports/` follows a numbered topical taxonomy (`04_governance_and_guardrails/`, `06_strategy_research/`, etc.). The reporting-stack workstream doesn't fit any current bucket — creating `12_reporting_stack/` would be premature and would imply finality these docs don't yet have.
  - Recommendation: leave at `outputs/*.md` for now. When Phase A and Phase B ship, promote finalized versions into a new `outputs/system_reports/12_reporting_stack/` and let the working drafts archive naturally.
- **`outputs/system_reports/` itself stays in Trade_Scan** regardless of policy enforcement. INTENT_INDEX.yaml is referenced by hooks; READMEs are cross-linked from CLAUDE.md. Tracked in git intentionally.

### Alternative considered and rejected

Moving per-strategy reports into `TradeScan_State/reports/strategies/<id>/REPORT_<id>.md` was rejected because:
1. Stage-2 reads them via `BACKTESTS_DIR / f"{clean_id}_{symbol}"` — a move forces a code change in the most-touched part of the pipeline.
2. `STRATEGY_CARD.md` and `AK_Trade_Report_*.xlsx` would either need to move too (and break Stage-2 in the same way) or stay separated from their report (worse than today).
3. The per-strategy report is naturally a child of the per-run artifact bundle. The new `reports/` directory should hold artifacts that DON'T have a natural per-run home — family analyses, cross-variant decisions, archives.

---

## 4. Part C — Migration plan

| # | Artifact | Current path | Action | Target path | Notes |
|---|---|---|---|---|---|
| 1 | `psbrk_finalist_decision_2026_05_11.md` | `Trade_Scan/outputs/` | MOVE | `TradeScan_State/reports/decisions/` | One-off; safe move; nothing links to it yet |
| 2 | `family_psbrk_24m_report.md` | `Trade_Scan/outputs/` | KEEP | (same) | Hand-authored reference; effectively the spec for tool #3. Lives in Trade_Scan as governance. Alternative: MOVE to `reports/archive/` once tool output has fully superseded it. Defer until tool report is validated equivalent. |
| 3 | `outputs/family_reports/65_BRK_XAUUSD_5M_PSBRK_20260511_144240.md` | `Trade_Scan/outputs/family_reports/` | MOVE | `TradeScan_State/reports/families/` | Today's runs; cheap to move |
| 4 | `outputs/family_reports/65_BRK_XAUUSD_5M_PSBRK_20260511_161703.md` | same | MOVE | same | same |
| 5 | `REPORT_AUDIT.md` | `Trade_Scan/outputs/` | KEEP | (same) | Active workstream; promote to `outputs/system_reports/12_reporting_stack/` post-ship |
| 6 | `REPORT_UPGRADE_PLAN.md` | same | KEEP | same | same |
| 7 | `FAMILY_REPORT_DESIGN.md` | same | KEEP | same | same |
| 8 | `FAMILY_REPORT_IMPLEMENTATION_PLAN.md` | same | KEEP | same | same |
| 9 | `CODE_REVIEW_ISSUES_CONSOLIDATED.md`, `NEWS_CALENDAR_INGESTION_PLAN.md` | same | KEEP | same | Governance |
| 10 | `outputs/system_reports/**/*` | same | KEEP | same | Architecture/audit corpus; part of codebase |
| 11 | `outputs/v158_probe/` | `Trade_Scan/outputs/` | MOVE | `TradeScan_State/sandbox/v158_probe/` (or similar) | Engine-probe runtime artifacts; CSVs already gitignored; JSON should not be in source tree |
| 12 | `outputs/*.docx` (Code_Review trio) | `Trade_Scan/outputs/` | KEEP | same | Already gitignored per `.gitignore:124`; staying is harmless. Optional: MOVE to `TradeScan_State/reports/archive/code_reviews/` |
| 13 | `governance/idea_gate_overrides.csv` | `Trade_Scan/governance/` | DEFER (DUPLICATE-OR-MOVE) | `TradeScan_State/ledgers/governance_audit/` (option) | Gitignored today; works fine. Move only if cross-repo standardization is desired. |
| 14 | `governance/reset_audit_log.csv` | same | DEFER | same | same reasoning |
| 15 | `governance/events.jsonl` | same | KEEP | same | Gitignored, lives next to runtime governance code |
| 16 | `governance/stop_contract_audit.jsonl` | same | KEEP + IGNORE FIX | same + add `governance/*.jsonl` to `.gitignore` | Add the ignore rule before any future commit picks it up |

### Code-level follow-ups (separate change tasks; not part of this audit)

| Code site | Issue | Required edit |
|---|---|---|
| `tools/family_report.py:83` | Hardcoded `_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "family_reports"` | Change to `_OUTPUT_DIR = TRADE_SCAN_STATE / "reports" / "families"` (TRADE_SCAN_STATE already imported on line 49) |
| `tools/family_report.py:152-156` | Uses `_OUTPUT_DIR` for default destination | Auto-fixed by line-83 change; no separate edit needed |
| `tools/orchestration/stage_portfolio.py:173` | Comment on this line already flags ambiguity (`# project_root here for code? usually reports go to outputs/ or repo`). Currently OK because Phase A §4.10 skip suppresses single-asset writes (`Trade_Scan/strategies/<id>/PORTFOLIO_*.md` files don't exist). But multi-asset PORTFOLIO_*.md writes DO appear under `TradeScan_State/strategies/PF_*/` — suggesting a different code path. Verify this before any movement. | Audit `generate_strategy_portfolio_report` callers; if multi-asset PORTFOLIO_*.md goes through `STATE_ROOT`, single-asset Phase A skip path is effectively dead-code and the parameter mismatch should be standardized to `STATE_ROOT`. |
| Future ad-hoc decision memos | Will silently violate the policy if written under `outputs/` | Add a one-line CONTRIBUTING note: decision memos go to `TradeScan_State/reports/decisions/`, not `outputs/` |
| `.gitignore` | Missing rule for `governance/*.jsonl` (only `events.jsonl` listed) | Add `governance/*.jsonl` to cover future audit logs (currently `stop_contract_audit.jsonl` is untracked but not ignored) |

---

## 5. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Stage-2 tooling assumes per-strategy reports live in `BACKTESTS_DIR/<dir>_<sym>/`.** Moving them would break the report-generator chain. | High | Plan correctly keeps them in place. No code change required for per-strategy reports. |
| **`outputs/family_reports/` may be referenced by existing hand-authored docs.** Moving auto-generated family reports breaks any markdown link in `family_psbrk_24m_report.md` or `psbrk_finalist_decision_2026_05_11.md` that points into that directory. | Medium | Grep both docs for `outputs/family_reports` before moving. |
| **`.gitignore` line 71 (`../TradeScan_State/`) is path-relative.** If `TradeScan_State` is reached via a path that doesn't match, generated artifacts could leak back into git history. | Medium | Confirmed `TradeScan_State/` has no `.git` — Trade_Scan's git index never sees those files from inside the Trade_Scan repo. Worktree-safety relies on `config/path_authority.py` (existing rules cover this). Verify the family_report.py code edit uses `TRADE_SCAN_STATE` from `path_authority`, not a literal path. |
| **Other callers of `outputs/family_reports/`.** Other scripts may hardcode the old output dir. | Low | Grep `outputs/family_reports` across the repo before applying the code fix. |
| **The 4 active design docs are cross-linked.** Moving any one would break in-doc links in the others. | Low | Plan KEEPs all four. |
| **Promotion-decision memos accumulate in `TradeScan_State/reports/decisions/` indefinitely.** | Low | Defer: add `archive/` move policy when count exceeds a threshold. Naming convention `<family>_<event>_<YYYY_MM_DD>.md` supports chronological sort. |
| **`outputs/v158_probe/` move may invalidate historical references in `memory/`.** | Low | Grep `memory/` for `v158_probe` before the move. Probe outputs are typically scratch. |

---

## Appendix — git-state facts

- `TradeScan_State/` has no `.git` — not a separate repo. Trade_Scan's `.gitignore` lines 71-72 prevent accidental addition.
- `outputs/family_reports/` and `outputs/psbrk_finalist_decision_2026_05_11.md` show as Untracked in `git status` — not gitignored, just not yet added.
- `outputs/system_reports/` is fully tracked (50+ markdown files committed).
- Design docs (#9-#14) all tracked in git as of HEAD.
- `outputs/*.docx` is gitignored (`.gitignore:124`).
- `outputs/v158_probe/*.csv` gitignored (`*.csv` line 50); JSON in that tree is not.
- `governance/idea_gate_overrides.csv` and `governance/reset_audit_log.csv` gitignored via `*.csv`.
- `governance/events.jsonl` gitignored explicitly.
- `governance/stop_contract_audit.jsonl` NOT gitignored, currently untracked. Add `governance/*.jsonl`.
