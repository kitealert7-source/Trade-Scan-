# RESEARCH MEMORY

FORMAT POLICY:
- Entries may be compacted for token efficiency; content is semantically identical
- Compaction does not violate the append-only rule
- Archive split enforced at 600 lines / 40 KB -> RESEARCH_MEMORY_ARCHIVE.md
- Tier A (3-line inline): simple findings, all sections ≤ 3 non-blank lines, no sub-lists
- Tier B (label-free paragraphs): complex entries, labels removed, paragraph structure kept
- Pre-2026-03-27 entries live in RESEARCH_MEMORY_ARCHIVE.md (compacted)

THIS FILE IS APPEND-ONLY. Corrections are new entries, not edits.
Post-contract entries must conform to the NEW ENTRY CONTRACT template.

------------------------------------------------------------------------
FRAMEWORK REFERENCE (appended 2026-03-19, do not modify)
------------------------------------------------------------------------

# Research Framework — System & Model

## System Layers

Three layers, strict separation:
- ENGINE — frozen, deterministic, never modified during research
- PIPELINE — orchestration, governance, artifact management
- RESEARCH — strategy discovery, operates entirely within defined boundaries

Engine changes require a version bump and full re-run of affected strategies.

## Data Authority Hierarchy

TradeScan_State/
  backtests/   → immutable execution results (raw artifacts)
  sandbox/     → completed runs awaiting evaluation
  candidates/  → strategies that passed sandbox filter
  strategies/  → promoted strategies with full capital evaluation

## Discovery Pipeline

INBOX → backtests → sandbox → candidates → strategies

## Three-Pass Research Model

Maximum three passes per strategy concept. Each pass introduces exactly
one new constraint — combining changes destroys attribution.

Pass 1: Concept validation — does the signal exist?
  Minimal filtering, wide parameters, maximize discovery throughput.

Pass 2: Structural robustness — does it hold across assets/regimes?
  Add one regime or asset filter, confirm edge is not instrument-specific.

Pass 3: Parameter refinement — best expression of a proven idea.
  Limited tuning only; structure must be fixed before optimising params.

## Pass-1 Environment

Timeframes: 15-minute, 1-hour preferred.
Test window: Jan 2024 → present (rolling).
Requirements: intraday exit, adequate trade density, minimal filtering.

## Diversity Controls

Sandbox promotion prioritizes idea diversity over run count.
Family = all sweeps sharing the same concept prefix (instrument + timeframe + mechanism).
Limits: max 2 runs per family, max 2 runs per asset class.
Selection within family: highest MAR, or highest PF with drawdown constraint.

## Research Discipline Principles

- Deterministic infrastructure: same directive + data = identical result
- Clean phase boundaries: no skipping stages, no partial state
- Orthogonal passes: one change per sweep, traceable attribution
- Limited parameter optimization: structure must work before tuning
- Promotion based on idea diversity: avoid single-concept concentration

## Strategic Observation

Platform is capital constrained rather than signal constrained.
More valid signals exist than can be sized within risk limits.
Future gains more likely from: capital allocation, regime-aware sizing,
signal prioritization — not from finding more signals.

------------------------------------------------------------------------
---
2026-03-27 | Tags: trend_following, drawdown_reduction, filter_stack | Strategy: 03_TREND_XAUUSD_1H_IMPULSE_S01 | Run IDs: 5e69d2bda4d3de9232a83adc, b6de931cd0740bf8b4983e13
The P05 iteration of the impulse trend follower produced higher net profit with a simultaneously lower maximum drawdown compared to the baseline P02. Max Drawdown shrank 23.7% -> 18.1% and Net PnL grew $1,236 -> $1,456. The tightened filter block prevented false breakout entries from triggering early drawdowns without prematurely closing positions on sustained historical trends. The P05 logic represents the canonical form for this trend-following engine. Lock this execution structure before attempting any further parameter sweeps.
---

---
2026-03-27 | Tags: mean_reversion, parameter_breakthrough, rsi_microrev | Strategy: 23_RSI_XAUUSD_1H_MICROREV_S01 | Run IDs: 434a9790e8bc1e47a0b06857, 07d7adcc1395ace2019a322a
The baseline RSI Micro-reversal logic (P00) generated negative net PnL, whereas the heavily constrained P13 iteration yielded positive net PnL. Net PnL inverted from -$1,521 (P00) to +$717 (P13). Raw 1H RSI on XAUUSD acts as a momentum-continuation trap, but extreme gating isolates a small, structurally valid sub-population of true micro-reversals. The baseline raw-RSI approach on XAUUSD is dead; all future iterations must inherit the gating logic established in P13 to prevent terminal bleed.
---

------------------------------------------------------------------------
LIVE DATA REFERENCES (appended 2026-03-27, do not modify)
------------------------------------------------------------------------

All numerical results live in these canonical files. Entries in this
file must NOT duplicate full metric tables. Use run_id to anchor
evidence to live records.

  Run results:  TradeScan_State/research/index.csv
                Per-symbol backtest rows. Join on run_id for raw metrics.
                Schema: run_id | strategy_id | symbol | timeframe |
                        date_start | date_end | profit_factor |
                        max_drawdown_pct | net_pnl_usd | total_trades |
                        win_rate | content_hash | git_commit |
                        execution_timestamp_utc | schema_version

  Run registry: TradeScan_State/registry/run_registry.json
                Provenance ledger — tracks what ran, not how it performed.
                Schema: run_id | tier | status | created_at |
                        directive_hash | artifact_hash

  Run summary:  TradeScan_State/research/run_summary.csv
                **PRIMARY RESEARCH QUERY FILE** — one row per run_id.
                Denormalized join of registry + index + portfolio + candidates.
                Auto-regenerated by pipeline after each PORTFOLIO_COMPLETE.
                Also runnable standalone: python tools/generate_run_summary.py
                Schema: run_id | strategy_id | status | tier |
                        symbol_count | symbols | timeframe |
                        total_trades | net_pnl_usd | avg_profit_factor |
                        avg_win_rate | max_drawdown_pct |
                        portfolio_verdict | candidate_status | in_portfolio |
                        date_start | date_end | created_at

