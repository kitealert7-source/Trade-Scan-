# COINTREV v1.2 — Trigger-Driven β-Weighted Spread Strategy
## Design doc for next session

**Status:** DRAFT — design captured 2026-05-23, implementation deferred
**Owner:** research-strategy layer
**Author:** captured at end of 2026-05-23 infrastructure session
**Supersedes:** the retired equal-lot COINTREV v1 (`tools/recycle_rules/cointegration_meanrev_v1.py`, removed 2026-05-21 per RESEARCH_MEMORY retirement entry)
**Depends on:** `cointegration_triggers` table (Phase 1a, 2026-05-23, commit ee5c857) — without this design is infeasible.

---

## 1. The problem this design solves

The 2026-05-21 retirement of COINTREV v1 left a known gap: we had no β-weighted strategy actually trading the screener's signals. The 2026-05-23 v2.1 event study predicted negative edge for FX-FX; the realized-backtest tool (Phase 3, same day) measured 80-95% reversion on real triggers. The v2.1 reconstruction-based and the realized-replay analyses disagree by ~55-65 percentage points.

To reconcile — and to actually validate whether the signals are tradeable — we need to backtest a properly β-weighted spread strategy on the screener's signals through the H2 basket pipeline, getting real $ P&L, drawdown, expectancy, Sharpe per pair-cluster.

The `cointegration_triggers` ledger built today is the prerequisite. Each row = "the screener flagged this pair on this date at this z, with this β". The strategy reads this ledger as its entry-signal stream.

---

## 2. Design decision: backtest granularity

### Misconception to clear up

**Wrong mental model:** "1 trigger event = 1 backtest run, so 865 backtests."

That's single-symbol-strategy thinking. The basket pipeline supports multi-trade-per-run.

### Right granularity: 1 directive per pair-pair, full year date range

```
286 directives
    ×  full-year date range each (e.g. 2025-05-23 → 2026-05-22)
    ×  strategy reads cointegration_triggers for that pair-pair
       on each bar, opens β-weighted basket on trigger dates,
       closes on reversion / stop / time-stop
    =  865 total trades across the cohort
       (each pair generates 1-19 sequential trades over the year)
```

Avg ~3 trades per pair, median probably 2-3, top pair (NZDUSD/USDCAD) = 19 trades.

### Edge cases for the strategy (BASE RUN — no pyramid, no hard stop)

Per operator direction 2026-05-23: base run captures the **pure cointegration
mean-reversion thesis** without mixing in stop-loss tail truncation. The
regime-break exit IS the de facto stop loss for a spread trade — when the
screener says regime is broken, qualification is gone, position closes. No
separate z-based hard stop in base run.

| Scenario | Decision |
|---|---|
| Trigger arrives while position is already open | **SKIP** — same direction, already covered. Don't pyramid. |
| `|z|` returns inside ±exit_z band | **MEAN-REVERSION EXIT** — primary success path. Bar of exit recorded for bars-to-reversion stat. |
| Regime breaks (broken/breaking) during open position | **REGIME-BREAK EXIT** — close at next bar. This IS the de facto stop loss for a cointegration trade; qualification is gone so the thesis is invalid. Per v2.1 event study `qual_break_rate` was 95-100%, so this exit fires reliably. |
| Reversion not reached within FORWARD_BARS (default 60) | **TIME-STOP EXIT** — close at bar 60 regardless of z. Thesis unresolved. |
| Adverse z excursion past entry | **NOT EXITED in base run** — recorded as an output metric per trade (max adverse \|z\| during position), but no explicit hard stop. v1.2.1 may add this after base results are evaluated. |

---

## 3. Architecture

```
SQLite cointegration_triggers (865 first-crossing events)
        │
        │  generate one directive per (pair_a, pair_b)
        ▼
286 directives in active/
    e.g. 90_PORT_CHFJPYUK100_15M_COINTREV_V2_P00.txt
         strategy: cointegration_meanrev_v1_2
         legs: [CHFJPY, UK100]
         date_range: 2025-05-23 → 2026-05-22
         params:
             entry_source: cointegration_triggers
             lookback_filter: 252  (or 504 — separate directive per window?)
             exit_z: 1.0
             time_stop_bars: 60
             hard_stop_z_above_entry: 2.0
             lot_sizing: octafx_beta_neutral
        │
        ▼
tools/basket_pipeline.py runs each directive
        │
        ▼
TradeScan_State/backtests/<run_id>/raw/results_basket_per_bar.parquet
        │
        ▼
Aggregator: per-pair-cluster P&L roll-up
    outputs/cointegration_screener_v1/v1_2_backtest/
        REPORT_<date>.md
        per_pair_results.csv
```

### New code surfaces

