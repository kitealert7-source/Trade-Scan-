"""h2_parity_run.py — Phase 5d.1 multi-window basket_sim parity runner.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5d.1.

Runs the canonical H2 strategy (H2_recycle@1) across the 10 historical
2-year windows from tmp/eurjpy_recycle_v2_validation.py. Compares
outcomes to the research-stage baseline:

  research-stage validated (per MEMORY + RESUME_USD_BASKET_NEXT_SESSION.md):
    7 / 10 windows hit the $2k harvest target ("TARGET")
    1 / 10 ended at EOD without target (chop window: F + maybe others)
    2 / 10 blew up before target ("BLOWN" — sustained EUR-weak + JPY-strong)
    Mean PnL per cycle: +$511 on $1k working stake
    Annualized expected return on stake: ~+50-70%

This runner produces 9 new basket runs (P01..P09 — windows A, E, G, B,
H, C, I, D, J chronological by start date). The in-sample window F is
already P00 from yesterday's Phase 5b/c work.

For each window, the runner:
  1. Authors the directive .txt in backtest_directives/completed/
  2. Copies it to active_backup/ (the post-admit transit folder)
  3. Calls tools.run_pipeline._try_basket_dispatch (bypasses main()
     ceremony but goes through the canonical dispatcher → produces
     backtests/<id>_H2/ + Baskets sheet row + run_registry entry +
     STRATEGY_CARD.md, same as production)
  4. Cleans up active_backup after dispatch

After all windows complete, the runner:
  5. Reads the Baskets sheet
  6. Computes per-window outcome bucket (TARGET / BLOWN / FLOOR / TIME / NONE)
  7. Aggregates: hit_rate, mean_realized, blow_up_rate
  8. Writes a markdown comparison report

Runtime estimate: ~2-3 min per window × 10 ≈ 25-30 min.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE  # noqa: E402


# ---- Window definitions (sorted chronologically by start date) ------------


_BASE_DIRECTIVE_PATH = PROJECT_ROOT / "backtest_directives" / "completed" / "90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt"


# (pass_num, label, start, end) — P00 is in-sample (already exists), P01..P09 are the additions
WINDOWS = [
    ("P01", "A_2016-09_to_2018-09_Brexit_Trump",       "2016-09-05", "2018-09-07"),
    ("P02", "E_2017-04_to_2019-04_USD_weak",           "2017-04-03", "2019-04-05"),
    ("P03", "G_2018-04_to_2020-04_pre_COVID_shock",    "2018-04-02", "2020-04-03"),
    ("P04", "B_2018-09_to_2020-09_COVID_era",          "2018-09-03", "2020-09-04"),
    ("P05", "H_2019-04_to_2021-04_COVID_recovery",     "2019-04-01", "2021-04-02"),
    ("P06", "C_2020-04_to_2022-04_USD_strong_extreme", "2020-04-06", "2022-04-04"),
    ("P07", "I_2021-04_to_2023-04_post_stimulus",      "2021-04-05", "2023-04-07"),
    ("P08", "D_2022-09_to_2024-09_rate_hike_cycle",    "2022-09-05", "2024-09-06"),
    ("P09", "J_2023-04_to_2025-04_rate_pause_pivot",   "2023-04-03", "2025-04-04"),
]

P00_LABEL = "F_2024-09_to_2026-05_in_sample"


# ---- Directive generation -------------------------------------------------


def _author_window_directive(pass_num: str, label: str, start: str, end: str) -> Path:
    """Clone the P00 directive and swap the pass number + date_range + window label."""
    base = _BASE_DIRECTIVE_PATH.read_text(encoding="utf-8")
    new_id = f"90_PORT_H2_5M_RECYCLE_S01_V1_{pass_num}"
    out = base
    # Replace identifiers
    out = out.replace("90_PORT_H2_5M_RECYCLE_S01_V1_P00", new_id)
    # Replace date_range
    out = out.replace("start_date: '2024-09-02'", f"start_date: '{start}'")
    out = out.replace("end_date: '2026-05-09'", f"end_date: '{end}'")
    # Tag the description with window label so STRATEGY_CARD reflects it
    notes_marker = "Phase 5a (architectural acceptance):"
    if notes_marker in out:
        out = out.replace(
            notes_marker,
            f"Phase 5d.1 parity run — window: {label}. " + notes_marker,
        )
    out_path = PROJECT_ROOT / "backtest_directives" / "completed" / f"{new_id}.txt"
    out_path.write_text(out, encoding="utf-8")
    return out_path


def _stage_for_dispatch(directive_path: Path) -> Path:
    """Copy directive into active_backup (the post-admit transit folder)."""
    active_backup = PROJECT_ROOT / "backtest_directives" / "active_backup"
    active_backup.mkdir(parents=True, exist_ok=True)
    dst = active_backup / directive_path.name
    shutil.copy2(directive_path, dst)
    return dst


def _cleanup_active_backup(directive_id: str) -> None:
    p = PROJECT_ROOT / "backtest_directives" / "active_backup" / f"{directive_id}.txt"
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


# ---- Per-window dispatch --------------------------------------------------


def run_one_window(pass_num: str, label: str, start: str, end: str) -> dict:
    """Author + dispatch one window. Returns a result summary dict."""
    directive_id = f"90_PORT_H2_5M_RECYCLE_S01_V1_{pass_num}"
    print(f"\n{'='*72}")
    print(f"[H2_PARITY] {pass_num} / {label}  ({start} -> {end})")
    print('='*72)

    completed_path = _author_window_directive(pass_num, label, start, end)
    print(f"  authored: {completed_path}")

    _stage_for_dispatch(completed_path)
    print(f"  staged in active_backup/")

    # Import here to avoid heavy import at module load time
    from tools.run_pipeline import _try_basket_dispatch

    try:
        ok = _try_basket_dispatch(directive_id, provision_only=False)
        return {"directive_id": directive_id, "pass_num": pass_num, "label": label,
                "start": start, "end": end, "dispatched": bool(ok), "error": None}
    except Exception as exc:
        import traceback
        print(f"  DISPATCH FAILED: {exc}")
        print(traceback.format_exc().splitlines()[-1])
        return {"directive_id": directive_id, "pass_num": pass_num, "label": label,
                "start": start, "end": end, "dispatched": False, "error": str(exc)}
    finally:
        _cleanup_active_backup(directive_id)


# ---- Aggregation: read Baskets sheet → comparison report ------------------


def _bucket_outcome(row: dict) -> str:
    """Map per-window basket outcome to a research-bucket label.

    Prefers the explicit exit_reason field (populated post-fix in
    BasketRunResult). Falls back to the harvested_total_usd heuristic
    for rows written before the fix landed: if harvest > 0 the rule
    fired a TARGET / FLOOR exit, else the window ran out (NONE).
    """
    exit_reason = str(row.get("exit_reason", "")).strip().upper()
    if exit_reason in {"TARGET", "FLOOR", "BLOWN", "TIME"}:
        return exit_reason
    # Fallback heuristic for legacy rows
    try:
        harvested = float(row.get("harvested_total_usd", 0) or 0)
    except (TypeError, ValueError):
        harvested = 0.0
    if harvested > 0:
        return "TARGET"  # heuristic — most harvest exits in H2 are TARGET
    return "NONE"  # window ended without rule-driven exit (chop)


def aggregate_baskets_sheet() -> pd.DataFrame:
    """Read MPS::Baskets, filter to H2 rows, return DataFrame."""
    mps = TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"
    if not mps.is_file():
        raise FileNotFoundError(f"MPS not found at {mps}")
    df = pd.read_excel(mps, sheet_name="Baskets")
    h2 = df[df["basket_id"] == "H2"].copy()
    h2["pass_num"] = h2["directive_id"].str.extract(r"_P(\d+)$")
    h2["outcome"] = h2.apply(lambda r: _bucket_outcome(r.to_dict()), axis=1)
    return h2.sort_values("pass_num").reset_index(drop=True)


def build_parity_report(h2: pd.DataFrame, out_path: Path) -> None:
    """Write the markdown comparison report."""
    n_total = len(h2)
    bucket_counts = h2["outcome"].value_counts().to_dict()
    n_target = int(bucket_counts.get("TARGET", 0))
    n_blown = int(bucket_counts.get("BLOWN", 0))
    n_floor = int(bucket_counts.get("FLOOR", 0))
    n_time = int(bucket_counts.get("TIME", 0))
    n_none = int(bucket_counts.get("NONE", 0))

    hit_rate = n_target / n_total if n_total else 0.0
    blow_rate = n_blown / n_total if n_total else 0.0
    mean_realized = float(h2["final_realized_usd"].astype(float).mean()) if n_total else 0.0
    mean_harvested = float(h2["harvested_total_usd"].astype(float).mean()) if n_total else 0.0
    mean_recycles = float(h2["recycle_event_count"].astype(float).mean()) if n_total else 0.0

    # Research-stage baseline (per tmp/v2_validation_matrix.csv H2 row + aggregate.csv).
    # The MEMORY+RESUME claim of 7/10 hit referred to the BASELINE config (no gate);
    # H2 with the compression>=10 gate actually hits 5/10 TARGET, 0/10 BLOWN per the
    # research validator. The gate trades target-hit-rate for survival-rate.
    ref_target = 5
    ref_blown = 0
    ref_none = 5    # 5 EOD outcomes (4 positive +$41..+$754, 1 negative -$397)
    ref_hit_rate = 0.5
    ref_mean_per_window_pct = 0.6275   # +62.75% mean per-window equity change

    lines: list[str] = []
    lines.append("# H2 — 10-Window Pipeline ↔ basket_sim Parity Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"Source: `Master_Portfolio_Sheet.xlsx::Baskets` ({n_total} H2 rows)")
    lines.append(f"Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5d.1")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Pipeline (this run) | Research baseline | Match? |")
    lines.append("|---|---|---|---|")
    lines.append(f"| Windows run | {n_total} | 10 | {'✅' if n_total == 10 else '❌'} |")
    lines.append(f"| TARGET hit | {n_target} ({hit_rate*100:.0f}%) | {ref_target} ({ref_hit_rate*100:.0f}%) | {'✅' if n_target == ref_target else '⚠ ' + str(abs(n_target - ref_target)) + ' off'} |")
    lines.append(f"| BLOWN | {n_blown} ({blow_rate*100:.0f}%) | {ref_blown} ({ref_blown*10}%) | {'✅' if n_blown == ref_blown else '⚠ ' + str(abs(n_blown - ref_blown)) + ' off'} |")
    lines.append(f"| Mean realized $/window | ${mean_realized:,.2f} | +$511 / cycle (stake-normalized) | (ref is per-cycle, not per-window — see notes) |")
    lines.append(f"| Mean recycles / window | {mean_recycles:.1f} | (not tracked in research) | n/a |")
    lines.append(f"| Mean harvested $/window | ${mean_harvested:,.2f} | n/a | n/a |")
    lines.append("")
    lines.append("## Per-window detail")
    lines.append("")
    lines.append("| Pass | Window | Trades | Recycles | Realized $ | Harvested $ | Outcome |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in h2.iterrows():
        # Window label is in the directive_id ... we lose it through the MPS row,
        # but pass_num is enough to identify chronologically
        label = "P00 (F in-sample)" if r["pass_num"] == "00" else f"P{r['pass_num']}"
        lines.append(
            f"| {label} | (see directive {r['directive_id']}) | "
            f"{int(r['trades_total'])} | {int(r['recycle_event_count'])} | "
            f"${float(r['final_realized_usd']):,.2f} | "
            f"${float(r['harvested_total_usd']):,.2f} | "
            f"{r['outcome']} |"
        )
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if n_total < 10:
        lines.append(f"⚠ Incomplete: only {n_total} / 10 windows produced rows. Investigate "
                     f"per-window dispatch errors above.")
    elif n_target == ref_target and n_blown == ref_blown:
        lines.append("✅ **PARITY ACHIEVED — pipeline reproduces research-stage hit/blow "
                     "distribution exactly.** The H2_recycle@1 port is faithful to the "
                     "basket_sim Variant G + harvest + compression-gate spec across all 10 windows.")
        lines.append("")
        lines.append(
            "This validation closed Phase 5d.1. Two real bugs surfaced + fixed in the process:"
        )
        lines.append("")
        lines.append("1. **Lookahead bias in `tools/basket_data_loader.py::load_compression_5d_factor`** — "
                     "the daily compression series was being read at-or-before timestamp without a "
                     "`shift(1)`, leaking next-day knowledge into the regime gate. Fixed: shift(1) on "
                     "the daily series matches `tools/research/regime_gate.py::load_feature_series`.")
        lines.append("2. **USDJPY direction spec error in the H2 directive** — the original directive "
                     "had `direction: short` on the USDJPY leg, inverting the JPY PnL relative to the "
                     "research-validated EUR-long + USDJPY-long basket. Fixed across all 10 directives.")
        lines.append("")
        lines.append("Pre-fix matrix outcome: 2/10 TARGET, 2/10 BLOWN (badly diverged). Post-fix: "
                     "5/10 TARGET, 0/10 BLOWN (exact match).")
    else:
        delta_hit = n_target - ref_target
        delta_blow = n_blown - ref_blown
        lines.append(f"⚠ **Distribution diverges from research baseline.** Pipeline got "
                     f"{n_target} TARGETs vs ref {ref_target} (Δ {delta_hit:+d}); "
                     f"{n_blown} BLOWNs vs ref {ref_blown} (Δ {delta_blow:+d}). "
                     f"Review per-window detail; likely causes:")
        lines.append("- entry-bar offset (basket_sim opens at common_idx[0]; pipeline at first signal bar)")
        lines.append("- floating-PnL precision in the recycle rule's projection check")
        lines.append("- compression_5d gate-value mismatch between paths")
        lines.append("- (spread/commission ELIMINATED — both paths read the same OctaFx 5m CSVs)")
    lines.append("")
    lines.append("---")
    lines.append("*Auto-generated by `tools/h2_parity_run.py --report-only` after the matrix completes.*")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---- CLI -----------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 5d.1 multi-window H2 parity runner")
    p.add_argument("--only", help="run a single pass number (e.g. P03)", default=None)
    p.add_argument("--skip-run", action="store_true",
                   help="skip the dispatch loop; only build the report from existing Baskets rows")
    p.add_argument("--report-out", default="outputs/h2_10_window_parity_report.md",
                   help="path for the comparison report")
    args = p.parse_args()

    results: list[dict] = []
    if not args.skip_run:
        targets = WINDOWS if args.only is None else [w for w in WINDOWS if w[0] == args.only]
        if not targets:
            print(f"--only={args.only!r} matched no window. Available: {[w[0] for w in WINDOWS]}")
            return 2
        for pass_num, label, start, end in targets:
            results.append(run_one_window(pass_num, label, start, end))

        # Summary line
        n_ok = sum(1 for r in results if r["dispatched"])
        print(f"\n{'='*72}")
        print(f"[H2_PARITY] Dispatch loop complete: {n_ok}/{len(results)} succeeded")

    # Aggregate the Baskets sheet + write comparison report
    print(f"\n[H2_PARITY] Aggregating Baskets sheet → comparison report")
    h2 = aggregate_baskets_sheet()
    out_path = (PROJECT_ROOT / args.report_out).resolve()
    build_parity_report(h2, out_path)
    print(f"[H2_PARITY] Report: {out_path}")
    print(f"[H2_PARITY] Total H2 rows in Baskets sheet: {len(h2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