------------------------------------------------------------------------
NEW ENTRY CONTRACT (refined 2026-03-27, do not modify)
------------------------------------------------------------------------

Every entry appended after this point MUST conform to this template.
Entries that omit Run IDs, lack numeric evidence, or exceed the Evidence
line limit will be considered invalid and must be re-appended in corrected form.

  YYYY-MM-DD
  Tags:
  <tag_1>
  <tag_2>
  <tag_3>

  Strategy:     <strategy_id>          (omit if portfolio-level finding)
  Run IDs:      <run_id_1>, <run_id_2> (MANDATORY — reference pointer, not validated)

  Finding:
  <One to two sentences. What was observed. Must be understandable without
  opening any external file.>

  Evidence:
  <MAX 2 LINES. Must include at least one numeric metric or delta.>
  <Example: PF 1.20 → 0.94 under 1-pip friction; MaxDD fell 8.18% → 4.35%.>
  <"See run_ids" alone is not valid evidence. No raw tables. No data dumps.>

  Conclusion:
  <One to two sentences. What it means mechanically.>

  Implication:
  <One to three sentences. What changes as a result. Actionable.>

Rules:
  1. Run IDs field is MANDATORY as a reference pointer. No run_id → invalid.
     Run IDs are NOT validated against index.csv or run_registry.json.
     They are lookup anchors, not enforced dependencies.
  2. Evidence is capped at 2 non-blank lines.
     Evidence MUST include at least one numeric metric or delta (e.g.,
     PF change, DD change, trade count shift). Vague or empty evidence
     is rejected — entries must be self-contained and durable.
  3. Every entry must be readable without external tools or file lookups.
     The reader must understand what changed, why it matters, and what
     to do next — from the entry text alone.
  4. No full stat tables. No raw backtest output. No entries that depend
     on index.csv or run_registry.json to make sense.
  5. Findings, Conclusions, Implications remain full prose (no cap).
  6. This file is still append-only. Existing entries are not modified.

------------------------------------------------------------------------
2026-03-30
Tags:
fx_15m
mean_reversion
rsi_pullback
trend_filter
multi_symbol

Strategy:
22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P00 through P04

Finding:
RSI(2) averaged over two bars (rsi_2_avg) combined with a trend score gate
(|trend_score| >= 2) produces a genuine, scalable edge on FX 15M across
7 major pairs. Four-pass sweep: P00 concept validated (EURUSD only),
P01 5-pair expansion, P02 7-pair hardened, P03 time-exit tightened,
P04 friction-resilient 5-pair deployment subset. P04 entered burn-in.

Evidence:
P00 (EURUSD only): 2,345 trades, Sharpe 2.77, PROMOTE — signal confirmed.
P01 (5 pairs): 11,510 trades, Sharpe 4.62, PROMOTE — scales cleanly.
P02 (7 pairs, hardened): 11,239 CONSERVATIVE trades, PF 1.18, CAGR 99.87%,
  Max DD 3.39%, break-even slippage 0.31 pip — signal genuine, friction thin.
P03 (7 pairs, max_bars 12->3): 14,224 trades, PF 1.19, CAGR 107%, break-even
  0.52 pip. Tighter exit freed positions faster, INCREASING trade count vs
  expected reduction (entry_when_flat_only creates re-entry opportunities
  when holding time drops). Win rate fell 63%->55% but payoff improved
  0.68->0.96.
P04 (5 pairs, drop NZDUSD+EURUSD): 11,216 trades, PF 1.23, CAGR 93.6%,
  Max DD 5.47%, MC 95th pctl DD 7.42%, break-even 0.65 pip. All 5 symbols
  survive +0.2 pip friction. Recovery factor 13.87. 0 negative years.

Conclusion:
The rsi_2_avg signal captures genuine mean reversion in trend-aligned
conditions. The primary edge lies in the first 3 bars post-entry — bars
4-12 are structurally net-negative across all pairs and regimes.
NZDUSD and EURUSD are friction-fragile and dilute the portfolio; removing
them improves PF, Max DD, and friction resilience simultaneously.

Implication:
1. For FX 15M pullback strategies, always decompose by bars_held before
   assuming max_bars is well-calibrated. The decomposition may reveal a
   hard cutoff (bar 3-4 in this case) where edge transitions from positive
   to negative. Tightening max_bars to that cutoff is a clean, attributable
   lever that does not require a new signal.

2. Reducing max_bars on an entry_when_flat_only strategy does NOT reduce
   trade count — it creates more entries by freeing positions faster.
   Expected: fewer trades, higher quality. Actual: more trades, different
   quality profile (lower WR, better payoff ratio). Account for re-entry
   dynamics before forecasting trade count impact.

3. Symbol pruning based on friction stress test is a valid deployment filter
   even when all symbols are profitable in backtest. A symbol that flips
   negative at +0.2 pip slippage has insufficient edge buffer for live
   execution and should be excluded from deployment regardless of raw PnL.

