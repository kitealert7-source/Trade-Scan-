# Kill-Switch Redesign Proposal — 2026-05-18

> **Status:** APPROVED (operator, 2026-05-18). Implementation in progress.
> **Scope:** `TS_SignalValidator/validators/guard.py` — `_check_kill_switch`
> **Plan v11 impact:** Material design change. Captured here as the formal
> governance artifact because plan v11 is LOCKED and modifications require
> an explicit revision proposal.

---

## 1. Why we're changing the kill-switch

The current `StrategyGuard._check_kill_switch` has three rules, all of
which derive their thresholds from per-strategy backtest baselines:

| Rule | Trigger | Baseline dependency |
|---|---|---|
| `HALT_LOSS_STREAK` | `live_loss_streak > baseline.max_loss_streak × multiplier (1.5)` | `bl.max_loss_streak` |
| `HALT_WIN_RATE` | `live_rolling_win_rate < baseline.expected_win_rate × tolerance (0.65)` | `bl.expected_win_rate` |
| `HALT_EQUITY_DD` | `live_equity < starting - baseline.max_drawdown_usd × multiplier (2.0)` | `bl.max_drawdown_usd` |

### What today's evidence showed (2026-05-18 Stage 5 replay)

The validator replayed the `shadow_journal_2026_04_to_05` corpus and
halted 5 of 6 portfolio strategies via `HALT_EQUITY_DD`:

```
AUDJPY:  HALT_EQUITY_DD  ($9,942.74 / $10,000 start)
AUDUSD:  HALT_EQUITY_DD  ($9,873.00 / $10,000 start)
GBPJPY:  HALT_EQUITY_DD  ($9,934.68 / $10,000 start)
NAS100:  HALT_EQUITY_DD  ($714.58   / $1,000  start)  ← 28.5% live DD
XAUUSD:  HALT_EQUITY_DD  ($9,671.21 / $10,000 start)
```

(The 6th — BTCUSD — halted via `hard_fail`, which is a schema/wiring
issue at a different layer, unrelated to this proposal.)

### The conflation problem

The current rule bundles two distinct concerns under one trigger:

1. **Capital preservation** — "don't lose more than I can afford"
2. **Strategy invalidation detection** — "this strategy stopped working"

This bundling produces false positives. When a strategy has a
worse-than-historical month it crosses the baseline-derived threshold
and is HALTED — even if its current state is within a reasonable
operator's risk tolerance. The kill-switch becomes a statistical
*model-fit detector* rather than a *risk-management backstop*.

### What we want instead

Separate the concerns:

- **Kill-switch = capital preservation only.** A mechanical floor.
  Trigger is independent of backtest quality.
- **Strategy invalidation = human analysis.** Operator reviews trade
  tape, regime, slippage, and fills *after* the validator surfaces a
  DD event. No automated "this strategy is broken" conclusion.

---

## 2. New design (locked)

### 2.1 The rule

Single trigger:

```
HALT if  current_equity < 0.60 × peak_equity_in_last_90_days
```

That is: **40% trailing drawdown from the strategy's rolling 90-day
peak equity**.

### 2.2 When the rule fires

**Daily, at 00:00 UTC.** Between checks, the validator does not
evaluate the kill condition. Equity and peak tracking continues
in real time (cheap); the gate evaluation is the only daily action.

### 2.3 No soft-alert channel

Removed from the design. The kill-switch is intentionally generous
(40% from peak is rarely tripped in normal operation). When it
fires, the event is by construction significant — no need for a
preceding "soft" notification tier. Operator-level monitoring of
intra-day risk lives outside the validator (manual review).

### 2.4 Granularity

**Per-strategy.** Each strategy gets its own peak and floor. One
strategy halting does not affect others. Portfolio-aggregate
protection is a separate concern that belongs in the allocator
layer (sizing), not the validator (gating).

### 2.5 Restart / unkill

**Manual operator unlock only.** When the kill fires:

1. Strategy state persists as `HALTED` in `state/kill_state/<id>.json`.
2. To re-enable, operator runs:
   ```
   python tools/unlock_kill_switch.py --strategy <id> --reason "<analysis>"
   ```
3. CLI requires `--reason` (free-text operator analysis); writes the
   reason to `state/kill_state/<id>_unlock_log.jsonl` for audit trail.
4. Validator reads `kill_state/<id>.json` on startup and per check —
   honors the unlock immediately.

No automatic re-enable on equity recovery. No time-based release.
A kill fire = mandatory operator engagement before trading resumes.

---

## 3. Comparison table

| Concern | Old design | New design |
|---|---|---|
| Trigger | 3 rules (LOSS_STREAK, WIN_RATE, EQUITY_DD), all baseline-comparison | 1 rule, peak-DD only |
| Fires on each | `record_trade()` call (event-driven) | Daily 00:00 UTC tick (time-driven) |
| Backtest dependency | High — every threshold derived from baseline stats | Zero — observe live equity only |
| Per-strategy tuning | Yes (each strategy has own thresholds) | No (40% rule uniform) |
| False-positive rate | High (5/6 in Apr-May 2026 replay) | Designed to be ~0 except for catastrophe |
| Restart | Not currently supported (HALTED is sticky in memory only) | Manual unlock with logged operator analysis |
| Lines of code | ~50 (3 rules + their detail strings) | ~30 (single rule + state IO) |

