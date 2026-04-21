"""Preflight checks — two entry points:

  preflight(strategy_id)                 — full public CLI readiness report (8 checks)
  _run_preflight(strategy_id, ...)       — inline quality_gate + freshness + validator
                                            block invoked by promote()
"""

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import STATE_ROOT, BACKTESTS_DIR, STRATEGIES_DIR, RUNS_DIR
from tools.pipeline_utils import find_run_id_for_directive
from tools.promote.audit import _write_audit_log
from tools.promote.quality_gate import _compute_quality_gate, _print_quality_gate
from tools.promote.yaml_writer import (
    _load_portfolio_yaml, _get_existing_ids, PROJECT_ROOT,
)


def preflight(strategy_id: str) -> dict:
    """Run all promote precondition checks and print a readiness report.

    Returns dict with overall pass/fail and per-check results.
    """
    print(f"\n{'=' * 60}")
    print(f"PREFLIGHT CHECK: {strategy_id}")
    print(f"{'=' * 60}\n")

    checks = {}

    # 1. strategy.py exists (or recoverable)
    base_spy = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if base_spy.exists():
        checks["strategy.py"] = ("PASS", str(base_spy))
    else:
        # Check if recoverable
        run_id = find_run_id_for_directive(strategy_id)
        snapshot = RUNS_DIR / run_id / "strategy.py" if run_id else None
        if snapshot and snapshot.exists():
            checks["strategy.py"] = ("PASS", f"Recoverable from run {run_id}")
        else:
            checks["strategy.py"] = ("FAIL", "Not found and no run snapshot")

    # 2. Backtest folders exist
    bt_dirs = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*"))
    if bt_dirs:
        syms = [d.name[len(strategy_id) + 1:] for d in bt_dirs]
        checks["backtests"] = ("PASS", f"{len(bt_dirs)} symbol(s): {syms}")
    else:
        checks["backtests"] = ("FAIL", "No backtest folders found")

    # 3. Run ID resolvable
    run_id = find_run_id_for_directive(strategy_id)
    if run_id:
        checks["run_id"] = ("PASS", run_id)
    else:
        checks["run_id"] = ("FAIL", "No run_id found via fallback chain")

    # 4. portfolio_evaluation/ (warn-only for single-symbol)
    pe = STRATEGIES_DIR / strategy_id / "portfolio_evaluation"
    is_single = len(bt_dirs) <= 1
    if pe.exists():
        checks["portfolio_evaluation"] = ("PASS", str(pe))
    elif is_single:
        checks["portfolio_evaluation"] = ("WARN", "Missing (expected for single-symbol)")
    else:
        checks["portfolio_evaluation"] = ("FAIL", "Missing for multi-symbol strategy")

    # 5. deployable/ artifacts
    deploy = STRATEGIES_DIR / strategy_id / "deployable"
    if deploy.exists() and any(deploy.iterdir()):
        checks["deployable"] = ("PASS", f"{len(list(deploy.iterdir()))} files")
    elif is_single:
        checks["deployable"] = ("WARN", "Missing (single-symbol may skip)")
    else:
        checks["deployable"] = ("WARN", "Missing — Step 8/8.5 may not have run")

    # 6. Not already in portfolio.yaml
    data = _load_portfolio_yaml()
    existing = _get_existing_ids(data)
    in_portfolio = strategy_id in existing or any(
        eid.startswith(strategy_id + "_") for eid in existing
    )
    if not in_portfolio:
        checks["not_in_portfolio"] = ("PASS", "Not in portfolio.yaml")
    else:
        checks["not_in_portfolio"] = ("FAIL", "Already in portfolio.yaml")

    # 7. PORTFOLIO_COMPLETE state
    ds_file = STATE_ROOT / "runs" / strategy_id / "directive_state.json"
    if ds_file.exists():
        try:
            ds = json.loads(ds_file.read_text(encoding="utf-8"))
            latest = ds.get("latest_attempt", "attempt_01")
            status = ds.get("attempts", {}).get(latest, {}).get("status", "?")
            if status == "PORTFOLIO_COMPLETE":
                checks["directive_state"] = ("PASS", f"PORTFOLIO_COMPLETE (attempt: {latest})")
            else:
                checks["directive_state"] = ("WARN", f"Status: {status} (not PORTFOLIO_COMPLETE)")
        except Exception:
            checks["directive_state"] = ("WARN", "directive_state.json unreadable")
    else:
        checks["directive_state"] = ("WARN", "No directive_state.json found")

    # 8. Quality gate
    qg = _compute_quality_gate(strategy_id)
    if qg["passed"] and not qg["warns"]:
        checks["quality_gate"] = ("PASS", "All 6 metrics OK")
    elif qg["passed"]:
        checks["quality_gate"] = ("WARN", f"{len(qg['warns'])} warning(s)")
    else:
        checks["quality_gate"] = ("FAIL", f"{len(qg['hard_fails'])} hard fail(s)")

    # Print report
    has_fail = False
    has_warn = False
    for name, (status, detail) in checks.items():
        marker = {"PASS": "OK", "WARN": "!!", "FAIL": "XX"}[status]
        print(f"  [{marker}] {name:25s} {detail}")
        if status == "FAIL":
            has_fail = True
        if status == "WARN":
            has_warn = True

    # Quality gate detail
    _print_quality_gate(qg)

    overall = "FAIL" if has_fail else ("WARN" if has_warn else "PASS")
    print(f"\n  OVERALL: {overall}")
    if overall == "FAIL":
        print(f"  Resolve FAIL items before promoting.")
    elif overall == "WARN":
        print(f"  WARN items are advisory — promotion will proceed with --skip-quality-gate if needed.")

    return {"overall": overall, "checks": checks, "quality_gate": qg}


