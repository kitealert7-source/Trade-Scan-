# Experiment 1 (Discovery) — Bollinger-on-Absolute Adaptive-Width Trigger

**Status: COMPLETED — verdict settled 2026-06-15 (corpus commit `fc30f0c4`), formalized 2026-06-16.**
The additive rule patch was applied and the full cohort run as **three arms × 497 pairs**
(475–476 `is_current` rows/arm in `cointegration_sheet` after tainted/thin drops). Verdict
reproduced from `run_id`-stamped ledger artifacts (Invariant #10 satisfied) — see **§0 Result**.
The "QUEUED — NOT RUN" framing in §§1–7 is preserved as the original design record.

Authored from an adversarially-verified draft (workflow `bb-adaptive-trigger-draft`,
corrections W1–W7) + the operator-confirmed control artifact.

---

## 0. RESULT — verdict (ledger-confirmed)

Three arms × 497-pair cohort, all uncharged `engine_abi.v1_5_9` (uniform stamp; within-batch
deltas valid). Corrected re-run **after** the `_instantiate_rule` fixed-z wiring fix (`374b061a`);
tainted pre-fix runs were **deleted** (497 authored → 475–476 `is_current`/arm).

| Arm | trigger | median Ret/DD | median trades | blowups (DD ≥ 50% stake) | verdict |
|---|---|---|---|---|---|
| **FXD25** | fixed `\|z\| > 2.5` (control) | 0.000 | 32 | 20 | baseline |
| **BBK20** | adaptive `k=2.0` (generic) | +0.116 | 62 (~1.94×) | 30 | **REJECT** — over-trades, blowups worse |
| **BBK25** | adaptive `k=2.5` (level-matched) | +0.064 | 42 (~1.3×) | 17 | **ACCEPT (conditional)** — blowups cut, no DD penalty |

**Conclusion.** The generic textbook band (`k=2.0`) **FAILS**: the looser ~2.0 average fires
~1.94× more trades and makes blowups *worse* (20→30) — the predicted "trade-count inflation"
failure mode. The **level-matched** band (`k=2.5`) is the operator-kept winner: it trims the
fat-tail blowups (20→17) with a modest Ret/DD uplift and **no DD penalty**, confirming the core
hypothesis *only when the level is held fixed* (you cannot also loosen the average level).
Carry-forward = **Exp 2 (calibration)**, OPEN / optional.

**Caveats.** Uncharged `v1_5_9` → absolute net% is spread-optimistic (deltas valid; engine-stamp
consolidation is the separate in-progress chip `task_edc22e4d`). On charged `v1.5.10` the baseline
edge sits *inside* the spread, so this is **blowup-reduction, not net-of-cost profitability**. Effect
is modest (3 fewer blowups of ~475 pairs). Nothing promoted to production (patch additive/default-off).
Decision recorded in `backtest_directives/hypotheses/BB_ADAPTIVE_WIDTH_V1.yaml` (`outcome: REJECT`
for the registered generic variant + conditional accept of the level-matched sibling).

---

## 1. Hypothesis & motivation

- **Bollinger-on-*price* ≡ the z-score.** Touch upper/lower band ⇔ `z = ±k`; `%B = z/2k + ½`;
  revert-to-middle-band ⇔ `z = 0` (= the existing z-cross exit). No new mechanism, **no fat-tail fix.**
- **The genuinely different idea (operator):** a σ-adaptive *width* on the **z-score series itself** —
  band = `±k·σ_M(z)`, **mid fixed at 0** (absolute mode; NO mean-detrend). The band **widens when z's
  local volatility spikes** (= the cointegration spread breaking/trending) → **withholds entry into the
  breakdown**, where a fixed `|z|>2.5` would fire into it. This targets the **fat-tail / blowup**
  constraint that neither fixed-z nor BB-on-price addresses.
- **Grounding (our research):** on v1.5.10 the edge lives *inside the spread* (median net% +0.17 → −2.37
  once charged; only 7/476 pairs robust — `project_cointegration_baseline_v1510_spread_verdict`).
  **Blowup-safety is the binding constraint.** So the test is judged on whether adaptivity **cuts
  blowups net of cost** — not on adding trades.

---

## 2. Design (Exp 1 = Discovery; generic, un-tuned)

| | CONTROL (exists) | TEST (to build) |
|---|---|---|
| z | absolute, N30 | absolute, N30 |
| mid | 0 | 0 |
| trigger | `\|z\| > 2.5` (fixed, Z25) | `\|z\| > k·σ_M(z)` (adaptive) |
| k, M | — | **k=2.0, M=20** (textbook, un-tuned) |
| exit | zcross (z=0) | zcross (z=0) |
| sizing / engine | granular_parity / **v1.5.10** | granular_parity / **v1.5.10** |

- **CONTROL = the EXISTING Z25 baseline run 2026-06-14.** Already `run_id`-stamped; **reused as-is, not
  regenerated.** Confirmed artifact: `90_PORT_ETHUSDGBPAUD_15M_COINTREV_V3_L30_GP_ZCRS_Z25__E240925`,
  **run_id `28e7277b05881ff25a591bb5`**, `z_entry: 2.5`, `entry_mode: absolute`, `n_window: 30`,
  rule `pine_ratio_zrev_v1_zcross@1`, **engine 1.5.10**.
- **TEST built by CLONING each control directive + flipping `adaptive_width=True`** (+ `_ADP` tag) — this
  **guarantees identical pairs and per-pair windows** (true apples-to-apples; honors
  `[[feedback_test_window_must_match_signal_class]]` by construction). **No generator change needed.**
- **The ONLY functional delta** is the band (`k·σ_M(z)` vs fixed `2.5`). Same rule/exit/sizing/pairs/
  windows/engine.

### Sequencing (operator-set falsification order)
- **Exp 1 first, with COMPLETELY GENERIC values (k=2, M=20).** If a generic, un-tuned adaptive band beats
  the hand-tuned fixed 2.5, the concept has merit *despite a tuning handicap*. If it needs calibration to
  win, the edge is in the tuning, not the concept.
- **Exp 2 (Optimization) is CONTINGENT on Exp 1 surviving.** Only then explore the calibrated/normalized
  threshold `thr_t = 2.5·σ_M(z)/mean(σ_M(z))` (level-matched), or tune k/M.

### Interpretation note (read the result carefully)
BB(20,2) averages a band of ~2.0 (k=2 on unit-variance z) — **looser** than 2.5, so the two outcomes are
asymmetric:
- **WIN = decisive** (won with a looser average, no tuning — purely on adaptive timing, the band inflating
  above 2.5 exactly during breakdowns).
- **LOSS = softer** — could be the looser ~2.0 average inflating trade count (→ more blowups, per threshold
  research), not the adaptivity. On a loss, read **trade count + whether blowups landed in episodes where
  the band actually widened** to distinguish "adaptivity useless" (real kill) from "just ran looser" (soft
  park → revisit in Exp 2). Prevents a false-negative kill.

### Metrics (from `run_id` artifacts only)
blowup count · realized_net% · Ret/DD · max DD · **trade count**. Compare **TEST − CONTROL per pair on
matched windows**. v1.5.10 net% is spread-inclusive.

---

## 3. Implementation — additive rule patch (apply at implement-time)

`tools/recycle_rules/pine_ratio_zrev_v1.py` — **PARENT only** (the `_zcross` variant inherits the band via
`super()._attach_z_r`). **No edit** to `pine_ratio_zrev_v1_zcross.py`, `ratio_hedged_spread_zscore.py`, or
`recycle_rules/__init__.py`. **Additive, default-off → `adaptive_width=False` is byte-identical to today's
corpus** (verifier-confirmed). **PROTECTED INFRA (Invariant #6) — needs operator approval at apply-time.**

**1a — dataclass fields** (after `target_notional_per_leg_usd`):
```python
    # --- Adaptive Bollinger-width entry (Exp1, 2026-06-15; default OFF) ---
    # When True AND entry_mode == "absolute", the fixed +/- z_entry band is
    # replaced by an adaptive band on the z-series: entry when |z| crosses
    # k*sigma_M(z), sigma_M = rolling std(z, M). Mid stays 0 (no mean-detrend).
    # Generic/un-tuned: k=2.0, M=20. Default False => corpus byte-identical.
    adaptive_width: bool = False
    bb_k: float = 2.0
    bb_m: int = 20
```

**1b — validation** (`__post_init__`, after the `z_entry <= 0` block):
```python
        if self.adaptive_width:
            if self.entry_mode != "absolute":
                raise ValueError("adaptive_width=True requires entry_mode='absolute'.")
            if self.bb_k <= 0:
                raise ValueError(f"bb_k must be > 0, got {self.bb_k!r}.")
            if self.bb_m < 2:
                raise ValueError(f"bb_m must be >= 2, got {self.bb_m!r}.")
```

**1c — warmup** (`required_warmup_bars`; the `+bb_m` is a conservative cushion, NOT required for (30,20)):
```python
        if self.entry_mode == "centered":
            return self.n_window + self.n_meta
        base = 2 * self.n_window           # floor already gives 31 valid z >= sigma_20 needs 20
        if self.adaptive_width:
            base += self.bb_m              # cushion; load-bearing only if bb_m > n_window+1
        return base
```

**1d — adaptive-band helper** (immediately before `_attach_z_r`):
```python
    def _adaptive_band(self, z_series: pd.Series) -> pd.Series:
        """Band width = bb_k * rolling_std(z, bb_m). Population std (ddof=0) to match the
        repo z convention; zero std -> NaN (no cross fires); NaN during the first bb_m-1 bars."""
        z_std = z_series.rolling(window=self.bb_m, min_periods=self.bb_m).std(ddof=0)
        z_std = z_std.replace(0, np.nan)
        return self.bb_k * z_std
```

**1e — band-relative entry detection** (replace the `# Active z series ...` block through the two
`crossed_*` assignments; **explicit form only** — with `adaptive_width=False` it reduces *exactly* to the
current scalar comparison, byte-identical):
```python
        if self.entry_mode == "centered":
            z_active = z_data["z_r_centered"]
        else:
            z_active = z_data["z_r"]

        if self.adaptive_width and self.entry_mode == "absolute":
            band = self._adaptive_band(z_active)     # per-bar Series, NaN in warmup
            band_pos, band_neg = band, -band
        else:
            band_pos, band_neg = self.z_entry, -self.z_entry   # scalar (control / centered)

        prev_z = z_active.shift(1)
        if self.adaptive_width and self.entry_mode == "absolute":
            prev_pos, prev_neg = band_pos.shift(1), band_neg.shift(1)   # moving band: prior-bar boundary
        else:
            prev_pos, prev_neg = band_pos, band_neg
        crossed_up = (prev_z <= prev_pos) & (z_active > band_pos)
        crossed_dn = (prev_z >= prev_neg) & (z_active < band_neg)
        # NaN bands (warmup / zero-std) compare False both sides -> no entry fires there.
```

**1f — loud-fail on adaptive warmup starvation** (replace the existing `2*n_window`-only floor check in
`_attach_z_r`):
```python
        floor = 2 * self.n_window + (self.bb_m if self.adaptive_width else 0)
        if len(common_idx) < floor:
            raise RuntimeError(
                f"_attach_z_r: need >= {floor} common bars "
                f"(2*n_window{' + bb_m' if self.adaptive_width else ''}), got {len(common_idx)}.")
```

---

## 4. TEST cohort generation (directive cloning — NOT protected infra)

A `tmp/` script that, for each CONTROL directive in the Z25 cohort, emits a TEST clone: same pair + span +
all params, with `adaptive_width: true`, `bb_k: 2.0`, `bb_m: 20` added to the recycle_rule params and the
directive id/variant tag changed `_Z25` → `_ADP`. Write to `directives/inbox/`. **Admission-safe:**
`window_validity_gate` keys on `(pair, lookback_days, start, end)` (identical) and `namespace_gate` on
`pine_ratio_zrev_v1_zcross@1` (`_ADP` bypasses NAME_PATTERN — PORT family, `parts[4]==COINTREV`; no token
registration).

---

## 5. Open governance decision (resolve at implement-time) — W1

Patching the **parent** makes its pinned `pine_ratio_zrev_v1@1` hash silently **stale** (a future landmine
— the two directives admit fine because they pin the *unchanged* `_zcross` subclass hash). Two ways:
- **(a) In-place patch + regen `governance/recycle_rules/rule_code_hashes.yaml`** — recommended for a
  discovery experiment; a protected-infra/governance edit needing explicit operator approval.
- **(b) Version-bump to `@2`** — cleaner isolation, but fragments the corpus. Overkill here.

---

## 6. Gates / risks

- **F19 NO_TRADES scan: CLEAR** (no prior NO_TRADES for `pine_ratio_zrev`/cointegration in research record).
- **W3 — cross-operator differs by construction** (control = constant boundary; test = moving boundary).
  Correct `ta.cross` for each; **document** so a later reader doesn't mistake it for a second uncontrolled
  delta. M=20 → smooth band, not a bug.
- **W4 — adaptive warmup starvation** is the dangerous silent-failure mode: a thin window that passes the
  loader but lacks `2*n_window + bb_m` (=80) bars → all-NaN bands → zero entries (looks like "adaptive
  killed all trades"). Patch 1f fails loud; verify the loader supplies ≥80 pre-start bars/pair for TEST.
- **Engine binding:** v1.5.10 is a run-time binding, NOT a directive field — must be bound when running TEST.

---

## 7. Apply checklist (when execution arc reaches a natural stop)

1. Operator approval for the protected-infra parent patch + the W1 hash approach (a vs b).
2. Apply patches 1a–1f to `pine_ratio_zrev_v1.py`; **verify `adaptive_width=False` reproduces the existing
   corpus byte-identically** (unit/sanity check) before trusting the TEST arm.
3. (If W1=a) regen `rule_code_hashes.yaml`.
4. Clone the TEST cohort from the CONTROL directives → `directives/inbox/` (window-matched).
5. Run **ONLY the TEST cohort** through the pipeline bound to **v1.5.10**.
6. Compare TEST vs the existing CONTROL `run_id`s per pair on matched windows (the §2 metrics).
7. Exp 2 (calibration) only if Exp 1 survives the §2 interpretation.
