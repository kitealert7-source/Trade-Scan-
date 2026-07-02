# Vault Reserve Snapshot — 2026-07-02

Snapshot of the TS_Obsidian_Vault `research-ideas/` corpus, cross-referenced against
`RESEARCH_MEMORY.md` + archive on 2026-07-02. **Batch 1** (morning): 21 ideas
(19 `developing`, 2 `archived`) → 16 reserved. **Batch 2** (same day, after the
7-video StatOasis ingest): 7 new ideas → all 7 reserved (none repeats tested work).
Each surviving idea is captured as a `PROPOSED` hypothesis YAML (SCHEMA.md-shaped) and
held **in reserve — nothing here is scheduled or authorized to run**. `TBD` fields are
resolved at directive-authoring time; the F19 re-test guard and Idea-Identity
registration apply then, not now.

> **Engine-capability triage:** before authoring any directive from this reserve,
> read [`ENGINE_CAPABILITY_TRIAGE.md`](./ENGINE_CAPABILITY_TRIAGE.md) — a living
> per-hypothesis assessment of whether each exit/stop design is buildable today
> (`rule_build_required`) vs needs `engine enhancement required`. As of 2026-07-02:
> 0 of 22 need exit-engine work; NOISE_AREA is conditional on trail monotonicity.

## Reserve contents (16)

