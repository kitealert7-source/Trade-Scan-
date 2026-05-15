# Post-Freeze Git Integrity Audit — 2026-05-12

Audit-only. No edits, no auto-fixes, no history rewrites.

## A. Overall result: **PASS**

The repo is in a clean, reproducible Git state after today's 17 commits.

| Part | Result | Notes |
|---|---|---|
| Working tree | **PASS** | Zero tracked modifications, zero staged, only two known leftover untracked dirs (yesterday's) |
| Hidden ignored production files | **PASS** | Zero ignored `.py` / `.yaml` under `indicators/`, `governance/`, `engines/`, `engine_dev/`, `config/`. One intentional carveout in `tools/` (documented). |
| Largest tracked objects | **PASS** | No binary/data files added today (0 .xlsx / .png / .csv / .zip / .db). Historical large objects all under `vault/snapshots/`, `archive/stale_portfolios/`, or `outputs/system_reports/` — none introduced this session. |
| Commit integrity | **PASS** | 17/17 commits single-purpose; subjects match file lists; 17/17 carry `Co-Authored-By` trailer; tests paired with every code-touching commit |

## B. Unexpected files

**Working tree untracked:**

```
archive/2026-05-11_tmp_cleanup/
pine_exports/
```

Both are pre-existing from 2026-05-11 — noted at yesterday's session-close as "safe to evaluate at next session start". Neither is from today's work. Not a finding.

**Hidden ignored files under production paths:**

`git ls-files --others --ignored --exclude-standard | grep ^tools/ | grep '.py$' | grep -v tmp` returned **one** entry:

```
tools/regenerate_all_reports.py
```

This is **intentionally ignored** per the root `.gitignore` under the "Specific tool scripts (local utility, not part of pipeline)" carveout (lines 137–139):

```
tools/new_pass.py
tools/regenerate_all_reports.py
tools/sync_portfolio_flags.py
```

Documented intent: local-utility scripts that are not part of the pipeline, not for review, kept off the source tree. **Not a finding.**

Zero ignored `.py`, `.yaml`, `.yml`, or `.json` under `indicators/`, `governance/`, `engines/`, `engine_dev/`, or `config/`. Today's G1 fix (commit `cd8f3b6`) closed the prior gap in this category — confirmed by re-running the check post-fix.

The remaining ignored files visible in `git ls-files --others --ignored --exclude-standard` are all legitimately ignored:
- `data_root/EXTERNAL_DATA/**` — runtime market data
- `data_root/SYSTEM_FACTORS/**` — runtime artifacts
- `outputs/audit _reports/**`, `outputs/logs/**` — generated reports
- `experiments/results/*.json` — experiment outputs
- `tools/regression/tmp/**`, `tools/tmp/**` — scratch
- `.claude/state/**`, `.claude/settings.local.json` — machine-local state
- `.pytest_cache/**` — test cache

None of these are governance or production code.

## C. Largest tracked objects

### Top 20 across full history

| Size | Path |
|---:|---|
| 3,951.9 KB | `outputs/system_reports/01_system_architecture/REPO_STATE_AFTER_RUN.txt` |
| 3,951.8 KB | `outputs/system_reports/01_system_architecture/REPO_STATE_BASELINE.txt` |
| 403.6 KB | `data_root/metadata/pipeline_hash_registry.json` |
| 342.8 KB | `vault/snapshots/DR_BASELINE_2026_04_20_v1_5_7/governance/events.jsonl` |
| 334.4 KB | `vault/snapshots/DR_BASELINE_2026_04_20_v1_5_6/governance/events.jsonl` |
| 302.0 KB | `BACKUPDATA/ORB_FX_01/portfolio_evaluation/correlation_matrix.png` |
| 300.3 KB | `BACKUPDATA/C_ORB_FX_01/portfolio_evaluation/correlation_matrix.png` |
| 265.7 KB | `vault/snapshots/DR_BASELINE_2026_04_19_v1_5_6_capability_full/governance/events.jsonl` |
| 225.6 KB | `vault/snapshots/DR_BASELINE_2026_04_19_v1_5_6/governance/events.jsonl` |
| 195.8 KB | `outputs/reports/IDX19_equity_curves/IDX19_AGGREGATE_equity.png` |
| 183.9 KB | `archive/stale_portfolios/01_MR_FX_1H_ULTC_REGFILT_S07_V1_P03_STALE/deployable/DYNAMIC_V1/equity_curve.png` |
| ... | (rest are similarly-sized `equity_curve.png` files under `archive/stale_portfolios/`) |

**None of these were added today.** They are all historical:
- `REPO_STATE_*.txt` — pre-2026-05 architecture snapshots
- `events.jsonl` inside vault — frozen baseline event logs (vault is explicitly re-included via the `!vault/` exception)
- `correlation_matrix.png` / `equity_curve.png` — under `BACKUPDATA/` and `archive/stale_portfolios/`, both expected dumping grounds

### Top 20 added/modified TODAY

All are source files (Python or markdown):

| Size | Path |
|---:|---|
| 86.6 KB | `indicators/INDICATOR_REGISTRY.yaml` (after 22-stub backfill, 67 entries × rich metadata) |
| 46.8 KB | `tests/test_family_report_phase_b.py` |
| 41.7 KB | `tools/run_pipeline.py` |
| 41.3 KB | `tools/system_introspection.py` |
| 41.2 KB | `outputs/FAMILY_REPORT_DESIGN.md` |
| 38.5 KB | `tools/semantic_validator.py` |
| 35.3 KB | `outputs/system_reports/04_governance_and_guardrails/GOVERNANCE_DRIFT_PREVENTION_PLAN.md` |
| 31.2 KB | `tests/test_indicator_registry_sync_hook.py` |
| 29.5 KB | `tools/report/family_renderer.py` |
| 26.2 KB | `tools/family_report.py` |
| 21.4 KB | `tools/verify_engine_integrity.py` |
| 20.2 KB | `outputs/FAMILY_REPORT_IMPLEMENTATION_PLAN.md` |
| 18.4 KB | `outputs/REPORT_AUDIT.md` |
| 17.0 KB | `outputs/REPORT_UPGRADE_PLAN.md` |
| 16.8 KB | `.claude/skills/session-close/SKILL.md` |
| 13.1 KB | `tools/orchestration/stage_portfolio.py` |
| 11.8 KB | `tools/utils/research/simulators.py` |
| 11.7 KB | `outputs/INDICATOR_REGISTRY_BACKFILL_PLAN.md` |
| 11.3 KB | `tests/test_indicator_allowlist_enforcement.py` |
| 10.6 KB | `outputs/INDICATOR_GOVERNANCE_SYNC_2026_05_12.md` |

**Zero binary/data files added today.** Specifically checked: 0 `.xlsx`, 0 `.png`, 0 `.csv`, 0 `.zip`, 0 `.db`, 0 `.parquet`, 0 `.h5`, 0 `.pkl`, 0 `.jpg`, 0 `.pdf`. Not a finding.

## D. Commit integrity

### Per-commit file count

| Commit | Files | Subject |
|---|---:|---|
| `4ac360f` | 2 | infra: restore portfolio report generation under state root |
| `e85192b` | 8 | reporting: phase B follow-ups for family analysis UX |
| `5a354db` | 4 | infra: indicator registry as Stage-0.5 allowlist authority |
| `f053e9a` | 5 | infra: pre-commit forcing function for indicator registry sync |
| `9048014` | 3 | infra: session-close blocks on indicator registry drift |
| `d09c0db` | 3 | infra: pre-push hook blocks indicator registry drift at network boundary |
| `9e1a929` | 4 | infra: runtime gates block indicator registry drift |
| `ebdd429` | 3 | infra: enforce append-only invariant on supersession_map.yaml |
| `e40771e` | 1 | docs: archive governance drift prevention audit |
| `009311c` | 2 | infra(D4): simulators robust to intra-bar entry/exit trades |
| `cd8f3b6` | 10 | infra: restore version control over production research modules (G1) |
| `6592c50` | 2 | infra(D3): enriched diagnostic when family has no usable MF rows |
| `0dac533` | 1 | session: closing SYSTEM_STATE snapshot |
| `7388453` | 2 | infra: backfill 22 indicator-registry stubs to structural completeness |
| `a497a40` | 1 | session: refresh SYSTEM_STATE post-backfill close |
| `670bf02` | 3 | infra: preserve SYSTEM_STATE manual notes across regeneration |
| `a29de74` | 1 | session: closing SYSTEM_STATE snapshot |

Median: 3 files. Max: 10 (`cd8f3b6`, G1 — gitignore fix + 5 production modules + test + audit doc, coherent).

### Test-fix pairing

Every commit that touches `tools/*.py` ALSO touches `tests/*.py` for the same concern:

```
$ for commit; do tool_files vs test_files; done | grep -v "tests"
(no commits touched tools without tests)
```

100% test-fix pairing. Not a finding.

### Mixed-concerns scan

Spot-checked the 4 largest commits and the 4 smallest:
- `cd8f3b6` (10 files): all related to G1 (gitignore restoration). Single concern.
- `e85192b` (8 files): all related to Phase B reporting (latest-only / Δ-prior-run / promotion summary). Single concern within the workstream.
- `5a354db`, `f053e9a` (4-5 files each): tightly scoped to the indicator registry layer.
- 1-file session commits: only `SYSTEM_STATE.md`, as expected.

No commit mixes governance + reporting + path-fix concerns. Single-purpose discipline held.

### Co-Authored-By trailer presence

17 / 17 commits carry the `Co-Authored-By: Claude` trailer. Not a finding.

### Docs ↔ code alignment

Spot-checks:
- `670bf02` body claims it preserves the Manual section verbatim → tests in `tests/test_system_state_manual_persist.py` directly pin that contract (Case 1, byte-for-byte assertion).
- `7388453` body claims 22 indicators backfilled → registry diff shows exactly 22 entries upgraded from stub to rich-metadata form.
- `cd8f3b6` body claims `tools/.gitignore:5` and `.gitignore:12` anchored → diff confirms both lines changed `research/` → `/research/`.

No drift detected.

## E. Lingering governance risks

**None active.** Today's session closed every governance issue it opened:

| Issue surfaced today | Closure commit |
|---|---|
| Indicator registry drift (22 modules missing) | `5a354db` + `f053e9a` (+ session-close gate `9048014`, pre-push `d09c0db`, runtime `9e1a929`) |
| Supersession map append-only invariant ungated | `ebdd429` |
| Portfolio report path ambiguity | `4ac360f` |
| Family-report renderer crash on intra-bar trades | `009311c` |
| Production code in `tools/utils/research/` outside git (source-of-truth corruption) | `cd8f3b6` |
| MF-missing error message unactionable | `6592c50` |
| Indicator registry structurally incomplete (22 stubs missing metadata) | `7388453` |
| `SYSTEM_STATE.md` Manual section silently destroyed on regen | `670bf02` |

Three test failures remain in `tests/` but are all pre-existing (`test_state_paths_worktree` ×2 + `test_indicator_semantic_contracts` ×1) and documented in `SYSTEM_STATE.md`'s Manual section. Not introduced by today's work, not blocking.

## Hard-rule compliance

- ✓ No files edited
- ✓ No files staged
- ✓ No commits made
- ✓ No history rewrites

This audit document is the only file added (`outputs/POST_FREEZE_GIT_AUDIT.md` itself, untracked at time of audit-write).

## Summary one-liner

**Repo is in PASS state. 17 single-purpose commits, zero binary artifacts, zero ignored production code, full test-fix pairing, full commit-trailer compliance, all governance issues opened today closed today.**
