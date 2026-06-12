---
name: hypothesis-testing
description: Unified orchestrator for backtest-from-a-hypothesis (single-asset + basket): classify → form → run → analyse → record.
---

# /hypothesis-testing — research orchestrator (single-asset + basket)

THE one place a backtest-from-a-hypothesis run starts. One command, one spine, both asset
classes. Read this, classify the hypothesis, follow the matching branch.

> **Principle:** *Humans decide what to test. The orchestrator determines how to test it
> rigorously.*

It classifies a human-proposed hypothesis and runs the matching workflow faithfully. It
never refuses, skips, or pre-rejects.

---

## 0 · Downstream contract (binds the delegates)

The delegated skills — [`/generate-directives`](../generate-directives/SKILL.md) (stage 2)
and [`/execute-directives`](../execute-directives/SKILL.md) (stage 3) — receive a classified
hypothesis plus a reference run (or a new-corpus signal) and proceed. They **must not** apply
worth-gates, overlap checks, diversity constraints, past-success thresholds, dead-strategy
skips, or any pre-validation rejection. On a *technical* blocker (e.g. reference-run folder
missing, integrity check fails) they report it and halt — they do **not** decline a
hypothesis on grounds of likelihood, redundancy, or resource priority.

---

## The spine (every branch runs all five)

```
1. classify    ← this skill (the table below)
2. form        → /generate-directives   (transform vs generator)
3. run         → /execute-directives     (governed Golden Path)
4. analyse     ← canonical, vs the LOCKED reference run
5. record      → research_memory_append.py (incl. nulls)
```

Stages 1, 4, 5 are spelled out below; 2 and 3 are owned by the linked skills.

---

## 1 · Classify

> **BASKET VARIANTS — the one distinction that picks the comparison table:**
> **mechanic = rule change on the same legs · architecture = legs change on the same rule.**
> If both move it is two hypotheses — see "two moving variables" below.

Map the hypothesis to one row. The row selects a formation method (§2) and an analysis
recipe (§4). Covers both asset classes.

| Hypothesis shape | Branch | Form (§2) | Analyse (§4) |
|---|---|---|---|
| Single-asset: exclude/filter trades (regime / session / direction / age) | single-asset-filter | transform · §1.SA insight scan first | §4.single |
| Single-asset: param / rule change vs a reference run | single-asset-param | transform | §4.single |
| Basket: recycle rule / rule-param change, same legs | basket-mechanic | transform (new rule → /port-strategy first) | §4.M + §4.S mechanic |
| Basket: leg-composition change, same rule | basket-architecture | transform | §4.M + §4.S architecture |
| Basket: entry/exit threshold at corpus scale | basket-cohort | transform → matched-pairs cohort | §4.cohort |
| Any: no reference run / fresh config | new-corpus | generator (Method B) | §4.M per-run, or §4.cohort once a reference exists |

`transform` = a reference run exists → Method A. `generator` = no reference run → Method B.

**Two moving variables — split, do not refuse.** If the proposal moves two variables, the
orchestrator does not reject it: it queues two directives (one per variable, sharing the
reference run) and records both, labelled split siblings. If the human insists on one run
with two variables, run it as a single hypothesis and note in the conclusion that
disentanglement is incomplete — recorded, not refused.

### 1.SA Single-asset insight scan (single-asset-filter only)

// turbo

```bash
python tools/hypothesis_tester.py --scan <reference_directive_name>
```

Prints ranked candidate filters (eligible, plus filtered-out ones *with their reasons* — it
hides nothing). It is a **proposal tool**: the human picks which candidate to test; the
orchestrator maps that pick to a directive-level filter in §2. No candidate is pre-rejected
on the human's behalf, and the orchestrator never refuses to run a filter the human chose.
The retired `shadow_filter` *rejection* gate is gone — extraction proposes, it does not bind.

---

## Scope & invariants (these forbid gating)

- **The human chooses what runs.** The orchestrator classifies and executes; it never
  declines a proposed hypothesis.
- **One moving variable per directive** (enforced by `/generate-directives`). Two variables
  → split into two directives (above), never a refusal.
- **Matched windows** — reference and variant run the same cointegrated spans.
- **The reference run is locked at session start** (next section); all §4 deltas read the
  frozen snapshot, never re-read live values.
- **No gates.** No worth-gate, no pre-validation/overlap/diversity/dead-strategy/pass-budget
  rejection — anywhere in the spine or its delegates (§0). The only hard limit is the
  external **20 req/min capacity ceiling**, already owned by the pipeline; this skill neither
  re-implements nor re-checks it.
- **Record everything, including nulls** — a no-effect result is a finding.

