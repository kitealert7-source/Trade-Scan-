# PORT / MACDX Duplication — Diagnosis (Read-Only)

**Date:** 2026-05-03
**Backlog item:** INFRA-NEWS-006
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
**Method:** Read-only inspection of strategy source files, run metadata, trade-level CSVs.

---

## TL;DR

The duplication is **intentional code reuse + a namespace mislabeling**, not a bug.

| Path | Identity (per filesystem) | Identity (per source code) |
|---|---|---|
| `strategies/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/strategy.py` | PORT (idea 05, model `PORT_TRENDFILT`) | **Actually MACDX S22 P00** — the docstring explicitly says `Directive: 54_STR_XAUUSD_5M_MACDX_S22_V1_P00`. Imports `macd` and `ema_cross` indicators. |
| `strategies/54_STR_XAUUSD_5M_MACDX_S22_V1_P04/strategy.py` | MACDX S22 P04 (idea 54, model `MACDX`) | MACDX S22 P04 — "Variant of S22 P00: entry/SL/TP/time-stop logic **provably byte-identical** to P00. Adds passive instrumentation only." |

Both files share **byte-identical `check_entry`**. Their trade lists are therefore byte-identical. This is **expected behavior** given the source code intent.

The discovery report's NEWS_AMPLIFIED bucket double-counted them because it grouped by `(idea_id, asset_class, timeframe)` — which sees PORT and MACDX as distinct — but the underlying logic is the same. The reported bucket size of 9 is effectively 8 distinct candidates.

---

## Evidence

### 1. PORT strategy is mislabeled MACDX

`strategies/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/strategy.py`:

```python
"""
54_STR_XAUUSD_5M_MACDX_S22_V1_P00 - Time-Stop Probe
Directive: 54_STR_XAUUSD_5M_MACDX_S22_V1_P00
...
"""

# --- IMPORTS (Deterministic from Directive) ---
from indicators.volatility.atr import atr
from indicators.trend.ema_cross import ema_cross
from indicators.momentum.macd import macd
from engines.filter_stack import FilterStack


class Strategy:
    name = "05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00"
    timeframe = "5m"
```

The strategy:
- Self-identifies as MACDX S22 P00 in its docstring
- Imports MACDX-style indicators (`macd`, `ema_cross`)
- Sets `name` to its filesystem path (PORT) rather than the docstring identity
- Was apparently authored by copying MACDX S22 P00 into a `05_PORT_…` folder without updating identity metadata

### 2. MACDX S22 P04 is byte-identical to S22 P00 by design

`strategies/54_STR_XAUUSD_5M_MACDX_S22_V1_P04/strategy.py`:

```python
"""
54_STR_XAUUSD_5M_MACDX_S22_V1_P04 - Convexity Proxy (Observation-Only)

Variant of S22 P00: entry/SL/TP/time-stop logic unchanged and provably
byte-identical (check_stop_mutation always returns None). Adds a passive
instrumentation layer that records events when adverse excursion crosses
-0.8R intrabar.

Integrity invariant:
  check_stop_mutation returns None on every call. The engine's monotonic SL
  gate therefore cannot tighten. results_tradelevel.csv MUST be byte-identical
  to P00.
"""
```

The author explicitly designed P04 as a passive instrumentation variant that produces the SAME trades as P00. The docstring contains a hard contract: `results_tradelevel.csv MUST be byte-identical to P00`.

### 3. `check_entry` byte-identical

`diff` of the two strategies' `check_entry` methods returns nothing for the entry function itself; the only file-level diff is that MACDX S22 P04 has an additional `check_stop_mutation` method that always returns `None` (instrumentation, no trading effect).

```bash
$ diff <(sed -n '/def check_entry/,/def check_exit/p' \
            strategies/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/strategy.py) \
       <(sed -n '/def check_entry/,/def check_exit/p' \
            strategies/54_STR_XAUUSD_5M_MACDX_S22_V1_P04/strategy.py)
# (only diff: MACDX S22 P04 has extra check_stop_mutation lines, no diff in check_entry)
```

### 4. Trade-level CSVs are byte-identical at the trade-decision level

```
PORT  shape=(1333, 44)  pnl_sum=2719.16
MACDX shape=(1333, 44)  pnl_sum=2719.16
PORT first 3 entry timestamps:  2024-07-19 02:55:00, 04:15:00, 08:35:00
MACDX first 3 entry timestamps: 2024-07-19 02:55:00, 04:15:00, 08:35:00
entry_timestamp same: True
exit_timestamp  same: True
pnl_usd         same: True
direction       same: True
entry_price     same: True
```