def _run_preflight(strategy_id: str, profile: str, dry_run: bool,
                   skip_quality_gate: bool, skip_replay: bool) -> dict:
    """Run quality gate + freshness gate + 4-layer pre-promote validator.

    Aborts via sys.exit on hard fails. Returns the quality-gate dict for
    downstream audit-log inclusion.
    """
    from tools.promote.metrics import _read_backtest_metrics

    # 3b. Quality gate (6-metric edge check)
    _metrics = _read_backtest_metrics(strategy_id)
    _qg = _compute_quality_gate(strategy_id)
    _print_quality_gate(_qg)
    if not skip_quality_gate:
        if not _qg["passed"]:
            _write_audit_log(strategy_id, profile, "QUALITY_GATE_FAIL",
                             dry_run=dry_run, reason="; ".join(_qg["hard_fails"]),
                             quality_gate=_qg)
            print(f"\n[ABORT] Quality gate HARD FAIL — promotion blocked.")
            print(f"  Use --skip-quality-gate to override (not recommended).")
            sys.exit(1)
        if _qg["warns"]:
            print(f"\n  [WARN] Quality gate has {len(_qg['warns'])} warning(s) — proceeding.")
    else:
        if not _qg["passed"]:
            print(f"\n  [OVERRIDE] Quality gate HARD FAIL bypassed (--skip-quality-gate)")

    # 3b1b. Baseline Freshness Gate — blocks stale baselines from reaching Layer 2.
    #        Threshold: 14 days. Cannot be bypassed (no --skip flag by design).
    from tools.baseline_freshness_gate import check_freshness, format_blocked_message
    print(f"\n  --- Baseline Freshness Gate (threshold=14 days) ---")
    _fr = check_freshness(strategy_id, threshold_days=14)
    if _fr.status != "OK":
        print(format_blocked_message(_fr))
        _write_audit_log(strategy_id, profile, "FRESHNESS_BLOCKED",
                         dry_run=dry_run, reason=_fr.message)
        sys.exit(1)
    print(f"  [OK] Baseline age: {_fr.worst_age_days}d (worst across {len(_fr.per_symbol)} symbol(s))")

    # 3b2. Pre-promote validation gate (4-layer) — always runs.
    #       --skip-replay only skips Layer 2 (replay regression).
    #       Layers 1, 3, 4 are mandatory and cannot be bypassed.
    from tools.pre_promote_validator import validate_strategy, print_summary
    print(f"\n  --- Pre-Promote Validation (4-layer) ---")
    vr = validate_strategy(strategy_id, skip_replay=skip_replay)
    if vr.final == "BLOCKED":
        print_summary([vr])
        _write_audit_log(strategy_id, profile, "VALIDATION_BLOCKED",
                         dry_run=dry_run, reason="Pre-promote validation BLOCKED")
        print(f"\n  [VALIDATION] BLOCKED")
        print(f"\n[ABORT] Pre-promote validation BLOCKED — resolve failures before promoting.")
        print(f"  Layers 1, 3, 4 are mandatory. Use --skip-replay to skip Layer 2 only.")
        sys.exit(1)
    elif skip_replay:
        print(f"\n  [VALIDATION] SKIP_REPLAY")
    else:
        print(f"\n  [VALIDATION] PASS")
    return _qg
