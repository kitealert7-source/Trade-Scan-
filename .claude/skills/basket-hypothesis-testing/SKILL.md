---
name: basket-hypothesis-testing
description: Orchestrator for basket-strategy hypothesis tests — Detect, Route, Execute, Summarize. v1 scope is two classes (mechanic = rule-class change, architecture = leg-composition change). Delegates pipeline runs to /execute-directives, new-rule builds to /port-strategy. Distinct from /hypothesis-testing (single-strategy directive-filter exclusion).
---

# /basket-hypothesis-testing — Basket-strategy hypothesis orchestrator

Authoritative conductor for basket-strategy hypothesis tests. Runs four
phases: **Detect → Route → Execute → Summarize**. v1 covers two
hypothesis classes; additional classes (parameter, composite,
regime-gate, window-robustness) accrete as needed without restructuring
the orchestrator.

> **Scope boundary.** This skill is for BASKET hypothesis testing. For
> single-strategy directive-filter exclusion testing, use
> [`hypothesis-testing`](../hypothesis-testing/SKILL.md) — different
> experiment shape, different orchestrator.

---

## v1 scope (hypothesis classes covered)

| Class | Tests | Sub-flow |
|---|---|---|
| **mechanic** | Different rule class on same architecture (`H2_recycle@1` vs `@4` vs `@5`) | §3.K |
| **architecture** | Same rule on different leg compositions (B1 vs B2 vs 4-leg) | §3.A |

Deferred to later versions: **parameter** (param sweeps), **composite**
(parallel-sleeve rollup), **regime-gate** (factor/threshold variants),
**window-robustness** (multi-window stress).

---

## Phase 0 — Hypothesis document (precondition)

Before invoking this orchestrator, the operator drafts a hypothesis
YAML at `backtest_directives/hypotheses/<HYPOTHESIS_ID>.yaml` per
[`backtest_directives/hypotheses/SCHEMA.md`](../../backtest_directives/hypotheses/SCHEMA.md).

The hypothesis YAML captures motivation, baseline, variants, acceptance
criteria, and evidence requirements. It is the single source of truth
for *what is being tested and why*. Conversation memory informs the
draft; the YAML is what survives.

The orchestrator is invoked with the hypothesis ID:

```
/basket-hypothesis-testing H3_TREND_FOLLOW_V1
```

The orchestrator at Phase 1 reads
`backtest_directives/hypotheses/<ID>.yaml`, validates it is
well-formed YAML with the required top-level keys, and proceeds with
the routing pulled from the YAML's `class`, `baseline`, and `variants`
fields. **Status transitions** are mechanical:
`PROPOSED → ACTIVE` at invocation; `ACTIVE → COMPLETED` at Phase 4
close after the decision block is filled.

Top-level `supersedes` (in the hypothesis YAML) records lineage between
hypothesis specs — e.g. when H3_V2 replaces H3_V1 before either runs.
Distinct from `decision.supersedes` (deployment leadership, filled
only on ACCEPT). See SCHEMA.md §"Two kinds of supersession".

If the YAML is missing or malformed, the orchestrator **blocks** and
prompts for the spec — refuses to proceed from chat-only intent.

---

## Phase 1 — Detect

Single-pass gathering of every signal that drives routing in Phase 2.
Run all checks; act on none yet. **All inputs sourced from the
hypothesis YAML drafted in Phase 0** — no information pulled from
chat.

```bash
# 1. Load hypothesis YAML (block + prompt if missing or malformed)
HYP=backtest_directives/hypotheses/<HYPOTHESIS_ID>.yaml
test -f "$HYP" || { echo "ERROR: hypothesis YAML not found: $HYP"; exit 1; }
python -c "import yaml; h=yaml.safe_load(open('$HYP', encoding='utf-8')); \
  required=['id','title','class','status','baseline','variants','acceptance_criteria','evidence_required']; \
  missing=[k for k in required if k not in h]; \
  assert not missing, f'missing keys: {missing}'; \
  assert h['status'] in ('PROPOSED','ACTIVE'), f\"status must be PROPOSED or ACTIVE to invoke; got {h['status']}\""

# 2. Transition status PROPOSED → ACTIVE (orchestrator is now running on this hypothesis)
#    (write back to YAML; commit at Phase 4 close along with decision)

# 3. Baseline existence (sourced from YAML's baseline.directive)
ls "<baseline.parquet_path>/results_basket_per_bar.parquet"
ls "<baseline.parquet_path>/results_basket.csv"

# 4. Visibility — is baseline in MPS Baskets sheet?
python -c "import pandas as pd; b=pd.read_excel('../TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx', sheet_name='Baskets'); print('<baseline.directive>' in b['directive_id'].astype(str).values)"

# 5. Sweep slot availability — next free SXX for the idea
grep "requested_sweep:" governance/namespace/sweep_registry.yaml | sort -u | tail
```

