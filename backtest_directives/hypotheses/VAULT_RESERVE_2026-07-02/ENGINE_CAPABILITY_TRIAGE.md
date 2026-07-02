# Reserve Engine-Capability Triage — VAULT_RESERVE_2026-07-02

**Living document.** Records, per reserve hypothesis, whether its **exit/stop
design is buildable on the current engine today** (`rule_build_required: true`)
or would need engine work first (**`engine enhancement required`**). Update a
row's Status when a hypothesis is authored / tested / retired; append to the
Update Log at the bottom. Keep the verdict grounded in the capability matrix,
not memory.

- **Canonical capability matrix (the authority this doc applies):**
  [`../../../outputs/system_reports/02_engine_core/ENGINE_EXIT_STOP_CAPABILITY_MATRIX_v1_5_11_2026-07-02.md`](../../../outputs/system_reports/02_engine_core/ENGINE_EXIT_STOP_CAPABILITY_MATRIX_v1_5_11_2026-07-02.md)
- **Reserve contents + rationale:** [`README.md`](./README.md)
- **Engine assessed:** v1.5.11 (FROZEN), single-asset `execution_loop`. Basket /
  cointegration ideas run on the recycle-rule layer — a **separate exit surface
  the matrix does not cover** (flagged per-row below).

---

## Headline (as of 2026-07-02)

**0 of 22 hypotheses require exit-side engine enhancement.** Every shortlisted
exit design is buildable on v1.5.11. The gates that remain are orthogonal to
exits — indicator modules, the basket/recycle-rule path, and cost exposure.

The one genuine pre-authoring **exit** question is NOISE_AREA's trail
monotonicity (below). Everything else is unambiguously supported.

**Exit-mechanism legend** (maps to the matrix rows):
`SIG` = signal exit (`check_exit`, Native) · `TIME` = time/session/EOD exit
(`check_exit`, Native) · `STOP` = single fixed / catastrophic stop (Native entry
bracket) · `PART1` = single partial / scale-out (Native, once) · `BE` =
break-even move (Emulated, `check_stop_mutation`) · `TRAIL` = monotone trailing
stop (Emulated, `check_stop_mutation`).

---

## Triage table

| # | Hypothesis | Exit/stop spec | Mechanism | Exit verdict | Non-exit gate | Status |
|---|---|---|---|:---:|---|---|
| 1 | BTC_TOD_SEASONALITY | 21:00→23:00 window | TIME | ✅ rule_build | intraday cost-mirage | Reserved |
| 2 | CASEY_C_MR_IDX | `uc>75` / exit-next-close | SIG/TIME | ✅ rule_build | — | Reserved |
| 3 | CHANNEL_TREND_LONGONLY | exit-to-flat < Donchian(40) | SIG | ✅ rule_build | — | Reserved |
| 4 | DMA_STRETCH_BAKEOFF | revert-to-SMA | SIG | ✅ rule_build | — | Reserved |
| 5 | DOJI_RANGE_POSITION | direction-confirmation | SIG | ✅ rule_build | — | Reserved |
| 6 | DOUBLE7_MULTI | close > 7-day high | SIG | ✅ rule_build | — | Reserved |
| 7 | EMA_STACK_ADX_SWING | 2×ATR stop → half-off @3×ATR → BE → 2×ATR trail | STOP+PART1+BE+TRAIL | ✅ rule_build ¹ | — | Reserved |
| 8 | GBP_SHORTBIAS_OSC | 10-bar time exit | TIME | ✅ rule_build | — | Reserved |
| 9 | KC_BANDS_MR_IDX | close>upper OR 5-bar cap | SIG+TIME | ✅ rule_build | — | Reserved |
| 10 | NAS100_MIDNIGHT_BREAKOUT | EOD flat | TIME | ✅ rule_build | intraday cost-mirage | Reserved |
| 11 | NQ_DUAL_SUPERTREND_1H | fast SuperTrend flips red | SIG | ✅ rule_build | supertrend indicator (landed `ff2077c1`) | Reserved |
| 12 | ORB_SESSION_FX | end-of-session | TIME | ✅ rule_build | — | Reserved |
| 13 | QUANTITATIVO_MR_COMPOSITION | close>prior-high + SMA300 regime stop | SIG×2 | ✅ rule_build | — | Reserved |
| 14 | R3_FILTER_BAKEOFF | RSI2>70 OR 5-bar | SIG+TIME | ✅ rule_build | — | Reserved |
| 15 | THREE_BAR_PATTERN_CENSUS | fixed-horizon | TIME | ✅ rule_build | — | Reserved |
| 16 | TWO_BAR_REVERSAL_FX_DAILY | first-profitable-close OR 10-bar | SIG+TIME | ✅ rule_build | — | Reserved |
| 17 | VOLFILTER_BAKEOFF_MR_IDX | inherits idea 69/70 MR exits | SIG/TIME | ✅ rule_build | — | Reserved |
| 18 | MOMO_BREAKOUT_MR_COMPLEMENT | ROC momentum + composite arm | SIG | ✅ rule_build | composite-portfolio path | Reserved |
| 19 | NOISE_AREA_INTRADAY_MOMO | `trail max(VWAP, band)` + cash-close-flat | TRAIL+TIME | ⚠️ conditional ² | VWAP + ToD-envelope indicators; 5M cost | Reserved |
| 20 | COINT_EXIT_OVERLAYS | fixed time exit + catastrophic stop | TIME+STOP | ✅ rule_build ³ | **basket/recycle-rule engine** (matrix N/A) | Reserved |
| 21 | GSR_METALS_RV | opposite-cross + bar-timeout | SIG+TIME | ✅ rule_build ³ | **basket/RV engine** (matrix N/A) | Reserved |
| 22 | IBS_MINMAX_BASKET | hold → next-close | TIME | ✅ rule_build ³ | **cross-sectional basket engine** (matrix N/A) | Reserved |
| — | DONCHIAN_4020_BASKET | close through opposite 20-bar channel | SIG | ✅ rule_build ³ | basket/per-symbol engine (matrix N/A) | Reserved |

