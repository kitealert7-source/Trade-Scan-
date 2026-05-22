# H2 Telemetry Parity Forensic — B1 Worst-DD Bar

**Status:** Operator gate triggered (worst-DD timestamps differ). Forensic evidence: **Case A confirmed — legacy reconstruction was wrong; emitter is correct per spec.**
**Run date:** 2026-05-16

---

## Operator's gate

> "If timestamps differ or one method sees deeper DD: state-capture bug. STOP. Fix before backfill."

Outcome: **STOP fired.** Worst-DD timestamps differ by 113 days. Below: which method is correct, and why.

---

## Side-by-side at each method's worst-DD bar

| | Emitter parquet | Legacy reconstruction (unpatched) |
|---|---|---|
| Worst-DD timestamp | **2025-02-10 00:05:00** | **2025-06-03 02:40:00** |
| Equity at that bar | $744.68 | $1030.14 |
| Peak equity preceding | $1069.79 | $1524.85 |
| `dd_from_peak_usd` | −$325.11 | −$494.71 |
| Floating PnL | −$372.03 | −$370.06 |
| Realized | $116.71 | $400.19 |

Note: the two methods see different bars as worst-DD AND see different peak equities. The emitter's peak ($1070) is far below the legacy's peak ($1525). The legacy reconstruction sees the basket as growing 52% larger before its worst-DD, then losing more. Which is reality?

---

## Diagnostic at legacy's "worst-DD bar" (2025-06-03 02:40:00)

At the bar the legacy module thinks is worst, emitter records:

| Quantity | Value |
|---|---|
| `floating_total_usd` | −$190.42 |
| `realized_total_usd` | +$400.19 (already banked) |
| `equity_total_usd` | $1209.78 |
| `peak_equity_usd` | $1297.32 |
| `dd_from_peak_usd` | −$87.54 |
| **leg_0 EURUSD** | lot=**0.10**, avg=1.1255, mark=1.1454, float=+$199.60 |
| **leg_1 USDJPY** | lot=**0.10**, avg=147.98, mark=142.43, float=−$390.02 |

The emitter sees the basket as **only $88 below its peak** at this bar — nowhere near the deepest DD. The legacy module computed $495 dd_from_peak. The gap is the legacy's state-model error: at this point of the basket lifecycle, both legs have grown to 0.10 lot. The legacy module's state timeline thinks the legs are at smaller lots, which distorts the entire equity curve from that event forward.

---

## The smoking gun — `recycle_events.jsonl`

The vault stores `recycle_events.jsonl`, written by the rule **at event time**, recording the actual `winner_realized` for each event. Those values were computed using whatever lot the rule had at that moment. This file pre-dates this validation patch entirely.

For B1, the top winner_realized events are:

| Event | Timestamp | Winner | winner_realized | Price move | **Implied lot at event** |
|---|---|---|---|---|---|
| 1 | 2025-07-04 00:05 | EURUSD | $271.50 | 1.14869 → 1.17584 | **0.1000** |
| 2 | 2025-06-04 13:50 | EURUSD | $126.30 | 1.12545 → 1.13808 | **0.1000** |
| 3 | 2025-04-25 10:00 | EURUSD | $83.20 | 1.11858 → 1.13522 | **0.0500** |
| 4 | 2024-11-01 00:00 | USDJPY | $64.36 | 147.16 → 152.05 | **0.0200** |
| 5 | 2025-06-11 13:20 | EURUSD | $57.10 | 1.13808 → 1.14379 | **0.1000** |

Initial leg lot per directive: **0.01**.

