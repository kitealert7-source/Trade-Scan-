# Cointegration Research Universe — Report v1

**Date:** 2026-06-20
**Author:** research session (eliminate-first universe definition)
**Status:** FINDINGS REPORT — advisory. Does **not** modify any governance artifact.

---

## Objective

Define a durable **Cointegration Research Universe** using an **eliminate-first**
methodology (discard the clearly-bad, keep the residual subset) based **entirely on
existing ledger data** — no new backtests, no new hypotheses.

## Data sources & provenance (read-only)

| Source | What it provided |
|---|---|
| `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx` → **Cointegration** tab | 2,378 per-(span×arm) rows · 265 distinct pairs · `n_spans`, `return_dd_ratio`, `total_trades`, `max drawdown %`, `pair_class`, `coint_friendly` |
| same workbook → **COINT TRADE CANDIDATES** tab | pair-level shortlist (265 pairs, `runs≥5` gate, reliability sort) |
| `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db` | daily regime series (case study) |
| Pipeline runs `8208d26caa396595aafcdb19`, `6e3d51f4fea07b7cbe2061ae` | BTCUSD/EUSTX50 case study |

> **Charge caveat (binding).** The ledger corpus is the 5 kept arms
> (`GP_ZCRS_{FXD25,BBK20,BBK25,HF55_Z25,CXN1_Z25_LM20}`), methodology `v2_log_eg`,
> on the **uncharged v1.5.9** engine. All Ret/DD figures below are therefore
> **gross of spread** and **optimistic**. Charged v1.5.10 pulls every figure down
> ("edge is inside the spread"); the low-Ret/DD tail is where pairs flip negative.
> See governance recommendation **G3**.

---

## 1 · Elimination funnel

Reproduced exactly, in the specified order. Per-pair aggregation: `friendly` =
best level across arms; `n_spans` = max; `runs` = ledger-row count; `maxDD` = worst
span's `max drawdown %`; `median Ret/DD` = median `return_dd_ratio` across rows.

| Step | Criterion (discard if…) | Removed | Remaining |
|---|---|---:|---:|
| 0 | — start — | — | **265** |
| 1 | `coint_friendly == WEAK` | −143 | 122 |
| 2 | `n_spans < 2` (one-off, never recurred) | −43 | 79 |
| 3 | `runs < 5` (insufficient evaluation) | −0 | 79 |
| 4 | `maxDD ≥ 100%` (account-blowup span) | −2 | 77 |
| 5 | `median Ret/DD ≤ 0` (no in-sample edge) | −41 | **36** |

**Read of the funnel.** Two cuts do the heavy lifting: **WEAK friendliness (−143)**
and **no-edge (−41)**. Even among friendly, recurring, non-blowup pairs, **53%
(41/77) have zero/negative median Ret/DD** — "MR fails on most pairs by design,"
quantified. The `runs<5` gate is non-binding here (every friendly + recurring pair
already had ≥5 evaluations) but is retained as a reliability floor.

---

## 2 · Survivor set characterization (n = 36)

**Pair-class distribution**

| Class | Count |
|---|---:|
| Cross | 15 |
| FX (FX-FX) | 13 |
| IDX (IDX-IDX) | 4 |
| Crypto | 3 |
| Metals | 1 |

**Ret/DD distribution (median per pair, uncharged)**

| min | p25 | p50 | p75 | max |
|---:|---:|---:|---:|---:|
| 0.02 | 0.13 | 0.34 | 0.61 | 1.79 |

Quality is **front-loaded and thin**: only 4 pairs ≥ 1.0, 10 pairs ≥ 0.5; the
remaining 26 sit in a marginal 0–0.5 band.

**Span distribution** (recurrence)

| n_spans | 2 | 3 | 4 | 5 |
|---|---:|---:|---:|---:|
| pairs | 24 | 8 | 3 | 1 |

Most survivors recur only twice; durable multi-span relationships are rare.

**Trade-count distribution** (pooled across arms×spans)

| min | p25 | p50 | p75 | max |
|---:|---:|---:|---:|---:|
| 254 | 689 | 892 | 1,673 | 2,508 |

Sample size is **not** the binding constraint — every survivor clears ≥250 trades.
The binding lever is Ret/DD.

---

## 3 · Research tiers

