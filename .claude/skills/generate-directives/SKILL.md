---
name: generate-directives
description: Form the backtest directive(s) from a hypothesis — decide whether a specific reference run must be preserved (transform its directives) or a new corpus is being created (generator), generate, validate integrity, then hand off to /execute-directives.
---

# /generate-directives — Form directives from a hypothesis

The front-end of the research pipeline:

```
generate-directives → execute-directives → analyze → decision
```

A hypothesis arrives as intent ("test z_stop=3.0", "enter deeper at z=4"), not a
finished `.txt`. This skill is the single place that turns intent into validated,
admitted directives, then hands off. It owns the formation decision; it does not run,
analyze, or decide.

> **Reference run** = the specific prior experiment a comparison is made against — a
> previous approved deployment, the current production config, a prior hypothesis run,
> a historically important experiment, or any deliberately chosen comparator. Not a
> "best" and not a "control" — just *the run whose context must be preserved*.

## Responsibilities (the flow)

```
hypothesis
  ↓  classify experiment type      — preserving a reference run  vs  new corpus
  ↓  choose formation method       — transform  vs  generator                 ◀ the decision
  ↓  generate directives
  ↓  validate directive integrity  — one moving variable + dispatch pre-flight
  ↓  hand off to /execute-directives
```

## Doctrine (durable — survives any tool rewrite)

1. **The critical question is not "which script?" but "am I preserving a specific
   reference run, or creating a new corpus?"** A comparison requires preserving the
   reference run's context — its windows *and* its config. **If a formation method
   cannot preserve that context, it is the wrong method.** Everything else follows.
2. **The directive is downstream of the hypothesis.** Start from intent + the right
   method, never from "I already have a directive."
3. **One moving variable, or it is not a comparison.** A variant is interpretable only
   if it differs from the reference run in *exactly one* thing.
4. **Matched windows, or it is not a comparison.** Reference run and variant must run
   the *same* cointegrated spans.
5. **A formed directive is unverified until proven** (one-moving-variable + dispatch
   pre-flight). Forming ≠ running.

## The decision (the centerpiece)

```
Do you already have a specific reference run whose windows + config must be preserved?
  ├─ YES → Transform the reference run's directives   (Method A)
  └─ NO  → Generate a new corpus                       (Method B)
```

That gate *is* the decision. The framings below are only *why*:

- **Comparison** — a variant vs a reference run, one variable changed → a reference run
  exists → **transform**.
- **New corpus** — a fresh config with no comparator (new exit family, sizing, lookback,
  an idea's first cohort) → no reference run → **generate**.
- *(Re-running an exact prior config → `/rerun-backtest`, not this skill.)*

## A · Transform the reference run's directives (when a reference run exists)

1. **Source:** the reference run's directives in `backtest_directives/completed/` — the
   run you're comparing against (e.g. the current deployed config `*GP_ZCRS_CXN1_Z25*`).
   They already encode that run's validated windows + exact config.
2. **Change ONE variable:** a param (`z_entry: 2.5 → 4.0`, add `z_stop: 3.0`), keeping the
   rule; OR swap `recycle_rule.name` — if that rule isn't pipeline-routable yet, build it
   via [`/port-strategy`](../port-strategy/SKILL.md) **first**.
3. **Retag the series** to a disjoint token (`GP_ZCRS → GP_ZSTOP3`, `Z25 → Z40`) in
   name / strategy / hypothesis_variant — no collision in MPS / ledger / `completed/`.

## B · Generate a new corpus (when no reference run exists)

// turbo

```bash
python tools/generate_cointrev_v3_directives.py --exit-variant <baseline|zcross|zband|zopp> --sizing-mode <granular_parity|notional|notional_ctl> [--lookback 252] --dry-run
```

Enumerates qualifying continuous-cointegrated spans (look-ahead-safe, N=5) and emits one
directive per span. `--dry-run` prints the span count; drop it to write staging. The
generator **cannot reproduce an arbitrary reference run's config** without template edits
(see *Implementation caveats*) — which is *why* a comparison transforms instead.

## Validate directive integrity (before any run)

- **One moving variable:** assert the *only* differences from the reference run are your
  one variable + the tag; everything else (windows, sizing, fill timing, CXN1) byte-preserved.
- **Dispatch pre-flight:** `_instantiate_rule(...)` on one directive returns the expected
  rule with the expected params.

## Hand off

Stage → `backtest_directives/INBOX/` → [`/execute-directives`](../execute-directives/SKILL.md),
which re-checks new-rule routing and "exit 0 ≠ success."

## Implementation caveats (current tooling — NOT doctrine)

*As of 2026-06-12:*
- `generate_cointrev_v3_directives.py` hardcodes `z_entry=2.0, n_window=30,
  entry_mode=absolute` (no CLI flags). It therefore **cannot reproduce an arbitrary
  reference run** without editing the template (≈ lines 387–390) — a Protected-
  Infrastructure change (plan + approval). If it later gains CLI flags for these, this
  caveat is obsolete; the doctrine above is not.

## Anti-patterns

- **Generating a comparison** — the generator can't preserve a reference run's config, so
  it silently tests a *different* config. Transform instead.
- **Changing >1 variable** in a comparison — uninterpretable.
- **Not retagging** — series collision in MPS / ledger / completed.
- **Trusting a formed directive unverified** — no one-moving-variable assert, no pre-flight.
- **Hand-writing a directive** when transforming the reference run would be exact and safer.

## Related skills

- [`/execute-directives`](../execute-directives/SKILL.md) — runs the formed directives (next stage).
- [`/basket-hypothesis-testing`](../basket-hypothesis-testing/SKILL.md) — orchestrator; calls this skill to form variant directives.
- [`/port-strategy`](../port-strategy/SKILL.md) — build a new recycle rule before transforming onto it.

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _new skill 2026-06-12 — no friction yet_ | | |