4. Burn-in gate for high-frequency 15M strategies should include a $/trade
   floor (warn < $2.00, abort < $1.20) in addition to PF and WR — PF can
   stay above 1.0 while per-trade expectancy quietly compresses toward zero
   under friction, spread widening, or execution slippage. The $/trade metric
   catches edge erosion before it is visible in PF or WR.

2026-03-30
Tags:
engine_fallback
stop_price
live_deployment
signal_schema
fx_15m

Finding:
Strategies using ENGINE_FALLBACK (omitting stop_price from the signal dict
to allow engine to compute stop from actual fill price) cannot be deployed
directly to TS_Execution. The live signal schema requires stop_price as a
mandatory field. Per-symbol live deployment wrappers must restore stop_price
using the same ATR multiplier as ENGINE_FALLBACK (2.0x ATR).

Evidence:
P02/P03 research strategy.py omits stop_price — stop computed by
execution_loop.py at fill time from entry_price (not signal close).
TS_Execution signal_schema.py: stop_price is in _REQUIRED_FIELDS and
rejects signals missing it with SCHEMA_MISSING_STOP_PRICE.
Per-symbol live wrappers for P04 restored: stop_price = close +/- 2.0*atr_val.
Phase 0 smoke test passed for all 5 per-symbol instances.

Conclusion:
ENGINE_FALLBACK is valid for research (avoids gap-over-stop on next-bar-open
fill). For live deployment, the stop must be computed at signal time using
signal-bar close, accepting a small gap risk on next-bar open — the same
trade-off as all other live strategies.

Implication:
Any future strategy using ENGINE_FALLBACK in research must have its
per-symbol live wrapper compute and include stop_price explicitly.
Document the ATR multiplier used in the research directive so the live
wrapper replicates it exactly. This is a deployment translation step, not
a strategy change — the mathematical stop distance is identical.

------------------------------------------------------------------------
NEW ENTRY — 2026-03-31 — Family 22 RSIAVG 15M: USDCAD Regime Incompatibility
------------------------------------------------------------------------
Tags: family-22, RSIAVG, USDCAD, regime, v1.5.4, 15M

Finding:
USDCAD is incompatible with RSIAVG_TRENDFILT under 1H regime (v1.5.4).
P04__V154 re-run: 5-symbol portfolio dropped from $781.75 (v1.5.3/4H) to
$618.51 (v1.5.4/1H). USDCAD alone went from +$149.47 to -$1.87 — the
entire $163 degradation. The other 4 symbols (GBPUSD, AUDUSD, USDJPY,
USDCHF) were near-identical: $620.38 vs ~$632 estimated.

Filter analysis on USDCAD v1.5.4 trades (3,054 total):
- SHORT only: $15.03, PF 1.03 (marginal)
- SHORT + |score|>=3: $9.00, PF 1.05 (noise)
- LONG only: -$16.90, PF 0.94 (negative)
- No filter combination produces PF > 1.10 on USDCAD under 1H regime.
- Monthly distribution has dead zones (Nov-Dec 2024: 6 trades, Jul-Dec 2025: 9 trades).

Root cause: 1H regime resolves direction faster than 4H. For USDCAD's
mean-reverting microstructure on 15M, this creates false trend signals —
the regime flips before the reversion completes. The 4H regime's slower
resolution was actually beneficial, providing a stable context window.

Action: Drop USDCAD from v1.5.4 15M RSIAVG portfolio. USDCAD may still
be viable under 4H regime (v1.5.3 showed +$149.47, PF ~1.20) — a
per-symbol regime override would be needed to confirm. This is a future
engine enhancement (per-symbol regime_timeframe_map override), not a
strategy fix.
2026-04-01
Tags:
CHOCH
timeframe
structural-comparison
XAUUSD
30M
1H
regime

Strategy: 26_STR_XAUUSD_30M_CHOCH_S02_V1_P00
Run IDs: e03a2a247fcfb6cac019e34c

Finding:
ChoCh at 30M amplifies noise vs 1H — same win rate (38.6% vs 40.0%) but K-Ratio -4.83 vs positive, PF 0.74 vs 1.08

Evidence:
30M: 88 trades, PnL -136.40, high-vol bucket -173.63 kills result. 1H: 50 trades, PnL +25.61, Normal-vol Short PF 5.40 drives edge.

Conclusion:
ChoCh is timeframe-sensitive. At 30M the 3-swing streak (~30h) does not filter intraday noise; at 1H (~60h) it captures genuine regime shifts. The entry condition fires correctly at both TFs but follow-through collapses at 30M in high-vol.

Implication:
Do not compress ChoCh below 1H without either raising streak threshold (>=5) or gating on low-vol regime only. High-vol regime is destructive at 30M and should be excluded in any 30M pass.
2026-04-01
Tags:
SFP
swing-validity
liquidity-grab
XAUUSD
1H
guard

Strategy: 24_PA_XAUUSD_1H_SFP_S01_V1_P00
Run IDs: 24_PA_XAUUSD_1H_SFP_S01_V1_P00

Finding:
SFP requires validity guard: swing level must be unbroken in the MIN_SWING_AGE (3) bars between detection and current bar

Evidence:
Guard: recent_low >= swing_low across 3 intervening bars. Without this, SFP fires on already-broken levels; expected false-positive rate >30% on sweep bars.

Conclusion:
A wick-reversal pattern against a structural level is only valid if that level has not been violated in the intervening bars. Stale levels produce high false-positive rate.