- **Tier A — median Ret/DD ≥ 0.5** (the durable core): **10 pairs** — FX 5, Cross 4, Crypto 1
- **Tier B — 0 < median Ret/DD < 0.5** (marginal; likely uncharged-inflated): **26 pairs** — Cross 11, FX 8, IDX 4, Crypto 2, Metals 1
- **Tier C — excluded by funnel:** **229 pairs**

### Tier A (10)

| Pair | Class | Friendly | Spans | Trades | Median Ret/DD | Worst-span maxDD% |
|---|---|---|---:|---:|---:|---:|
| AUDJPY / CADJPY | FX | FRIENDLY | 3 | 2400 | 1.79 | 19 |
| CHFJPY / EURJPY | FX | FRIENDLY | 2 | 1656 | 1.61 | 15 |
| AUDUSD / GER40 | Cross | FRIENDLY | 3 | 550 | 1.05 | 12 |
| ETHUSD / GBPAUD | Crypto | FRIENDLY | 2 | 1052 | 1.02 | 18 |
| EURJPY / USDCHF | FX | FRIENDLY | 2 | 952 | 0.86 | 19 |
| GBPAUD / USDCHF | FX | FRIENDLY | 2 | 738 | 0.71 | 8 |
| AUDJPY / UK100 | Cross | FRIENDLY | 4 | 1534 | 0.70 | 15 |
| NZDUSD / UK100 | Cross | FRIENDLY | 2 | 988 | 0.69 | 13 |
| US30 / USDCHF | Cross | FRIENDLY | 3 | 886 | 0.62 | 27 |
| CHFJPY / NZDJPY | FX | FRIENDLY | 2 | 746 | 0.61 | 7 |

### Tier B (26)

| Pair | Class | Spans | Trades | Median Ret/DD | Worst-span maxDD% |
|---|---|---:|---:|---:|---:|
| BTCUSD / JPN225 | Crypto | 2 | 1574 | 0.44 | 38 |
| SPX500 / USDCHF | Cross | 2 | 824 | 0.42 | 4 |
| AUDJPY / AUDNZD | FX | 2 | 808 | 0.41 | 7 |
| GBPUSD / JPN225 | Cross | 2 | 1924 | 0.40 | 8 |
| EURAUD / EURUSD | FX | 2 | 686 | 0.40 | 16 |
| CHFJPY / EUSTX50 | Cross | 2 | 898 | 0.37 | 22 |
| EURJPY / USDJPY | FX | 2 | 654 | 0.35 | 14 |
| GER40 / XAUUSD | Metals | 2 | 406 | 0.34 | 20 |
| CHFJPY / UK100 | Cross | 4 | 2324 | 0.33 | 79 |
| CADJPY / EURUSD | FX | 4 | 858 | 0.32 | 13 |
| CADJPY / ESP35 | Cross | 3 | 254 | 0.29 | 35 |
| EURAUD / JPN225 | Cross | 3 | 1724 | 0.28 | 14 |
| GBPJPY / UK100 | Cross | 5 | 2370 | 0.27 | 44 |
| EURJPY / US30 | Cross | 2 | 1150 | 0.23 | 36 |
| BTCUSD / USDCHF | Crypto | 2 | 508 | 0.16 | 26 |
| UK100 / USDJPY | Cross | 2 | 594 | 0.14 | 26 |
| CADJPY / GBPJPY | FX | 3 | 1982 | 0.14 | 12 |
| EURJPY / GBPJPY | FX | 2 | 818 | 0.12 | 16 |
| AUS200 / JPN225 | IDX | 3 | 1084 | 0.12 | 10 |
| AUS200 / US30 | IDX | 2 | 2508 | 0.11 | 37 |
| JPN225 / UK100 | IDX | 2 | 2142 | 0.11 | 25 |
| EURUSD / JPN225 | Cross | 2 | 2088 | 0.08 | 10 |
| EURAUD / UK100 | Cross | 2 | 638 | 0.06 | 50 |
| EURJPY / EURUSD | FX | 2 | 690 | 0.06 | 9 |
| CHFJPY / USDJPY | FX | 2 | 756 | 0.04 | 9 |
| ESP35 / JPN225 | IDX | 3 | 496 | 0.02 | 14 |

> Tiers are **dynamic** — they are the output of the funnel against the live ledger,
> not a hand-curated list (see **G2**).

