---
name: to-waiting
description: Transition a strategy from BURN_IN to WAITING after burn-in passes
---

# /to-waiting -- Post Burn-In Transition

Moves a strategy from BURN_IN to WAITING lifecycle. Creates a lightweight snapshot
in DRY_RUN_VAULT/WAITING/ (vault reference + decision + summary only -- no data
duplication). Disables the strategy in portfolio.yaml.

> **Human-gated**: Only runs when explicitly triggered with a decision.

---

## Input

The human provides:
- **Strategy ID** (required) -- e.g., `27_MR_XAUUSD_1H_PINBAR_S01_V1_P05`
- **Decision** (required) -- `PASS`, `FAIL`, or `HOLD`
- **Notes** (optional) -- decision rationale
- **Burn-in metrics** (optional) -- trades, PF, WR, DD from monitoring

---

## Pre-Conditions (verify ALL)

// turbo

1. Strategy is in `portfolio.yaml` with `lifecycle: BURN_IN`
2. Strategy has a `vault_id` field in portfolio.yaml
3. Vault snapshot exists at `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/meta.json`
4. No existing WAITING snapshot for this strategy (idempotent guard)

If ANY fails, STOP and report.

---

## Step 1: Gather Burn-In Metrics

// turbo

If burn-in metrics are available from `burnin_monitor.py`:

```bash
cd ../TS_Execution && python tools/burnin_monitor.py --no-mt5
```

Record: total trades, PF, win rate, max DD, duration.

If not available, the human provides them manually or they can be edited in the
WAITING snapshot after creation.

---

## Step 2: Run Transition

// turbo

```bash
python tools/transition_to_waiting.py <STRATEGY_ID> \
    --decision PASS \
    --notes "description of why" \
    --burnin-trades 95 \
    --burnin-pf 1.35 \
    --burnin-wr 0.58 \
    --burnin-dd 4.2
```

Use `--dry-run` first to preview:

```bash
python tools/transition_to_waiting.py <STRATEGY_ID> --decision PASS --dry-run
```

**What this does:**
1. Validates strategy is BURN_IN with vault_id
2. Creates `DRY_RUN_VAULT/WAITING/{ID}_{date}/` with 3 files:
   - `vault_ref.json` -- pointer to full vault snapshot (vault_id + run_id)
   - `decision.json` -- PASS/FAIL/HOLD + rationale
   - `burnin_summary.json` -- burn-in execution metrics
3. Updates portfolio.yaml: `enabled: false`, `lifecycle: WAITING`
4. Runs WAITING invariant check

**NO data is copied.** The vault_ref.json points to the full vault snapshot.
Storage cost: ~1KB per transition.

---

## Step 3: Validate

// turbo

Run the invariant check to confirm all WAITING strategies are valid:

```bash
python tools/transition_to_waiting.py --validate-only dummy --decision PASS
```

Wait -- simpler:

```bash
python -c "
from tools.transition_to_waiting import validate_waiting_strategies
failures = validate_waiting_strategies()
if failures:
    print(f'FAIL: {len(failures)} violations')
    for f in failures:
        print(f'  - {f}')
else:
    print('OK: All WAITING strategies valid')
"
```

---

## Step 4: Report

Report to the human:

| Item | Value |
|------|-------|
| Strategy | `<STRATEGY_ID>` |
| Decision | PASS / FAIL / HOLD |
| Vault reference | `<vault_id>` |
| WAITING snapshot | `WAITING/{ID}_{date}` |
| portfolio.yaml | enabled: false, lifecycle: WAITING |
| Invariant check | PASS / FAIL |

**Next steps:**
- **If PASS**: Strategy is queued for `/to-live` when capital is allocated
- **If FAIL**: Strategy stays WAITING+disabled. Consider removal from portfolio.yaml
- **If HOLD**: Re-evaluate after more observation time

---

## WAITING Snapshot Structure

```
DRY_RUN_VAULT/WAITING/{STRATEGY_ID}_{date}/
  vault_ref.json        <- pointer to full vault (NO data copy)
  decision.json         <- PASS/FAIL/HOLD + rationale
  burnin_summary.json   <- burn-in execution metrics
```

**Why no data copy?** The full snapshot lives at `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/`.
The vault_ref.json contains the vault_id, which is a deterministic, immutable pointer.
Duplicating ~100 files per strategy serves no purpose when the pointer is unbreakable.

---

## Hard Invariant

**Every strategy with `lifecycle: WAITING` in portfolio.yaml MUST have:**
1. A `vault_id` field pointing to an existing vault snapshot
2. A `WAITING/{ID}_*` folder containing `vault_ref.json`
3. The vault_ref.json must contain a valid vault_id that resolves to a real snapshot

This invariant is checked:
- Automatically at the end of `/to-waiting`
- On-demand via `python tools/transition_to_waiting.py --validate-only`
- Optionally at TS_Execution startup (future integration)

**If the invariant fails, the strategy CANNOT transition to LIVE.**

---

## Related Workflows

| Workflow | Purpose |
|----------|---------|
| `/promote` | Upstream: PIPELINE_COMPLETE -> BURN_IN (creates vault snapshot) |
| `/to-live` | Downstream: WAITING -> LIVE (future, enables strategy) |
| `/portfolio-selection-remove` | Remove strategy from portfolio entirely |

## Related Files

| File | Location |
|------|----------|
| Transition tool | `tools/transition_to_waiting.py` |
| Promote tool | `tools/promote_to_burnin.py` |
| Portfolio YAML | `TS_Execution/portfolio.yaml` |
| WAITING snapshots | `DRY_RUN_VAULT/WAITING/` |
