---
name: hypothesis-testing
description: Controlled hypothesis-driven re-testing using ranked actionable insights from hypothesis_tester.py
---

## Hypothesis Testing Workflow

Orchestrates bounded, single-variable hypothesis testing against baseline strategies.
Each hypothesis is a single exclusion derived from structured insight analysis.
Every pass executes the full Golden Path (`execute-directives.md`) — no shortcuts.

> **This workflow is a SUPERVISOR over execute-directives.md, not a replacement.**
> Every pipeline run follows the exact same admission, approval, and execution sequence.

---

### Scope & Invariants

- **One insight per pass.** Never combine multiple exclusions.
- **Each pass starts from baseline (P00).** No chaining — P02 does not build on P01.
- **Directive-level changes only.** Strategy.py logic is never modified.
- **No optimization loops.** Fixed budgets, fixed thresholds, no recursive relaxation.
- **Human gating preserved.** Every pass requires approval before pipeline execution.
- **No overlapping hypotheses.** Reject any insight whose target field + value range overlaps with a previously tested hypothesis in the same session. Prevents hidden parameter search (e.g. Age 3-5 then Age 3-6).
- **Hypothesis diversity.** No two consecutive passes may target the same dimension (same `hypothesis_class`). After testing `regime_age_gradient`, the next pass must be a different class (e.g. `session_divergence`, `direction_bias`). Prevents hammering one dimension repeatedly.

---

### Budget Limits

| Budget | Limit | Enforcement |
|---|---|---|
| Shadow evaluations per strategy | 10 | Counted in hypothesis_log.json |
| Pipeline passes per strategy | 4 | Counted in hypothesis_log.json |
| Global pipeline passes per session | 25 | Counted in hypothesis_log.json |

Shadow rejections do NOT consume pipeline budget.
Budget is checked BEFORE every shadow evaluation and pipeline execution.

---

### Prerequisites

- Baseline run (P00) completed through full Golden Path (PORTFOLIO_COMPLETE)
- `results_tradelevel.csv` exists for baseline
- `tools/hypothesis_tester.py` available
- `tools/shadow_filter.py` available
- `tools/new_pass.py` available

### Baseline Snapshot Lock

**At session start**, before any hypothesis is evaluated, compute and record baseline metrics:

```python
baseline_snapshot = {
    "strategy": "<BASELINE_NAME>",
    "locked_at": "<UTC timestamp>",
    "total_trades": <N>,
    "profit_factor": <X>,
    "sharpe_ratio": <X>,
    "max_dd_pct": <X>,
    "net_profit": <X>,
    "top5_concentration": <X>,
    "losing_years": [<list>]
}
```

This snapshot is written as the first entry in hypothesis_log.json (with `stage: "baseline_lock"`).
**All comparisons in Steps 1 and 5 use this locked snapshot**, not re-read values.
If the baseline run folder is modified or re-run during the session, the lock is stale — abort and re-lock.

---

### Step 0: Generate Hypothesis Report

Run the structured insight extractor on the baseline strategy.

```bash
python tools/hypothesis_tester.py --scan <BASELINE_DIRECTIVE_NAME>
```

This outputs ranked, structured insights with eligibility already applied.

**Strategy skip rules (any triggers immediate STOP):**
- Zero eligible insights → nothing to test
- Baseline PF < 1.0 AND no single eligible insight has PF > 1.3 with ≥15 trades → dead strategy, exclusion cannot fix it. (If a localized strong bucket exists, the strategy may be salvageable — allow it through.)
- Baseline total trades < 40 → insufficient data for meaningful exclusion testing

**Present to user:**
```
Eligible insights: N
Top hypothesis: <class> — <description>
Recommend testing? (yes/no)
```

User must approve before proceeding. If user says no, **STOP**.

**Batch approval mode (optional):** User may grant batch approval for N passes at once:
```
"Approve next 3 passes"
```
This pre-authorizes shadow + pipeline execution for the next N hypotheses without per-step prompts.
All governance gates (admission, registry, rehash) still execute. Results are still presented after each pass for review.

**Batch class freeze:** At batch grant time, record which `hypothesis_class` values are permitted.
Only insights matching frozen classes execute within the batch. If a different class surfaces as
top-ranked, the batch pauses and re-prompts. This prevents batch mode from drifting into exploration.

---

### Step 1: Shadow Pre-Validation

For the top-ranked eligible insight, generate a filter spec and run shadow evaluation.

```python
from tools.hypothesis_tester import extract_structured_insights
from tools.shadow_filter import evaluate_shadow_filter

# Load baseline trades
insights = extract_structured_insights(trades, starting_capital)
eligible = [i for i in insights if i.eligible]
top = eligible[0]  # top-ranked

# Generate filter spec and evaluate
spec = top.to_filter_spec()
result = evaluate_shadow_filter(trades, starting_capital, spec)
```

**Rejection criteria (ANY triggers reject):**