---

## 4 · Case study — BTCUSD / EUSTX50 (why the funnel matters)

This pair is the report's keystone: it is **exactly the trap a "rank by Ret/DD"
shortlist would have fallen into**, and the funnel catches it on a single gate.

**Ledger view (looks elite):** 5 arms, all FRIENDLY, **median Ret/DD 4.32**
(arms 5.46 / 5.29 / 4.32 / 2.47 / 1.56), maxDD 13–24% — the **highest median
Ret/DD of any friendly pair**. By quality alone it ranks #1.

**The single disqualifier — `n_spans = 1`.** The pair cointegrated for exactly one
continuous span (2024-08-29 → 2024-11-08, ~52 daily obs); the screener shows it
**broken 79.5% / breaking 9.3% / cointegrated 11.2%** of its 2023-12 → 2026-06
history, with four other "spans" being 2–8-day noise. The Ret/DD 4.32 is one
productive episode, nothing repeatable. **Recurrence (n_spans ≥ 2) is the only
funnel criterion that removes it.**

**Confirmation — full-window unconditioned test** (pipeline run
`6e3d51f4fea07b7cbe2061ae`, charged v1.5.10, 2023-04-01 → 2026-06-18):

| | episode (run 8208d26c, uncharged) | full window unconditioned (charged) |
|---|---|---|
| Net % | +72.3% | **−405%** (floored −100%, liquidated) |
| Ret/DD | +5.46 | **−0.98** |
| first negative equity | — | **2024-02-26** (account blown 7 months *before* the episode) |

**Regime attribution of the full-window PnL** (realized USD):

| cointegrated | breaking | broken | pre-screener (2023) |
|---:|---:|---:|---:|
| +235 | +196 | **−3,892** | −589 |

**Structural reason.** The traded spread `ln(BTC/EUSTX50)` is **96% BTC variance**
(corr 0.93); granular_parity equalizes leg *dollars* but not *volatility* (BTC 2.7×
EUSTX50), so the basket is BTC-dominated by construction and runs to 10.9× leverage.

**Key lessons:**
1. **A single dominant productive episode can masquerade as a top-tier edge.** Pure
   Ret/DD ranking is fooled; **recurrence (`n_spans ≥ 2`) is the primary defense.**
2. **Cointegration conditioning is part of the strategy *definition*, not an
   optimization.** Profit is confined to cointegrated/breaking regimes (+431);
   unconditioned exposure to the broken 61% is net-destructive (−3,892).
3. **`window_validity_gate` is load-bearing**, not friction — removing it is what
   exposed the −405% blowup. (See [[feedback_test_window_must_match_signal_class]].)

---

## 5 · Governance recommendations (advisory — not applied here)

- **G1 — Lock the funnel *criteria* as the Cointegration Research Universe filter.**
  Universe = pairs surviving: `friendly ∈ {FRIENDLY, STRONG}` **and** `n_spans ≥ 2`
  **and** `runs ≥ 5` **and** `maxDD < 100%` **and** `median Ret/DD > 0`. The
  `n_spans ≥ 2` recurrence gate is non-negotiable — it is the BTCUSD/EUSTX50 defense.
- **G2 — Use *dynamic* criteria, never a frozen Top-20 list.** The universe is the
  funnel applied to the live ledger; it regenerates as spans accrue and pairs are
  re-tested. A hardcoded list goes stale and re-introduces survivorship bias.
- **G3 — Require *charged* (v1.5.10) confirmation before any demo/deployment
  research.** The present universe is uncharged-screened; the Tier-B 0–0.5 band is
  where charging flips pairs negative. A pair is deployment-eligible only after its
  cointegrated-span performance survives charged Ret/DD > 0.

---

## Constraints honored

No new backtests · no new hypotheses · existing ledger/report data only · no
governance artifact modified (recommendations are advisory). Uncharged-provenance
caveat stated throughout.

## Limitations

- Ret/DD is uncharged v1.5.9 (gross of spread) — see charge caveat & **G3**.
- `n_spans` reflects the daily 252-lookback screener; pairs with < 252 days of
  joint price history (e.g. later-added symbols) are structurally span-limited.
- Pooled trade counts span arms × spans; treat as a reliability floor, not a
  per-strategy trade tally.