(File-level CSV byte hashes differ slightly — different file sizes 546 KB vs 533 KB — likely due to per-row metadata fields (`run_id`, `strategy_name`, etc.) reflecting their distinct strategy IDs. The trading-decision content is identical.)

---

## What it isn't

| Hypothesis | Evidence against |
|---|---|
| Aliasing (one strategy module imports the other) | Both are self-contained `Strategy` classes. Neither imports the other. |
| Emitter contamination (artifact bleed-through during run) | Different `run_id`s, different folder paths, different `strategy_name` values in trade CSVs. The two runs are mechanically independent. |
| Name-collision in run_registry | run_registry.json entries for both have unique `run_id` UUIDs. |
| Hidden import / monkey-patching | No `import` statements cross-reference the two strategies. |

---

## What it is

**Two distinct manifestations of the same MACDX S22 P00 logic:**

1. **PORT idea-05 entry was authored by copying MACDX S22 P00 into a PORT folder.** The new file kept the MACDX docstring (giving away its origin), kept the MACDX indicators, but changed `name` to match its filesystem location. Whether this was deliberate (multi-idea registration of the same logic for some governance reason) or accidental (forgot to rewrite the strategy after copying the template) is unclear from the code alone.
2. **MACDX S22 P04 is a deliberate instrumentation overlay** on S22 P00 — same trading decisions, additional event recording. The duplication is by design and the author specified it explicitly.

The discovery report saw both PORT (idea 05) and MACDX S22 P04 (idea 54) as separate NEWS_AMPLIFIED candidates because the grouping key `(idea_id, asset_class, timeframe)` treated them as different families. Underlying logic is the same.

---

## Implications for prior research

### Discovery report

[outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md](outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md) listed both as NEWS_AMPLIFIED at rank 7 and rank 8 with identical numbers. **The bucket size should be 8 distinct candidates, not 9.** The two metrics-identical rows refer to one underlying strategy.

### Path A side-channel report

[outputs/PHASE2_PATHA_GENERALITY_TEST_2026_05_03.md](outputs/PHASE2_PATHA_GENERALITY_TEST_2026_05_03.md) ran Path A on PORT only (not MACDX) per the user's instruction "If identical, test only one." The Path A PASS verdict (N=55, PF=3.21, trim=1.66) applies to **MACDX S22 P00 logic**, regardless of which folder it's loaded from. The result is correct; the *labelling* of the surviving candidate as "PORT XAU 5M" is misleading. It should be referred to as **"MACDX S22 (XAU 5M)"** in any follow-up Phase 3 work.

---

## Recommended actions (NOT executed — read-only diagnosis)

1. **Rename or deprecate `strategies/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/`**:
   - Option A: rewrite the strategy file's `name`, docstring, and STRATEGY_SIGNATURE to match the filesystem identity (i.e., make it actually a PORT strategy with PORT logic). This is a redo-from-scratch, not a fix.
   - Option B: move the folder to `strategies/54_STR_XAUUSD_5M_MACDX_S22_V1_P00/` (its true identity per docstring), update sweep_registry, deprecate the PORT_TRENDFILT path.
   - Option C: leave as-is; document the misalignment in `RESEARCH_MEMORY.md` so future agents don't double-count.
2. **De-duplicate the discovery report's NEWS_AMPLIFIED count** in any future re-issue.
3. **Add a discovery-time guard:** when scanning the backtest archive, group by `(strategy_name → trade-list-hash)` and warn on duplicate trade lists across distinct strategy names. Single-line addition to the discovery script.
4. **Refer to the surviving NEWS_AMPLIFIED candidate as MACDX S22, not PORT,** in Phase 3 if and when Phase 3 happens.

---

## Severity update

Original INFRA-NEWS-006 severity: **MEDIUM** (could indicate broader emitter bleed).

**Revised severity: LOW.** This is one researcher's authoring choice (or naming oversight) on one specific strategy folder. There is no evidence of cross-strategy artifact contamination or emitter bug. The discovery report's count is off-by-one in the NEWS_AMPLIFIED bucket; the *numbers* for the surviving candidate are unaffected. The pattern is unlikely to recur unless someone deliberately copies a strategy into another idea folder again.

---

## Files inspected

- `strategies/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00/strategy.py` (166 lines)
- `strategies/54_STR_XAUUSD_5M_MACDX_S22_V1_P04/strategy.py` (290 lines)
- `TradeScan_State/backtests/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00_XAUUSD/raw/results_tradelevel.csv`
- `TradeScan_State/backtests/54_STR_XAUUSD_5M_MACDX_S22_V1_P04_XAUUSD/raw/results_tradelevel.csv`

No mutations made. No commits made. Pure analysis.