If the rule reset winner lot to 0.01 on every realize (legacy module's assumption), the largest possible winner_realized for an EUR move of $0.02715 would be `0.01 × 100k × 0.02715 = $27.15`. The actual event recorded $271.50 — exactly 10× larger — implying the rule used lot=0.10 at that event.

**The events.jsonl on disk directly disagrees with the legacy module's state model.** The rule was using grown winner lots all along. The emitter records this faithfully; the legacy reconstruction overwrites it with a hardcoded 0.01.

---

## Verdict — Case A confirmed

Operator's framing:
- **Case A**: Old reconstruction was wrong → fine, backfill
- **Case B**: New emitter missing some states → dangerous, stop

Evidence supporting Case A:
1. **basket_sim.py:362,388 spec** ("Close winner: realize full floating, reset avg to current price (lot unchanged)") — research-validated rule mechanic explicitly says lot unchanged. The emitter implements this. The legacy module violates it.
2. **recycle_events.jsonl values** — winner_realized at multiple events implies lots well above 0.01 (up to 0.10). The on-disk events were written by the rule, independent of any patch. They prove the rule used grown lots at event time.
3. **Internal consistency** — emitter's equity invariant (`equity = stake + realized + floating`) holds on every record after the same-session fix. Regression test pins it.
4. **Champion-level reproducibility** — all three champions (B1, AJ, B2) show internally consistent ledgers with peak_lots = (0.16, 0.16), (0.26, 0.20), (0.12, 0.18) — all matching the events.jsonl winner_realized inverse-formulas.

Evidence against Case B:
- No symptom of the emitter "missing states." The 35 fixed + 16 leg columns are populated on every bar. The `_record_bar` helper is called from every code path (verified by the `test_skip_reason_*` tests). After the recycle-bar fix, internal invariants hold.
- The emitter's Max DD ($325) matches what one computes from the events.jsonl + basket_sim spec. The legacy module's $495 only matches if one substitutes a wrong state model.

**Conclusion: the emitter is correct. The legacy reconstruction has been overstating DD on every basket where legs grew (which is essentially all of them — H2 is built on cumulative lot growth).**

---

## What this means for prior research

Prior B1 DD reports cited the legacy module's $495 figure. The actual intra-bar Max DD is **$325**. Roughly 35% lower than what was reported.

For AJ: prior $599 — likely also overstated; emitter records the spec-correct value.

For B2: prior $342 vs emitter $331 — small delta because B2's lots peaked at lower values (0.12, 0.18) so the bug had less room to compound.

**Past research notes citing legacy module DD numbers have been over-counting risk by ~5–35% depending on leg-growth.** That's a real correction, not a phantom one.

---

## Updated decision

**Original operator framing:**
- Same timestamp + values differ only by rounding → GO
- Different timestamps or one sees deeper DD → STOP, fix

**The deeper-DD path triggered.** But the gate was crafted to catch a state-capture bug in the new emitter. The forensic shows the deeper-DD path was caused by a state-capture bug in the LEGACY module, not the emitter.

**Recommended action:**
1. **GO on backfill** — the emitter is correct and the on-disk events.jsonl proves it. Backfill writes spec-correct ledgers.
2. **Mark the legacy module as known-wrong** until the Phase 7 refactor lands. Old research analyses that cite its output should be flagged for re-computation against the new parquet.
3. **Fix the legacy module's two bugs** (winner-lot-reset, bar-0 entry-price) in plan §9 Phase 7 alongside the parquet-read refactor. The 3-line fix could land standalone if the operator prefers; it just needs explicit approval per Protected Infrastructure invariant 11.

The risk profile for backfill:
- Backfill produces 268 correct parquet files
- No risk of polluting the archive with wrong DD — the parquet is the truth
- Old MPS Baskets rows from pre-patch runs keep their existing 1.2.0 schema columns; new columns get NaN-filled (handled by basket_ledger_writer.py:213–224)
- Legacy module continues running on legacy runs (still wrong, but unchanged behavior — no regression)

---

## Reproduction

```bash
python tmp/parity_worst_dd_bar_b1.py
python -c "import json; ...  # see top section's winner_realized table"
```

Both scripts read from the on-disk `recycle_events.jsonl` and the emitter parquet — no in-memory patches, no test fixtures.