| Check | Rule |
|---|---|
| PF floor | Filtered PF < 1.0 |
| PnL flip | Baseline positive -> filtered negative |
| Trade drop (>=150 baseline) | Drop > 30% |
| Trade drop (<150 baseline) | Drop > 20% |
| Max DD increase | Filtered DD > baseline DD x 1.2 |
| Top-5 concentration | Filtered top-5% > baseline top-5% x 1.2 |

> **Note:** Shadow uses DD x 1.2 (lenient gate). Pipeline acceptance (Step 5) uses DD x 1.15 (stricter). This is intentional — shadow is a fast pre-filter, pipeline is the binding evaluation. An insight can pass shadow but still be rejected at pipeline evaluation on DD grounds.

**If shadow REJECTS:**
1. Log to hypothesis_log.json with `stage: "shadow_prevalidation"`
2. Increment shadow attempt counter
3. Move to next eligible insight
4. If shadow attempt budget (10) exhausted, **STOP** this strategy

**If shadow PASSES:**
Continue to Step 2.

**Present to user:**
```
Shadow result for: <hypothesis>
  Baseline: PF <X>, Sharpe <X>, Trades <N>
  Filtered: PF <X>, Sharpe <X>, Trades <N>
  Trade retention: <X>%
  Pre-validation: PASS
Proceed to pipeline execution? (yes/no)
```

User must approve. If no, move to next insight or **STOP**.

---

### Step 2: Create Pass Directive

Use `new_pass.py` to scaffold the new pass from baseline.

```bash
python tools/new_pass.py <BASELINE_NAME> <NEW_PASS_NAME>
```

**Naming convention:** `<FAMILY>_<..>_P01`, `P02`, etc. Sequential from baseline P00.

**Then apply the hypothesis as a directive-level filter change.** Map the insight to directive YAML:

| Hypothesis Class | Directive Change |
|---|---|
| `weak_cell` (Dir x Vol) | Add `market_regime_filter.exclude: [<regime>]` + strategy direction constraint |
| `weak_cell` (Dir x Trend) | Add `trend_filter.exclude_regime: <value>` + direction constraint |
| `direction_bias` | Set direction constraint (long_only / short_only) in directive |
| `session_divergence` | Add session filter constraint to directive |
| `regime_age_gradient` | Add exact bucket exclusion: e.g. Age 3-5 = `regime_age_filter: {enabled: true, exclude_min: 3, exclude_max: 5}`. No threshold reinterpretation — bucket boundaries are literal. |
| `late_ny_asymmetry` | Add session + direction constraint to directive |

**Critical:** Only the directive YAML is edited. Strategy.py is copied unchanged from baseline — `new_pass.py` handles this. The only edit to strategy.py is the automatic name replacement (`new_pass.py` does this).

Add a comment in the directive describing the hypothesis:

```yaml
# HYPOTHESIS: Exclude <description>
# SOURCE: hypothesis_tester.py rank #<N>, score <X>
# BASELINE: <P00_NAME>
```

---

### Step 3: Rehash

After editing the directive with the filter change:

```bash
python tools/new_pass.py --rehash <NEW_PASS_NAME>
```

This:
1. Cleans stale state
2. Recomputes directive hash
3. Updates sweep_registry.yaml
4. Pre-injects canonical signature into strategy.py
5. Writes `.approved` marker
6. Ensures directive is in INBOX

---

### Step 4: Execute Golden Path

**Read `execute-directives.md` in full.** Then execute:

```bash
python tools/run_pipeline.py --all
```

This runs the complete governed pipeline:
- Admission gates (namespace, sweep registry, canonicalizer)
- Stage 1 (engine execution)
- Stage 2 (AK Trade Report — now includes Regime Lifecycle sheet)
- Stage 3 (Master Filter aggregation)
- Stage 4 (filter_strategies.py)

Then continue the Golden Path:

```bash
python tools/capital_wrapper.py <NEW_PASS_NAME>
python tools/filter_strategies.py
```

**Do NOT skip any step.** The hypothesis pass goes through the identical pipeline as any other pass.

---

### Step 5: Evaluate Results

Compare the new pass results against baseline (P00).

**Data sources:**
- Baseline: P00 AK Trade Report or `results_standard.csv` + `results_risk.csv`
- Result: New pass AK Trade Report

**Acceptance criteria (ALL must pass):**

| Metric | Rule | Notes |
|---|---|---|
| Profit Factor | Must not decrease | Strict, no tolerance |
| Sharpe Ratio | Must not decrease | Strict, no tolerance |
| Max Drawdown | Must not increase materially | Filtered DD <= baseline DD x 1.15 |
| Yearwise stability | No new losing year | Year PnL < 0 that was >= 0 in baseline |
| Trade retention | >= 70% of baseline | Hard floor |
| Top-5 concentration | Must not increase > 20% | top-5% <= baseline x 1.2 |
| Single-bucket PnL dominance | No single bucket > 60% of total net PnL | Catches hidden concentration spikes where "improvement" is just one lucky cluster |

**Present to user:**