| Path | Purpose | LOC estimate |
|---|---|---|
| `tools/recycle_rules/cointegration_meanrev_v1_2.py` | β-weighted basket strategy, trigger-ledger-driven entry | ~250 |
| `tools/generate_cointrev_v1_2_directives.py` | Scan cointegration_triggers, emit one directive per pair_a/pair_b | ~100 |
| `governance/recycle_rules/registry.yaml` | Add `cointegration_meanrev_v1_2` entry | +5 lines |
| `tools/basket_pipeline.py:_try_basket_dispatch` | Add dispatch branch | +10 lines |
| `tools/cointrev_v1_2_aggregator.py` | Read backtest outputs, aggregate per-class report | ~150 |
| Tests | `test_cointegration_meanrev_v1_2.py`, dispatch test | ~150 |

Total: ~650-700 new LOC + 5-line yaml/registry edits.

---

## 4. Strategy class spec — `cointegration_meanrev_v1_2`

### Inputs (params) — BASE RUN

| Param | Default | Notes |
|---|---|---|
| `entry_source` | `"cointegration_triggers"` | SQLite table name; allows future swap to a stub for testing |
| `lookback_filter` | `252` | Only trigger if matching lookback row exists; one directive per lookback (avoid double-counting) |
| `exit_z` | `1.0` | Spread z that triggers mean-reversion exit |
| `time_stop_bars` | `60` | Time stop — close at this bar regardless of z |
| `regime_break_action` | `"exit_at_next_bar"` | Mandatory; serves as the de facto stop loss for the trade |
| `min_gap_days_between_triggers` | `5` | Dedupe consecutive triggers (matches Phase 3 default) |
| ~~`hard_stop_z_above_entry`~~ | ~~`2.0`~~ | **REMOVED for base run.** No z-based hard stop. v1.2.1 may add this after base results are evaluated. |

### Optional params for v1.2.x extensions (NOT in base run)

These would be added in subsequent iterations to measure their incremental
effect on top of the base. Don't include in v1.2 base directives.

| Param | Future default | Purpose |
|---|---|---|
| `hard_stop_z_above_entry` | `2.0` | Z-based hard stop (cuts adverse tail); v1.2.1 |
| `enable_pyramid` | `false` | Add to position on new trigger if already in; v1.2.2 |
| `harvest_scale_out` | `false` | Partial close at intermediate z levels; v1.2.3 |
| `pre_break_exit` | `false` | Exit when regime flips to "breaking" (one step before "broken"); v1.2.4 |

Doctrine: each v1.2.x adds **one knob**. Compare against base (and previous
x) to attribute the delta. Don't bundle 3 changes in one variant or you
can't tell which helped.

### Bar-by-bar logic

```python
def on_bar(self, bar):
    # 1. If we have an open position, check exits FIRST
    if self.position_open:
        if self.regime_at(bar) != 'cointegrated':
            self.close_position(reason='regime_break')
        elif abs(self.spread_z_at(bar)) <= self.params.exit_z:
            self.close_position(reason='mean_reversion')
        elif self.bars_in_position >= self.params.time_stop_bars:
            self.close_position(reason='time_stop')
        elif self.spread_z_at(bar)_breached_hard_stop():
            self.close_position(reason='hard_stop')
        return

    # 2. No position: check for new trigger
    trigger = self.lookup_trigger(bar.as_of, self.pair_a, self.pair_b,
                                    lookback=self.params.lookback_filter)
    if trigger is None:
        return

    # 3. Skip if within min_gap_days of last entry on this pair
    if self.last_entry_date and (bar.as_of - self.last_entry_date).days < self.params.min_gap_days_between_triggers:
        return

    # 4. Open β-weighted position
    lot_a, lot_b = self.compute_neutral_basket(trigger.beta_at_trigger)
    direction = trigger.direction  # LONG_SPREAD or SHORT_SPREAD
    self.open_basket(self.pair_a, lot_a, self.pair_b, lot_b, direction)
    self.last_entry_date = bar.as_of
```

### Lot sizing — reuse existing infrastructure

`tools.cointegration_excel._compute_neutral_basket()` already implements the β-neutral basket lot calculation using OctaFX broker specs (commit da6c8bf). Just import + call it. NO new sizing code needed.

---

## 5. Directive generation

`tools/generate_cointrev_v1_2_directives.py`:

```python
def main():
    # Read all unique pair-pairs from cointegration_triggers
    conn = connect(SQLITE_DB)
    pairs = conn.execute("""
        SELECT DISTINCT pair_a, pair_b, lookback_days
        FROM cointegration_triggers
        ORDER BY pair_a, pair_b, lookback_days
    """).fetchall()

    # Date range = full trigger history extent (auto-pick)
    earliest = conn.execute("SELECT MIN(as_of) FROM cointegration_triggers").fetchone()[0]
    latest = conn.execute("SELECT MAX(as_of) FROM cointegration_triggers").fetchone()[0]

    for pair_a, pair_b, lookback in pairs:
        # Each (pair, lookback) gets its own directive
        write_directive(
            name=f"90_PORT_{pair_a}{pair_b}_15M_COINTREV_V2_L{lookback}",
            strategy="cointegration_meanrev_v1_2",
            symbols=[pair_a, pair_b],
            date_range=(earliest, latest),
            params={
                "entry_source": "cointegration_triggers",
                "lookback_filter": lookback,
                "exit_z": 1.0,
                "time_stop_bars": 60,
                # ... defaults from spec
            },
        )
```