Implication:
Any pattern referencing a prior swing for entry/TP/SL must include an intervening-bar violation check. Canonical pattern: recent_extreme vs swing_level before firing signal.
2026-04-01
Tags:
LIQGRAB
asian-session
early-exit
XAUUSD
15M
time-stop

Strategy: 25_REV_XAUUSD_15M_LIQGRAB_S01_V1_P01
Run IDs: 25_REV_XAUUSD_15M_LIQGRAB_S01_V1_P01

Finding:
Asian liquidity grab edge lives in first 3 bars post-sweep. Holding to 12:00 UTC converts winners into losers (55% fake-reversal rate in P00)

Evidence:
P01 (TP=1.0R, 3-bar exit) produced cleaner curve vs P00 (TP=asian_range_opposite, 12:00 UTC exit). P00 degraded primarily in bars 4-12 post-entry.

Conclusion:
Session-reversal patterns have a decay window. The structural snap-back happens fast or not at all. Time stops at 3 bars are more protective than session-end exits for 15M setups.

Implication:
For session-reversal strategies on 15M, default time stop should be 3-5 bars. Wider exits expose the trade to re-sweeps and session continuation. Validate TP=1R vs 1.5R next.
2026-04-02
Tags:
PINBAR
hybrid-exit
trailing-stop
MFE-giveback

Strategy: 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05
Run IDs: P03 (baseline), P04 (pure trail, failed), P05 (hybrid, promoted)

Finding:
Pure trailing stop (remove TP, trail from 0.5R) destroyed edge on pin bars (PF 1.42->1.27, high-vol collapsed $411->$40). Hybrid exit (keep TP + trail only after 1.0R, lock 0.5R) preserved PF while improving Sharpe 2.23->2.82 and Return/DD 6.10->8.06.

Evidence:
P04 pure trail: 438 trades PF 1.27 $642. P05 hybrid: 451 trades PF 1.41 $1061, Max DD 0.13%. Trail converted 28 time exits to locked wins without choking TP runners.

Conclusion:
Short-duration MR patterns (avg 5.8 bars) need fixed TP as primary exit -- pullbacks within the move exceed loose trail thresholds. Trailing only adds value as insurance layer above 1.0R, not as replacement for TP.

Implication:
For sub-10-bar MR strategies, never replace fixed TP with trailing. Hybrid trail (activate above 1R, lock 0.5R floor) is the only valid trailing architecture for this trade duration class.
2026-04-04
Tags:
ENGULF
15M
edge-decay
exit-timing
isolation-decomposition

Strategy: 28_PA_XAUUSD_15M_ENGULF_S03_V1_P01 through P07
Run IDs: 683fd6191db71f348f34006a (P06 best), a4e9cb986f6a54c3001b42fb (1H P03)

Finding:
15M bullish/bearish engulfing edge decays within 2 bars (~30 min). The P01 baseline's 2-bar exit was accidental (unrealized_pnl bug: ctx.get("unrealized_pnl", 0) always returns 0, so bars_held >= 2 AND unrealized_pnl <= 0 fires on ALL trades at bar 2). Isolation-first decomposition (P02 regime, P03 direction, P04 exit, P05 time-normalized, P06 combined best, P07 pure 5-bar) confirmed: removing the 2-bar exit destroys the edge in every variant tested. P06 (regime filter + direction gate, keeping 2-bar exit) is the optimal expression.

Evidence:
P06: 123 trades, PF 2.55, Return/DD 7.97, Max DD $31.83. P07 (same as P06 minus 2-bar exit): PF 1.27, Return/DD 0.58, Max DD $174.65. P04 (8-bar exit): PF 0.89. P05 (32-bar): PF 0.86.

Conclusion:
15M engulfing captures a micro-reversion impulse that completes within 2 bars. Holding longer adds noise, drawdown, and SL exposure (1 SL in P06 vs 4 in P07). The "bug" is the feature: fast exit locks in the mean-reversion impulse before fade.

Implication:
1. For 15M MR patterns, always test bars_held decomposition before assuming exit timing from higher TFs. 1H optimal hold (8 bars) does NOT transfer to 15M.
2. When an accidental mechanism produces strong results, isolate and confirm it before "fixing" it. The bug produced PF 2.55; the fix produced PF 0.89.
3. Direction-specific regime gating (block shorts in LOW vol and STRONG UP only) required AST workaround: class-level string constants + frozenset membership tests bypass semantic_validator's BehavioralGuard. FilterStack only supports global regime exclusion.
2026-04-04
Tags:
portfolio
diversification
multi-timeframe
same-instrument
correlation

Strategy: PF_9D1FEA9AD62B (1H P03 + 15M P06)
Run IDs: a4e9cb986f6a54c3001b42fb, 683fd6191db71f348f34006a

Finding:
Two engulfing strategies on XAUUSD at different timeframes (1H + 15M) produce near-zero correlation (-0.05) and 42% drawdown diversification benefit. Combined: 258 trades, PF 1.57, Sharpe 2.08, 0/16 negative rolling windows. Only 24/210 active days had trades from both.