```
=== HYPOTHESIS EVALUATION ===
Strategy:    <NAME>
Hypothesis:  <description>
Pass:        <P0X>

                  Baseline    Result     Delta
Profit Factor:    <X>         <X>        <+/- X>
Sharpe Ratio:     <X>         <X>        <+/- X>
Max DD (%):       <X>         <X>        <+/- X>
Total Trades:     <N>         <N>        <-N (-X%)>
Top-5 Conc.:      <X>%        <X>%       <+/- X>
Losing Years:     <list>      <list>     <new?>

Decision: ACCEPT / REJECT (<reason>)
================================
```

---

### Step 6: Log Results

Append to `TradeScan_State/hypothesis_log.json`:

**First entry per strategy — baseline lock:**
```json
{
    "timestamp": "<UTC>",
    "strategy": "<BASELINE_NAME>",
    "stage": "baseline_lock",
    "baseline": {
        "total_trades": <N>,
        "profit_factor": <X>,
        "sharpe_ratio": <X>,
        "max_dd_pct": <X>,
        "net_profit": <X>,
        "top5_concentration": <X>,
        "losing_years": [<list>]
    }
}
```

**Per-pass entry:**
```json
{
    "timestamp": "<UTC>",
    "strategy": "<BASELINE_NAME>",
    "pass_id": "<P0X>",
    "run_id": "<from pipeline>",
    "hypothesis_class": "<class>",
    "hypothesis": "<description>",
    "filter_spec": { ... },
    "stage": "shadow_prevalidation | pipeline | SKIPPED_OVERLAP | SKIPPED_DIVERSITY",
    "baseline": "<reference to locked snapshot>",
    "result": {
        "total_trades": <N>,
        "profit_factor": <X>,
        "sharpe_ratio": <X>,
        "max_dd_pct": <X>,
        "net_profit": <X>,
        "top5_concentration": <X>
    },
    "yearwise_check": "PASS/FAIL",
    "trade_retention_pct": <X>,
    "decision": "ACCEPT/REJECT/SKIP",
    "rejection_reason": "<criterion> or null"
}
```

---

### Step 7: Loop or Stop

After logging, check:

1. **Per-strategy pipeline budget remaining?** If exhausted (4 passes), **STOP** this strategy.
2. **Global pipeline budget remaining?** If exhausted (25 passes), **STOP ALL**.
3. **More eligible insights?** Before selecting the next insight, apply:
   - **Overlap rejection:** Skip any insight whose `target_field` + value range overlaps with a previously tested hypothesis. Examples: Age 3-6 after Age 3-5 (overlap), Short x Low after Short x Normal (no overlap, different value — allowed).
   - **Diversity constraint:** Skip insights with the same `hypothesis_class` as the most recently tested pass. Must alternate dimensions. E.g. after `regime_age_gradient`, next must be `weak_cell`, `direction_bias`, `session_divergence`, or `late_ny_asymmetry`.
   - If all remaining insights fail overlap or diversity checks, **STOP** this strategy.
4. Return to Step 1 with the next qualifying insight.
5. **No more eligible insights?** **STOP** this strategy, move to next strategy in queue.

**Present to user before each new iteration (unless batch-approved):**
```
Pass budget: <N>/4 used (this strategy), <N>/25 used (global)
Next hypothesis: <class> — <description>
Skipped: <N> (overlap: <N>, diversity: <N>)
Continue? (yes/no)
```

---

### Step 8: Session Summary

After all strategies are processed (or global budget exhausted):

```
=== HYPOTHESIS TESTING SESSION SUMMARY ===
Strategies evaluated:  <N>
Total shadow probes:   <N> (rejected: <N>)
Total pipeline passes: <N> (accepted: <N>, rejected: <N>)

Per-strategy results:
  <NAME>  P01: ACCEPT (weak_cell, PF +0.12)
  <NAME>  P02: REJECT (direction_bias, new losing year)
  <NAME>  P01: REJECT (shadow, PF < 1.0)
  ...

No automatic deployment. Accepted hypotheses require
human review via promote.md workflow before any execution
layer changes.
==========================================
```

---

### What This Workflow Does NOT Do

- Does not bypass execute-directives.md
- Does not call run_pipeline.py outside the Golden Path
- Does not skip admission gates, approval, or registry steps
- Does not modify strategy.py logic (directive-level filters only)
- Does not chain accepted changes into subsequent passes
- Does not auto-deploy accepted hypotheses
- Does not perform cross-strategy learning
- Does not relax thresholds on rejection
- Does not combine multiple insights into a single pass

---

### Relationship to Other Workflows

| Workflow | Relationship |
|---|---|
| `execute-directives.md` | **Called by** this workflow for every pipeline pass (Step 4) |
| `promote.md` | **Called after** this workflow for accepted hypotheses (human decision) |
| `portfolio-research.md` | Independent — can run on hypothesis pass results post-hoc |
| `system-health-maintenance.md` | Independent — run if workspace drift detected |

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
