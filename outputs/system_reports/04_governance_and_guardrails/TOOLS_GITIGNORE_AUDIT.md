# tools/.gitignore Audit — 2026-05-12

Documents the scope of a source-of-truth corruption surfaced
incidentally by Patch D4 (see commit `009311c` `infra(D4):
simulators robust to intra-bar entry/exit trades`).

## Correction note (added during G1 implementation)

The original audit framed `tools/.gitignore:5:research/` as the
offending rule and the root `.gitignore:12:research/` as the
"intended top-level" rule. That was incomplete — **the root pattern
is unanchored too** and was *also* matching `tools/utils/research/`.
The audit's reasoning held but the fix scope was wrong: anchoring
only `tools/.gitignore` would have left the BUG live because the root
rule alone keeps the modules ignored.

Patch G1 anchored BOTH rules in one commit. The audited intent
(top-level scratch ignored, nested production tracked) is preserved
by the anchored form `/research/`. See the regression test
`tests/test_gitignore_production_imports.py` for the recurrence pin.

---

## Q1 — Was `research/` intended top-level or all-descendants?

**Intended top-level. Pattern is wrong.**

Evidence:

- `tools/.gitignore:1-5` is a *byte-for-byte copy* of `.gitignore:9-12`:
  ```
  # Runtime artifacts (never commit)
  backtests/
  runs/
  results/
  research/
  ```
  Same comment, same four patterns. `tools/.gitignore` is a stale
  duplicate of the root rule.

- The intent at the root level was clearly the top-level `research/`
  directory — a runtime mirror of `TradeScan_State/research/`
  (run_summary.csv, hypothesis_log.json, RESEARCH_MEMORY.md, etc.).
  None of those artifacts live under `tools/`.