Print the detection summary (every field sourced from the YAML or its
derived state):

```
PHASE 1 — DETECT (<UTC>)
  Hypothesis ID              : <ID>                  ← yaml.id
  Hypothesis class           : <mechanic | architecture>  ← yaml.class
  Status transition          : PROPOSED → ACTIVE
  Top-level supersedes       : <prior_id_or_null>    ← yaml.supersedes
  Baseline directive         : <NAME>                ← yaml.baseline.directive
  Baseline parquet present   : YES / NO
  Baseline in MPS Baskets    : YES / NO              (NO → 3.V flag in Phase 4)
  Variants to test (N)       : <list>                ← yaml.variants[].id
  Rule-build required        : YES / NO              ← any yaml.variants[].rule_build_required = true
  Sweep slot to reserve      : SXX
  In-process probe motivated : YES / NO              ← yaml.evidence_required.parity_gate = "required"
  Operational window         : <start> → <end>       ← yaml.variants[0].window
  Acceptance primary metric  : <metric>              ← yaml.acceptance_criteria.primary_metric
```

**Visibility gate (v1 policy):** if baseline NOT in MPS, surface but do
not block — operator proceeds and the gap is flagged in Phase 4. Auto-
backfill deferred until a backfill module exists.

**Session suppression:** once the MPS visibility warning has fired for
any baseline in a session, subsequent baselines in the same session
skip the warning line (the gap is already captured in Phase 4.G). The
operator hears it once per session, not once per hypothesis.

---

## Phase 2 — Route

Given Phase 1, declare the execution plan. Print BEFORE Phase 3 so the
operator sees the full sequence at a glance and can challenge it before
anything runs.

```
PHASE 2 — ROUTE

ALWAYS:
  3.0  Sweep slot pre-reservation
  3.M  Canonical metrics convention (declared, applied throughout)
  3.L  hypothesis_log.json append per variant
  3.S  At-a-glance summary table (Phase 4)
  3.D  Current-best declaration (Phase 4)

CONDITIONAL (gated by class):
  3.K  Mechanic sub-flow          ← class = mechanic
  3.A  Architecture sub-flow      ← class = architecture

CONDITIONAL (gated by Phase 1):
  3.V  MPS visibility flag        ← baseline NOT in MPS
  3.G  Parity gate                 ← in-process probe motivated → MANDATORY
```

> **Routing is not negotiable mid-execution.** If a Phase 3 step
> uncovers a second-order hypothesis from results, record it in Phase 4
> and address in the next session — do not loop back to re-route.

---

## Phase 3 — Execute

### 3.0 Sweep slot pre-reservation [ALWAYS]

Before authoring any directive, reserve the SXX slot in
`governance/namespace/sweep_registry.yaml`. Skipping this works (the
pipeline has a DIRECTIVE_NOT_ADMITTED fallback) but breaks the audit
trail.

```python
from tools.sweep_registry_gate import _hash_signature, reserve_sweep_identity

result = reserve_sweep_identity(
    idea_id="<ID>", directive_name="<NAME>",
    signature_hash=_hash_signature(directive_path),
    requested_sweep="SXX", auto_advance=True,
)
```

### 3.M Canonical metrics convention [ALWAYS]

**One formula** for `net_pct` and `dd_pct` across all baskets — applied
in 3.L logging and 3.S comparison tables. Resolves the
MPS-vs-parquet discrepancy that surfaced for @4 baskets in the 2026-05-16
session.

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

**Rules:**
- `stake_usd` is each directive's `basket.initial_stake_usd` field
  (NOT $1k assumed) — handles 4-leg ($2k) vs 2-leg ($1k) normalization.
- **Do NOT** compute `net_pct` from MPS `final_realized_usd / stake` — it
  diverges from the parquet's `equity_total_usd.iloc[-1]` for @4 baskets
  due to force-close PnL accounting. Parquet is the source of truth.