Evidence:
Combined Max DD $87.43 vs sum-of-parts $150.49 (42% reduction). Combined Return/DD 5.84. MC 5th pctl CAGR +0.25%. 15M P06 anchors drawdown ($31.83 DD offsets 1H's $118.66 DD periods).

Conclusion:
Different timeframes on the same instrument act as independent signal sources. 15M micro-reversion (~30 min) is structurally distinct from 1H (~8hr). Multi-TF diversification is real and measurable.

Implication:
1. When a strategy works on one TF, test adjacent TFs as portfolio diversifiers. 15M added $254 PnL while reducing combined DD below 1H standalone.
2. Same-instrument multi-TF portfolios should be evaluated as a unit -- individual metrics understate combined value.
3. Temporal separation (24/210 overlap days) explains diversification: strategies rarely compete for the same price action.
2026-04-04
Tags:
session_close
mean_reversion
vwap_fade
exit_timing
regime_dependency

Strategy: 29_MR_XAUUSD_1H_CMR_S01
Run IDs: ad3d27bf3d884a47398364d4, cbb5b0c79f00f51e9c6999f6

Finding:
London close VWAP fade (16:00 UTC, 1.5x ATR extension) does not produce a universal mean-reversion edge on XAUUSD 1H. P00 (VWAP TP): PF 0.64. P01 (0.5R fixed TP): PF 0.87. The pullback exists but is shallow (<0.5R) and regime-dependent: Short x High Vol (PF 2.44, 33T) and Long x Low Vol (PF 3.62, 18T) are the only viable cells.

Evidence:
P00->P01: PnL -$436 -> -$135, WR 41%->49%, DD $547->$376. TP hit rate stayed ~3% in both. Time exit bleed is the primary loss mechanism (70%->43%).

Conclusion:
The London close extension is not a session-anchored mean reversion -- it is a volatility-regime directional signal. Shorts work in high vol (institutional unwind), longs work in low vol (range compression snap). VWAP is not a valid TP anchor; extension remains a valid trigger.

Implication:
Do not pursue VWAP-based TP for session-close strategies. If revisiting, test as a regime-gated directional strategy (Short+HighVol only) with fixed 0.5R TP and 2-bar max hold. The 51-trade combined subset (~23/yr) needs at least 3 years of data to validate.
2026-04-04
Tags:
SMI
divergence
direction_asymmetry
counter_trend
XAUUSD
1H

Strategy: 30_REV_XAUUSD_1H_SMI_S01
Run IDs: c983098dd875e9fa0ced28a0

Finding:
SMI pivot divergence on XAUUSD 1H produces strong directional asymmetry: longs PF 1.04 (92T, +$27), shorts PF 0.51 (152T, -$723). Bearish divergence fires 66% more often but wins only 41% vs 61% for bullish. Zero TP exits (0/244) at 1.0R target.

Evidence:
Long x Normal Vol: PF 5.71 but only 20T (statistically fragile). Long x WeakUp: PF 1.73, 31T. Short x any cell: PF <= 0.78 except StrongDn (PF 1.07, 14T). 36% of time exits had MFE >= 0.5R.

Conclusion:
Signal shows directional asymmetry; long-side behavior may contain weak edge but not yet validated. Bullish divergence aligns with mean-reverting behavior after downside exhaustion, while bearish divergence conflicts with persistent upward drift and continuation bias in XAUUSD. Reversal magnitude is insufficient to reach 1.0R within observed holding window, indicating shallow counter-moves rather than full reversals.

Implication:
P01 should test longs only + 0.5R TP to match observed MFE distribution. If long-only PF stays near 1.0 after TP change, the divergence signal lacks sufficient edge for deployment. The bottom-detection asymmetry may generalize to other trending instruments -- worth testing on indices if validated here.

---

### Entry: Family 31 — BRK XAUUSD ATRSQZ — Cross-Timeframe Finding
Tags: ATRSQZ, family-31, cross-timeframe, XAUUSD
Date: 2026-04-04
Strategies: S01_P00 (1H), S02_P00 (30M), S02_P01 (30M long-only), S03_P00 (15M)

Finding:
The ATR squeeze breakout strategy is the only tested class on XAUUSD showing stable expectancy across timeframes and regimes, with edge entirely driven by long-side expansion; short-side participation is structurally invalid.

---

### Entry: Family 32 — TREND XAUUSD EMAXO — Regime Filter Meta-Insight
Tags: EMAXO, family-32, regime-filters, meta-insight, XAUUSD
Date: 2026-04-04
Strategies: S01_P00 (1H), S02_P00 (30M), S03_P00 (15M)
Run IDs: 732772dc867e82892dc92d50, a8cafb275069f1bb5e1a1583, a3f73d2563dbd9bcabdffde9

Finding:
EMA(10/30) crossover on XAUUSD produces no raw edge (PF 0.83-1.13 across 15M/30M/1H). Conditional profitability appears in specific regime intersections, but is attributable to underlying market structure rather than the crossover signal. EMA crossover demonstrates that regime filters do not create edge but can isolate conditions where weak signals align with underlying market behavior. The observed edge in Long x WeakDn (PF 1.93-2.05, 36-99T) is not attributable to the crossover itself but to a broader pattern of mean-reverting bounces after trend exhaustion.

Evidence:
Unfiltered PF: 1H 1.13, 30M 0.83, 15M 1.08. Long x WeakDn isolated: 1H PF 2.05 (36T, $193), 15M PF 1.93 (99T, $335). Short x StrongUp consistently PF 0.38-0.43 across all TFs.

Conclusion:
This experiment confirms that filter stacks are effective for segmentation and analysis, but not for transforming non-edge signals into robust strategies. Regime-conditioned profitability in a weak signal reflects the regime's own behavior, not the signal's predictive power.

Implication:
When evaluating new signal classes, raw unfiltered PF < 1.0 should disqualify the signal before regime decomposition. Regime filters should refine existing edge, not rescue absent edge. The Long x WeakDn pattern may generalize as a structural feature of XAUUSD rather than a signal-specific finding -- future strategies showing this cell as dominant should be scrutinized for false attribution.

2026-04-06
Tags:
momentum_ignition
BTCUSD
1H
cross_timeframe
regime_filter
IMPULSE

Strategy: 33_TREND_BTCUSD_1H_IMPULSE_S03_V1_P02
Run IDs: 717230561d233f4a243f8a1f

Finding:
BTC 1H momentum ignition (bar_range > 1.8x avg_range(5), close in top/bottom 20% zone)
produces genuine edge after two isolation passes. Cross-timeframe comparison (15M/30M/1H)
confirmed 1H optimal: higher TF = better signal-to-noise for impulse detection. P01 excluded
WeakUp regime (trend_regime == 1) where both directions lose. P02 added Age 1 exclusion
(PF 0.53, noise immediately post-regime-transition). P03 (low-vol gate) and P04 (higher
range_mult 2.2x) both rejected -- trade count collapsed without proportional PF gain.
P05 extended backtest (2020-2026, 633 trades) validated P02 edge survives full BTC cycle
with no negative years but PF diluted from 1.70 to 1.45. P02 promoted to BURN_IN.

Evidence:
Cross-TF: 15M PF 1.06, 30M PF 1.17, 1H PF 1.25 (baseline). P02: 262 trades, PF 1.70,
Sharpe 2.98, Max DD 7.03%, Return/DD 11.39. P05 (6yr): PF 1.45, 633T, 0 negative years.

Conclusion:
Impulse detection is timeframe-sensitive -- lower TFs produce more signals but worse
signal quality. WeakUp regime is structurally untradable for impulse (both Long PF 0.66
and Short PF 0.40 lose). Age 1 is pure noise post-transition (PF 0.53). These are
structural exclusions, not parameter tuning -- the market microstructure does not support
impulse follow-through in these conditions.

Implication:
1. For impulse/breakout strategies, always test 15M/30M/1H before committing to a
   timeframe. The optimal TF depends on the instrument's noise profile, not the signal.
2. WeakUp regime exclusion should be tested on any trend-following BTC strategy --
   the regime represents directional ambiguity where impulse signals fire but lack
   follow-through momentum.
3. First BTC strategy in portfolio. Correlation with XAUUSD engines expected to be
   low (different asset class, different microstructure). Portfolio diversification
   benefit should be evaluated once burn-in data accumulates.

2026-04-06
Tags:
filter_stack
bug_fix
exclude_regime
direction_gate
infrastructure

Strategy: (all strategies using FilterStack with direction_gate + exclude_regime)
Run IDs: 717230561d233f4a243f8a1f

Finding:
FilterStack had a silent bug: when direction_gate=true, the entire trend_filter block
was skipped via `continue` at line 114, which meant exclude_regime was never evaluated.
Any strategy combining direction_gate + exclude_regime was running WITHOUT the exclusion.
Discovered when P01 (exclude WeakUp) produced identical results to P00 (no exclusion).

Evidence:
Pre-fix P02: 264 trades, PnL $830.94, PF 1.73. Post-fix P02: 262 trades, PnL $800.40,
PF 1.70. 2 fewer trades taken, metrics slightly lower but edge confirmed genuine.

Conclusion:
The exclude_regime check must fire BEFORE the direction_gate continue statement.
Fix applied: exclude_regime evaluation inserted before the `continue` in filter_stack.py.
All strategies using direction_gate + exclude_regime should be verified.

Implication:
1. Any previously run strategy with both direction_gate=true AND exclude_regime set
   was effectively running without the exclusion. Results are valid but represent the
   unfiltered version. Re-run if the exclusion was material to the edge hypothesis.
2. filter_strategies.py merge logic also fixed: existing rows now get metrics refreshed
   from Master Filter on re-run (was append-only, never updated stale data).
   candidate_status also auto-syncs with portfolio.yaml on every run.

------------------------------------------------------------------------
2026-04-07
Tags:
burn_in_live_validation
fx_mean_reversion_friction
strategy_selection_criteria

Strategy:     22_CONT_FX / 15_MR_FX (portfolio-level finding)
Run IDs:      20260406T170841Z_41372, 20260406T095611Z_14752

Finding:
FX mean-reversion and short-hold continuation strategies (M15, max_bars=3) show near-zero
or negative expected value under real spreads in burn-in. Backtest expectancy of $0.04-0.09
per trade is too thin to survive real-world friction. High win rates (79-82%) mask
unfavorable reward/risk ratios (0.09-0.19).

Evidence:
22_CONT_FX archive: 88 exits, 82% WR, avg win $0.0097, avg loss $0.0510, R:R 0.19, EV -$0.0013/trade.
XAU/BTC strategies: expectancy $2.18-5.30/trade, R:R ~1.0+, friction-resilient by construction.

Conclusion:
FX M15 mean-reversion with 3-bar holds produces wins smaller than typical spread costs.
The strategies are structurally friction-fragile — the edge exists in backtest but is
consumed by bid-ask spread in live markets. Strategies with expectancy below ~$0.50/trade
on FX are unlikely to survive real execution.

Implication:
1. FX research should pivot toward breakout/momentum strategies with wider stops and
   larger per-trade expectancy ($1+) that can absorb spread + slippage.
2. The 22_CONT_FX 30M variants (expectancy $0.10-0.23) are marginal — monitor but
   do not expect positive live performance.
3. XAU, BTC, and index strategies are inherently more friction-resilient due to higher
   tick values and larger price movements. Prioritize these asset classes for new research.
4. Minimum viable expectancy threshold for FX should be established (~$0.50/trade)
   as a pre-promotion gate to avoid wasting burn-in slots on friction-fragile strategies.

------------------------------------------------------------------------
2026-04-07
Tags:
pipeline_gate_expectancy
candidate_filtration
capital_allocation_limits

Strategy:     (portfolio-level — pipeline design)
Run IDs:      20260406T170841Z_41372, 20260406T095611Z_14752

Finding:
Capital allocation (burn-in lot sizing at 1% risk on $10K notional) cannot compensate
for a strategy with insufficient per-trade expectancy. Backtest uses real spreads, yet
22_CONT_FX passed candidates with $0.04-0.07 expectancy — spreads were modeled but the
filter pipeline did not gate on absolute expectancy, only on PF/Sharpe/RetDD ratios.

Evidence:
22_CONT_FX M15 GBPUSD: backtest PF 1.19, 2858 trades, expectancy $0.06. Live burn-in: 0/4 WR, -$204.85 net.
15_MR_FX M15 AUDNZD: backtest PF 1.54, 437 trades, expectancy $0.09. Live burn-in: 2/4 WR, -$240.49 net.

Conclusion:
Ratio-based filters (PF, Sharpe, Return/DD) pass strategies where the absolute dollar
edge per trade is too small to survive execution. A strategy can have PF 1.19 across
2858 trades and still be unviable — the edge is real but too thin. Capital allocation
scales position size, not the underlying edge quality.

Implication:
1. Add a minimum absolute expectancy gate to the candidates filtration pipeline.
   Proposed thresholds: FX pairs >= $0.50/trade, XAU/BTC/Index >= $1.00/trade.
   This filters before burn-in, saving observation slots for viable strategies.
2. Existing ratio gates (PF >= 1.20, Sharpe, RetDD) remain necessary but are
   insufficient alone — they must be paired with the expectancy floor.
3. Strategies currently in BURN_IN with expectancy below threshold should complete
   their 90-trade cycle for data, but expectations should be set accordingly.

------------------------------------------------------------------------
2026-04-07
Tags:
expectancy_threshold_calibration
candidate_gate_design
burn_in_evidence

Strategy:     (portfolio-level — pipeline gate calibration)
Run IDs:      20260406T170841Z_41372, 20260406T095611Z_14752

Finding:
Burn-in data across 12 strategies with live exits shows a clear dividing line: every FX
strategy with backtest expectancy below $0.10/trade is negative in live (7/8, the one
exception is likely noise at n=7). XAU strategies with $2-5 expectancy show negative on
n=1-2 trades each — too small to judge. No live data yet in the $0.10-$1.00 range.

Evidence:
BT exp <$0.10: 8 strategies with live data, 7 negative. 22_CONT USDCHF: BT $0.06, live -$5.06/trade (n=28).
BT exp >$1.00: 4 strategies with live data, 1 positive (17_REV $1.33/trade n=2), 3 negative (n=1 each).

Conclusion:
The failure zone for FX is definitively below $0.10/trade — spread costs alone consume the
edge. The viable zone boundary is somewhere between $0.10 and $1.00 but burn-in has no data
there yet. Sample sizes for XAU/BTC/Index are too small (n=1-2) to calibrate their threshold.

Implication:
1. Implement minimum expectancy gate in candidates filtration pipeline NOW:
   - FX pairs: >= $0.25/trade (see 2026-04-07 threshold revision below)
   - XAU/BTC/Index: >= $1.50/trade (provisional, refine after 90-trade burn-in cycles)
2. These are first-pass thresholds. Refine as more burn-in data fills the $0.10-$1.00 gap.
3. Do NOT remove sub-threshold strategies from active burn-in — let them complete 90 trades
   to build the calibration dataset, but do not promote new sub-threshold strategies.

------------------------------------------------------------------------
2026-04-07
Tags:
expectancy_threshold_revision
fx_strategy_viability
honest_research_gates

Strategy:     (portfolio-level — pipeline gate revision)
Run IDs:      20260406T170841Z_41372, 20260406T095611Z_14752

Finding:
Distribution analysis of all 124 FX strategies in Filtered_Strategies_Passed.xlsx shows
the maximum FX expectancy in the entire pool is $0.23 (22_CONT_FX_30M AUDJPY). Zero
strategies pass at $0.25. The $0.15-$0.23 range (18 strategies, 14.5%) represents the
best current FX research output — but burn-in evidence shows even $0.10 strategies fail
in live. Lowering the threshold to keep strategies alive would defeat the purpose.

Evidence:
124 FX strategies: 0 pass $0.25, 4 pass $0.20, 18 pass $0.15, 43 pass $0.10, 109 pass $0.05.
Best FX family: 22_CONT_FX_30M avg_exp=$0.14, max=$0.23. All tested <$0.10 strategies negative live.

Conclusion:
The $0.25 threshold is correct and should not be lowered to accommodate existing strategies.
If current FX archetypes cannot meet the bar, that is an honest signal that the research
direction must change — not that the bar should be bent. The gate exists to prevent
wasting burn-in slots and capital on friction-fragile strategies.

Implication:
1. FX expectancy gate stays at $0.25/trade. This currently eliminates all 124 FX strategies.
   That is the intended outcome — it forces research toward higher-expectancy FX archetypes
   (breakout, momentum, structure) with wider risk distances and larger per-trade targets.
2. Current FX burn-ins complete their 90-trade cycle for calibration data only.
   No new FX strategies below $0.25 enter burn-in.
3. XAU/BTC/Index gate remains $1.50/trade (provisional). These asset classes have
   demonstrated viable expectancy ranges ($2-5+/trade) in existing research.

------------------------------------------------------------------------
2026-04-07
Tags:
candidate_status_gates
expectancy_tiered_pipeline
fx_status_criteria

Strategy:     (portfolio-level — pipeline status gates)
Run IDs:      20260406T170841Z_41372, 20260406T095611Z_14752

Finding:
Tiered FX expectancy gates defined for the candidate pipeline, mapping each status level
to a minimum expectancy threshold. Gates are calibrated from burn-in evidence: all FX
strategies below $0.10 are confirmed negative in live, the $0.10-$0.25 range is marginal
with no positive evidence, and no existing FX strategy reaches $0.25.

Evidence:
124 FX strategies: 0 pass $0.25, 18 pass $0.15, 109 pass $0.05. All 8 tested below $0.10 negative live.
Current max FX expectancy: $0.23 (22_CONT_FX_30M AUDJPY). 100% of pool would be FAIL or WATCH.

Conclusion:
FX candidate status gates (per-trade expectancy):
  FAIL:     < $0.15  — cull, doesn't survive friction
  WATCH:    $0.15 - $0.24  — worth monitoring, not ready for live test
  BURN_IN:  >= $0.25  — approved for live shadow observation
  CORE:     >= $0.25 + passed 90-trade burn-in gates (PF, WR, MaxDD, fill_rate)
XAU/BTC/Index gates (logic-driven, finalized 2026-04-07):
  Derivation: spread_cost_at_min_lot(class) / spread_cost_at_min_lot(FX) = ~3.3x multiplier.
    FX (EURUSD): 0.6 pips * $1000/PU @ 0.01 lot = $0.06
    XAU: $0.20 spread * $1.00/PU @ 0.01 lot = $0.20 (3.3x)
    BTC: $20 spread * $0.01/PU @ 0.01 lot = $0.20 (3.3x)
    INDEX (GER40): 2 pts * $0.115/PU @ 0.01 lot = $0.23 (3.8x)
  Slippage proportional to spread (microstructure principle). Conservative 3.0x applied.
  FAIL: XAU < $0.50, BTC < $0.50, INDEX < $0.50
  BURN_IN: XAU >= $0.80, BTC >= $0.80, INDEX >= $0.80

Implication:
1. Apply these gates in filter_strategies.py as automatic candidate_status assignment.
2. Current FX pipeline output: 106 FAIL, 18 WATCH, 0 BURN_IN. This is correct —
   forces research pivot toward higher-expectancy FX archetypes before any reach burn-in.
3. Existing sub-threshold BURN_IN strategies complete their 90-trade cycle for data
   but are not replaced when done. New BURN_IN slots reserved for qualifying strategies.
2026-04-07
Tags:
regime_gate
pipeline_staging
OOS_validation
overfit
capital_wrapper

Run IDs: experiments/regime_gate_validation.py, experiments/results/regime_gate_validation.json

Finding:
Regime gating (blocking trades in unprofitable regime cells) improves in-sample metrics but fails OOS stability — 0/5 active-gated portfolios survived 60/40 split. Direction reversal in all cases: blocked trades were losers in training but winners in OOS.

Evidence:
In-sample: 5/9 improved, +$9525 total dPnL, avg PF +0.11, avg DD -0.45pp. OOS: 0/5 active stable; PF_7FCF1D2EB158 reversed from +$6420 IS to -$7360 OOS. Blocked OOS PnL was positive in all 5 cases ($1427, $455, $160, $52, $1143).

Conclusion:
REJECT for pipeline integration. Regime labels lack forward-predictive signal at current sample sizes (min_trades=10). Ordering confirmed: if ever used, gating must precede capital allocation (B != C in 5/5 active cases). Profile selection unaffected (0/9 changed).

Implication:
Stage 4 Regime Audit stays diagnostic/reporting only — never auto-block. If revisited: require min_trades >= 50, walk-forward validation, regime-cluster stability checks. Strategy Activation System remains valid as monitoring layer, not gating layer.
2026-04-07
Tags:
regime_gate
activation
exposure_control
concurrency
pipeline_staging

Run IDs: experiments/regime_gate_validation.py, experiments/activation_vs_filtering.py, experiments/exposure_control_vs_activation.py, experiments/concurrency_diagnostics.py

Finding:
Portfolio-level regime filtering, activation, and exposure control do not provide material improvement with current regime definitions. Regime buckets (vol, trend) are too coarse to partition trades into stable, behaviorally distinct populations.

Evidence:
3 experiments, 9 portfolios. Post-trade filtering: +$1058 avg IS but 0/5 OOS stable. Binary activation: -$3332 avg but 9/9 OOS stable (returns to baseline). Exposure control: +$11 avg (noise). REV max_concurrent=2, cap fires 6-9 trades. TREND low-vol signal ~$130 avg.

Conclusion:
Do not implement regime-based gating, activation, or exposure control in pipeline. REV×TREND overlap is beneficial diversification. Only valid signal (TREND in low-vol) is too small for system-level rules. Revisit only if regime classification becomes granular and aligned with strategy entry logic.

Implication:
No Stage 4 Regime Audit in pipeline. Current regime labels (vol bucket, trend label) lack forward-predictive power for trade-level decisions. Future work requires feature-level regime alignment, not coarse state labels.
