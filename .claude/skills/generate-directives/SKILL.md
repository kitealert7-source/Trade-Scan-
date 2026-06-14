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
6. **Backtest window convention.** Single-asset directives span `[2024-01-02, max-available]`
   (`config/backtest_dates.py::resolve_dates(tf, stage="extended")`; 2024-01-02 = the first bar
   on/after the 2024-01-01 floor, since 01-01 is a market holiday). Cointegration directives stay
   **per-span** — bounded to cointegrated spans with `entry_date ≥ 2024-01-01`, each a separate
   test on its own `[entry_date, exit_date]` window (a fixed 2024→max window is rejected by
   `window_validity_gate`, which requires containment in one cointegrated span — #4 above /
   [[feedback_test_window_must_match_signal_class]]). Apply the **same** window to reference and
   variant; when transforming a reference whose window predates this convention, re-baseline both
   to it so the comparison stays matched. *(Doc convention; tool auto-set / generator `--since`
   are pending — see [`/rerun-backtest`](../rerun-backtest/SKILL.md) "Backtest date window".)*

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

1. **Source — via `resolve_baseline` (the authority):** do not hand-pick from
   `backtest_directives/completed/`. Call the resolver; it selects the **`is_current`** run
   (never a superseded first-match) and returns the executable **seed** — the byte-exact
   directive — from the run's governed homes:

   // turbo

   ```bash
   python tools/resolve_baseline.py <reference_handle> --json
   ```

   Use `seed.path` as the source directive — it already encodes that run's validated windows +
   exact config. **Graceful degradation:** the resolver walks a fallback ladder
   (`DIRECTIVE_SOURCE.txt` → `runs/<run_id>/directive.txt` → `strategies/<id>/directive.txt` →
   `completed/` → git), so `completed/` is still the source for older runs — just reached
   *through* the resolver, not by hand. If `seed.source` is `ABSENT` (unrecoverable), it says so;
   surface that rather than guessing a baseline.
2. **Change ONE variable:** a param (`z_entry: 2.5 → 4.0`, add `z_stop: 3.0`), keeping the
   rule; OR swap `recycle_rule.name` — if that rule isn't pipeline-routable yet, build it
   via [`/port-strategy`](../port-strategy/SKILL.md) **first**.
3. **Retag the series** to a disjoint token (`GP_ZCRS → GP_ZSTOP3`, `Z25 → Z40`) in
   name / strategy / hypothesis_variant — no collision in MPS / ledger / `completed/`.

## B · Generate a new corpus (when no reference run exists)

// turbo

```bash
python tools/generate_cointrev_v3_directives.py \
    --exit-variant <baseline|zcross|zband|zopp> --sizing-mode <granular_parity|notional|notional_ctl> \
    --z-entry <2.0|2.5|3.0|...> --n-window <30|...> --since <YYYY-MM-DD> [--lookback 252] --dry-run
```

Enumerates qualifying continuous-cointegrated spans (look-ahead-safe, N=5) and emits one
directive per span. `--dry-run` prints the span count; drop it to write staging. The recycle-rule
params are **directive-driven** — `--z-entry`, `--n-window`, `--n-meta`, `--entry-mode` (the
directive guides the experiment; nothing is hardcoded). Defaults reproduce the historical baseline
**byte-identically**; a non-default `z_entry` flips a `_Z<int(z*10)>` cohort tag (2.5 -> `_Z25`) so
passes at different thresholds stay disjoint. The backtest-window convention passes
**`--since 2024-01-01`** — keeps only spans entering on/after the floor, each per-pair
`[entry,exit]` window preserved (NOT clipped); cf. [`/rerun-backtest`](../rerun-backtest/SKILL.md)
"Backtest date window" + [[feedback_test_window_must_match_signal_class]].

## Validate directive integrity (before any run)

- **One moving variable:** assert the *only* differences from the reference run are your
  one variable + the tag; everything else (windows, sizing, fill timing, CXN1) byte-preserved.
- **Dispatch pre-flight:** `_instantiate_rule(...)` on one directive returns the expected
  rule with the expected params.

## Hand off

Stage → `backtest_directives/INBOX/` → [`/execute-directives`](../execute-directives/SKILL.md),
which re-checks new-rule routing and "exit 0 ≠ success."

## Implementation caveats (current tooling — NOT doctrine)

*As of 2026-06-14:* `generate_cointrev_v3_directives.py`'s recycle-rule params are now
**flags** — `--z-entry` / `--n-window` / `--n-meta` / `--entry-mode` (+ `--since` for the
date bound). Defaults reproduce the historical template byte-for-byte; non-default `z_entry`
gets a `_Z<int(z*10)>` cohort tag. (Supersedes the prior "hardcoded z_entry=2.0, edit the
template" caveat — that template edit is no longer needed.) Note: it still **cannot reproduce
the `CXN1` token** — that is applied by a separate naming module, not the generator.

## Anti-patterns

- **Generating a comparison** — the generator can't preserve a reference run's config, so
  it silently tests a *different* config. Transform instead.
- **Changing >1 variable** in a comparison — uninterpretable.
- **Not retagging** — series collision in MPS / ledger / completed.
- **Trusting a formed directive unverified** — no one-moving-variable assert, no pre-flight.
- **Hand-writing a directive** when transforming the reference run would be exact and safer.

## Related skills

- [`/execute-directives`](../execute-directives/SKILL.md) — runs the formed directives (next stage).
- [`/hypothesis-testing`](../hypothesis-testing/SKILL.md) — orchestrator; calls this skill (stage 2) to form directives.
- [`/port-strategy`](../port-strategy/SKILL.md) — build a new recycle rule before transforming onto it.

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _new skill 2026-06-12 — no friction yet_ | | |