- DD% definition is `peak_equity_usd - equity_total_usd` per bar (the
  parquet's running peak vs current equity), divided by stake. Single
  convention across the whole skill.

### 3.V MPS visibility flag [conditional: baseline NOT in MPS]

v1 surfaces the gap; does NOT auto-backfill. Decision tree:

| Choice | Implication |
|---|---|
| Proceed without backfill | Baseline visible only via parquet/REPORT.md; flag in Phase 4 |
| Manual backfill + re-run orchestrator | Operator runs backfill (not yet a module); baseline appears in MPS |
| Defer hypothesis | Session ends; backfill becomes its own task |

**v1 default: PROCEED + flag in Phase 4 summary.**

### 3.K Mechanic sub-flow [conditional: class = mechanic]

Compare a **new rule class** against an existing one on the same
architecture.

**Inputs:** `baseline_rule`, `variant_rules[]`, shared architecture
(same legs, same stake, same window).

**Steps:**

1. **Baseline status.** Confirm baseline run exists with `baseline_rule`
   (parquet present). If not, run baseline first via
   [`/execute-directives`](../execute-directives/SKILL.md).

2. **For each variant rule:**
   - If the variant rule class **doesn't exist yet** → call
     [`/port-strategy`](../port-strategy/SKILL.md) to build it (new
     class in `tools/recycle_rules/`, registry entry in
     `governance/recycle_rules/registry.yaml`, dispatch wiring in
     `tools/basket_pipeline.py::_instantiate_rule`, tests). The rule
     MUST be pipeline-routable before any backtest — NOT optional.
   - Author a variant directive from the baseline directive: same legs,
     same stake, same window, only `recycle_rule.version` (and any new
     rule-specific params) differ. **Insert `hypothesis_ref` and
     `hypothesis_variant` under the directive's `test:` block** so the
     directive carries linkage back to the hypothesis YAML.
   - Run through pipeline via [`/execute-directives`](../execute-directives/SKILL.md).

3. **Parity gate (3.G)** if any in-process probe motivated the variant
   — mandatory before trusting the pipeline matrix as deployment evidence.

4. **Extract canonical metrics (3.M)** for baseline + each variant.

5. **Comparison output (3.S):**

   ```
   MECHANIC COMPARISON — <basket_id> [legs], <window>, $<stake>k stake

     Rule       net%      DD%      ret/DD   Exit       Special events
     @1         +100.70%  32.51%   3.10     TARGET     (baseline)
     @4         +59.95%   32.51%   1.84     EOD        bumps=5, liq=5
     @5         <X>       <Y>      <Z>      <exit>     <events>
   ```

6. **Decision** (operator-gated): ACCEPT / REJECT / INCONCLUSIVE per
   variant, on the operator-selected metric (typically `ret/DD` for
   tail-bounded mechanics, `net%` for upside-maximizers).

### 3.A Architecture sub-flow [conditional: class = architecture]

Compare **different leg compositions** with the same rule on the same
window.

**Inputs:** shared `rule`, `architectures[]` (each = legs +
initial_stake_usd + harvest_threshold_usd), shared window.

**Steps:**

1. **Stake-basis normalization.** 4-leg uses 2× stake of 2-leg ($2k vs
   $1k). The canonical metrics module (3.M) handles this via per-
   directive `stake_usd`. The comparison report normalizes to `ret/DD`
   (scale-invariant) and `net%` (already normalized).

2. **For each architecture:**
   - Author directive (basket.legs + initial_stake_usd +
     harvest_threshold_usd) with the shared rule. **Insert
     `hypothesis_ref` and `hypothesis_variant` under the directive's
     `test:` block** so the directive carries linkage back to the
     hypothesis YAML.
   - Run through pipeline via [`/execute-directives`](../execute-directives/SKILL.md).

3. **Extract canonical metrics (3.M)** for each architecture (with each
   directive's own `stake_usd`).

4. **Comparison output (3.S):**

   ```
   ARCHITECTURE COMPARISON — <rule>, <window>

     Architecture          stake    net%      DD%      ret/DD   exit       events
     B1 (EUR+JPY)          $1k      +100.70%  32.51%   3.10     TARGET     30 recyc
     B2 (AUD+CAD)          $1k      +59.30%   33.10%   1.79     EOD        28 recyc
     4-leg single          $2k      +100.03%  25.16%   3.98 ⭐  TARGET     44 recyc
   ```

5. **Decision** (operator-gated): typically rank by `ret/DD`; flag the
   leader. Output of 3.A feeds the 4.D current-best declaration.

### 3.G Parity gate [conditional: in-process probe motivated]

If a hypothesis was motivated by results from `tools/research/basket_sim.py`
or any `tmp/` script (NOT the pipeline emitter), confirm pipeline ↔
basket_sim parity on at least one window before trusting matrix results
as deployment evidence.

**Acceptance — ALL must hold:**

| Metric | Tolerance |
|---|---|
| `max_dd_usd` | exact match (byte-perfect) |
| `recycle_events` count | exact match |
| `bumps` count (if @4+) | exact match |
| `liquidations` count (if @4+) | exact match |
| `net_pct` | ≤ 3% relative drift (floating-point accumulator ordering) |

If parity fails → fix the divergence before trusting any in-process
result. The 2026-05-16 H2_recycle@4 parity gate (commit `703a6cf`) is
the reference exemplar: byte-perfect on the F window, all 10-window
counts matched to byte precision after.

### 3.L hypothesis_log.json append [ALWAYS]

Append one entry per variant tested to
`TradeScan_State/hypothesis_log.json`:

```json
{
    "timestamp": "<UTC>",
    "hypothesis_class": "mechanic | architecture",
    "baseline_directive": "<NAME>",
    "baseline_rule": "<rule@version>",
    "variant_directive": "<NAME>",
    "variant_rule": "<rule@version>",
    "architecture": "<basket_id> [legs]",
    "window": "<start>→<end>",
    "stake_usd": <X>,
    "canonical_metrics": { ... },
    "parity_gate": "PASS | SKIPPED (no in-process probe) | FAIL",
    "decision": "ACCEPT | REJECT | INCONCLUSIVE",
    "current_best_supersedes": "<previous_best_or_null>"
}
```

---

## Phase 4 — Summarize

Three structural deliverables every session, no exceptions.

### 4.S At-a-glance comparative table [ALWAYS]

Regenerate a consolidated table of all baskets relevant to this
session's hypothesis. Use the canonical metrics formula (§3.M) for every
row.

Until a dedicated module exists, regenerate inline (template — adapt
per session):

```python
import os, re, pandas as pd

base = "../TradeScan_State/backtests"
runs_of_interest = [<directive ids tested this session, plus baselines>]
rows = []
for run in runs_of_interest:
    parq = f"{base}/{run}_H2/raw/results_basket_per_bar.parquet"
    stake = <pull from the directive's basket.initial_stake_usd>
    m = canonical_metrics(parq, stake)
    rows.append({"directive": run, "stake": stake, **m})
df = pd.DataFrame(rows).sort_values("ret_dd", ascending=False)
df.to_csv("outputs/basket_hypothesis_<session>_summary.csv", index=False)
print(df.to_string(index=False))
```

Save under `outputs/basket_hypothesis_<session>_summary.csv` for
operator review.

### 4.D Current-best declaration [ALWAYS]

Print the operator-facing leader:

```
CURRENT BEST CANDIDATE (post-<session>)
  Architecture     : <basket_id> [legs]
  Rule             : <rule@version>
  Stake            : $<X>
  Window evidence  : P00 (<start>→<end>)
  Evidence class   : <single-window | multi-window-N | composite>  [+ parity-gated if §3.G passed]
  Evidence details : <free-text qualifier; e.g. "operational P00 only", "10/10 historical survival", "parity ≡ basket_sim byte-perfect on F window">
  net%             : <X>%
  Max DD%          : <X>%
  ret/DD           : <X>
  Decision         : LEADING / TIED / SUPERSEDED
  Supersedes       : <previous_best_or_null>
  Reason           : <metric that ranks it leading>
```

**Evidence class semantics:**
- `single-window` — tested on one operational window (typically P00). Weakest evidence; says nothing about regime robustness.
- `multi-window-N` — tested on N historical windows (e.g. `multi-window-10` for the A-J stress set). Adds regime-robustness signal but does NOT supersede single-window on the operational metric (2026-05-16 lesson).
- `composite` — bar-aligned multi-basket rollup validated (future composite-class hypothesis).
- `+ parity-gated` — append when §3.G passed; confirms pipeline implementation matches the in-process probe that motivated the hypothesis.

A leader with `single-window + parity-gated` is deployment-viable on the operational window. A leader with `multi-window-10` adds tail-risk evidence but does not by itself justify deploying a lower-ret/DD candidate over a higher-ret/DD single-window leader (yesterday's framing-drift trap).

Persist this to the project memory file documenting the current best.

**Write decision back to hypothesis YAML:** at Phase 4.D close, update
`backtest_directives/hypotheses/<HYPOTHESIS_ID>.yaml`:

- Set `status: COMPLETED`
- Fill `decision.outcome` (ACCEPT | REJECT | INCONCLUSIVE — operator-adjudicated)
- Fill `decision.decided_at` (UTC), `decision.decided_by`
- Fill `decision.evidence_actual.class_achieved` (e.g. `single-window + parity-gated`)
- Fill `decision.evidence_actual.canonical_metrics` (§3.M output per variant)
- Fill `decision.reasoning` (1-3 line free-text justification)
- Fill `decision.supersedes` ONLY on ACCEPT that promotes this variant
  past the prior current-best (deployment-leadership supersession;
  distinct from top-level `supersedes` which is hypothesis-spec lineage)

Commit the updated YAML in the same session-close commit that lands
the directive `completed/` files.

### 4.G Reporting gaps surfaced [ALWAYS]

Echo any drift detected in Phase 1 and friction encountered in Phase 3:

```
REPORTING GAPS (post-<session>)
  MPS Baskets coverage delta : N runs on disk / N runs in MPS (missing: K)
  DD-definition mismatches   : N runs where MPS net% differs from parquet
  Sweep slots not pre-reserved: N (DIRECTIVE_NOT_ADMITTED fallback used)
```

Flagged items become next-session tasks. Not auto-fixed.

---

## What this skill calls (delegation map)

| Sub-task | Delegates to |
|---|---|
| Building a new rule class | [`/port-strategy`](../port-strategy/SKILL.md) |
| Running directives through pipeline | [`/execute-directives`](../execute-directives/SKILL.md) |
| Re-test of previously-tested config | [`/rerun-backtest`](../rerun-backtest/SKILL.md) |
| (Future) composite portfolio rollup | [`/run-composite-portfolio`](../run-composite-portfolio/SKILL.md) — out of v1 scope |
| (Future) promotion to LIVE | [`/promote`](../promote/SKILL.md) — operator-gated, post-ACCEPT |

## What this skill does NOT do (anti-bloat boundaries)

- Doesn't embed `/execute-directives` Golden Path — calls it
- Doesn't embed `/port-strategy` rule-build logic — calls it
- Doesn't decide capital sizing (operator after ACCEPT)
- Doesn't run multi-window matrix by default (2026-05-16 lesson:
  operational P00 is primary; stress windows opt-in only via a future
  window-robustness class)
- Doesn't auto-promote
- Doesn't replace `/hypothesis-testing` (single-strategy directive-filter
  exclusion stays in that skill — different experiment shape)
- Doesn't build modules speculatively (v1 has zero new modules; build
  `canonical_metrics.py`, `at_a_glance.py`, `parity_gate.py` only when
  inlining them becomes painful)