- gitignore pattern semantics: `research/` (unanchored) matches a
  directory named `research` **at any depth** below the gitignore file's
  location. `/research/` (anchored) would only match the immediate
  child. The current pattern, in `tools/.gitignore`, therefore matches:
  - `tools/research/` (doesn't exist)
  - `tools/utils/research/` ← **6 production modules silently excluded**
  - `tools/anywhere/research/` (doesn't exist)

- `tools/.gitignore` has exactly **one** commit in history:
  `9a6be58 add completed directives, new indicator, backup tool, vault
  snapshot v1.5.3`. Likely copy-pasted from `.gitignore` during a
  v1.5.3 bulk commit without thinking through the path-scope semantics.

**Correct fix shape (not applied):** change `research/` to `/research/`
in `tools/.gitignore` — or delete the file entirely since every rule
in it duplicates the root `.gitignore`.

---

## Q2 — Gitignored-but-imported modules + tracked importers

`tools/utils/research/` contents:

```
__init__.py            IGNORED (no importers — package marker)
block_bootstrap.py     IGNORED
drawdown.py            IGNORED
friction.py            IGNORED
robustness.py          IGNORED  ← biggest hub
rolling.py             IGNORED
simulators.py          TRACKED  ← force-added today via Patch D4
```

**Active tracked importers per module** (excluding `vault/snapshots/*`
and `archive/*`):

| Ignored module | Active tracked importers |
|---|---|
| **`block_bootstrap`** (4 importers) | `tests/test_family_report_phase_b.py`, `tools/family_report.py`, `tools/robustness/bootstrap.py`, `tools/tests/freeze_baselines.py` |
| **`drawdown`** (2 importers) | `tools/family_report.py`, `tools/robustness/drawdown.py` |
| **`friction`** (3 importers) | `tests/test_family_report_phase_b.py`, `tools/family_report.py`, `tools/robustness/friction.py` |
| **`robustness`** (8 importers — highest) | `tests/test_simulators_same_bar_trade.py`, `tools/family_report.py`, `tools/report/family_verdicts.py`, `tools/report/report_sections/verdict_risk.py`, `tools/robustness/directional.py`, `tools/robustness/symbol.py`, `tools/robustness/tail.py`, `tools/robustness/temporal.py` |
| **`rolling`** (2 importers) | `tools/family_report.py`, `tools/robustness/rolling.py` |
| **`simulators`** (4 importers — now tracked) | `tests/test_family_report_phase_b.py`, `tests/test_simulators_same_bar_trade.py`, `tools/family_report.py`, `tools/robustness/monte_carlo.py` |

**Hub view:** `tools/family_report.py` imports **all 6** modules (today's
work depends entirely on this invisible subtree). The Phase A
`verdict_risk.py` and the family-verdicts orchestrator also reach
into it. The wider `tools/robustness/` package — which contains the
deployable robustness suite — has an importer per ignored module.

**A fresh clone would fail at import time for any of these importers if
the local `tools/utils/research/*.py` files are not present.** They
are present locally only because they were authored before the
gitignore rule was added (early-2026), and have been edited in place
since without ever being committed.

---

## Q3 — Classification

**BUG.**

This is *source-of-truth corruption*. Production code that is
imported by tracked modules is itself outside version control. Every
governance gate today's session has hardened — pre-commit hooks,
Stage-0.5 admission, session-close drift checks, the registry-sync
forcing function — presupposes that production code is in git. None
of them inspect `tools/utils/research/*.py`. The byte content on disk
is unrecoverable from any commit, undiff-able across worktrees, and
unrestorable from upstream.

Concrete failure modes that are already latent today:

1. **Diverging clones.** Another machine running this repo will not
   have the latest `_simulate` fix from Patch D4 unless it manually
   re-applies it. The fix landed in git only because I used
   `git add -f` for that one file; the other 5 ignored modules remain
   unsynced.

2. **No code review.** Changes to `robustness.py`, `drawdown.py`,
   etc. cannot land in a PR. They are invisible to `git diff`. There
   is no commit history to audit.

3. **No tampering signal.** `tools/tools_manifest.json` (the guard
   manifest) cannot hash an ignored file — so silent edits to
   `simulate_percent_path`, `early_late_split`, or any other
   primitive cannot be detected even though they affect the family
   report and verdict_risk outputs.

4. **The Rule-3 forbidden-import list in `family_report.py` is
   provably ineffective today.** The audit yesterday noted that
   `simulators` is reached transitively through `early_late_split`.
   That observation has more force now: `early_late_split` lives in
   `robustness.py`, which is itself ignored — so the call chain that
   violates the "forbidden direct import" rule cannot be inspected
   without filesystem access to a specific clone.

5. **Patch D4's commit landed asymmetrically.** Only `simulators.py`
   is now tracked. `robustness.py` (which calls it) is still
   ignored. A fresh checkout would get `simulators.py` (with the
   intra-bar fix) but no `robustness.py` — so the importer would
   `ImportError` immediately.

The fix for the BUG is mechanically small (one or two lines in
`tools/.gitignore`, then `git add -f` the affected files in a single
commit). The harder part is verifying the historical contents are
authoritative — given that nothing has ever been committed, there is
no record of what each function should be doing. The current disk
state is the only source. Treat that as the canonical baseline; any
future fixes go through git from this point onward.

---

## Why this outranks D3

D3 ("better diagnostic when MF rows missing for a family prefix") is
an *operator-experience* fix: clearer log messages, no behavioral
change. The current behavior already fails closed (the reporter
raises SystemExit). The diagnostic is poor but the safety is fine.

This gitignore corruption is *source-of-truth* breakage. It violates
the invariant that all production code is in git, which underwrites
every governance gate today's work hardened. Fixing diagnostics on a
system whose underlying code is partially untracked is governance
theater.

Recommended order:

1. **This audit** (now — done, this file).
2. **`tools/.gitignore` fix + force-add of the 5 remaining modules**
   in a single commit, with the disk state as canonical baseline.
3. **Then D3** — diagnostic improvement on the now-fully-tracked
   reporting path.

The fix in (2) is small in line count but operationally important:
no behavioral change, just bringing 5 production modules into version
control with their current disk content as the baseline commit.

---

## Appendix — gitignore pattern reference

Source: [gitignore docs](https://git-scm.com/docs/gitignore).

| Pattern | Match scope (relative to gitignore location) |
|---|---|
| `research/` | Directory named `research` at ANY depth below this gitignore file |
| `/research/` | Directory named `research` at the SAME depth as this gitignore file |
| `research/*` | Files directly under any `research/` directory at any depth |
| `**/research/` | Equivalent to `research/` — explicit any-depth match |

The fix is to use `/research/` (anchored), which would scope to
`tools/research/` only — a directory that doesn't exist and never has,
making the rule a no-op in this gitignore. That is the intended
semantic: the runtime `research/` directory the rule is supposed to
catch is at the **root** of the repo, governed by the root
`.gitignore`, not by `tools/.gitignore`.

---

## Files surveyed for this audit

| File | Role |
|---|---|
| `tools/.gitignore` | The offending gitignore. 1 commit in history (`9a6be58`). 39 lines, all duplicating root rules. |
| `.gitignore` | Authoritative root gitignore. Has the same `research/` pattern, but at the root level this is the intended runtime-artifact directory. |
| `tools/utils/research/__init__.py` | Package marker. Currently ignored. |
| `tools/utils/research/{block_bootstrap,drawdown,friction,robustness,rolling}.py` | 5 production modules, all ignored. |
| `tools/utils/research/simulators.py` | Force-added in commit `009311c` today. |
| Output of `git ls-files \| grep tools/utils/research/` | One line: `tools/utils/research/simulators.py`. Confirms the asymmetry. |

---

## Decision pending

No fixes applied. Awaiting direction on:

- Approve the proposed fix shape (change `research/` to `/research/` in
  `tools/.gitignore`, then `git add -f` the 5 remaining production
  modules with their current disk content as the baseline commit).
- Or alternative scope (delete `tools/.gitignore` entirely since it
  duplicates the root, move the rule semantics differently, etc.).
- Or hold and revisit later (the bug is latent but not actively
  blocking anything today — production runs work because disk state
  is correct on this machine).
