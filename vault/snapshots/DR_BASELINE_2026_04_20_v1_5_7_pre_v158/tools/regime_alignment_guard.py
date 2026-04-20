"""regime_alignment_guard.py — warn-mode audit of dual-time regime_age fields.

Purpose:
    Post-run structural audit of regime_age_signal / regime_age_fill fields in
    the stage-1 trade CSV. WARN-ONLY — never blocks the pipeline. Exit code is
    always 0.

What it checks (post v1.5.5):
    1. Dual-age columns present when expected (warn if missing on a run that
       used engine v1.5.5+).
    2. Structural invariants on the trade sample:
         - sum(signal_buckets) == sum(fill_buckets) == n_total
         - sum(delta_buckets)   == n_delta_valid
    3. HTF-quantization sanity (given the current HTF-broadcast architecture,
       documented in RESEARCH_MEMORY 2026-04-14):
         - delta distribution should live in {<=-2, 0, +1}
         - delta == -1 or delta >= +2 indicate a semantic change (exec-TF clock
           appeared, or broadcast broke) — surface a WARN for follow-up.
    4. NaN budget: large regime_age_signal NaN counts suggest upstream merge
       breakage.

Usage:
    python tools/regime_alignment_guard.py <DIRECTIVE_ID>
    python tools/regime_alignment_guard.py --all-recent   # last 10 completed runs

Output:
    stdout: [ALIGN-GUARD] ... one-line summary per run + WARN lines
    log:    logs/regime_alignment_audit.jsonl (append-only per-run record)

Exit:
    Always 0 — this is advisory only. Tightening to block mode is a future task.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.metrics_core import compute_age_dual_breakdown, compute_exec_delta_distribution  # noqa: E402
from config.state_paths import RUNS_DIR  # noqa: E402

LOG_PATH = PROJECT_ROOT / "logs" / "regime_alignment_audit.jsonl"


def _load_trades(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _audit_run(run_id: str, trades: list[dict]) -> dict:
    """Return a structured audit record for one run."""
    warnings: list[str] = []
    if not trades:
        return {"run_id": run_id, "trades": 0, "status": "EMPTY", "warnings": []}

    hdr = set(trades[0].keys())
    has_sig = "regime_age_signal" in hdr
    has_fil = "regime_age_fill" in hdr

    if not (has_sig and has_fil):
        warnings.append(
            f"dual-age columns missing (signal={has_sig}, fill={has_fil}); "
            "pre-v1.5.5 engine output or upstream drop"
        )
        return {
            "run_id": run_id,
            "trades": len(trades),
            "status": "NO_DUAL_AGE",
            "warnings": warnings,
        }

    out = compute_age_dual_breakdown(trades)
    meta = out["meta"]

    # Invariant 1: signal/fill sum = total
    sig_sum = sum(r["trades"] for r in out["signal_buckets"])
    fil_sum = sum(r["trades"] for r in out["fill_buckets"])
    dlt_sum = sum(r["trades"] for r in out["delta_buckets"])
    if sig_sum != meta["n_total"]:
        warnings.append(f"sum(signal_buckets)={sig_sum} != n_total={meta['n_total']}")
    if fil_sum != meta["n_total"]:
        warnings.append(f"sum(fill_buckets)={fil_sum} != n_total={meta['n_total']}")
    if dlt_sum != meta["n_delta_valid"]:
        warnings.append(
            f"sum(delta_buckets)={dlt_sum} != n_delta_valid={meta['n_delta_valid']}"
        )

    # HTF-quantization sanity: delta -1 and delta >=2 should be empty under the
    # current architecture. Non-empty => semantic change worth investigating.
    d_by_label = {r["label"]: r["trades"] for r in out["delta_buckets"]}
    d_neg1 = d_by_label.get("Delta -1", 0)
    d_pos2 = d_by_label.get("Delta >=2", 0)
    if d_neg1 > 0:
        warnings.append(
            f"delta=-1 bucket non-empty ({d_neg1} trades) — either exec-TF clock "
            "was introduced, or HTF broadcast broke; review run_stage1 merge"
        )
    if d_pos2 > 0:
        warnings.append(
            f"delta>=2 bucket non-empty ({d_pos2} trades) — HTF broadcast may "
            "have been replaced; review run_stage1 merge"
        )

    # v1.5.6 probe: exec-TF delta dominance check.
    # On the exec-TF clock under next_bar_open, Delta 1 should dominate. If
    # Delta 0 dominates on exec, either the exec age column was not populated
    # (broadcast broke) or the engine is reading fill_age at the signal bar.
    has_exec_sig = "regime_age_exec_signal" in hdr
    has_exec_fil = "regime_age_exec_fill" in hdr
    if has_exec_sig and has_exec_fil:
        exec_out = compute_exec_delta_distribution(trades)
        xd = {r["label"]: r["trades"] for r in exec_out["delta_buckets"]}
        xm = exec_out["meta"]
        x_d1 = xd.get("Exec Delta 1", 0)
        x_d0 = xd.get("Exec Delta 0", 0)
        x_valid = xm.get("n_delta_valid", 0)
        if x_valid > 0:
            if x_d1 < x_d0:
                warnings.append(
                    f"exec delta=0 ({x_d0}) >= delta=+1 ({x_d1}) — exec clock "
                    "not advancing between signal and fill; regime_age_exec "
                    "may not be populated on exec TF"
                )
            elif (x_d1 / x_valid) < 0.80:
                warnings.append(
                    f"exec delta=+1 dominance only {100.0*x_d1/x_valid:.1f}% "
                    "(<80%) — investigate regime flips or missing column"
                )
    elif has_sig and has_fil:
        # Dual HTF age present but exec fields absent → pre-v1.5.6 engine.
        warnings.append(
            "exec-TF age columns missing (regime_age_exec_signal/_fill) — "
            "pre-v1.5.6 engine; exec clock probe unavailable"
        )

    # NaN budget: warn if > 1% of trades have signal NaN (last-bar fill NaN is
    # structural and capped at 1 trade, so tolerated up to ~1% for small runs).
    if meta["n_total"] > 0:
        sig_nan_pct = 100.0 * meta["n_signal_nan"] / meta["n_total"]
        if sig_nan_pct > 1.0:
            warnings.append(
                f"regime_age_signal NaN fraction {sig_nan_pct:.1f}% > 1% — "
                "upstream regime merge may be breaking"
            )

    result = {
        "run_id": run_id,
        "trades": meta["n_total"],
        "status": "OK" if not warnings else "WARN",
        "meta": meta,
        "delta_distribution": d_by_label,
        "warnings": warnings,
    }
    if has_exec_sig and has_exec_fil:
        result["exec_delta_distribution"] = {
            r["label"]: r["trades"] for r in exec_out["delta_buckets"]
        }
        result["exec_meta"] = exec_out["meta"]
    return result


def _emit(record: dict) -> None:
    """Print one-line summary + WARN lines; append JSONL."""
    rid = record["run_id"]
    status = record["status"]
    n = record.get("trades", 0)
    if status == "OK":
        dlt = record.get("delta_distribution", {})
        d0 = dlt.get("Delta 0", 0)
        d1 = dlt.get("Delta 1", 0)
        dm2 = dlt.get("Delta <=-2", 0)
        print(
            f"[ALIGN-GUARD] {rid[:12]} trades={n} OK  "
            f"delta0={d0} delta+1={d1} delta<=-2={dm2}"
        )
    elif status == "NO_DUAL_AGE":
        print(f"[ALIGN-GUARD] {rid[:12]} trades={n} NO_DUAL_AGE (pre-v1.5.5)")
    elif status == "EMPTY":
        print(f"[ALIGN-GUARD] {rid[:12]} EMPTY")
    else:
        print(f"[ALIGN-GUARD] {rid[:12]} trades={n} WARN")
        for w in record.get("warnings", []):
            print(f"  [WARN] {w}")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record_out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record_out) + "\n")


def _find_runs_for_directive(directive_id: str) -> list[Path]:
    """Find run CSVs for a given directive via run_state.json.directive_id."""
    matches: list[Path] = []
    if not RUNS_DIR.exists():
        return matches
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        state_path = run_dir / "run_state.json"
        if not state_path.exists():
            continue
        try:
            s = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("directive_id") == directive_id:
            csv_path = run_dir / "data" / "results_tradelevel.csv"
            if csv_path.exists():
                matches.append(csv_path)
    return matches


def _find_recent_runs(limit: int) -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    candidates: list[tuple[float, Path]] = []
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        csv_path = run_dir / "data" / "results_tradelevel.csv"
        if csv_path.exists():
            candidates.append((csv_path.stat().st_mtime, csv_path))
    candidates.sort(reverse=True)
    return [p for _, p in candidates[:limit]]


def main() -> int:
    ap = argparse.ArgumentParser(description="Dual-age regime alignment audit (warn-only).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("directive_id", nargs="?", help="Run audit for a specific directive ID.")
    g.add_argument("--all-recent", type=int, nargs="?", const=10, default=None,
                   help="Audit the N most recent runs (default 10).")
    args = ap.parse_args()

    if args.all_recent is not None:
        paths = _find_recent_runs(args.all_recent)
        if not paths:
            print("[ALIGN-GUARD] no runs found under RUNS_DIR")
            return 0
    else:
        paths = _find_runs_for_directive(args.directive_id)
        if not paths:
            print(f"[ALIGN-GUARD] no run CSVs found for directive {args.directive_id}")
            return 0

    for p in paths:
        run_id = p.parent.parent.name
        try:
            trades = _load_trades(p)
            rec = _audit_run(run_id, trades)
        except (OSError, ValueError) as e:
            rec = {"run_id": run_id, "status": "ERROR", "warnings": [str(e)]}
        _emit(rec)

    return 0


if __name__ == "__main__":
    sys.exit(main())