---

## Quick Version (copy-paste, phase-ordered)

```bash
# === PHASE 1 — DETECT ===
# Operator declares hypothesis class (mechanic | architecture).
# Check baseline parquet exists, baseline in MPS, sweep slot available.

# === PHASE 2 — ROUTE ===
# Print plan: which Phase 3 steps will run, in order.

# === PHASE 3 — EXECUTE ===
# 3.0 Pre-reserve sweep slot
python -c "from tools.sweep_registry_gate import _hash_signature, reserve_sweep_identity; ..."

# 3.K (if mechanic):
#   For each variant rule:
#     If rule class doesn't exist → /port-strategy
#   Author variant directives (only recycle_rule.version differs)
#   /execute-directives

# 3.A (if architecture):
#   Author variant directives (one per architecture, same rule)
#   /execute-directives

# 3.G (if in-process probe used to motivate variant):
#   Compare basket_sim output vs pipeline parquet
#   ALL counts must match exactly; net% drift ≤ 3%

# 3.L Append hypothesis_log.json entries (one per variant)

# === PHASE 4 — SUMMARIZE ===
# 4.S At-a-glance CSV → outputs/basket_hypothesis_<session>_summary.csv
# 4.D Current-best declaration (architecture + rule + ret/DD + supersession)
# 4.G Reporting gaps surfaced (MPS coverage, DD mismatches, unreserved slots)

# Operator reviews → ACCEPT / REJECT / INCONCLUSIVE per variant.
```

---

## When to skip

- Trivial one-off probe — skip the orchestrator, run ad-hoc
- Re-test of previously-tested variant — use
  [`/rerun-backtest`](../rerun-backtest/SKILL.md) instead
- Single-strategy directive-filter exclusion — use
  [`/hypothesis-testing`](../hypothesis-testing/SKILL.md) (different
  skill, different experiment shape)

## Anti-patterns

- Running multi-window matrix as the default (operational P00 is primary)
- Trusting in-process probe results without the 3.G parity gate
- Computing `net%`/`DD%` from MPS `final_realized_usd / stake` (use
  the canonical parquet formula — they diverge for @4+ baskets)
- Skipping sweep slot pre-reservation (DIRECTIVE_NOT_ADMITTED fallback
  works but breaks audit)
- Declaring "champion" without 4.D supersession log
- Inlining `/execute-directives` or `/port-strategy` logic instead of
  calling them
- Building modules speculatively (v1 ships with zero — let real friction
  drive the first extraction)

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _v1 skeleton 2026-05-17 — no friction yet_ | | |