---

## Lock the reference run (session start, once)

Lock the comparator so every delta is measured against a frozen baseline. "Reference run" is
the `/generate-directives` term: the specific prior experiment this comparison is made
against (a deployed config, a prior hypothesis run, a chosen comparator) — not a "best", not
a "control". Hold the lock as a session-scoped note (UTC `locked_at` + the snapshot below);
§4 reads it, §5 cites it.

- **Single-asset:** snapshot `total_trades, profit_factor, sharpe_ratio, max_dd_pct,
  net_profit, top5_concentration, losing_years`.
- **Basket:** snapshot the reference directive's §4.M `canonical_metrics` (from its parquet).
- **Cohort:** the reference is a **series tag** (e.g. `GP_ZCRS_CXN1_Z25`) — record the tag;
  `compare_cohorts.py` reads its rows live from the MPS.

**Stale lock is advisory, never a halt.** If the reference run is modified or re-run
mid-session, the orchestrator continues, reports the delta against the now-stale snapshot,
and notes the stale `locked_at` in the §5 record. The human may re-lock if concerned; the
orchestrator never refuses a variant on lock-staleness grounds.

---

## 2 · Form — /generate-directives

[`/generate-directives`](../generate-directives/SKILL.md) owns the formation decision
(transform a reference run vs generate a new corpus), one-moving-variable, retag, and
dispatch pre-flight. Hand it the classified intent; it returns validated directives to §3.

- A reference run exists → **transform** (Method A), one variable.
- No reference run → **generator** (Method B).
- A new recycle rule is needed first → [`/port-strategy`](../port-strategy/SKILL.md), then
  transform onto it. Do not inline rule-build here.

For basket variants, the directive carries hypothesis linkage under its `test:` block —
`/generate-directives` injects it during transform:

```yaml
test:
  hypothesis_ref:     <reference_run_id>
  hypothesis_variant: <variant_id>
```

§4 reads `hypothesis_variant` to label comparison rows back to the hypothesis.

---

## 3 · Run — /execute-directives

[`/execute-directives`](../execute-directives/SKILL.md) owns the governed Golden Path
(admission, new-rule routing, Stages 1–4, capital wrapper, the "exit 0 ≠ success" rule). This
skill passes the variant directives to it and receives the result — read it in full before
`run_pipeline.py`.

---

## 4 · Analyse — vs the locked reference

Run the recipe the classifier chose. No metric is labelled "better" — direction is
metric-dependent (lower maxDD is better); interpretation is the human's.

### 4.M Canonical basket metrics (one formula everywhere)

The **canonical basket formula** — `tools/basket_hypothesis/canonical_metrics.py` implements it (the snippet below mirrors it); `basket_report.py` in that package emits the §4.S tables. `equity_total_usd.iloc[-1]` is
truth; **do NOT** derive `net_pct` from MPS `final_realized_usd / stake` (diverges for @4+
baskets via force-close accounting). `stake_usd` = the directive's `basket.initial_stake_usd`
(handles 4-leg $2k vs 2-leg $1k). Applied in both the §4.S tables and the §5 record.

```python
import pandas as pd

def canonical_metrics(parquet_path: str, stake_usd: float) -> dict:
    df = pd.read_parquet(parquet_path)
    final_eq = float(df['equity_total_usd'].iloc[-1])
    peak_dd  = float((df['peak_equity_usd'] - df['equity_total_usd']).max())
    return {
        "final_equity_usd": final_eq,
        "net_pct":          (final_eq - stake_usd) / stake_usd * 100,
        "max_dd_usd":       peak_dd,
        "max_dd_pct":       peak_dd / stake_usd * 100,
        "ret_dd":           ((final_eq - stake_usd) / stake_usd * 100) /
                            (peak_dd / stake_usd * 100) if peak_dd > 0 else 0,
        "recycle_events":   int(df['recycle_executed'].sum()),
        "bumps":            int((df['skip_reason'] == 'BUMP_INTO_HOLD').sum())
                            if 'skip_reason' in df.columns else 0,
        "liquidations":     int((df['skip_reason'] == 'LIQUIDATE_RESET').sum())
                            if 'skip_reason' in df.columns else 0,
    }
```

### 4.S Comparison output (mechanic / architecture)

```
MECHANIC COMPARISON — <basket_id> [legs], <window>, $<stake> stake
  Rule   net%      DD%      ret/DD   exit     special events
  @1     +100.70%  32.51%   3.10     TARGET   (reference)
  @4     +59.95%   32.51%   1.84     EOD      bumps=5, liq=5

ARCHITECTURE COMPARISON — <rule>, <window>
  Architecture    stake   net%      DD%      ret/DD   exit     events
  B1 (EUR+JPY)    $1k     +100.70%  32.51%   3.10     TARGET   30 recyc
  4-leg single    $2k     +100.03%  25.16%   3.98 ⭐  TARGET   44 recyc
```

