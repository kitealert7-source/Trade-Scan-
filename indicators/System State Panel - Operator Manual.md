# System State Panel (SSP) — Design, Interpretation and Operating Guide

**Version:** 2.8 (Breakout Fit criterion #1 hardening — code v2.4.2)
**Status:** Stabilized
**Companion code:** [`indicators/System State Panel.txt`](System%20State%20Panel.txt)
**Engine reference:** [`engines/regime_state_machine.py`](../engines/regime_state_machine.py)

---

## Document scope

This is a maintainable reference for the System State Panel — its architecture, mathematical underpinnings, operating semantics, and known failure modes. It is intentionally written for the operator-author returning after months away, not for first-time retail users. Read sections 1–6 once for context, then return to sections 7–10 as a working reference during use and calibration.

---

## 1. Executive Overview

### Problem statement

The Trade_Scan project runs a Python research engine (`regime_state_machine.py`, v1_5_8) that performs systematic strategy classification, backtesting, and portfolio evaluation. The Python engine has full visibility into market state via a 3-axis regime model (Direction × Structure × Volatility) resolved into one of six discrete market regimes per bar. This classification drives every gating decision in the pipeline.

The operator does not have this visibility while observing markets in TradingView. The chart shows price and indicators; it does not show what the Python engine would classify the current bar as. This creates a translation gap: an operator cannot tell whether the Python system would currently consider the market trending, ranging, mean-reverting, or unstable — without leaving the chart and running pipeline tooling.

### Why this indicator exists despite the Python engine

The SSP is a TradingView-side mirror of the Python regime model. It approximates the engine's regime classification, axis scores, and supporting diagnostics directly on the chart. The operator gains:

- **Live regime read** without running pipeline tooling
- **Strategy-type screening** — which family of approach the current environment supports
- **Pre-trade qualification** for any manual oversight of automated positions
- **Multi-timeframe alignment context** for hypothesis formation before authoring directives

The SSP does not replace the Python engine. It does not generate signals. Its outputs are advisory and approximate — the engine remains the authority for any classification that drives gating decisions in the pipeline. Where SSP and Python diverge, Python is correct by definition.

### Three operating modes

The panel supports three concurrent functions:

1. **Regime situational awareness** — what kind of market is this right now
2. **Strategy hypothesis screening** — which strategy family is favored / disfavored
3. **Live trade qualification** — is the current environment supportive for an active position

These three uses are served by a single panel architecture rather than three separate views. The architectural decision is intentional — the same regime classification feeds all three, and an operator switching between uses benefits from a single, consistent state read.

### Philosophy

The SSP is a **decision-support dashboard, not a signal generator**. It does not output buy/sell. It does not output "trade now." It outputs current state. Operators interpret state and decide.

This distinction is load-bearing. A signal generator hides its model from the operator and asks for trust. A decision-support dashboard exposes its model and asks for judgment. The latter is what the SSP optimizes for.

### Direction as break-resolution bias

One interpretive principle deserves elevation to the executive level because it changes how the panel is read:

> **The Direction axis should be interpreted not only as directional trend conviction but as expected break-resolution bias, particularly when paired with Breakout Fit.**

Operators who read the Direction row as "current trend slope" use the panel correctly in trending regimes but miss its highest-value signal in compression and pre-breakout states. Section 4.1 documents this in detail; section 7 documents the operating rule.

### Known non-uses

The SSP is **not** for:

- **Entry trigger generation** — it does not signal when to enter, only what state the market is in
- **Parameter optimization** — there is no objective function to optimize against; outputs are descriptive, not predictive
- **Strategy expectancy prediction** — the panel reports regime, not expected return
- **Replacing backtests** — backtests measure outcome; the panel describes context

These are explicit non-features. Operators or future contributors who attempt to use the panel for any of these purposes will encounter inconsistent results — the panel was not designed to answer those questions.

---

## 2. Design Architecture — Core Layer

The Core Layer is the always-visible state surface. 15 data rows, each answering a specific operational question. All rows derive from the same upstream state computation; nothing is duplicated, nothing is decorative.

### Row inventory

| # | Row | Type | Question answered |
|---|---|---|---|
| 1 | Market Regime | discrete label | What regime classification applies |
| 2 | Trend Label | discrete label | Direction conviction, human-readable |
| 3 | Direction Score | scalar | Direction conviction, numeric |
| 4 | **Trade Bias** | **synthesized label** | **Resolved bias from regime+direction+hazard+fit** |
| 5 | Structure Score | scalar | How organized / linear is price action |
| 6 | Volatility Score | scalar | Where in the vol distribution are we |
| 7 | Vol Regime | discrete label | Volatility regime, classified |
| 8 | ATR Ratio 14/100 | ratio | Vol expansion or contraction signal |
| 9 | Z-Score | scalar | Stretch from mean (mean-reversion oriented) |
| 10 | TF Fit | category | Trend-following suitability |
| 11 | MR Fit | category | Mean-reversion suitability |
| 12 | Breakout Fit | category | Coiled-spring / breakout suitability |
| 13 | Environment | category | Composite supportive / neutral / degrading |
| 14 | Regime Age / Stability | composite | Bars in current regime + stability label |
| 15 | Market Hazard | category | Composite instability / caution flag |

### Field-by-field documentation

#### Market Regime

Discrete label from the 6-state resolver: `trend_expansion`, `trend_compression`, `unstable_trend`, `mean_reversion`, `range_low_vol`, `range_high_vol`. Mirrors the Python `market_regime` field.

Resolution logic (3-axis space):
- High direction + high structure + high vol → `trend_expansion`
- High direction + high structure + low vol → `trend_compression`
- High direction + low structure → `unstable_trend`
- Low direction + high structure + negative autocorr → `mean_reversion`
- Low direction + low vol → `range_low_vol`
- Low direction + (default) → `range_high_vol`

**Why this exists:** the single most important field on the panel — the engine's authoritative classification expressed as one label.

#### Trend Label

5-state human-readable label derived from direction score: STRONG UP / WEAK UP / NEUTRAL / WEAK DOWN / STRONG DOWN. Thresholds at ±0.6 and ±0.2.

**Why this exists:** complements the 6-state regime label with directional conviction at human reading speed. The regime label says what *type* of market; trend label says *which way*.

**Note on NEUTRAL:** with 5 discrete voters, direction score takes one of {−1, −0.6, −0.2, +0.2, +0.6, +1}. The strict NEUTRAL band (between −0.2 and +0.2 exclusive) is therefore never triggered in practice. The label is retained for forward compatibility if voter outputs become continuous in future revisions.

**Rename recommendation:** "Trend Label" undersells what this row does. Consistent with the Direction row's reframing as expected break bias, the row's semantic content is closer to **"Break Bias"** than "Trend Label" — it expresses which side of structural resolution is favored, in human-readable form. The numeric Direction row ("Directional Pressure") and the categorical row pair naturally as:

- Direction row: *Directional Pressure* (numeric magnitude of bias)
- This row: *Break Bias* (categorical bucket of bias)

This pairing is conceptually clean and avoids the implication that the row is only valid in trending regimes. **"Break Bias" is recommended for a future code rename.** The current "Trend Label" displays correctly and the change is non-urgent — listed here so the rename has documented rationale when adopted.

#### Direction Score — *Directional Pressure (Expected Break Bias)*

Scalar in {−1.0, −0.6, −0.2, +0.2, +0.6, +1.0}. Average of 5 binary direction voters. See section 4 for voter inventory.

**Conceptual framing — recommended naming:** "Directional Pressure (Expected Break Bias)" better captures the row's operational meaning than "Direction Score." The Pine table cell currently displays "Direction" for compactness; the documentation uses both names interchangeably and prefers the longer form when the distinction matters. A future Pine code revision may rename the cell label; the underlying field is unchanged.

**What this row actually represents:**

The Direction row is *not* simply a trend descriptor. It is a probabilistic statement about which side of the current price structure is more likely to resolve. Its operational role shifts with regime context:

- In **active trends**, it expresses trend pressure / continuation conviction
- In **compression or pre-breakout setups**, it expresses expected resolution side / break bias
- In **ranges**, it expresses latent bias with weaker informational weight
- In **unstable / transitional states**, it is suggestive only — the regime label takes precedence

This multi-role interpretation is what justifies the row's prominence in the Core Layer. A pure trend descriptor would not need this much real estate.

**Why this exists:** numeric form of directional pressure, granular enough to distinguish 4/5 from 5/5 voter conviction. Coupled with Breakout Fit, it forms the panel's core "setup + side" model (see section 7).

#### Trade Bias

Synthesized summary label resolving regime + direction + hazard + fit into one operator-facing bias. Ten possible values:

| Label | Meaning | Triggered by |
|---|---|---|
| `LONG BIAS` | Trade side hypothesis is long | Trend regime + Direction > 0 |
| `SHORT BIAS` | Trade side hypothesis is short | Trend regime + Direction < 0 |
| `FADE LONG` | Trade is a long fade-entry | Mean-reversion regime + Z < −0.5 (price stretched down) |
| `FADE SHORT` | Trade is a short fade-entry | Mean-reversion regime + Z > +0.5 (price stretched up) |
| `UP BREAK BIAS` | Expected breakout direction is up | Breakout PRIME + Direction ≥ +0.6 |
| `DOWN BREAK BIAS` | Expected breakout direction is down | Breakout PRIME + Direction ≤ −0.6 |
| `WATCH UP` | PRIME setup, soft bullish lean from Kalman | Breakout PRIME + \|D\| < 0.6 + Kalman velocity > 0 |
| `WATCH DOWN` | PRIME setup, soft bearish lean from Kalman | Breakout PRIME + \|D\| < 0.6 + Kalman velocity < 0 |
| `BREAK WATCH` | PRIME setup, no directional lean (rare edge case) | Breakout PRIME + \|D\| < 0.6 + Kalman velocity ≈ 0 |
| `COIL / UNRESOLVED` | Conditions ambiguous; bias not determinable | unstable_trend, range_low_vol without PRIME, etc. |
| `STAND ASIDE` | Hard veto — do not act on any bias | HAZARD or range_high_vol |

**Note on the WATCH family:** these three labels are PRIME-gated watching states — the rare breakout setup is confirmed, but voter consensus hasn't aligned strongly enough to commit to an UP/DOWN BREAK BIAS. They render with **yellow text on amber background**, signaling "rare setup present, side soft" — visually distinct from gray COIL (no setup) and red STAND ASIDE (do not trade). The Kalman velocity sign provides a tiebreaker hint when the 5-voter Direction stalls at ±0.2.

**Confidence encoded via color and background tint, not label:**
- Active bias labels (LONG/SHORT/FADE/BREAK BIAS) render **green** at high confidence and **yellow** at medium confidence on white background
- WATCH UP / WATCH DOWN / BREAK WATCH render **yellow text on amber background** — PRIME setup confirmed but side not committed
- STAND ASIDE renders **red text on lavender background** — hard veto
- COIL / UNRESOLVED renders **gray** on white — informational, neither favorable nor adverse

**Resolver cascade (priority order, first match wins):** see section 4.9 for full logic. Summary:
1. HAZARD or range_high_vol → STAND ASIDE
2. mean_reversion + MR Fit HIGH → fade biases (Z sign inverted to trade direction)
3. Breakout PRIME → break biases (Direction = resolution side)
4. Trend regimes → long/short bias (Direction sign = trade side)
5. unstable_trend / leftovers → COIL / UNRESOLVED

**Why this exists:** completes the panel's reasoning stack (Regime → Direction → Trade Bias → Fit). Compresses logic operators previously had to compute mentally from 4–6 rows into one synthesized read.

**Critical interpretation rule:** Trade Bias is a *side hypothesis*, not an entry trigger. `LONG BIAS` does not mean "enter long now." It means: *if* you trade in this regime, the side is long. Entry timing, stop placement, and sizing are operator decisions the panel does not address. The most likely misuse of Trade Bias is reading it as a trigger row. **It is not.**

**Architectural note:** Trade Bias introduces no new inputs and no upstream dependencies — it is a pure synthesis of fields already computed. The row exists because manual synthesis is error-prone under cognitive load, not because the underlying logic is novel.

#### Structure Score

Scalar in [0, 1]. Average of 3 normalized inputs: ADX/100, R² of linear regression fit, and inverted Choppiness Index.

**Why this exists:** measures how organized / linear price action is, independent of which direction. High structure with high direction = clean trend. High structure with low direction = clean range or potential mean-reversion territory.

#### Volatility Score

Scalar in [0, 1]. Average of ATR(14) percentile (200-bar lookback) and realized volatility percentile (200-bar lookback).

**Why this exists:** position in the volatility distribution. Drives the Vol Regime tag and is one of the three primary axes feeding regime classification.

#### Vol Regime

Discrete label: COMPRESSED / NORMAL / EXPANDED / EXTREME, based on volatility score thresholds (<0.25 / <0.55 / <0.80 / else).

**Why this exists:** vol context expressed at glance. EXTREME triggers trade qualification warnings; COMPRESSED supports breakout setups.

#### ATR Ratio 14/100

Scalar ratio of short-window ATR to long-baseline ATR. Reads vol expansion (>1.0) or contraction (<1.0) relative to the asset's own recent baseline. Asset-class neutral (no dollar values).

**Why this exists:** detects vol regime *transitions* faster than the vol score itself, which uses 200-bar percentile lookback. ATR Ratio responds to vol changes in tens of bars; the percentile reflects them in hundreds.

#### Z-Score

Standard mean-reversion Z: `(close − sma(50)) / stdev(50)`. Reports stretch from mean in standard-deviation units.

**Why this exists:** stretch / exhaustion read. Drives mean-reversion suitability scoring and feeds the Hazard composite.

#### TF Fit / MR Fit / Breakout Fit

Categorical suitability scores. Each is a 0–N point scoring system across orthogonal criteria, bucketed into LOW / MED / HIGH (TF, MR) or LOW / FORMING / PRIME (Breakout).

These three rows answer "which strategy type does this environment support." See section 4.5 for scoring details and section 7 for operating use.

#### Environment

Composite trade-qualification label: SUPPORTIVE / NEUTRAL / DEGRADING. Aggregates regime stability, vol extremity, Z-score stretch, and at-least-one suitability HIGH.

**Why this exists:** single-row qualifier for "is this environment good to trade right now." DEGRADING is a stand-aside cue.

#### Regime Age / Stability

Combined display: integer age (bars in current confirmed regime) + label (FRESH / NEW / STABLE).

Stability label thresholds:
- < 3 bars: **FRESH** (still inside the regime confirmation window — treat as unconfirmed)
- 3–7 bars: **NEW** (recently confirmed but not stable)
- ≥ 8 bars: **STABLE** (established)

**Why this exists:** a regime label of `trend_expansion` means very different things at age 1 vs age 25. Operators need this distinction for live trade decisions.

#### Market Hazard

Composite alert flag: HAZARD / CAUTION / CLEAR.

- **HAZARD**: any of {regime age < 3, vol regime = EXTREME, |Z| > 2.5}
- **CAUTION**: any of {regime age 3–7, |Z| > 1.5, autocorr near zero with |Z| > 1.2}
- **CLEAR**: none of the above

**Why this exists:** single-row alert for "should I be cautious about active positions or new entries right now."

---

## 3. Research / Extended Layer

The extended layer provides depth diagnostics for hypothesis screening and panel calibration. It is not visible by default — operators toggle to Core+Context or Full Research mode when needed.

The extended rows fall into two categories:

### Context anchors (Core+Context mode)

These are familiar legacy indicators that operators use as "feel" reference points. They are not regime inputs, but they earn their rows for two reasons: (1) they let the operator compare intuitive read to system classification, and (2) divergence between feel anchors and system reads is itself signal.

| Row | Purpose | Decision-or-diagnostic |
|---|---|---|
| VWAP | Session reference price | Diagnostic — manual entry timing |
| EMA 20 | Short-term mean reference | Diagnostic — mean-reversion trade context |
| ADX (raw) | Familiar trend-strength scalar | Diagnostic — calibrate against Structure Score |
| Chop Index | Familiar trend-vs-range scalar | Diagnostic — convergence check with R² |
| BB Width % | Familiar compression scalar | Diagnostic — drives Breakout Fit |

### Research diagnostics (Full Research mode)

These expose internal model state. Useful for tuning, debugging, and verifying that composite outputs reflect plausible underlying values.

| Row | Purpose | Type |
|---|---|---|
| RV %ile | Realized volatility position | Diagnostic — feeds Vol Score |
| Bar Range Ratio | Current bar HL vs 20-bar mean | Diagnostic — instability proxy |
| R² (LinReg) | Linearity of recent price | Diagnostic — feeds Structure Score |
| Autocorr | Lag-1 log-return autocorrelation label | Diagnostic — drives MR detection |
| LinReg HTF (resolved) | HTF direction voter raw | Diagnostic — verify HTF voter |
| Kalman Velocity | Raw Kalman state velocity | Diagnostic — verify Kalman voter |
| Regime Transition | Boolean — true on the bar a regime confirmed | Decision — replay analysis aid |

### Decision variables vs observability

The clear distinction: **all decision variables live in the Core Layer**. The extended layer is observability, not decision input. If an operator finds themselves making decisions from extended-layer rows, they should ask why the core didn't already encode that information.

The one exception is Regime Transition — it is a decision-relevant flag that lives in the extended layer because it fires for exactly one bar per transition and is too sparse to warrant a permanent core row. Treat it as a momentary alert when toggled into Full Research mode.

---

## 4. Mathematical Components

This section documents the internals conceptually, not as code. Implementation lives in `indicators/System State Panel.txt`; the engine reference is `engines/regime_state_machine.py`.

### 4.1 Five-voter direction model

Direction score is the average of five binary voters, each outputting +1 or −1:

1. **LinReg slope (chart TF)** — sign of `ta.linreg(close, 50)` rate of change between consecutive bars
2. **EMA slope (chart TF)** — sign of `ema(20)` rate of change
3. **SHA direction** — sign of EMA-smoothed Heikin-Ashi close rate of change (3-bar smooth)
4. **LinReg slope (HTF)** — same formula on the resolved HTF (see 4.3)
5. **5th voter — selectable** — Kalman velocity (default) or Donchian midline slope (fallback)

Output domain: 6 discrete values {−1.0, −0.6, −0.2, +0.2, +0.6, +1.0} representing `sum / 5`.

#### Why 5 voters and not 3

A 3-voter discrete model produces only 4 buckets and saturates at ±1 too easily. 5 voters reduce saturation, give finer resolution. Mirrors Python's 5-voter direction axis exactly.

#### Rejected — HMA slope as 5th voter

HMA is a smoothing kernel variant of EMA. Adds little independent information; correlates ~0.85 with EMA direction in most market conditions. Kalman velocity is structurally distinct (velocity-domain estimate, not level-domain) — genuinely independent.

#### Rejected — trend persistence as 5th voter

Trend persistence is a *consistency* metric (how stable is direction), not a *direction* estimator. Putting it on the direction axis cross-wires what should be axis-orthogonal information. Persistence belongs in structure scoring, not direction scoring.

#### Direction as Resolution Bias (not just trend slope)

This subsection elevates an interpretive principle that recurs throughout the panel's operating semantics.

**The Direction axis is not merely a trend descriptor.** It is a probabilistic statement about which side of the current price structure is more likely to resolve. The same numeric reading carries different operational meaning depending on the regime context the panel reports:

| Regime context | Direction interpretation | Informational weight |
|---|---|---|
| Active trend (`trend_expansion` / `trend_compression`) | Trend pressure / continuation conviction | High |
| Compression / breakout setup (Breakout Fit FORMING or PRIME) | **Expected resolution side / break bias** | Very high — pairs with Breakout Fit |
| Range (`range_low_vol`, `range_high_vol`) | Latent bias, slow-moving | Lower — ranges resolve in either direction frequently |
| Unstable / transitional (`unstable_trend`, fresh regime) | Suggestive only | Use the regime label as authoritative |
| Mean-reversion (`mean_reversion`) | Bias *opposite* the expected trade direction (MR fades direction) | Inverted — high \|Direction\| with high MR Fit means fade entries are stronger |

The conceptual reframe: in a compressed range with Breakout Fit PRIME, a Direction reading of +0.6 means the eventual break is more likely to be upside than downside. The row is forecasting structural resolution, not describing current slope.

**Why this matters operationally:** the most common misuse of the panel is reading Direction in isolation as "the market is trending up" or "the market is trending down" without checking the regime context. That reading is correct in trending regimes and misleading in compression. Section 7 documents the Breakout Fit + Direction paired interpretation rule that makes this concrete.

**Implications for downstream rows:**
- TF Fit reads Direction as conviction (high \|Direction\| supports trend strategies)
- MR Fit reads Direction as fade target (low \|Direction\| supports MR; the *sign* informs which side is faded if other criteria align)
- Breakout Fit does not read Direction directly in its scoring — Direction is a separate input that operators consult alongside Breakout Fit (see section 7)

This separation is intentional. Embedding Direction inside Breakout Fit scoring would conflate "does setup exist" with "which way will it resolve" — these are independent questions and deserve independent rows.

#### Directional Bias ≠ Resolution Confidence

A subtle but important distinction that prevents the most consequential misuse of the Direction row:

- **Bias** is *which side* the direction reading favors. Encoded as `sign(Direction)`.
- **Confidence** is *how strongly that bias should weigh in a decision*. A function of the surrounding regime context, structure quality, and hazard state.

The same Direction value carries different confidence in different contexts. A reading of +0.6 in `trend_expansion` with STABLE regime age is a high-confidence bullish bias. The identical +0.6 in `unstable_trend` is a low-confidence bias — the structure is poor, the regime is questionable, and the voter agreement may not survive the next few bars.

Operationally:

```
Bias       = sign(Direction)
Confidence = f(Regime, Structure Score, Hazard, Regime Age)
```

These two readings combine into the operator's actual decision weight. Bias alone is half the information.

**Confidence-by-context matrix** (same Direction = +0.6 reading across different regime states):

| Regime context | Bias | Confidence | Operating read |
|---|---|---|---|
| `trend_expansion` + STABLE + Hazard CLEAR | up | **High** | Strong continuation conviction; standard sizing |
| `trend_compression` + STABLE | up | **High** | Continuation bias under contained vol |
| `range_low_vol` + Breakout Fit PRIME | up | **High** | Actionable bullish break bias (paired model) |
| `unstable_trend` | up | **Low** | Suggestive only; regime label says structure is poor |
| `mean_reversion` + MR Fit HIGH | up | **Inverted** | Bias points to fade target — direction reads where price has stretched |
| `range_high_vol` | up | **Low** | Latent bias; ranges resolve in either direction frequently |
| Any regime + Regime Age = FRESH | up | **Gated** | Wait — voter consensus may shift on confirmation |
| Any regime + Hazard = HAZARD | up | **Suspended** | Bias is real but trade qualification overrides |

**Why this matters:** an operator who reads "Direction +0.6 = bullish, take long" without consulting the confidence column will trade the same way in `trend_expansion` and `unstable_trend`. The first is favorable; the second is the panel's signature low-quality state. The difference is not in the bias — both read +0.6 — but in the confidence the surrounding rows assign to that bias.

This is the deeper meaning of the precedence hierarchy in section 7: priority 1 (Market Regime) and priority 4 (Hazard / Regime Age) are not just informational rows — they are *confidence modulators* on the priority-2 Direction reading.

### 4.2 Two-dimensional Kalman velocity voter

Constant-velocity state-space filter with:
- State: `[position, velocity]`
- Observation model: position observed only
- Process noise: `Q = diag(0.0001, 0.001)`
- Measurement noise: `R = 1.0`

**Predict step:**
```
position_pred = position + velocity
velocity_pred = velocity
covariance_pred = F · P · Fᵀ + Q
```

**Update step (after observing close):**
```
innovation = close − position_pred
gain = covariance_pred[:, 0] / (covariance_pred[0,0] + R)
position = position_pred + gain[0] · innovation
velocity = velocity_pred + gain[1] · innovation
covariance = (I − gain · H) · covariance_pred
```

Direction signal: `sign(velocity)`.

#### Why constant-velocity (2D) and not constant-position (1D)

1D form gives smoothed price — direction = sign of price change vs prior smoothed price. That's redundant with EMA. 2D form gives an explicit velocity estimate independent of EMA's smoothing — genuinely new direction information.

#### Q/R kept internal

Q and R control filter aggressiveness. Tuning them per asset is theoretically beneficial but practically opens a calibration rabbit hole. Defaults are calibrated for typical 15m–4H equity / FX / crypto behavior. If Kalman appears noisy on a specific asset, the Donchian fallback is a one-input switch.

#### Fallback voter — Donchian midline slope

Selectable via input. Computed as `sign((highest(high, 20) + lowest(low, 20)) / 2 − previous bar)`. Genuinely independent (uses extremes, not closes). Three lines of Pine. Available as plug-in replacement for Kalman if the latter proves unstable on a given instrument.

### 4.3 Adaptive HTF mapping

Higher-timeframe resolution targets 12–30× separation between chart and HTF — large enough for structural separation, small enough for the HTF voter to remain responsive.

| Chart TF | HTF (resolved) | Multiple |
|---|---|---|
| ≤ 1m | 30m | ~30× |
| ≤ 3m | 30m | ~10× |
| ≤ 5m | 1H | 12× |
| ≤ 15m | 4H | 16× |
| ≤ 30m | D | session-adjusted |
| ≤ 1H | D | 24× |
| ≤ 2H | D | 12× |
| ≤ 4H | W | ~42× |
| ≤ D | W | 5× |
| ≤ W | M | ~4× |

Implementation: `timeframe.in_seconds()` mapped to a TradingView TF string, used as the second argument to `request.security` for the HTF LinReg voter and the diagnostic row label.

**Manual override available:** `HTF Mode = Manual` lets the operator pick directly. Auto is the default and should suffice for nearly all cases.

#### Rejected — fixed daily HTF

Original v2.0 design. Daily on a 1m chart is structurally meaningful but on a 4H chart is too close (only 6×) — the HTF voter correlates with chart-TF voters and adds no information. Adaptive scaling solves this.

### 4.4 R² replacing Efficiency Ratio in Structure axis

`structure_score = (adx_score + r2_val + chop_inverted) / 3`, where `r2_val = correlation(close, bar_index, 50)²`.

#### Why R² over ER

ER measures path efficiency — net change divided by sum of bar-by-bar absolute changes. In a strong trend with deep pullbacks, the path lengthens (denominator grows) while net change is preserved, collapsing ER. The structure axis then registers low structure, which classifies a real trend as `unstable_trend`. False classification.

R² measures how well prices fit a straight line. A trend with pullbacks still fits a line well — R² stays elevated. A choppy market does not fit a line — R² drops. Better-aligned to the conceptual goal of structure scoring (is this market organized).

#### Rejected — slope consistency (variance of slope)

More complex Pine implementation, similar information content to R², no robust advantage.

#### Rejected — DI spread

|+DI − -DI| / sum is a directional efficiency metric, but redundant with ADX which is already in the structure axis.

### 4.5 Suitability scoring (TF / MR / Breakout)

Each suitability row scores criteria binary (1 if met, 0 if not), sums them, and buckets into a label.

#### TF Fit (5 criteria, max 5)
1. `abs(direction_score) >= 0.55` — 4/5 voter agreement
2. `structure_score > 0.6` — clean structure
3. `0.25 < volatility_score < 0.80` — not compressed, not extreme
4. `|z_score| < 1.5` — room to run
5. `regime_age > 5` — established

Buckets: **HIGH** (≥4) / **MED** (≥2) / **LOW** (<2)

#### MR Fit (5 criteria, max 5)
1. `abs(direction_score) <= 0.2` — directionless
2. `|z_score| > 1.2` — stretched from mean
3. autocorr indicates mean-reversion (lag-1 < −0.05)
4. `volatility_score < 0.55` — vol expansion kills MR
5. `structure_score < 0.5` — low structure = range-bound

Buckets: **HIGH** (≥4) / **MED** (≥2) / **LOW** (<2)

#### Breakout Fit (4 criteria, max 4)
1. **Compression confirmed**: `bb_width_percentile < 30 AND atr_ratio < 0.85` — bands compressed *and* absolute vol below baseline. The dual condition exists for percentile-saturation defense (see "Percentile saturation defense" subsection below).
2. **Volatility contraction persistence**: `atr_ratio < 0.9` — vol regime below baseline (looser threshold than criterion 1; different role)
3. **Price near equilibrium**: `|z_score| < 0.8` — not yet broken
4. **Structure improving**: `structure_score > structure_score[5]` — over 5-bar smoothed window

Buckets: **PRIME** (=4) / **FORMING** (≥2) / **LOW** (<2)

#### Note on criteria 1 and 2 sharing `atr_ratio`

Both criteria 1 and 2 reference `atr_ratio`, which is mild double-counting by design. The two thresholds (0.85 vs 0.9) and roles (compression event vs persistence context) are distinct enough to justify separate scoring weight. A market that is genuinely setting up for breakout will satisfy both; a market that is merely drifting at low vol will satisfy criterion 2 but fail criterion 1's tighter corroboration. The redundancy adds robustness rather than information duplication.

#### Percentile saturation defense (criterion 1 corroboration)

`ta.percentrank` returns the percentage of bars in the lookback window with values *strictly less than* the current value. When current `bb_width` is at or below the 200-bar minimum, the percentile floors at 0 — regardless of whether the compression is genuinely extreme or merely the lowest within a particular 200-bar window that happened to contain higher-vol bars.

This saturation creates a calibration risk: in mild compression environments where the 200-bar lookback contains earlier high-vol bars, `bb_pct < 30` can fire on what is in fact only modest compression. Without corroboration, criterion 1 alone can produce false positives.

The dual condition `bb_pct < 30 AND atr_ratio < 0.85` defends against this:
- `bb_pct < 30` confirms compression *relative to the recent past* (percentile-based)
- `atr_ratio < 0.85` confirms compression *in absolute terms vs long baseline* (non-percentile, doesn't saturate)

Both must agree. A market with saturated `bb_pct = 0` but `atr_ratio = 0.95` (only mildly compressed vs baseline) will fail criterion 1 — correctly, since the percentile reading was a lookback-window artifact rather than genuine compression.

Threshold choice (`< 0.85` rather than `< 0.8` or `< 0.9`):
- `< 0.9` would catch nearly all percentile saturation cases but is too loose — barely-compressed conditions still trigger
- `< 0.8` is too strict — filters out genuine early-compression coils that should still register
- `< 0.85` is the empirical compromise: filters shallow fake-compression while preserving real early coils

This is a prophylactic hardening, not a behavioral change. In genuine compression environments where both percentile and ratio agree, criterion 1 fires as before. The change only suppresses fires where percentile saturated but absolute compression is modest.

#### The Z-score criterion as hidden protection (sophistication observation)

A subtle property of the Breakout Fit cascade worth documenting: criterion 3 (`|z_score| < 0.8`) acts as an implicit defense against many false-positive scenarios that the other criteria might otherwise admit.

Consider a quiet trend with low vol but steady directional drift:
- Criterion 1 (compression): may saturate to fire (bb_pct floors at 0)
- Criterion 2 (vol baseline): may fire (atr_ratio low because trend bars are small)
- Criterion 4 (structure improving): may fire if structure is firming up

Three of four criteria can fire on what is in fact a calm trend, not a coiled spring. **What stops PRIME from firing is the Z-score criterion** — in a trending market, price has by definition moved away from the rolling mean, so `|z_score| < 0.8` fails. Criterion 3 acts as the "is the price actually still at equilibrium" check that prevents calm-trend setups from being misclassified as breakout setups.

This is structural protection, not luck. The Z-score criterion is the single criterion that distinguishes "compressed trend" from "compressed range about to break" — and only the latter produces a genuine breakout setup. Future contributors should preserve this criterion specifically; removing or weakening it would unbalance the Breakout Fit cascade in a way no single replacement metric covers.

The criterion 1 hardening (added in v2.8) and the Z-score criterion (always present) work together: Z-score gates trending-but-low-vol setups, criterion 1 corroboration gates ranging-but-shallow-compression setups. Together they restrict PRIME to its intended scope: range with genuinely deep compression near the mean.

#### Why Breakout requires 4-of-4 and others 4-of-5

Breakout has 3 primary necessary conditions (criteria 1, 2, 3) and 1 supporting (criterion 4). Missing any primary means the setup isn't actually present. TF and MR have 3 primary + 2 supporting structure, so 4-of-5 (allowing one supporting miss) is structurally analogous.

#### Rejected — Breakout HIGH at 3-of-4

Produced ~8% HIGH frequency on typical instruments, devaluing the signal. 4-of-4 yields ~1% — appropriate for "rare premium setup."

#### Why criterion 4 uses [5] not [3]

The 3-bar lookback was sensitive to bar-level noise and could flip "improving" status spuriously. 5-bar lookback smooths without losing the criterion's discrete-comparison semantics.

#### Why PRIME / FORMING vocabulary instead of HIGH / MED

Two reasons:
1. **Scarcity signaling** — "HIGH" reads as "high score in the current scoring system." "PRIME" reads as "rare premium signal." With Breakout Fit requiring unanimous criteria, the label should communicate that this is a genuinely uncommon condition.
2. **Operational distinction** — TF Fit HIGH and MR Fit HIGH appear in normal trending or ranging markets respectively. Breakout Fit PRIME marks a specific setup state — a coiled spring — that is qualitatively different from "the market is currently trending."

### 4.6 Environment State

Composite scoring (4 criteria, max 4):
1. `regime_age >= 8` — regime established
2. `vol_regime != EXTREME`
3. `|z_score| < 1.5`
4. `tf_pts >= 4 OR mr_pts >= 4` — at least one strategy type strongly favored

Buckets: **SUPPORTIVE** (≥3) / **NEUTRAL** (≥2) / **DEGRADING** (<2)

### 4.7 Market Hazard

Two-tier OR logic with strict precedence:

**HAZARD** — any of:
- `regime_age < 3` (inside confirmation window)
- `vol_regime == EXTREME`
- `|z_score| > 2.5`

**CAUTION** (only if not HAZARD) — any of:
- `regime_age < 8`
- `|z_score| > 1.5`
- `|autocorr| < 0.05 AND |z_score| > 1.2` (noisy autocorr + stretch)

**CLEAR** — otherwise.

#### Why composite over standalone Autocorr Regime label

Autocorr Regime as a labeled output (MOMENTUM / NOISE / MEAN-REV) takes a row and provides information that's already partially encoded in the suitability rows. Hazard is genuinely new — answers "should I be cautious right now" with three traffic-light states. Autocorr as raw input still feeds MR detection and contributes to the Hazard composite.

### 4.8 Regime confirmation and stability

State machine with 3-bar confirmation:
- Each bar computes a raw regime classification
- A change from the current stable regime requires 3 consecutive bars of the same alternative regime to confirm
- During confirmation, the regime label remains the current stable one
- On confirmation, age resets to 0; transition flag fires for one bar

Mirrors Python's `regime_confirm_bars=3` exactly.

The stability label (FRESH / NEW / STABLE) is derived from age, not from the confirmation state machine — once a regime is confirmed (age ≥ 0), it's already "stable" in a state-machine sense. The stability label adds a *post-confirmation grace window* concept that's separate from the confirmation logic itself.

### 4.9 Trade Bias Resolver

Synthesized summary row resolving upstream state into one operator-facing bias label. Pure cascade — no new inputs, no math beyond label routing.

#### Cascade priority (first match wins)

```
PRIORITY 1 — Hard veto (no bias actionable)
  if hazard == HAZARD                     → STAND ASIDE
  if regime == range_high_vol             → STAND ASIDE

PRIORITY 2 — Mean-reversion fade (Z sign inverts to trade direction)
  if regime == mean_reversion AND MR Fit == HIGH:
    if z_score >  0.5  → FADE SHORT       (fade the long stretch — trade is short)
    if z_score < -0.5  → FADE LONG        (fade the short stretch — trade is long)
    else               → COIL / UNRESOLVED

PRIORITY 3 — Breakout PRIME (Direction = expected resolution side)
  if Breakout Fit == PRIME:
    if direction >= +0.6 → UP BREAK BIAS
    if direction <= -0.6 → DOWN BREAK BIAS
    else (|direction| < 0.6, typically 0.2 with discrete voters):
      // Kalman velocity sign breaks the tie when 5-voter Direction stalls
      if kalman_velocity > 0 → WATCH UP
      if kalman_velocity < 0 → WATCH DOWN
      if kalman_velocity = 0 → BREAK WATCH    (rare edge case)

PRIORITY 4 — Trend regime (Direction sign = trade side)
  if regime in (trend_expansion, trend_compression):
    if direction > 0     → LONG BIAS
    if direction < 0     → SHORT BIAS
    else                 → COIL / UNRESOLVED

PRIORITY 5 — Default catch-all
  → COIL / UNRESOLVED
```

#### Why the WATCH family exists (and why PRIME never falls back to COIL)

PRIME is by-design ~1% of bars. When it fires, the operator should always see *something* meaningfully distinct from "no setup, no bias." Earlier resolver drafts (v2.6) routed PRIME with weak Direction (±0.2) into COIL / UNRESOLVED. This was wrong: it conflated two operationally distinct states.

- **COIL / UNRESOLVED** = no setup AND no clear bias (most common ambiguous state; gray, informational)
- **WATCH family** = rare setup confirmed, side not yet committed (yellow text on amber background; alert-soft)

The WATCH labels render with **amber background tint** — the same tint used for CAUTION and DEGRADING states — signaling "soft alert, requires attention." Distinct from STAND ASIDE's lavender (hard veto) and from COIL's white (informational only).

The Kalman velocity tiebreaker exists because 5-voter Direction has discrete output buckets {−1, −0.6, −0.2, +0.2, +0.6, +1}. When the inner-PRIME branch fires with weak Direction, |Direction| is almost always exactly 0.2 — a 3/5 voter split. In that narrow case, the Kalman velocity (continuous-domain estimate) provides finer directional resolution than the discrete vote sum. The operator gets WATCH UP or WATCH DOWN instead of an undirected BREAK WATCH.

The `BREAK WATCH` fallback (Kalman velocity exactly 0) is a true edge case — it occurs only when the Kalman state machine is in warmup or has not yet accumulated a velocity estimate. In normal operation, the resolver produces WATCH UP or WATCH DOWN.

#### Why `unstable_trend` is NOT in the hard veto

Earlier resolver drafts included `unstable_trend` in priority 1. This was changed during v2.6 design review. Rationale:

`unstable_trend` is the regime classification for "directional pressure exists but structure is poor." That is *informative ambiguity*, not a hard stop. A panel that auto-routes `unstable_trend` to STAND ASIDE conflates the two and overuses the strongest stand-aside signal. STAND ASIDE should be **rare and meaningful**.

By routing `unstable_trend` to priority 5 (COIL / UNRESOLVED), the panel correctly signals "no clear bias" without invoking the hard-veto vocabulary. The operator sees an honest read of an ambiguous environment and can choose to wait, scale back, or interpret further via the Fit rows. STAND ASIDE remains reserved for genuinely adverse conditions: HAZARD or `range_high_vol`.

This preserves the meaning hierarchy:
- COIL / UNRESOLVED = "I cannot resolve a bias here, but the environment isn't dangerous"
- STAND ASIDE = "do not trade, period"

#### Confidence determination (via color, not label suffix)

Confidence modulates the color of the bias label without altering the label itself. Justification documented in Section 5.

| Bias label | High confidence (green) | Medium confidence (yellow) | Watching state |
|---|---|---|---|
| LONG BIAS / SHORT BIAS | Regime STABLE AND TF Fit HIGH | Regime NEW or TF Fit MED | — |
| FADE LONG / FADE SHORT | Regime STABLE | Regime NEW | — |
| UP / DOWN BREAK BIAS | Always green (PRIME is the gate) | — | — |
| WATCH UP / WATCH DOWN / BREAK WATCH | — | — | **Always yellow text on amber bg** (PRIME-gated watching) |
| COIL / UNRESOLVED | — | — | (always gray, informational) |
| STAND ASIDE | — | — | (always red on lavender alert bg) |

PRIME requires unanimous criteria (4/4); when triggered with strong Direction (≥ \|0.6\|), the breakout setup is by definition high-confidence. When Direction is weak (\|0.2\|), the WATCH state preserves the rarity signal of PRIME without committing to a side.

#### Naming convention (resolves a future-bug source)

`FADE LONG` and `FADE SHORT` could mean either "fade the long side" or "long fade trade." The convention adopted across the panel and documentation:

- **The label always names the trade side**, consistent with LONG BIAS / SHORT BIAS.
- `FADE LONG` = trade is a long entry (fading a downward stretch). Triggered when Z < −0.5.
- `FADE SHORT` = trade is a short entry (fading an upward stretch). Triggered when Z > +0.5.

Z-sign inversion happens *inside* the resolver (Z > 0 routes to FADE SHORT). The operator reads only the resolved label and trades the named side.

#### What this row is not

Trade Bias is a **synthesized side hypothesis**, not an entry signal. It addresses one question — *which side* — and explicitly does not address:

- When to enter
- Where to place stops
- How large a position
- Whether to take the trade at all

Operators who treat Trade Bias as a trigger row will misuse it. Section 9 documents this as a primary misuse case.

---

## 5. Color Grammar / Display Semantics

Color encodes meaning at the system level, not the row level. The same color signifies the same concept on every row, regardless of what the row measures. This is enforced as a design constraint and should never be relaxed without a deliberate review.

### Color semantics

| Color | Hex | Meaning | Examples |
|---|---|---|---|
| Teal-green | `#00897b` | Confirmed / favorable / clear | HIGH/PRIME fit, STABLE, CLEAR hazard, SUPPORTIVE, NORMAL vol |
| Light teal | `#80cbc4` | Mildly positive / soft | WEAK UP, `trend_compression` regime, direction 0–0.4 |
| Dark amber | `#ef6c00` | Caution / transitioning / watch | CAUTION, NEW regime, MED/FORMING fit, COMPRESSED vol |
| Red | `#d32f2f` | Adverse / extreme / alert | DEGRADING, EXTREME vol, \|Z\| > 2.5, STRONG DOWN |
| Light red | `#ef9a9a` | Mildly negative / soft | WEAK DOWN, direction −0.4 to 0 |
| Purple | `#8e24aa` | Instability / hazard / fresh | HAZARD, FRESH regime age, regime transition |
| Mid gray | `#616161` | Neutral / normal — DEFAULT | Z within ±1.2, NEUTRAL environment, NOISE autocorr |
| Light gray | `#bdbdbd` | Not applicable / muted | LOW favorability rows |

### Critical rule: LOW favorability is dim gray, not red

LOW Trend-Following Fit in a ranging market is not adverse — it is simply the wrong strategy type for the current environment. Rendering it red would train the operator's eye to read most market conditions as dangerous. Dim gray says "doesn't apply right now." Red says "something is wrong." Confusing these is the most common cosmetic mistake in dashboard design.

This rule applies to all three Fit rows: TF Fit LOW, MR Fit LOW, Breakout Fit LOW all render dim gray, never red.

### Background tinting: alert states only

Three states warrant a tinted background (not just text color):
- HAZARD or FRESH regime age → pale lavender (`#f3e5f5`)
- DEGRADING environment or CAUTION hazard → pale amber (`#fff3e0`)
- Regime Transition true → pale lavender (one-bar)

All other states use white background. Background tinting is the dashboard equivalent of bold-for-alerts. It makes the eye go to alert states first.

### PRIME vs FORMING semantics

Breakout Fit alone uses different label vocabulary (PRIME / FORMING / LOW) instead of (HIGH / MED / LOW). The `col_fit` resolver recognizes both label sets, so all three Fit rows color consistently using the same green / amber / dim-gray palette.

PRIME is operationally rare — ~1% of bars on typical instruments. Treating PRIME as common (e.g., "I see PRIME multiple times per session") indicates either a genuinely high-compression instrument or a calibration drift; investigate via the BB Width % and ATR Ratio diagnostic rows.

---

## 6. Multi-Timeframe Usage Framework

The SSP runs on a single timeframe — the chart's. Multi-timeframe usage is achieved by running the indicator on multiple charts simultaneously, with operators interpreting alignment manually. The adaptive HTF voter handles cross-TF logic *within* a single chart; multi-chart alignment is the operator's overlay on top of that.

### Hierarchy

The recommended hierarchy mirrors traditional trading framework levels:

| Level | Role | Authority |
|---|---|---|
| **Higher TF** (4H, D) | Regime authority | Determines which strategy type is fundamentally appropriate |
| **Middle TF** (15m, 1H) | Setup authority | Identifies setup formation within the higher-TF regime |
| **Lower TF** (5m) | Execution authority | Confirms entry timing |

### Recommended default stacks

| Trading style | HTF | MTF | LTF |
|---|---|---|---|
| Day trade / scalp | 1H | 15m | 5m |
| Swing | D | 4H | 1H |
| Position | W | D | 4H |

### Alignment interpretation

| Pattern | Read | Operational implication |
|---|---|---|
| All three TFs same direction, all SUPPORTIVE | Highest-conviction trend environment | Standard sizing on TF entries |
| HTF + MTF aligned, LTF disagrees | Pullback entry zone | Common; not a problem — the disagreement *is* the opportunity |
| HTF aligned, MTF disagrees | Counter-trend setup forming | Higher risk; HTF will eventually reassert |
| All three TFs disagree | Mixed environment | Stand aside or wait for clarification |
| HTF = `unstable_trend` or `range_high_vol` | Structural override | Disregard MTF setup signals until HTF stabilizes |

### Asymmetric trust

The hierarchy is asymmetric. HTF is rarely wrong about overall regime. LTF is frequently wrong about direction but correct about timing. The middle is the negotiation layer — MTF trumps LTF on direction questions, defers to LTF on entry questions.

When MTF and LTF disagree, trust HTF for bias and LTF for timing.

---

## 7. Operating Playbook

This section documents the practical decision flows for each strategy family. The panel does not generate signals; the operator interprets state and decides.

### Row precedence hierarchy

The 15 core rows are not 15 equal indicators. They are read in priority order:

| Priority | Row(s) | Role |
|---|---|---|
| 1 | Market Regime | Master context — what kind of market is this |
| 2 | Direction (Directional Pressure) | Side hypothesis — which way the structure resolves |
| 2.5 | **Trade Bias** | **Synthesized resolution of priorities 1+2 with hazard / fit overrides applied** |
| 3 | TF Fit / MR Fit / Breakout Fit | Strategy applicability — which engine fits |
| 4 | Environment / Regime Age / Hazard | Permission filter — is now a good time |
| 5 | Vol Regime / ATR Ratio / Z-Score | Supporting context |

The extended layer (when toggled on) is **always** lower priority than any core row.

**Reading discipline:** start at priority 1. If the master context (Regime) reads `unstable_trend` or `range_high_vol`, lower-priority rows are interpreted *within* that context, not independently of it. Operators who treat all 14 rows as equal-weighted indicators consistently misuse the panel — the most common misuse is reading a HIGH Fit row in isolation and ignoring an unfavorable Regime or HAZARD upstream.

The interpretation rule "regime label trumps Fit rows when they disagree" (documented in section 9 and Appendix B Example 5) is a direct consequence of this hierarchy. Priority 1 always overrides priority 3.

**Working through the panel — the standard read order:**

1. *What is this market?* → Market Regime + Trend Label
2. *Which side does it want?* → Direction Score
3. *What is the resolved bias?* → **Trade Bias** (the synthesized answer)
4. *Which strategy family applies?* → TF / MR / Breakout Fit rows
5. *Should I act now?* → Environment + Regime Age + Hazard
6. *What's the supporting context?* → Vol Regime, ATR Ratio, Z-Score

If priority 5 says no, priorities 1–4 are reference information for *next* time, not actionable now. Trade Bias compresses the answer to "which side" — but never to "act now."

### Regime interaction matrix

The 6 Market Regime states each impose different rules on how the rest of the panel should be read. This matrix compresses the per-regime interpretation guidance into one operator artifact:

| Regime | Trust Direction? | Trust Fit rows? | Trade bias | Primary use |
|---|---|---|---|---|
| `trend_expansion` | **High** | **High** | Continuation | TF trades, pullback entries |
| `trend_compression` | **High** | **High** | Continuation | TF trades under contained vol; entries can be aggressive |
| `unstable_trend` | **Low** | **Medium** | Caution | Stand aside on new entries; existing positions reduce |
| `mean_reversion` | **Inverted** | **High** | Fade | MR trades; Direction sign points to fade target, not entry side |
| `range_low_vol` | **Medium** | **Medium** | Breakout prep | Watch for Breakout Fit progression FORMING → PRIME |
| `range_high_vol` | **Low** | **Low** | Stand aside | No strategy family well-supported; wait for regime shift |

**How to read this matrix:**

- **"Trust Direction?"** modulates how much weight the Direction row carries when forming a side hypothesis. *Inverted* (`mean_reversion`) means the direction reading still has informational value but operates opposite the natural reading — the row tells you which side has stretched, and the trade is to fade that side.
- **"Trust Fit rows?"** modulates how much weight TF / MR / Breakout Fit carry. Low trust regimes like `range_high_vol` produce noisy Fit reads that can swing between LOW and MED on every bar without representing meaningful state changes.
- **"Trade bias"** is the regime's natural strategy posture, not a guarantee — it is the type of trade *most likely* to align with the regime, conditional on the rest of the panel cooperating.

**Special interactions:**

- `unstable_trend` + TF Fit HIGH: a known false-positive pattern (see Appendix B Example 5). The regime label trumps; do not trade.
- `mean_reversion` + Direction ±0.2: low directional pressure means the row provides weak fade-target information; rely on Z-Score for stretch read instead.
- `range_low_vol` + Breakout Fit PRIME + Direction ≥ \|0.6\|: the highest-conviction breakout setup the panel produces. The matrix's "medium trust" baseline lifts to high specifically when Breakout Fit confirms.
- Any regime with Regime Age FRESH: the matrix's trust columns apply *only after* confirmation. Inside the 3-bar confirmation window, all rows downgrade to suggestive.

This matrix supersedes the longer prose-form per-regime guidance scattered through earlier sections. When the prose and the matrix disagree on a future amendment, the matrix is authoritative — it is the more compact and easier to maintain.

### Trend-following

**Panel conditions supporting trend trade:**
- Market Regime: `trend_expansion` or `trend_compression`
- Trend Label: STRONG UP or STRONG DOWN
- Direction Score: |0.6| or higher
- Structure Score: ≥ 0.6
- TF Fit: HIGH
- Environment: SUPPORTIVE
- Regime Age: STABLE (≥ 8 bars)
- Market Hazard: CLEAR

**Decision flow:**
1. Confirm Market Regime is trend-type
2. Confirm TF Fit = HIGH (4–5 of 5 criteria met)
3. Verify Hazard ≠ HAZARD (would override)
4. Verify Regime Age = STABLE (avoid fresh regimes)
5. If all clear, the environment supports trend entries. Determine direction from Trend Label.

**Yellow-flag conditions:**
- TF Fit = MED with the rest aligned: marginal. Trade smaller or wait.
- Regime Age = NEW: regime confirmed but not stable. Acceptable for continuation entries, risky for fresh trend entries.
- Vol Regime = EXTREME: trend may be in blowoff phase. Reduce size.

### Mean-reversion

**Panel conditions supporting MR trade:**
- Market Regime: `mean_reversion` or `range_low_vol`
- Direction Score: |0.2| or lower (directionless)
- |Z-Score|: > 1.2 (stretched)
- Autocorr (research): MEAN-REV
- MR Fit: HIGH
- Vol Regime: NORMAL or COMPRESSED (not EXPANDED, not EXTREME)
- Market Hazard: CLEAR or CAUTION (not HAZARD)

**Decision flow:**
1. Confirm Market Regime is range-type or `mean_reversion`
2. Confirm Z-Score is stretched (|Z| > 1.2)
3. Confirm MR Fit = HIGH
4. Verify Vol Regime is not EXPANDED or EXTREME
5. If Hazard = HAZARD, stand aside — extreme stretch is reversion *risk* but also continuation risk
6. Trade direction is opposite of Z-Score sign

**Yellow-flag conditions:**
- Z-Score > 2.5: MR signal but also Hazard trigger. Reduced position warranted.
- Vol Regime transitioning to EXPANDED: MR setup degrading rapidly.

### Breakout stalking

**Panel conditions supporting breakout setup:**
- Vol Regime: COMPRESSED
- ATR Ratio 14/100: < 0.9
- BB Width % (Context layer): < 30
- Z-Score: |Z| < 0.8 (not yet moved)
- Structure Score: rising (visible by watching the row)
- Breakout Fit: PRIME

**Decision flow:**
1. Identify compression: Vol Regime = COMPRESSED, ATR Ratio < 0.9
2. Confirm Z-Score is near zero (price has not yet moved)
3. Watch Breakout Fit progress from FORMING to PRIME
4. PRIME is the alert state. Direction is undetermined until breakout occurs.
5. Set bracket orders or wait for first directional bar to determine side.

**Yellow-flag conditions:**
- Breakout Fit = FORMING with Z-Score > 1.0: setup is partially in motion. May be late.
- Structure Score not improving: compression without coiling. Often resolves into more compression, not breakout.

#### Direction-paired interpretation (when Breakout Fit is PRIME or FORMING)

When the panel reads Breakout Fit = PRIME or FORMING, the Breakout Fit row and Direction row form a **coupled model**:

- **Breakout Fit answers:** does a setup exist?
- **Direction answers:** which way will it resolve?

| Breakout Fit | Direction | Read |
|---|---|---|
| PRIME | ≥ +0.6 | Bullish breakout bias — directional bracket favored upside |
| PRIME | ≤ −0.6 | Bearish breakout bias — directional bracket favored downside |
| PRIME | ±0.2 | Unresolved coil — stand aside, or use symmetric bracket only |
| FORMING | any | Setup not yet confirmed; observe but do not act on direction yet |

This pairing is the intended use of the Direction row in a breakout context — it converts an undirected "setup exists" signal into a directional thesis. **Breakout Fit alone is not actionable; Breakout Fit + Direction together is.**

The reasoning: Breakout Fit's four criteria (BB compressed, ATR contracted, Z near zero, structure improving) describe pre-resolution state but do not encode resolution side. The Direction row encodes accumulated voter pressure across 5 independent estimators. When five voters lean toward one side under compression, the resolution is more likely (not certain) to favor that side.

**What this is not:** it is not a directional signal that breakout *will* occur in that direction. It is a probabilistic bias that, conditional on a breakout occurring, makes one side more likely. Operators who treat PRIME + +0.6 Direction as a guaranteed long are confusing a bias with a forecast.

### "Do nothing" conditions

The panel actively communicates *not* to trade. Recognize these:

- **Market Hazard = HAZARD** — stand aside on new entries. Re-evaluate active positions.
- **Environment = DEGRADING** — reduce activity broadly.
- **Regime Age = FRESH (< 3 bars)** — regime not yet confirmed. Wait.
- **Market Regime = `unstable_trend`** — structure too low for trend trades, direction too high for MR trades. Most strategies fail here.
- **All three Fit rows reading LOW or FORMING** — no strategy type clearly supported. Wait for clarity.

The "stand aside" decision is itself a use of the panel. An operator who never reads "no trade" from the dashboard isn't using it correctly.

### Using SSP for strategy prototyping (research triage)

Beyond live trade qualification, the SSP serves a second high-value role: a **research triage layer** that filters strategy hypotheses *before* they consume Python pipeline cycles. This is one of the SSP's highest-leverage uses and is easy to overlook.

#### The cost-asymmetry argument

Authoring a directive, running Stage 1 backtest, evaluating Stage 4 portfolio fit, and producing a deployable strategy is a multi-day cycle with non-trivial compute cost. A 30-minute panel-replay session can rule out hypotheses that would otherwise consume that cycle.

The SSP is calibrated against the same regime model the Python engine uses. If a strategy's edge is not *visible* at the panel level — that is, if the conditions the strategy depends on do not visually correspond to the panel states the operator predicts — that strategy is unlikely to survive Python validation. The panel is therefore a cheap pre-filter for the expensive pipeline.

#### Workflow

1. **Form a strategy hypothesis.** Example: *"There may be edge in trading XAUUSD pullback entries during expansion regimes."*
2. **Define the panel state the strategy should live in.** Example: TF Fit = HIGH, Market Regime = `trend_expansion`, Z-Score retracing toward zero, Hazard = CLEAR.
3. **Replay several months of chart data with the panel visible.** Step bar by bar through historical price action.
4. **Observe whether the hypothesized panel state actually occurs, and whether the strategy thesis appears to work in those bars.**

#### Triage decisions

| Observation | Decision |
|---|---|
| Hypothesis correlates with the expected panel state, and visible setup is plausible | Strategy worth Python research |
| Expected panel state never occurs | Re-examine hypothesis or instrument selection — the regime the strategy depends on may not exist on this asset |
| Expected panel state occurs but strategy doesn't appear to have an edge | Strategy hypothesis likely flawed; do not waste pipeline cycles |
| Strategy appears to work in panel states beyond the expected ones | Original thesis may be wrong, but a different thesis may be implicit; reformulate before coding |

#### Reference panel-state hypotheses by strategy type

| Strategy type | Panel-state hypothesis to probe |
|---|---|
| Trend-following pullback | TF Fit HIGH + Regime `trend_*` + STABLE + Z-Score retraced toward zero |
| Mean-reversion fade | MR Fit HIGH + Hazard CLEAR or CAUTION + \|Z\| > 1.5 + Vol not EXPANDED |
| Breakout long/short | Breakout Fit PRIME + Vol Regime COMPRESSED + Direction ≥ \|0.6\| |
| Reversal at exhaustion | Vol Regime EXTREME + \|Z\| > 2.5 + Hazard HAZARD |
| Range fade | Regime `range_low_vol` + STABLE + Z-Score reaching opposite extreme |

#### What this is not

This workflow is not a substitute for backtesting. The panel cannot measure expectancy, drawdown, or fill quality. It can only verify whether the *conditions* the strategy depends on are observable — a necessary but insufficient property. Strategies that pass panel triage still need Python validation; strategies that fail it should not advance.

#### Recommended logging

A lightweight notes file alongside the validation log (section 10) makes the triage activity reviewable later:

```
Hypothesis        : <one-line description>
Expected state    : <panel rows expected>
Instruments tried : <list>
Bars observed     : <approximate count>
Verdict           : ADVANCE / RECONSIDER / REJECT
Notes             : <observations that drove the verdict>
```

Strategies that reach Python research with this verdict-trail attached are easier to interpret when results come back from the pipeline — the operator already has a hypothesis-to-evidence chain in place.

---

## 8. Default Settings and Calibration Philosophy

### Stable defaults — rarely change

These defaults encode the architecture and changing them invalidates other components. Treat as fixed unless undertaking a deliberate calibration cycle:

| Parameter | Default | Stability |
|---|---|---|
| LinReg Length | 50 | Stable — matches Python regime model |
| EMA Length | 20 | Stable |
| Regime Confirm Bars | 3 | Stable — matches Python `regime_confirm_bars` |
| ATR Short / Long | 14 / 100 | Stable |
| RV Window / Percentile Window | 20 / 200 | Stable |
| Z-Score Window | 50 | Stable |
| Kalman Q_x / Q_v / R | 0.0001 / 0.001 / 1.0 | Internal — not exposed |

### Calibratable parameters — per asset class

These may need adjustment when applying the panel to non-default asset classes:

| Parameter | Default | When to consider adjustment |
|---|---|---|
| 5th Direction Voter | Kalman | Switch to Donchian if Kalman appears noisy on a specific asset (typically observable on choppy small-cap equities) |
| HTF Mode | Auto | Manual override useful for asset classes with non-standard session structures (e.g., FX vs equities on intraday charts) |
| Display Mode | Core | Increase to Core+Context or Full Research only when needed |

### Tunable thresholds — research parameters

Threshold values inside the resolvers (regime classification cutoffs, Fit point requirements, Hazard triggers) are tuning parameters in principle. In practice they are part of the architecture as currently defined.

If empirical observation suggests a threshold is mis-calibrated:
1. Document the observation (which threshold, what behavior, on which instruments)
2. Treat as a calibration item, not an emergency fix
3. Adjust in the source file with a comment recording the change date and justification
4. Re-validate across the panel's validation protocol (section 10)

### Calibration philosophy

Calibration is a **low-frequency activity**. The panel is not a tunable signal generator. Its outputs are descriptive, not predictive — there is no objective function to optimize against. Threshold adjustments should be rare, justified by observation, and recorded.

If you find yourself wanting to adjust thresholds frequently, the issue is usually elsewhere: misreading a Fit signal as a trade trigger, not understanding the stability layer, or attempting to apply the panel to an asset class for which the architecture is not suited.

---

## 9. Interpretation Guidelines / Failure Modes

### What not to over-interpret

**Direction Score precision.** The score is the average of 5 binary voters and lands at one of 6 discrete values. Reading "Direction = 0.62" as more bullish than "Direction = 0.60" is false precision — both round from the same underlying voter state. The score is meaningful at bucket boundaries, not within them.

**Vol Score numerical value.** The vol score is a percentile ratio. Differences like 0.55 vs 0.60 represent percentile shifts that may or may not correspond to operationally meaningful state changes. Trust the Vol Regime label; the score is informational.

**Single-bar regime transitions.** A Regime Transition flag firing means the 3-bar confirmation window completed *now*. The new regime is freshly stable, not deeply established. Avoid making large position decisions on the transition bar itself; wait for at least 3–5 bars of post-transition stability.

**Breakout Fit FORMING as actionable.** FORMING is observability — *something* is starting to form. It is not a setup. PRIME is the actionable state. Trading on FORMING is anticipation, not execution.

### Common misuse cases

**"The panel is bullish, why is this trade losing?"**
The panel describes regime, not entry quality. A SUPPORTIVE environment does not protect against bad entries within it. The panel is a filter, not an entry system.

**"TF Fit is HIGH so trends always continue?"**
HIGH means the environment supports trend strategies on average. Individual trends still end. The panel does not predict reversals; it characterizes the regime state through which prices currently flow.

**Treating Hazard = CLEAR as permission.**
CLEAR means no specific instability detected. It does not mean "go trade aggressively." It means "no specific reason to be cautious." Combine with the rest of the panel; Hazard alone is not a green-light system.

**Ignoring Regime Age.**
Operators reading Market Regime alone make the most common interpretation mistake. A regime label of `trend_expansion` means very different things at age 1 vs age 30. The Stability label is not optional reading — it gates the rest of the panel.

**Reading the label and ignoring the value.**
The Direction row says "Direction" and "0.6" with green text. The 0.6 carries the actual information; the green text is the same green that would render at 1.0. Both columns matter.

**Treating Trade Bias as an entry trigger.**
`LONG BIAS` does not mean "enter long now." It means: *if* you trade in this regime, the side hypothesis is long. Trade Bias addresses one question (which side) and explicitly does not address timing, stops, sizing, or whether to take the trade at all. The row's compactness makes this misuse tempting — a single-cell "LONG BIAS" reads more authoritatively than a multi-row inference. Resist the compression. The row exists because manual synthesis is error-prone, not because the panel has gained signal-generation capability. **Trade Bias is the most likely row to be misread as a trigger; this is why STAND ASIDE renders red and `unstable_trend` deliberately routes to COIL / UNRESOLVED rather than to a bias.**

### Known failure modes

**Adaptive HTF on illiquid assets.**
Some assets do not have consistent higher-timeframe data (e.g., low-volume crypto, off-hours equities). The HTF voter can return na or stale values.
*Mitigation:* switch HTF Mode to Manual and select a known-liquid HTF.

**Kalman warmup.**
The first ~10 bars of any chart load have meaningless Kalman velocity (covariance not yet at steady state). The Kalman direction voter contributes noise during warmup.
*Mitigation:* do not interpret the panel during the first 10 bars after loading.

**Vol percentile windows on new instruments.**
RV percentile uses a 200-bar lookback. For instruments with less than 200 bars of history, percentile reads are degenerate.
*Mitigation:* ensure ≥ 250 bars of chart history before relying on Vol Score.

**Choppy autocorr on 5m and below.**
Lag-1 log-return autocorrelation becomes noisy at very low timeframes. The MR detection (autocorr < −0.05) can fire spuriously, contaminating mean-reversion regime classification.
*Mitigation:* treat MR-related panel reads with reduced confidence on sub-15m timeframes.

**Pine `request.security` repaints during partial bar.**
While the panel uses `lookahead_off`, intra-bar HTF reads can shift as new HTF bars form. This is inherent to TradingView's `request.security`; not a panel bug.
*Mitigation:* read panel state on bar close, not intrabar.

**Percentile saturation in compressed periods.**
`bb_pct`, `atr_pct`, and `rv_pct` all use `ta.percentrank` over a 200-bar window. When current vol is at-or-below the 200-bar minimum, all three saturate to 0. This is mathematically correct (correctly reports "lowest in window") but loses granularity — extreme compression and merely-lowest-in-window compression both produce 0.
*Mitigation in code:* Breakout Fit criterion 1 was hardened in v2.8 to require `bb_pct < 30 AND atr_ratio < 0.85`, providing absolute corroboration that protects against percentile-saturation false positives. See section 4.5 "Percentile saturation defense" for full rationale.
*Operator-side cross-check:* When percentile rows saturate at 0, consult ATR Ratio 14/100 in the Core Layer to assess actual magnitude of compression. If ATR Ratio is also low (< 0.7), compression is genuine. If ATR Ratio is moderate (> 0.85), the saturation is a lookback-window artifact and any breakout signal should be treated with reduced confidence.

**Unstable_trend with strong Direction Score.**
The TF Fit scoring can read MED (or even HIGH) when direction is strong (4/5 voters), regime age is established, vol is moderate, and Z is contained — but structure is poor. The Market Regime label correctly classifies this as `unstable_trend` to flag low-quality structure. The Fit row alone may be misleading in this case.
*Mitigation:* the regime label trumps the Fit rows when they disagree. See Appendix B Example 5.

### Regime disagreement interpretation

When TF Fit, MR Fit, and Breakout Fit all read LOW or FORMING simultaneously, the environment is genuinely without a favored strategy type. This is not a panel failure — it's an honest read of a transitional or low-information market. The correct response is to stand aside.

When the panel disagrees with the operator's chart read (e.g., "looks like a clear trend to me, but TF Fit says LOW"): pause and investigate. The operator's eye sees the chart; the panel sees a multi-axis decomposition. Disagreement usually means one of:
- The operator is anchored on recent price action; the panel is integrating longer windows
- A criterion the operator overlooked is failing (e.g., regime is fresh, structure is improving but not yet > 0.6)
- The pattern looks like a trend but autocorr suggests it's mean-reverting

Investigation is more valuable than override.

### False precision risks

Composite outputs (Environment State, Market Hazard, the Fit rows) compress multiple criteria into single labels. A label change from CAUTION to CLEAR does not mean the world changed — it means a specific criterion crossed a specific threshold. Use the extended layer to understand which criterion drove the change before reacting to a label flip.

### Diagnostic sanity-checking

When a composite output reads strangely, the extended layer is the inspection tool:

| Symptom | Inspection target |
|---|---|
| Direction Score reads ±0.6 unexpectedly | Full Research → check Kalman Velocity sign + LinReg HTF; one voter has likely flipped against the others |
| Structure Score low despite visible trend | Check R² (LinReg) row; likely the ADX or Chop component is dragging the average |
| Hazard = HAZARD without obvious cause | Check Regime Age row first; FRESH (age < 3) is the most common cause |
| Vol Regime = EXTREME on a calm-looking chart | Check RV %ile and ATR Ratio; if both moderate, the percentile baseline may be calibrated to a quieter window than current |

These are not bug reports — they are the intended use of diagnostic visibility.

### The black-box warning

The SSP exposes its model deliberately. Resist the temptation to treat it as a black-box "is environment good?" oracle. Operators who learn the underlying axis decomposition, voter structure, and composite scoring use the panel substantially better than operators who memorize "green = trade, red = don't." The latter pattern is observable and should be self-corrected.

---

## 10. Validation Protocol

Validation is the workflow for confirming that the panel reads correctly across market conditions before relying on it for live decisions. The protocol below applies for each major calibration change and as a periodic review.

### What to validate

Each change touches a specific layer; validate accordingly.

**Threshold changes** (e.g., trend threshold, Fit point cutoffs):
- Replay across 6 months of recent data on 3+ instruments
- Note frequency of HIGH/PRIME firings — should match expected scarcity
- Verify no obvious mismatches (Fit HIGH on choppy chart, Fit LOW on clean trend)

**Voter changes** (e.g., adding/swapping direction voters):
- Sanity-check direction score distribution — should not over-saturate at ±1
- Verify each voter contributes meaningfully (look at extended-mode diagnostic rows)
- Cross-instrument: confirm change improves classification on multiple asset classes, not just the calibration instrument

**Architecture changes** (new fields, new layers):
- Full validation: replay + live observation + cross-TF consistency
- Document the change rationale
- Re-validate downstream composites (Hazard, Environment) that consume the changed input

### Observation logging approach

For systematic validation, maintain notes:

```
Date / Instrument / TF / Panel state observed
What chart actually did next
Was panel read correct in retrospect?
If not — what was missing or misclassified?
```

A few weeks of these notes — even informally — surface miscalibrations more reliably than algorithmic backtests because the panel's outputs are descriptive (regime label) rather than predictive (signal direction). The validation question is "did this read accurately describe the market state" not "did the signal make money."

### Calibration issue vs redesign trigger

Not every observed mismatch warrants action. Distinguish:

**Calibration issue (threshold adjustment):**
- Single criterion firing too often or too rarely
- Label boundary slightly off (e.g., COMPRESSED firing at 0.30 should fire at 0.25)
- Stable improvement: change a threshold, document, re-validate

**Redesign trigger (architecture review):**
- A composite never fires when expected, or always fires when not expected
- A criterion is structurally redundant or structurally absent
- A row's information has migrated into a different layer
- The same calibration request recurs across multiple sessions

The first calls for a thresholds-only PR. The second calls for a feasibility report (analogous to v2.0–v2.3 documents) before code changes.

### What should never trigger redesign

- One bad trade — sample size of one is meaningless against descriptive state outputs
- An operator's gut feel disagreeing with the panel — investigate first, do not modify the panel
- Performance of strategies executed *based on* the panel — the panel is decision-support, not a strategy

---

## 11. Future Extensions (Appendix — Non-Core)

These items are documented for awareness, not as roadmap commitments. None are required for the panel to function as designed.

### MTF alignment summary

A possible future enhancement: a single row aggregating the panel's read across HTF/MTF/LTF charts, computed via cross-chart references. Would require multi-chart data exchange (Pine table sharing, alerts, or external orchestration). Cost: significant complexity. Benefit: replace manual cross-chart alignment reading.

*Status:* speculative. Manual alignment works adequately.

### Asset-class profiles

Hypothesis: thresholds calibrated for Gold may be miscalibrated for FX or BTC. A possible enhancement: an "Asset Profile" input that swaps threshold sets based on user selection.

*Concern:* introduces calibration debt. Each profile must be maintained, validated, and may diverge over time. The current single-profile approach forces the operator to acknowledge cross-asset miscalibrations explicitly when they appear.

*Status:* deferred. Current single-profile defaults work across the project's primary instruments (XAUUSD, FX majors, BTC, US indices) with acceptable cross-instrument variance.

### Probabilistic regime confidence

The current 6-state regime classifier is hard-thresholded. A probabilistic version would output "trend_expansion: 0.65, unstable_trend: 0.30, ..." reflecting axis proximity to thresholds. Useful for soft gating in strategies; less useful for visual dashboard reading.

*Status:* would belong in Python first if implemented. SSP would mirror.

### Portfolio-level resonance

Beyond a single-instrument panel: a portfolio-level resonance dashboard reading SSP state across all positioned instruments simultaneously, summarizing portfolio-wide environment quality.

*Status:* belongs in TS_Execution or as a separate Python tool, not in TradingView.

### Breakout Fit criterion #2 orthogonality refinement (deferred — observation phase)

Following the v2.8 hardening of criterion #1 to require `bb_pct < 30 AND atr_ratio < 0.85`, criterion #2 (`atr_ratio < 0.9`) now logically depends on criterion #1: any state firing criterion #1 also fires criterion #2. The 4-of-4 PRIME vote is structurally a 3-of-3 + 1 carrier, with criteria 1 and 2 sharing the atr_ratio metric.

Two replacement candidates were architecturally evaluated:

| Candidate | Adds dimension | Orthogonal to #1 | Orthogonal to #4 (structure) | Notes |
|---|---|---|---|---|
| **Bar Range Ratio Persistence** (recommended) | Duration | High — different timescale, different data path | High — uses bar HL not regression fit | Failure modes (post-shock quiet, lower-TF noise) addressable in count-based formulation |
| **Linear Regression Residual Dispersion** | Refined tightness | Moderate — both are variance measures | Low — correlates with R² in structure_score | Trend-hugging false-compression risk; criterion #3 protects PRIME but not FORMING |
| Keep ATR duplicate | None | — | — | Acknowledged 3-of-3 + carrier; stable, suboptimal |

**Status: deferred to baseline observation phase.** No empirical evidence of false PRIME or false FORMING firings caused by the orthogonality compression. The concern is structural, not behavioral. Action requires observed pattern of misclassification across multiple instruments, not single anomalies.

**If action becomes warranted**, the recommended path is Bar Range Ratio Persistence in count-based formulation (e.g., `≥12 of last 20 bars where (high − low) / ema(high − low, 20) < threshold`), with formulation parameters designed in a separate analysis cycle. The Z-score-as-hidden-protection structure (Section 4.5) carries part of the load that an orthogonal criterion #2 would otherwise carry; this should be re-validated if criterion #2 is replaced.

This entry exists so that future-you knows the analysis was done, the recommendation reached, and the deliberate decision was to observe before acting.

---

## Appendix A — One-Page Operator Quick Reference

```
┌─────────────────────────────────────────────────────────────┐
│  SYSTEM STATE PANEL — QUICK REFERENCE                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  REGIME CORE (rows 1-6)                                      │
│    Market Regime → THE label. 6 states.                      │
│    Trend Label   → directional conviction, human-readable    │
│    Direction     → -1.0 to +1.0; buckets at ±{0.2, 0.6, 1.0} │
│    Trade Bias    → SYNTHESIZED bias label (see below)        │
│    Structure     → 0-1; > 0.6 = clean                        │
│    Volatility    → 0-1; position in vol distribution         │
│                                                              │
│  VOL & STRETCH (rows 7-9)                                    │
│    Vol Regime    → COMPRESSED / NORMAL / EXPANDED / EXTREME  │
│    ATR Ratio     → < 1.0 contracting, > 1.0 expanding        │
│    Z-Score       → > 1.5 stretched, > 2.5 extreme            │
│                                                              │
│  STRATEGY SUITABILITY (rows 10-12)                           │
│    TF Fit        → HIGH = trend trade environment            │
│    MR Fit        → HIGH = mean-reversion environment         │
│    Breakout Fit  → PRIME = coiled spring (rare; ~1% of bars) │
│                                                              │
│  TRADE QUALIFICATION (rows 13-15)                            │
│    Environment   → SUPPORTIVE / NEUTRAL / DEGRADING          │
│    Regime Age    → "X bars / FRESH|NEW|STABLE"               │
│    Market Hazard → HAZARD / CAUTION / CLEAR                  │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  COLOR GRAMMAR (system-level, fixed):                        │
│    Green   confirmed / favorable                             │
│    Yellow  caution / transitioning                           │
│    Red     adverse / extreme                                 │
│    Purple  hazard / fresh                                    │
│    Gray    neutral / normal (most cells, most of the time)   │
│    Dim Gray inapplicable (LOW favorability — NOT red)        │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  ROW PRECEDENCE (read top-down, do not flatten)              │
│    1. Market Regime         (master context)                 │
│    2. Direction             (side hypothesis / break bias)   │
│    2.5 Trade Bias           (synthesized resolution)         │
│    3. TF / MR / BO Fit      (which strategy applies)         │
│    4. Environment / Age / Hazard (permission filter)         │
│    5. Vol / ATR / Z         (supporting context)             │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  TRADE BIAS LABELS                                           │
│    LONG BIAS / SHORT BIAS    trend regime + direction sign   │
│    FADE LONG / FADE SHORT    MR regime + Z-sign-inverted     │
│      (label = trade side, NOT side being faded)              │
│    UP / DOWN BREAK BIAS      PRIME + Direction ≥ |0.6|       │
│    WATCH UP / WATCH DOWN     PRIME + |D|<0.6 + Kalman sign   │
│    BREAK WATCH               PRIME, Kalman ≈ 0 (rare)        │
│    COIL / UNRESOLVED         ambiguous (incl. unstable_trend)│
│    STAND ASIDE               HAZARD or range_high_vol only   │
│                                                              │
│    Color/bg encodes state:                                   │
│      green text/white bg     committed bias, high conf       │
│      yellow text/white bg    committed bias, med conf        │
│      yellow text/AMBER bg    WATCH state (rare, watching)    │
│      gray text/white bg      COIL informational              │
│      red text/LAVENDER bg    STAND ASIDE / HAZARD            │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  GO / NO-GO QUICK CHECK                                      │
│    Trade Bias = STAND ASIDE    → DO NOT TRADE                │
│    Trade Bias = COIL/UNRESOLVED→ NO BIAS — WAIT              │
│    Hazard = HAZARD             → STAND ASIDE                 │
│    Environment = DEGRADING     → REDUCE ACTIVITY             │
│    Regime Age = FRESH          → WAIT FOR CONFIRMATION       │
│    All Fits = LOW/FORMING      → NO STRATEGY FAVORED         │
│                                                              │
│    TF Fit HIGH + Regime trend_* + STABLE + CLEAR → TF GO     │
│    MR Fit HIGH + Z stretched + Vol not Expanded  → MR GO     │
│    BO PRIME + Vol COMPRESSED + Z near 0          → BO GO     │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  INTERPRETATION RULES                                        │
│    1. Market Regime trumps Fit rows when they disagree       │
│    2. Regime Age gates everything — FRESH is unconfirmed     │
│    3. Direction is BREAK BIAS, not just trend slope          │
│    4. Breakout Fit + Direction = coupled model (setup+side)  │
│    5. Trade Bias is SIDE HYPOTHESIS, not entry trigger       │
│    6. unstable_trend → COIL / UNRESOLVED (ambiguity, not veto)│
│    7. Composites compress info — flip = single criterion     │
│       crossed; check extended layer for which one             │
│    8. Standing aside is a valid panel read, not a failure    │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  KNOWN NON-USES (do NOT use SSP for):                        │
│    • Entry trigger generation                                │
│    • Parameter optimization                                  │
│    • Strategy expectancy prediction                          │
│    • Replacing backtests                                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Appendix B — Interpretation Examples (Hypothetical)

### Example 1: Clean trend, ride it

```
Market Regime    | trend_expansion
Trend Label      | STRONG UP
Direction        | 0.60
Trade Bias       | LONG BIAS                 (green — high confidence)
Structure        | 0.71
Volatility       | 0.62
Vol Regime       | EXPANDED
ATR Ratio 14/100 | 1.18
Z-Score          | 1.10
TF Fit           | HIGH
MR Fit           | LOW
Breakout Fit     | LOW
Environment      | SUPPORTIVE
Regime Age       | 22 bars / STABLE
Market Hazard    | CLEAR
```

**Read:** Strong uptrend, established (22 bars), structure clean, vol expanding (typical of healthy trends), no hazard. TF Fit confirms environment supports trend trades. Z-Score moderately positive but within normal range — price has moved but is not exhausted. Trade Bias resolves to LONG BIAS at high confidence (priority 4 cascade: trend regime + Direction > 0; STABLE age + TF Fit HIGH lifts to high confidence).

**Action:** Trend-following entries on pullbacks supported. Standard sizing.

---

### Example 2: Stretched at the top

```
Market Regime    | trend_expansion
Trend Label      | STRONG UP
Direction        | 0.60
Trade Bias       | STAND ASIDE               (red, lavender bg — hard veto)
Structure        | 0.65
Volatility       | 0.85
Vol Regime       | EXTREME
ATR Ratio 14/100 | 1.42
Z-Score          | 2.80
TF Fit           | MED
MR Fit           | LOW
Breakout Fit     | LOW
Environment      | DEGRADING
Regime Age       | 18 bars / STABLE
Market Hazard    | HAZARD
```

**Read:** Same uptrend as Example 1, now in blowoff phase. Z reaching 2.80 + Vol EXTREME + ATR ratio 1.42 indicates exhaustion or climax. Hazard fires on multiple criteria. Trade Bias resolves to STAND ASIDE via priority 1 (HAZARD active) — overriding the directional pressure that would otherwise produce LONG BIAS. This is the resolver behaving correctly: high direction conviction is *not* actionable when hazard is elevated.

**Action:** Do not initiate new trend longs. If holding existing, consider partial exit. Wait for vol to normalize before re-engaging.

---

### Example 3: Coiled spring (low directional pressure → WATCH state)

```
Market Regime    | range_low_vol
Trend Label      | WEAK DOWN
Direction        | -0.20
Trade Bias       | WATCH DOWN                (yellow on amber — PRIME watching, soft bearish)
Structure        | 0.42
Volatility       | 0.18
Vol Regime       | COMPRESSED
ATR Ratio 14/100 | 0.78
Z-Score          | 0.30
TF Fit           | LOW
MR Fit           | LOW
Breakout Fit     | PRIME
Environment      | NEUTRAL
Regime Age       | 14 bars / STABLE
Market Hazard    | CLEAR
```

**Read:** Textbook breakout setup. Range with low vol, established (14 bars), bands compressed, ATR contracted, price near equilibrium (Z = 0.30), structure improving over the smoothed window. Breakout Fit PRIME = all 4 criteria met. TF and MR both LOW — neither approach is currently favored.

**Trade Bias resolves to WATCH DOWN** via priority 3: Breakout PRIME fires, Direction = −0.20 is below the ±0.6 commitment threshold, so the resolver enters the inner WATCH branch. Kalman velocity (assumed negative on bearish-leaning compression) breaks the tie → WATCH DOWN. The yellow text on amber background visually distinguishes this from gray COIL / UNRESOLVED — operator sees "rare setup present, soft bearish lean" rather than "no setup."

**Action:** Breakout-stalk mode with downside bias. Operator may deploy an asymmetric bracket favoring the short side, or use a symmetric bracket with the awareness that Kalman is leaning bearish. Watch for Direction Score to strengthen — if it shifts to ≤ −0.6 while PRIME persists, Trade Bias upgrades to DOWN BREAK BIAS (committed signal, green). If PRIME drops to FORMING, Trade Bias falls through to priority 5 → COIL / UNRESOLVED.

---

### Example 4: Fresh transition — wait

```
Market Regime    | trend_compression
Trend Label      | STRONG UP
Direction        | 0.60
Trade Bias       | STAND ASIDE               (red, lavender bg — HAZARD veto)
Structure        | 0.65
Volatility       | 0.40
Vol Regime       | NORMAL
ATR Ratio 14/100 | 0.95
Z-Score          | 0.40
TF Fit           | MED
MR Fit           | LOW
Breakout Fit     | FORMING
Environment      | NEUTRAL
Regime Age       | 2 bars / FRESH
Market Hazard    | HAZARD
```

**Read:** Just-confirmed trend regime (only 2 bars old). Direction is strong (0.60 = 4/5 voters), structure is good (0.65), vol is moderate (NORMAL). But Regime Age = FRESH triggers HAZARD via the "regime age < 3" criterion. TF Fit reads MED rather than HIGH because the `regime_age > 5` criterion fails. **Trade Bias resolves to STAND ASIDE** via priority 1 (HAZARD active) — even though the trend regime + Direction would otherwise produce LONG BIAS at priority 4. The resolver correctly suppresses bias on a regime that hasn't yet confirmed.

**Action:** Stand aside on new entries. Watch for regime to age past 3 bars before treating as actionable. Once age reaches 3+, HAZARD lifts (assuming vol and Z stay contained), and Trade Bias should upgrade to LONG BIAS at medium confidence.

---

### Example 5: Unstable trend with HAZARD — regime + hazard veto

```
Market Regime    | unstable_trend
Trend Label      | STRONG DOWN
Direction        | -0.60
Trade Bias       | STAND ASIDE               (red, lavender bg — HAZARD veto)
Structure        | 0.41
Volatility       | 0.85
Vol Regime       | EXTREME
ATR Ratio 14/100 | 1.45
Z-Score          | -2.10
TF Fit           | MED
MR Fit           | LOW
Breakout Fit     | LOW
Environment      | DEGRADING
Regime Age       | 12 bars / STABLE
Market Hazard    | HAZARD
```

**Read:** Direction is decisive (4/5 voters bearish) but structure is weak (0.41) — so the regime classifies as `unstable_trend` rather than `trend_*`. Vol is extreme, Z is exhausted. Hazard fires on vol = EXTREME. TF Fit reads MED. **Trade Bias resolves to STAND ASIDE** via priority 1 (HAZARD active). Note that even *without* HAZARD, this example would route to COIL / UNRESOLVED (priority 5) because `unstable_trend` is no longer in the hard-veto set — it falls through to ambiguity. The HAZARD here is what produces STAND ASIDE; the unstable regime alone would not.

**Action:** Stand aside. The HAZARD is what provides the hard-veto signal. The `unstable_trend` label adds context (poor structure under directional pressure) but does not by itself prevent a bias read.

### Example 6: Unstable trend without hazard — ambiguity, not veto

```
Market Regime    | unstable_trend
Trend Label      | STRONG DOWN
Direction        | -0.60
Trade Bias       | COIL / UNRESOLVED         (gray — informative ambiguity)
Structure        | 0.45
Volatility       | 0.55
Vol Regime       | NORMAL
ATR Ratio 14/100 | 1.05
Z-Score          | -1.10
TF Fit           | MED
MR Fit           | LOW
Breakout Fit     | LOW
Environment      | NEUTRAL
Regime Age       | 14 bars / STABLE
Market Hazard    | CLEAR
```

**Read:** Same regime label as Example 5 (`unstable_trend`) but vol is contained (NORMAL), Z is moderate, hazard is CLEAR. **Trade Bias resolves to COIL / UNRESOLVED** via priority 5 — `unstable_trend` is not in the hard-veto set and does not match priorities 2 (not MR), 3 (no PRIME), or 4 (regime not in trend_expansion/trend_compression). The panel correctly reports informative ambiguity rather than overriding to STAND ASIDE.

This example demonstrates the design choice documented in section 4.9: **`unstable_trend` is informative, not adverse**. The operator sees gray COIL / UNRESOLVED — "I cannot resolve a clear bias here" — without the panel invoking the strongest stand-aside vocabulary. Reserving STAND ASIDE for HAZARD and `range_high_vol` keeps it rare and meaningful.

**Action:** Wait for the regime to either confirm into `trend_compression` (structure improves) or roll into `range_*` (direction fades). The panel is honestly reporting that no actionable bias exists; respect that read.

---

## Document Maintenance

This document should be updated when:
- The panel architecture changes (new layers, new rows, removed rows)
- Threshold values change after deliberate calibration
- A new failure mode is discovered and validated
- A future extension graduates from speculative to implemented

This document should *not* be updated for:
- Single-instance interpretation observations
- Operator preference changes
- Threshold experiments not yet validated

The companion code file is [`indicators/System State Panel.txt`](System%20State%20Panel.txt). The Python engine reference is [`engines/regime_state_machine.py`](../engines/regime_state_machine.py). Both must remain consistent with this document.

**End of document.**