---

## 4. Implementation plan

### 4.1 Code changes

**`TS_SignalValidator/validators/guard.py`:**
- Add `daily_equity_log: list[tuple[str, float]]` field to `StrategyGuard`
- Add `last_check_event_utc: str | None` field
- Add `check_peak_drawdown_kill(event_utc: str) -> None` method
- Remove old `_check_kill_switch` (preserve as `_legacy_check_kill_switch_DEPRECATED` for one release if needed for migration; otherwise delete)
- `record_trade()` no longer calls the old kill check — just updates state
- New `_persist_kill_state()` writes `kill_state/<id>.json` on state change
- New `_load_kill_state()` reads on init
- Update `from_vault()` to pass through baseline still (we don't gate on it but it's useful metadata)

**`TS_SignalValidator/validators/signal_validator.py`:**
- Main event loop calls `guard.check_peak_drawdown_kill(event_utc)` on every event
- The guard internally checks if a day boundary has crossed; if not, no-op

**`TS_SignalValidator/tools/unlock_kill_switch.py` (NEW):**
- CLI: `--strategy <id> --reason "<text>"`
- Updates `kill_state/<id>.json` to `halted: false`
- Appends to `kill_state/<id>_unlock_log.jsonl`

**`TS_SignalValidator/decision_emitter.py`:**
- Update the kill-switch reason string format: `HALT_PEAK_DD` event type

**`TS_SignalValidator/config.*.yaml`:**
- Add new keys:
  ```yaml
  kill_switch:
    peak_window_days:    90
    threshold_pct:       40   # halt if equity < (100 - 40)% = 60% of peak
    check_interval:      daily_00_utc
  ```
- Mark old keys `dd_multiplier`, `max_loss_streak_multiplier`,
  `win_rate_tolerance`, `rolling_window_trades` as DEPRECATED (still
  parsed for backward compat but unused).

### 4.2 Test changes

**`TS_SignalValidator/tests/test_peak_drawdown_kill.py` (NEW):**
1. New peak high → updates peak; no kill
2. 39.9% from peak → no kill (just under threshold)
3. 40.0% from peak → kill fires (boundary)
4. 40.1% from peak → kill fires
5. Daily check fires once per day (not per event)
6. Rolling 90-day window: peak from day 100 doesn't matter if today is day 200
7. Kill state persists across `StrategyGuard` reinit
8. Operator unlock restores `ACTIVE` state
9. Unlock requires `--reason`; CLI errors without it
10. Unlock log appends one record per unlock

**Existing tests to update:**
- `test_strategy_guard.py` — old `HALT_LOSS_STREAK` / `HALT_WIN_RATE` /
  `HALT_EQUITY_DD` tests deleted (no longer relevant)
- `test_adversarial_phase7a.py` — kill-switch stickiness tests need to
  reflect the new event type `HALT_PEAK_DD`

### 4.3 Documentation

- This proposal doc lives at `outputs/system_reports/01_system_architecture/`
- `PHASE_7A_PROGRESS_AUDIT.md §7` gets a decision-log row referencing
  this proposal
- `H2_PLAN_REVISION_PROPOSAL_2026-05-15.md` (if it references kill
  behavior) gets a cross-reference

---

## 5. Migration

Stage 5 (current 72h field stress) was running on the OLD kill-switch.
Operator stopped both `TS_SignalValidator_Stage5` and
`TS_SignalValidator_Stage5_Monitor` at 2026-05-18 ~15:34 IST before
this implementation begins.

After implementation lands + tests pass + commits push, the validator
gets restarted with the new code in place. The fresh Stage 5 cycle
will run against the same shadow journal but evaluate kills under the
new rule. Expected outcome: 0 kill-fires (since 40% from peak is
deliberately generous for normal-vol replay).

---

## 6. Open questions / future work

None blocking implementation. Future considerations:

1. **Portfolio-aggregate kill** (if ever wanted): separate proposal,
   lives in allocator layer, not validator.
2. **Variable threshold per strategy** (if some strategies want a
   tighter floor): trivial config extension — `threshold_pct` becomes
   optional per-strategy override. Not in v1.
3. **Notification on close-to-trigger** (e.g., 35% from peak alert):
   explicitly *not* included per the design discussion. Add later as
   a separate observability concern if monitoring need surfaces.

---

## 7. Approval

| Date | Actor | Decision |
|---|---|---|
| 2026-05-18 | Operator | APPROVED — implement with defaults as proposed (90d window, 40% threshold, daily 00:00 UTC check, per-strategy, manual unlock) |
| 2026-05-18 | Claude (executor) | Implementation in progress — see commit log |