Rank on the human's chosen metric (`ret/DD` for tail-bounded mechanics, `net%` for upside).
`ret/DD` is scale-invariant — use it when stakes differ across rows.

### 4.cohort Corpus matched-pairs

// turbo

```bash
python tools/compare_cohorts.py --reference-series <REF_TAG> --variant-series <VAR_TAG>
```

Inner-joins on `(pair, test_start, test_end)` so every compared row is the same window with
one variable changed. Output is neutral (medians, per-pair `variant - reference` deltas,
`variant_higher_pct`, corpus net%/worst/blowups). `matched_pairs=0` → check the series tags /
KEY columns.

### 4.single Per-run metrics (single-asset)

Compare the new run vs the **locked** reference: PF, Sharpe, max DD%, net profit, trade count,
top-5 concentration, yearwise PnL (any new losing year). Present the delta table; the human
adjudicates. No accept/reject thresholds — that was a gate, and it is gone.

---

## 5 · Record — research memory (incl. nulls)

Every branch records its result, including null / no-effect results — a null is evidence.

Present the candidate entry to the human (per `/execute-directives` Step 8: exactly 0 or 1
candidate, severe template) and get **explicit approval before appending**. Refine the
wording with the human first; do not append without that approval. This human gate governs
what is *written* to the permanent ledger (recording hygiene) — it is **not** a worth-gate,
and never blocks a hypothesis from being *run*, which is never refused.

// turbo

```bash
python tools/research_memory_append.py \
  --tags <t1>,<t2>,<t3> \
  --strategy <name_or_omit> \
  --run-ids <id1>,<id2> \
  --finding "<what changed>" \
  --evidence "<≤2 lines, must contain a numeric metric/delta>" \
  --conclusion "<mechanism — why, not a repeat of finding>" \
  --implication "<actionable future constraint>"
```

Validator: **≥3 tags**, non-empty run-ids, evidence **≤2 lines with at least one digit**; the
UTC date is stamped for you. Appends to `Trade_Scan/RESEARCH_MEMORY.md`.

**Anti-overclaim discipline (guidance — write the finding honestly):**

- **One moving variable** — the claim attaches to the single thing that changed.
- **Scope to the cohort tested** — name it: single-asset-filter = the trades matching the
  filter; basket-mechanic/architecture = the trades in the matched windows; basket-cohort =
  the matched pairs. Say "on the N matched H1 windows", not "in general".
- **Never write "disproven" for what was untested.** A null on this cohort is "no detectable
  effect on <cohort>", not a universal refutation — recorded with its numbers.

---

## What this does NOT do

- **Does not gate on worth** — no pre-validation/overlap/diversity/dead-strategy/pass-budget
  rejection, in this skill or its delegates (§0).
- **Does not embed the delegated skills** — `/generate-directives` (form),
  `/execute-directives` (Golden Path), `/port-strategy` (rule-build) are called, not inlined.
- Does not auto-promote — accepted hypotheses go to a separate human-gated promotion.
- Does not chain accepted changes into the next variant (each variant vs the locked reference).

---

## Loop / session summary

Re-run the spine per variant the human queues (no budget cap). When the human ends the session,
print the summary and halt:

```
=== HYPOTHESIS SESSION SUMMARY ===
Reference run locked : <name/tag>  @ <UTC>   (stale: yes/no)
Variants run         : <N>
  <branch>  <variant>  → <leader metric / delta>   (recorded: yes / null / held)
  ...
Recorded to RESEARCH_MEMORY.md : <N> (nulls: <N>)
No auto-deploy. Promotion is a separate human decision.
==================================
```

---

## Related skills

- **Stage 2 (form):** [`/generate-directives`](../generate-directives/SKILL.md).
- **Stage 3 (run):** [`/execute-directives`](../execute-directives/SKILL.md).
- **Conditional:** [`/port-strategy`](../port-strategy/SKILL.md) — build a new recycle rule
  before transforming onto it.
- **Alternative:** [`/rerun-backtest`](../rerun-backtest/SKILL.md) — re-run an exact prior
  config (not a hypothesis).
- (Retired) `basket-hypothesis-testing` — folded into this orchestrator + `compare_cohorts.py` + `tools/basket_hypothesis/`; its skill dir is now a redirect stub (full prior content in git history).

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _repurposed 2026-06-12 — no friction yet_ | | |