"""cointegration_event_study.py — concept-validation event study.

Tests whether structurally persistent FX cointegration relationships
exhibit reliable forward mean-reversion after abnormal spread
displacement, across multiple z-score thresholds.

DESIGN (per user spec 2026-05-20):
  * Universe: 18 FX pairs, 153 unordered pair-pairs (no hindsight).
  * Qualification at bar t: ADF p < 0.05 at the nearest MONTHLY anchor
    ≤ t-1 in BOTH 252-day AND 504-day windows. Anchor must be in the
    past — no look-ahead.
  * Event = first bar where |z_t| crosses ≥ threshold from below
    (|z_{t-1}| < threshold ≤ |z_t|) AND pair qualified at t.
  * Forward window = 60 trading days from event bar.
  * Reversion target = |z| ≤ 0.5 (standard normalized definition).
  * Failure mode = no reversion within 60d; log max |z| and whether
    the qualification broke during the window.
  * No per-pair optimization; no survivorship filter; no hindsight.

  Computational shortcut: ADF tested at monthly anchors only (every
  21 trading days). Daily ADF across 153 pairs × 2 windows is too
  expensive for concept validation. Forward-fill from anchor → daily
  with strict ≤ t-1 lag (never use a future anchor).

ALSO COMPUTED: same statistics WITHOUT the cointegration filter
(baseline cohort). Measures the LIFT of cointegration filtering vs
naive z-score reversion trading.

Outputs (under outputs/cointegration_screener_v1/event_study/):
  * event_summary_by_threshold.csv
  * events_detail.parquet
  * EVENT_STUDY_REPORT.md
"""
from __future__ import annotations

import itertools
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

# utf-8 stdout/stderr before anything that might print unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from config.path_authority import DATA_ROOT
from tools.factors.fx_correlation_matrix import FX_UNIVERSE, _load_native_closes


# --- Study parameters --------------------------------------------------
THRESHOLDS = [1.5, 2.0, 2.5, 3.0]
HEDGE_WINDOW = 252           # bars for rolling OLS β + spread mean/std
ADF_WINDOW_SHORT = 252
ADF_WINDOW_LONG = 504
ADF_SAMPLE_EVERY = 21        # monthly anchors
ADF_LAG_BARS = 1             # require anchor strictly before t (no look-ahead)
FORWARD_BARS = 60            # lookahead window for reversion
REVERSION_TARGET = 1.0       # exit when |z| returns to the "normal" zone
                              # (per operator: entry at |z|>=tau is large
                              # displacement; exit needn't wait for full
                              # mean revert to 0.5 — back to ~1 is plenty)
P_QUALIFY = 0.05

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "cointegration_screener_v1" / "event_study"


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}", flush=True)


# --- Data loading ------------------------------------------------------


def load_aligned_closes() -> pd.DataFrame:
    """Load all 18 FX daily closes, intersect indexes, return wide DataFrame."""
    closes: dict[str, pd.Series] = {}
    for sym in FX_UNIVERSE:
        closes[sym] = _load_native_closes(sym, "1d", None, None)
    df = pd.concat(closes, axis=1, join="inner").dropna()
    df.columns = list(closes.keys())
    return df


# --- Per-pair rolling stats -------------------------------------------