| Hypothesis | One-liner | Cost-risk note |
|---|---|---|
| `COINT_EXIT_OVERLAYS_V1` | time exit + catastrophic stop on the cointegration z-exit (open EXIT frontier; entry-filter arc is closed) | cohort A/B, BB-Exp1 template |
| `QUANTITATIVO_MR_COMPOSITION_V1` | IBS<0.3 + pullback band + SMA300 stop vs the bare IBS<0.2 champion | direct A/B vs idea 70 |
| `DMA_STRETCH_BAKEOFF_IDX_V1` | DMA %-below-SMA on SPX500 1D — missing third arm of the RSI/IBS stretch census | negative prior, cheap |
| `MOMO_BREAKOUT_MR_COMPLEMENT_V1` | 4H ROC(40) momentum leg — hypothesis is ~0 correlation to the MR book, not standalone edge | combo via composite path |
| `DOUBLE7_MULTI_IDX_V1` | Connors Double 7 pooled across index CFDs — the density-clearing aggregation play | solos first, per-identity |
| `CHANNEL_TREND_LONGONLY_IDX_V1` | Keltner+Donchian long-only position trend, exit-to-flat — lowest turnover in the set | most cost-robust |
| `EMA_STACK_ADX_SWING_V1` | triple-EMA + ADX>25 swing trend, 4H crypto/index | needs partial-close capability check |
| `NQ_DUAL_SUPERTREND_1H_V1` | dual SuperTrend + SMA200 long-only NAS100 1H — new trend primitive (GMAFLIP forward-pointer) | new indicator module |
| `DOJI_RANGE_POSITION_IDX_V1` | doji body-position-in-range pattern, SPX500 1D | low density, edge-existence probe |
| `THREE_BAR_PATTERN_CENSUS_V1` | full 8-pattern three-bar census on matched instruments, predictions pre-registered | census, not cherry-pick |
| `TWO_BAR_REVERSAL_FX_DAILY_V1` | two-bar reversal at DAILY TF with the validated USD_SYNTH gate (intraday arc exists; daily doesn't) | SMA gates known-bad — avoided |
| `IBS_MINMAX_BASKET_V1` | cross-sectional long-min/short-max IBS index basket, market-neutral | most cost-fragile; parity gate required |
| `BTC_TOD_SEASONALITY_V1` | buy BTCUSD 21:00 / sell 23:00 UTC, zero-parameter falsification probe | spread is the whole question |
| `NAS100_MIDNIGHT_BREAKOUT_V1` | midnight-close-anchored long-only intraday breakout, one entry/day, EOD exit | intraday cost-mirage flag |
| `NOISE_AREA_INTRADAY_MOMO_V1` | Zarattini noise-area 5M momentum, VWAP/band trail — run ONLY if the midnight breakout survives costs | highest cost exposure |

(16 hypotheses; MOMO + QUANTITATIVO are the two ideas ingested 2026-07-01.)

## Batch 2 — StatOasis ingest of 2026-07-02 (7)

| Hypothesis | One-liner | Relationship to tested work |
|---|---|---|
| `VOLFILTER_BAKEOFF_MR_IDX_V1` | ATR/StdDev/BB-width vol filters on the tested RSI/IBS MR lines + filter-variant portfolio | extends ideas 69/70 — vol-filter axis untested; placebo control included |
| `R3_FILTER_BAKEOFF_IDX_V1` | relaxed Connors R3 on 4 indices — SMA200 vs volatility filter bake-off | filter-arm + portfolio extension of idea 69 (reuse its skeleton) |
| `CASEY_C_MR_IDX_V1` | KCC% (min-max rank of close-change) trigger — 3-way bake-off vs RSI/IBS | decorrelation thesis; prior says it should NOT beat IBS |
| `KC_BANDS_MR_IDX_V1` | EMA-of-H/L ± ATR bands MR entry — reference-choice decorrelation | bands-on-PRICE (archived BB work was on-SPREAD); corr matrix is the deliverable |
| `DONCHIAN_4020_BASKET_V1` | 40-in/20-out Donchian, per-instrument direction-gated, 9-symbol basket | inverse-parameter cousin of `CHANNEL_TREND_LONGONLY_IDX_V1` — bake off, don't duplicate |
| `GSR_METALS_RV_V1` | Gold-Silver ratio synthetic 1D — MR fade + breakout mirror; single-leg vs dollar-neutral fork | first metals RV; ratio ≠ cointegration z-spread; 2-leg spread ×4 cost flag |
| `GBP_SHORTBIAS_OSC_V1` | GBPUSD 1D short-side structural bias — oscillator short vs long control | corroborates archived two-bar FX short-bias by an independent method; cheap census gates it |

Batch-2 cross-notes: VOLFILTER and R3 are siblings (same filter thesis, different base) —
run one first, cross-inform. CASEY_C and KC_BANDS are both decorrelation-not-superiority
plays on the same MR book — their acceptance is a measured correlation, not a PF headline.

## Indicator inventory check (verified against `indicators/` 2026-07-02)

The vault pages' "needs authoring" claims were mostly WRONG — corrected in the YAMLs:

- **Casey C% EXISTS** as `indicators/momentum/ultimate_c_percent.py` (UC% = same Ali
  Casey indicator; ULTC model token registered). The `01_MR_FX_1H_ULTC_REGFILT` lineage
  (idea 01) exhausted its preset sweeps 2026-03 — baseline (5/3/75-25) confirmed
  strongest. `CASEY_C_MR_IDX_V1` therefore continues under model token **ULTC** with a
  new identity (SPX500 1D), baseline preset only, no re-sweep at P00.
- Already present, zero authoring: `atr` + `atr_percentile`, `bollinger_bands` +
  `bollinger_band_width` + `bb_squeeze`, `realized_vol`, `volatility_regime`,
  `keltner_channel`, `donchian_channel`, `highest_high` + `lowest_low`, `dma_pct`,
  `rolling_percentile`, `ratio_hedged_spread_zscore`, `roc`, `rsi`, `adx`, `ema_cross`.
  → VOLFILTER / DONCHIAN_4020 / CHANNEL_TREND / DMA_STRETCH need **no** indicator work.
- **Authoring run completed 2026-07-02** (generic defaults, concept-harvest — no source
  parity intended; registry v16→v19, 28 new unit tests, full indicator sweep 80 PASS):
  - `indicators/volatility/kc_bands.py` — KC Bands + %C + Width-C (7/7 tests)
  - `indicators/trend/supertrend.py` — textbook 10/3.0, ratchet + flip (7/7 tests)
  - `indicators/momentum/cci.py` — Lambert CCI, source param typical/hl2/close (8/8 tests)
  - `indicators/stats/pair_ratio.py` — GSR substrate, strict-alignment default (6/6 tests)
- **Deliberately NOT built:** session VWAP + noise-area envelope — NOISE_AREA is gated
  behind NAS100_MIDNIGHT_BREAKOUT surviving costs (build-to-falsify: don't build infra
  before the cheaper probe motivates it).
- **LANDED 2026-07-02 (end-of-batch, operator pre-approved):** `kc_band_stretch`,
  `supertrend_flip`, `cci_threshold` added to `_ALLOWED_PRIMITIVES` in
  `tools/semantic_validator.py`; semantic/allowlist suites 9/9, full indicator-related
  sweep 147 PASS. All three modules are declarable. `pair_ratio` carries no primitive by design.

## Excluded — already answered (do not re-test without a material delta)

| Vault idea | Why excluded |
|---|---|
| `adx-volatility-gate-pairs-trading` | vault-archived; entry-filter arc closed 2026-06-19 |
| `bb-adaptive-threshold-fx-pairs` | vault-archived; BB adaptive-width Exp1 settled 2026-06-16 (generic k=2.0 REJECTED, level-matched k=2.5 conditional) |
| `spx500-rsi-mean-reversion-cfd` | tested — idea 69, WATCH + 10-index sweep; arc live in RESEARCH_MEMORY |
| `ibs-mean-reversion-cfd` | tested — idea 70, IBS<0.20 champion; threshold-shape arc CLOSED |
| `daily-sma-regime-filter-intraday` | component, not a strategy — folded into `ORB_SESSION_FX_V1` as its trend gate (its ON/OFF delta answers the filter hypothesis); note: SMA trend gates destroyed value in the archived two-bar FX arc |

## Dedup deltas (kept despite partial overlap)

- **DMA**: idea 72 tested DMA on XAUUSD **5M** (closed WATCH); the reserve tests SPX500 **1D** — different identity tuple, and it completes the stretch-family bake-off.
- **Two-bar reversal**: archive covers **15M/1H/4H** FX; the reserve tests **1D**, and swaps the vault's SMA macro gate for the archive-validated USD_SYNTH gate.
- **Quantitativo**: bare IBS trigger is settled; the reserve tests the **composition** (band + confirmation exit + regime stop) head-to-head vs the champion.

## Standing cautions inherited from RESEARCH_MEMORY

- High-freq intraday was a **uniform cost-mirage** across the legacy corpus — every
  intraday idea here carries a full-history, charged-engine, year-wise-concentration
  acceptance bar (SPKFADE lesson), and one-entry-per-day caps (PSBRK lesson).
- Judge survival by **full-history Ret/DD + year-wise**, never recent-window PF.
- One symbol = one idea_id — multi-index extensions are separate ideas, and pooled
  composites go through the composite-portfolio path.