Output: ~347 directives (286 unique pair-pairs × 1-2 lookbacks each).

To start: do 252-lookback only → 286 directives. Add 504 in a second pass if needed.

---

## 6. Reporting

Per-directive output (basket_pipeline standard): equity curve, trade list, Sharpe, MaxDD per pair.

Per-class aggregator: roll up per pair_class (FX / IDX / CROSS), per direction (LONG_SPREAD vs SHORT_SPREAD).

Key metrics to report:
- **Win rate per class** — does the realized 80-95% reversion translate to win rate, or do losers cluster?
- **Net $ per class** — is the edge tradeable after slippage / spread cost / time-in-market?
- **MaxDD per class** — does the regime-break-during-position exit save capital effectively?
- **Sharpe per class** — risk-adjusted edge
- **Comparison vs v2.1 + Phase 3 report** — three data points: reconstruction, statistical replay, actual backtest

---

## 7. Open questions for next session

1. **One directive per lookback or one combined?** Start with 252-only (286 directives). If results encouraging, run 504 as separate cohort. Don't mix — entry semantics differ between windows.

2. **Hard stop magnitude?** Defaulted to z_entry+2.0; could also use the p90 adverse excursion empirical value (1.4-1.7) from the v2.1 event study. The empirical stop is tighter (~3.5 hard stop on 2.0 entry vs 4.0 default).

3. **Should we allow re-entry after a stop-out?** Default: yes, on the NEXT trigger after a 5-day gap. Could also lock out a pair for longer after a stop.

4. **Concurrent positions across pairs?** YES — different pair-pairs are independent. The basket pipeline already handles this. Portfolio-level risk caps (max concurrent positions, max $ at risk) would need a separate wrapper.

5. **Do we need a survivor-bias check?** The trigger ledger was backfilled using TODAY's COINT_UNIVERSE — if a pair didn't exist in MASTER_DATA a year ago, it doesn't appear in triggers. That's fine for the strategy (the screener wouldn't have flagged it either) but the result population is asymmetric vs a pair-pair that existed throughout.

6. **What's "success"?** Define explicitly before running, to avoid post-hoc rationalization:
   - **Strong:** Sharpe ≥ 1.5 per class on net-of-cost basis, MaxDD ≤ 20%
   - **Moderate:** Sharpe ≥ 1.0, edge positive after costs, MaxDD ≤ 30%
   - **Weak (no-go):** Sharpe < 0.8 OR negative net after costs OR MaxDD > 40%

---

## 8. Implementation order for next session

1. Build the strategy class (`cointegration_meanrev_v1_2.py`) — ~250 LOC
2. Write 3-5 unit tests against fixture trigger ledger
3. Add to recycle_rules registry + basket dispatch
4. Write directive generator — ~100 LOC
5. Generate 286 directives (252-lookback only first pass)
6. Run through basket_pipeline as a batch
7. Aggregate via cointrev_v1_2_aggregator — ~150 LOC
8. Write report `outputs/cointegration_screener_v1/v1_2_backtest/REPORT_<date>.md`
9. Compare against v2.1 reconstruction + Phase 3 realized replay — three-way table

**Estimated session length:** 4-6 hours of focused work assuming basket_pipeline knowledge already fresh.

---

## 9. Pre-session checklist

Before resuming, confirm:
- `cointegration_triggers` table populated (865 rows, today's backfill) ✓
- OctaFX broker spec YAMLs current (refresh via DATA_INGRESS daily post-hook) ✓
- basket_pipeline.py + H2 engine current (last touched 2026-05-22) ✓
- recycle_rules infrastructure understood — read tools/basket_runner.py if it's been a while
- DRY_RUN_VAULT space available (~5-10 GB for 286 backtest run_ids)

If any of these is stale, fix it first; otherwise jump to step 1.

---

## 10. What this design replaces (and what it doesn't)

**Replaces:** the retired COINTREV v1 (equal-lot, no trigger ledger). v1.2 fixes both the sizing bug AND the entry-signal opacity.

**Does NOT replace:** the screener itself. The screener is the monitoring + signal-generation layer; v1.2 is the strategy that ACTS on those signals. Both run in parallel.

**Does NOT replace:** the v2.1 event study or the Phase 3 realized-backtest. Those are statistical / regime-replay analyses. v1.2 will be the THIRD data point — full strategy backtest with real P&L mechanics. The three-way comparison is the deliverable.