*(24 tracked YAMLs = 22 numbered hypotheses above + DONCHIAN + README; VOLFILTER
/ R3 / CASEY carry multiple filter arms under one id.)*

### Footnotes / conditional items

1. **EMA_STACK — flagged "partial-close capability check" resolves GREEN.**
   `half off @3×ATR` is a **single** scale-out (Native, once) followed by BE +
   monotone trail (Emulated). Fully supported. **Constraint:** it must stay a
   *single* partial — if the design grows to laddered/multiple scale-outs it
   flips to `engine enhancement required` (the `partial_taken` once-per-trade
   lock, matrix §Partial close).

2. **NOISE_AREA — the one open exit question.** A monotone trailing stop is
   Emulated/supported. But `max(session_vwap, current_band)` *computes* a level
   that can DECREASE; if the source intends the stop to be able to **loosen**,
   that is non-monotone → `engine enhancement required` (matrix trigger #2). If
   it is a standard one-way ratchet, it is `rule_build`. **Pin the trail
   semantics before authoring.** Independent of that, its real blockers are
   indicator infra (session-VWAP + time-of-day envelope modules) and the 5M
   cost-mirage exposure.

3. **Basket / recycle-rule ideas.** Exits are simple (signal / time /
   catastrophic) and buildable, but authored in a **recycle rule**, not
   `strategy.py`, and run on the basket/cointegration engine — whose exit
   capabilities are NOT the single-asset matrix. Re-triage against the basket
   engine surface at authoring time.

---

## How to use

- **Before authoring a directive from a reserve hypothesis:** read its row. If
  ✅ rule_build → proceed to `/generate-directives` (exit is not a blocker;
  handle any non-exit gate listed). If ⚠️ conditional → resolve the flagged
  question first. If a future edit introduces laddered partials, non-monotone /
  intrabar stops, or multiple TP targets → re-classify as `engine enhancement
  required` and do NOT test until the engine supports it (the fail-closed
  `partial_taken` lock + monotone gate would silently mis-model it).
- **Keep it living:** update the Status column (Reserved → Authored → Tested →
  Retired) and append to the Update Log whenever a hypothesis moves or a
  re-assessment changes a verdict.

---

## Update log

| Date | Change |
|---|---|
| 2026-07-02 | Initial triage of all 22 reserve hypotheses against the v1.5.11 exit/stop capability matrix. Verdict: 0 require exit-engine enhancement; NOISE_AREA conditional on trail monotonicity; basket ideas flagged for basket-engine re-triage. |
