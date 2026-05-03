# NEWSBRK A1 5M Pre-Event Hypothesis Test — Closing Verdict

**Date:** 2026-05-03
**Symbol:** NAS100
**Backtest period (5M):** 2024-08-07 → 2026-03-20 (~19 months, aligned to actual 5M data coverage)
**Backtest period (15M baseline):** 2024-01-01 → 2026-03-20 (~27 months)
**Calendar:** ForexFactory RESEARCH-layer, USD High-impact only
**Pre-event window:** 30m | Post-event window: 90m
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`

---

## Verdict: **A1 = KILL conclusively. NEWSBRK family closed.**

---

## The three answers you asked for

### 1. Trade count vs 15M

| | 5M (S02) | 15M (S03) |
|---|--:|--:|
| Total trades (3 patches) | **459** | 366 |
| Per-month rate | 24.2 / mo | 13.6 / mo |
| Coverage-rebased (if 5M had full 27 mo) | ~652 est. | 366 actual |

5M produces **~78 % more trades per month** than 15M. The hypothesis that 5M would lift sample size — confirmed.

### 2. True pre-event share vs overlap/post-event

| Directive | N | pre N | pre % | post N | outside N |
|---|--:|--:|--:|--:|--:|
| S02_V1_P00 5M | 229 | **153** | **66.8 %** | 76 | 0 |
| S02_V1_P01 5M | 123 | 3 | 2.4 % | 120 | 0 |
| S02_V1_P02 5M | 107 | 4 | 3.7 % | 103 | 0 |
| **S02 5M aggregate** | **459** | **160** | **34.9 %** | 299 | 0 |
| S03_V1_P00 15M | 159 | 4 | 2.5 % | 153 | 2 |
| S03_V1_P01 15M | 114 | 2 | 1.8 % | 110 | 2 |
| S03_V1_P02 15M | 93 | 1 | 1.1 % | 90 | 2 |
| **S03 15M aggregate** | **366** | **7** | **1.9 %** | 353 | 6 |

**At 5M, pre-event structure does appear — but only in S02_V1_P00.** P01 and P02 fall back to the same near-null pre-event share as the 15M baseline. The compression-box filter only fires at meaningful frequency under one specific parameter configuration; the other two patches are effectively post-event strategies misclassified as pre-event.

### 3. Top-5 % trimmed PF

| Directive | total PF | total PnL | trim PF |
|---|--:|--:|--:|
| S02_V1_P00 5M | **0.59** | **-$277.0** | **0.23** |
| S02_V1_P01 5M | 0.92 | -$19.5 | 0.54 |
| S02_V1_P02 5M | 1.01 | +$2.3 | 0.61 |
| **S02 5M median** | **0.92** | — | **0.54** |
| S03 15M median | 1.21 | — | 0.74 |

**Trim PF is < 1.0 for every single 5M directive.** Removing the top 5 % of winners collapses the underlying distribution to losing on every patch. The 5M version is **worse on the trim-PF gate than the 15M version it replaced.**

---

## What 5M actually revealed

The original 15M sweep left the pre-event hypothesis **undecided** — only 1–4 pre-event trades per directive, far too sparse to test. 5M was the honest test.

S02_V1_P00 at 5M finally generated a usable pre-event sample: **153 pre-event trades**. The pre-event component's verdict on its own:

| Metric | S02_V1_P00 pre-event | Verdict |
|---|--:|---|
| N | 153 | Sufficient sample |
| PF | **0.55** | Losing |
| PnL | **-$191.1** | Losing |

The pre-event compression-breakout hypothesis is **not unsupported — it is statistically refuted.** When the architecture finally fires inside its intended window, the trades it produces lose money.

P01 and P02 reverted to the post-event-dominated behavior we already documented at 15M, with trim PFs of 0.54 and 0.61 — same tail-carried disease, no new edge.

---

## Decision-rule check (per directive)

> *"If trimmed PF remains < 1 or pre-event trades remain sparse, mark A1 = KILL conclusively and close the NEWSBRK family.
> If pre-event structure appears but robustness still fails, mark A1 = REFINE_LATER and stop."*

| Criterion | Result |
|---|---|
| trim PF < 1 across all directives? | **Yes (0.23, 0.54, 0.61)** — KILL trigger fires |
| Pre-event structure appears? | Mixed: P00 yes (153), P01/P02 no (3, 4) — *partial* |
| If structure appears, is it robust? | No: P00's pre-event PF = **0.55** (losing) |

The first criterion (trim PF < 1 universally) triggers KILL on its own. The second clause ("structure appears but robustness fails") would map to REFINE_LATER, but the data shows worse than failure-of-robustness — the pre-event component **loses money outright**. Refining a losing component is not a research strategy.

---

## A1 = KILL conclusively. NEWSBRK family closed.

The pre-event compression-breakout hypothesis on NAS100 is now refuted, not deferred. No future NEWSBRK directive should be authored under the same architecture without a fundamentally different filter or instrument.

---

## Memory entry to append

A single `RESEARCH_MEMORY.md` entry will close out this family:

```
2026-05-03 | Tags: NEWSBRK, INDEX, NAS100, A1_PRE_EVENT, A2_POST_EVENT, KILL
Strategy: 64_BRK_IDX_NEWSBRK_*
Run IDs: 64_BRK_IDX_5M_NEWSBRK_S02_V1_P00..P02 + 64_BRK_IDX_15M_NEWSBRK_S03_V1_P00..P02 + 64_BRK_IDX_15M_NEWSBRK_S05_V1_P00..P02
Finding: NEWSBRK family on NAS100 fails the trim-PF gate across all 9 directives
  (5M + 15M, A1 + A2). At 15M the pre-event hypothesis was statistically
  null (1–4 pre-event trades per directive). At 5M with adequate coverage
  (153 pre-event trades in S02_P00), the pre-event component itself loses
  money: PF 0.55, PnL -$191.
Evidence: trim_PF median 0.54 (5M S02), 0.74 (15M S03), 0.67 (15M S05);
  pre-event PF 0.55 in the only patch with sample size > 100.
Conclusion: Pre-event compression-breakout hypothesis is refuted on NAS100,
  not undecided. Same tail-carried-edge disease as ZREV / ZPULL / SYMSEQ.
Implication: Do not author new NEWSBRK directives on NAS100 without a
  fundamentally different filter or instrument. Cross-asset re-test would
  most likely repeat the same null per the established pattern.
```

I have **not** appended this to `RESEARCH_MEMORY.md` yet — flagging it for your sign-off per the standing rule that `research_memory_append.py` requires explicit human approval.

---

## Artifacts

- 5M trade-level: `TradeScan_State/backtests/64_BRK_IDX_5M_NEWSBRK_S02_V1_P0*_NAS100/raw/results_tradelevel.csv`
- 15M trade-level: `TradeScan_State/backtests/64_BRK_IDX_15M_NEWSBRK_S0[35]_V1_P0*_NAS100/raw/results_tradelevel.csv`
- Prior 15M comparative: [outputs/NEWSBRK_15M_COMPARATIVE_2026_05_03.md](outputs/NEWSBRK_15M_COMPARATIVE_2026_05_03.md)
- Framework anchor: `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