def compute_pair_series(a: pd.Series, b: pd.Series,
                          window: int = HEDGE_WINDOW
                          ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Rolling β (cov/var), spread, and z-score using only data ≤ t.

    β_t = cov(b,a)_{[t-window+1, t]} / var(a)_{[t-window+1, t]}
    spread_t = b_t - β_t · a_t
    z_t = (spread_t - mean(spread)_{[t-window+1, t]})
          / std(spread)_{[t-window+1, t]}
    """
    mean_a = a.rolling(window).mean()
    mean_b = b.rolling(window).mean()
    cov_ab = (a * b).rolling(window).mean() - mean_a * mean_b
    var_a = a.rolling(window).var(ddof=0)
    beta = cov_ab / var_a
    spread = b - beta * a
    sp_mean = spread.rolling(window).mean()
    sp_std = spread.rolling(window).std(ddof=0)
    z = (spread - sp_mean) / sp_std
    return beta, spread, z


# --- Monthly ADF anchors ----------------------------------------------


def compute_adf_anchors(spread: pd.Series, anchor_window: int,
                         sample_every: int = ADF_SAMPLE_EVERY) -> pd.Series:
    """Compute ADF p-value at monthly anchors, forward-fill onto daily index.

    Each anchor uses the `anchor_window` bars ending AT that anchor (inclusive).
    Returns a Series aligned to `spread.index`; anchors before warmup are NaN.
    """
    valid = spread.dropna()
    if len(valid) < anchor_window:
        return pd.Series(np.nan, index=spread.index)

    pvals: dict[pd.Timestamp, float] = {}
    for end_pos in range(anchor_window - 1, len(valid), sample_every):
        window_data = valid.iloc[end_pos - anchor_window + 1: end_pos + 1].values
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                p = float(adfuller(window_data, autolag="AIC")[1])
        except Exception:
            p = 1.0
        pvals[valid.index[end_pos]] = p

    anchor_series = pd.Series(pvals).sort_index()
    # Forward-fill from each anchor. For honest as-of, also shift by
    # ADF_LAG_BARS so today's bar doesn't see today's own anchor.
    daily = anchor_series.reindex(spread.index, method="ffill")
    return daily.shift(ADF_LAG_BARS)


# --- Event detection + forward tracking -------------------------------


def detect_events(z: pd.Series, qualified: pd.Series,
                   thresholds: list[float]) -> list[dict]:
    """First-crossing events: |z_t| ≥ τ AND |z_{t-1}| < τ AND qualified_t."""
    abs_z = z.abs()
    abs_z_prev = abs_z.shift(1)
    events = []
    for tau in thresholds:
        crossing = (abs_z >= tau) & (abs_z_prev < tau) & qualified.fillna(False)
        for ts in z.index[crossing.fillna(False)]:
            events.append({
                "ts": ts,
                "threshold": tau,
                "z_at_event": float(z.loc[ts]),
            })
    return events


def track_forward(z: pd.Series, qualified: pd.Series, event_ts: pd.Timestamp,
                   forward_bars: int = FORWARD_BARS,
                   target: float = REVERSION_TARGET) -> dict:
    """Walk forward from event_ts; record reversion / failure stats."""
    idx_pos = z.index.get_loc(event_ts)
    end_pos = min(idx_pos + 1 + forward_bars, len(z))
    forward = z.iloc[idx_pos + 1: end_pos]
    if len(forward) == 0:
        return None
    abs_forward = forward.abs()
    z_at_event = abs(float(z.iloc[idx_pos]))

    reverted_mask = abs_forward <= target
    if reverted_mask.any():
        first_rev_idx = reverted_mask.idxmax()
        bars_to_rev = forward.index.get_loc(first_rev_idx) + 1   # 1-based
        max_z_in_window = float(abs_forward.loc[:first_rev_idx].max())
        reverted = True
    else:
        bars_to_rev = None
        max_z_in_window = float(abs_forward.max())
        reverted = False

    adverse = max_z_in_window - z_at_event
    # Did qualification break during the forward window?
    fwd_qual = qualified.iloc[idx_pos + 1: end_pos]
    qual_broke = (not fwd_qual.fillna(False).all())

    return {
        "reverted": reverted,
        "bars_to_reversion": bars_to_rev,
        "max_z_in_window": max_z_in_window,
        "adverse_excursion": float(adverse),
        "qualification_broke_in_window": bool(qual_broke),
        "forward_bars_available": len(forward),
    }


# --- Main pipeline ----------------------------------------------------


def run_study(closes: pd.DataFrame) -> pd.DataFrame:
    """Run the full event study. Returns events_df with one row per event."""
    rows = []
    pairs = list(itertools.combinations(sorted(closes.columns), 2))
    t0 = time.time()

    for i, (sa, sb) in enumerate(pairs):
        beta, spread, z = compute_pair_series(closes[sa], closes[sb])

        adf_short = compute_adf_anchors(spread, ADF_WINDOW_SHORT)
        adf_long = compute_adf_anchors(spread, ADF_WINDOW_LONG)
        qualified = (adf_short < P_QUALIFY) & (adf_long < P_QUALIFY)
        # "all" cohort = no qualification filter (for baseline comparison)
        all_mask = pd.Series(True, index=z.index)

        for cohort_name, mask in (("qualified", qualified), ("all", all_mask)):
            events = detect_events(z, mask, THRESHOLDS)
            for e in events:
                tracking = track_forward(z, mask, e["ts"])
                if tracking is None:
                    continue
                rows.append({
                    "cohort": cohort_name,
                    "pair_a": sa, "pair_b": sb,
                    "event_ts": e["ts"], "threshold": e["threshold"],
                    "z_at_event": e["z_at_event"],
                    **tracking,
                })

        if (i + 1) % 10 == 0 or (i + 1) == len(pairs):
            elapsed = time.time() - t0
            _log(f"  pair {i+1}/{len(pairs)}  ({sa}/{sb})  elapsed={elapsed:.1f}s  events={len(rows)}")

    df = pd.DataFrame(rows)
    return df


def summarize(events_df: pd.DataFrame) -> pd.DataFrame:
    """Cohort × threshold summary."""
    rows = []
    for cohort in ["qualified", "all"]:
        for tau in THRESHOLDS:
            sub = events_df[(events_df.cohort == cohort) & (events_df.threshold == tau)]
            if sub.empty:
                rows.append({
                    "cohort": cohort, "threshold": tau, "n_events": 0,
                    "reversion_rate": np.nan,
                    "median_bars_to_reversion": np.nan,
                    "median_max_z_in_window": np.nan,
                    "median_adverse_excursion": np.nan,
                    "p90_adverse_excursion": np.nan,
                    "qual_break_rate": np.nan,
                })
                continue
            reverted = sub[sub.reverted]
            rows.append({
                "cohort": cohort,
                "threshold": tau,
                "n_events": len(sub),
                "reversion_rate": float(sub.reverted.mean()),
                "median_bars_to_reversion": float(reverted["bars_to_reversion"].median())
                    if not reverted.empty else np.nan,
                "median_max_z_in_window": float(sub["max_z_in_window"].median()),
                "median_adverse_excursion": float(sub["adverse_excursion"].median()),
                "p90_adverse_excursion": float(sub["adverse_excursion"].quantile(0.9)),
                "qual_break_rate": float(sub["qualification_broke_in_window"].mean()),
            })
    return pd.DataFrame(rows)


def write_report(events_df: pd.DataFrame, summary_df: pd.DataFrame,
                 closes: pd.DataFrame, report_path: Path | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if report_path is None:
        report_path = OUTPUT_DIR / "EVENT_STUDY_REPORT.md"

    universe_start = closes.index[0].date()
    universe_end = closes.index[-1].date()
    n_qualified_total = int((events_df.cohort == "qualified").sum())
    n_all_total = int((events_df.cohort == "all").sum())

    qual = summary_df[summary_df.cohort == "qualified"].sort_values("threshold")
    base = summary_df[summary_df.cohort == "all"].sort_values("threshold")

    lines = []
    lines.append("# Cointegration Event Study — Concept Validation\n")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ")
    lines.append(f"**Spec reference:** [`COINTEGRATION_SCREENER_V1_SPEC.md`](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md)\n")

    lines.append("## Hypothesis under test\n")
    lines.append("> Do structurally persistent FX relationships (cointegrated in BOTH 252d and 504d windows, "
                 "qualification held as-of event) exhibit reliable forward mean-reversion after abnormal "
                 "spread displacement, before structural regime degradation?\n")

    lines.append("## Methodology\n")
    lines.append(f"- **Universe:** {len(FX_UNIVERSE)} FX pairs, {len(list(itertools.combinations(FX_UNIVERSE, 2)))} unordered pair-pairs")
    lines.append(f"- **Date range:** {universe_start} → {universe_end} ({len(closes)} daily bars, intersection of all 18 pairs)")
    lines.append(f"- **Qualification:** ADF p < {P_QUALIFY} at nearest **monthly anchor** ≤ event_bar−1 in **BOTH** {ADF_WINDOW_SHORT}d AND {ADF_WINDOW_LONG}d windows")
    lines.append(f"- **Hedge ratio:** rolling OLS over {HEDGE_WINDOW} bars (β_t = cov(b,a)/var(a))")
    lines.append(f"- **Spread:** b_t − β_t·a_t")
    lines.append(f"- **Z-score:** (spread_t − mean_t) / std_t over {HEDGE_WINDOW}-bar window")
    lines.append(f"- **Event:** first bar where |z| crosses ≥ τ from below AND pair qualified at t")
    lines.append(f"- **Thresholds:** {THRESHOLDS}")
    lines.append(f"- **Forward window:** {FORWARD_BARS} trading days")
    lines.append(f"- **Reversion target:** |z| ≤ {REVERSION_TARGET}")
    lines.append(f"- **No-lookahead invariant:** ADF anchor must be ≥ 1 bar before t (shift={ADF_LAG_BARS})\n")

    lines.append("**Baseline cohort** (`all`): same event detection without cointegration filtering. "
                 "Measures the LIFT of qualification — proves filtering does real work rather than selecting "
                 "the same population a naive trader would.\n")

    lines.append("## Cohort sizes\n")
    lines.append(f"- Qualified-cohort events: **{n_qualified_total:,}** across all thresholds + pairs")
    lines.append(f"- All-cohort events:        **{n_all_total:,}** (baseline)")
    lines.append(f"- Filter retention:         **{n_qualified_total/max(n_all_total,1)*100:.1f}%** "
                 f"(cointegration qualification removes {(1-n_qualified_total/max(n_all_total,1))*100:.1f}% of events)\n")

    lines.append("## Summary by threshold — QUALIFIED cohort\n")
    lines.append(_md_table(qual.drop(columns="cohort")))

    lines.append("\n## Summary by threshold — ALL (baseline) cohort\n")
    lines.append(_md_table(base.drop(columns="cohort")))

    lines.append("\n## Reversion lift over baseline\n")
    lift = []
    for tau in THRESHOLDS:
        q = qual[qual.threshold == tau].iloc[0]
        b = base[base.threshold == tau].iloc[0]
        if q["n_events"] == 0 or b["n_events"] == 0 or pd.isna(b["reversion_rate"]):
            lift_pct = np.nan
        else:
            lift_pct = (q["reversion_rate"] - b["reversion_rate"]) * 100
        lift.append({
            "threshold": tau,
            "qualified_reversion_rate": q["reversion_rate"],
            "baseline_reversion_rate":  b["reversion_rate"],
            "lift_percentage_points":   lift_pct,
        })
    lines.append(_md_table(pd.DataFrame(lift)))

    lines.append("\n## Interpretation\n")
    # Best-threshold recommendation: maximize reversion_rate × (1 - p90_adverse / 5)
    qual_valid = qual.dropna(subset=["reversion_rate"]).copy()
    if not qual_valid.empty:
        # Adverse-excursion penalty: normalize p90 by 5 (a "5σ further" excursion = total penalty)
        qual_valid["score"] = qual_valid["reversion_rate"] * (1.0 - qual_valid["p90_adverse_excursion"].clip(0, 5) / 5)
        best = qual_valid.sort_values("score", ascending=False).iloc[0]
        lines.append(f"- **Suggested threshold (qualified cohort):** τ = **{best['threshold']}**")
        lines.append(f"  - reversion rate {best['reversion_rate']*100:.1f}% over {int(best['n_events'])} events")
        lines.append(f"  - median bars-to-reversion {best['median_bars_to_reversion']:.0f}")
        lines.append(f"  - p90 adverse excursion {best['p90_adverse_excursion']:.2f} z-units past entry\n")

    lines.append("- **Caveats:**")
    lines.append("  - In-sample β and z-score windows — no out-of-sample validation of the hedge ratio")
    lines.append("  - Monthly ADF sampling — qualification could be over/under-stated by up to 21 days")
    lines.append("  - 60-bar forward window is arbitrary — longer windows would raise reversion rate AND mean-time-to-reversion")
    lines.append("  - No trading-cost model — z-score reversion ≠ tradable P/L")
    lines.append("  - Failure-mode skew: pairs that broke during the forward window are counted in `qual_break_rate`")

    lines.append("\n## Files\n")
    lines.append(f"- `event_summary_by_threshold.csv` — the summary tables above as CSV")
    lines.append(f"- `events_detail.parquet` — every event as a row (cohort, pair, ts, threshold, all stats) "
                 f"for any follow-up slicing (per-pair, per-year, per-direction, etc.)")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _log(f"wrote {report_path}")


def _md_table(df: pd.DataFrame) -> str:
    """Render a small DataFrame as a Markdown table."""
    rounded = df.copy()
    for c in rounded.select_dtypes(include="float").columns:
        rounded[c] = rounded[c].round(3)
    return rounded.to_markdown(index=False)


def main() -> int:
    _log("loading FX closes...")
    closes = load_aligned_closes()
    _log(f"aligned: {closes.shape[0]} bars  {closes.shape[1]} symbols  "
         f"{closes.index[0].date()} → {closes.index[-1].date()}")

    _log("running event study (will take 10-15 min for full ADF anchor sweep)...")
    events_df = run_study(closes)
    _log(f"events: {len(events_df):,}")

    summary_df = summarize(events_df)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Robust write: if a file is locked (Excel open, etc.), fall back to a
    # timestamped name and continue so the rest of the outputs still land.
    def _safe_write(target: Path, write_fn) -> Path:
        try:
            write_fn(target)
            return target
        except PermissionError:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fallback = target.with_name(f"{target.stem}_{ts}{target.suffix}")
            _log(f"WARN: {target.name} locked; writing to {fallback.name} instead")
            write_fn(fallback)
            return fallback

    csv_path = _safe_write(OUTPUT_DIR / "event_summary_by_threshold.csv",
                            lambda p: summary_df.to_csv(p, index=False))
    pq_path = _safe_write(OUTPUT_DIR / "events_detail.parquet",
                           lambda p: events_df.to_parquet(p, index=False))
    _log(f"wrote {csv_path}")
    _log(f"wrote {pq_path}")

    _safe_write(OUTPUT_DIR / "EVENT_STUDY_REPORT.md",
                 lambda p: write_report(events_df, summary_df, closes, p))

    print()
    print("=" * 70)
    print(summary_df.to_string(index=False))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
