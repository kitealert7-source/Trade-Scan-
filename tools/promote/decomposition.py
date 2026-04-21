"""Composite-portfolio decomposition + per-constituent promotion.

  decompose_portfolio(PF_*)  — returns constituent strategy_ids + symbols + run_ids
  promote_composite(PF_*)    — decomposes then promotes each base strategy
                                via the standard promote() path (shim module)
"""

import json
import sys
from collections import OrderedDict
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import STRATEGIES_DIR, RUNS_DIR
from tools.promote.audit import _write_audit_log
from tools.promote.quality_gate import _compute_quality_gate, _print_quality_gate
from tools.promote.yaml_writer import _load_portfolio_yaml, _get_existing_ids


def decompose_portfolio(portfolio_id: str) -> list[dict]:
    """Decompose a composite portfolio (PF_*) into its constituent strategies.

    Reads constituent_run_ids from portfolio_metadata.json (primary) or
    Master_Portfolio_Sheet.xlsx (fallback), then traces each run_id to its
    source strategy via Strategy_Master_Filter.xlsx.

    Returns list of dicts: [{strategy_id, symbol, run_id, per_symbol_id}, ...]
    Raises RuntimeError if the portfolio cannot be decomposed.
    """
    # 1. Read constituent_run_ids from portfolio_metadata.json
    meta_path = STRATEGIES_DIR / portfolio_id / "portfolio_evaluation" / "portfolio_metadata.json"
    constituent_run_ids = None

    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        constituent_run_ids = meta.get("constituent_run_ids", [])

    # Fallback: read from ledger.db (source of truth), then Excel
    if not constituent_run_ids:
        try:
            from tools.ledger_db import read_mps
            df_mps = read_mps()
            if not df_mps.empty and "constituent_run_ids" in df_mps.columns:
                match = df_mps.loc[df_mps["portfolio_id"] == portfolio_id, "constituent_run_ids"]
                if not match.empty and pd.notna(match.values[0]):
                    constituent_run_ids = [r.strip() for r in str(match.values[0]).split(",")]
        except Exception:
            pass  # Fall through to error

    if not constituent_run_ids:
        raise RuntimeError(f"Cannot decompose {portfolio_id}: no constituent_run_ids found")

    # 2. Trace each run_id to source strategy via ledger.db (DB-first, Excel fallback)
    from tools.ledger_db import read_master_filter
    df_mf = read_master_filter()
    if df_mf.empty:
        raise RuntimeError("Cannot trace run_ids: Master Filter is empty (DB and Excel)")

    target_set = set(constituent_run_ids)
    run_map = {}
    for _, row in df_mf.iterrows():
        rid = str(row.get("run_id", ""))
        if rid in target_set:
            run_map[rid] = {
                "per_symbol_id": str(row.get("strategy", "")),
                "symbol": str(row.get("symbol", "")),
            }

    # 3. Build result list, deriving base strategy_id from per-symbol name
    constituents = []
    for rid in constituent_run_ids:
        if rid not in run_map:
            # Fallback: read strategy_id + symbol from run folder directly
            run_dir = RUNS_DIR / rid
            rs_path = run_dir / "run_state.json"
            rm_path = run_dir / "data" / "run_metadata.json"
            if rs_path.exists() and rm_path.exists():
                rs = json.loads(rs_path.read_text(encoding="utf-8"))
                rm = json.loads(rm_path.read_text(encoding="utf-8"))
                fallback_sid = rs.get("strategy_id") or rs.get("directive_id", "")
                fallback_sym = rm.get("symbol", "")
                if fallback_sid and fallback_sym:
                    run_map[rid] = {
                        "per_symbol_id": f"{fallback_sid}_{fallback_sym}",
                        "symbol": fallback_sym,
                    }
                    print(f"  [INFO] run_id {rid[:12]}... recovered from run folder: {fallback_sid} / {fallback_sym}")
                else:
                    print(f"  [WARN] run_id {rid[:12]}... run folder incomplete — skipping")
                    continue
            else:
                print(f"  [WARN] run_id {rid[:12]}... not in Master Filter and no run folder — skipping")
                continue
        info = run_map[rid]
        per_sym_id = info["per_symbol_id"]
        symbol = info["symbol"]

        # Derive base strategy_id: strip trailing _SYMBOL suffix
        if per_sym_id.endswith(f"_{symbol}"):
            base_id = per_sym_id[: -(len(symbol) + 1)]
        else:
            base_id = per_sym_id  # single-symbol: no suffix to strip

        constituents.append({
            "strategy_id": base_id,
            "symbol": symbol,
            "run_id": rid,
            "per_symbol_id": per_sym_id,
        })

    if not constituents:
        raise RuntimeError(
            f"Cannot decompose {portfolio_id}: no run_ids matched in Master Filter"
        )

    return constituents


def promote_composite(portfolio_id: str, profile: str, description: str = "",
                      dry_run: bool = False,
                      skip_quality_gate: bool = False) -> dict:
    """Decompose a composite portfolio and promote each constituent individually.

    For each unique base strategy found in the composite:
    - Runs quality gate (per-constituent, not composite-level)
    - Promotes via the standard promote() path
    - Skips constituents already in portfolio.yaml

    Returns dict with per-constituent results.
    """
    # Lazy import to break the cycle: promote() lives in the CLI shim and
    # imports THIS module via re-export; we import back only at call time.
    from tools.promote_to_burnin import promote

    print(f"\n{'=' * 60}")
    print(f"COMPOSITE PROMOTION: {portfolio_id}")
    print(f"Profile: {profile}")
    print(f"{'=' * 60}\n")

    # 1. Decompose
    try:
        constituents = decompose_portfolio(portfolio_id)
    except RuntimeError as e:
        print(f"[ABORT] {e}")
        sys.exit(1)

    print(f"  Found {len(constituents)} constituent run(s):\n")
    for c in constituents:
        print(f"    {c['strategy_id']:50s}  {c['symbol']:10s}  run={c['run_id'][:12]}...")
    print()

    # 2. Group by base strategy_id (multiple symbols may share a base)
    strategy_groups = OrderedDict()
    for c in constituents:
        sid = c["strategy_id"]
        if sid not in strategy_groups:
            strategy_groups[sid] = []
        strategy_groups[sid].append(c)

    print(f"  {len(strategy_groups)} unique base strategy/strategies to promote:\n")
    for sid, members in strategy_groups.items():
        syms = [m["symbol"] for m in members]
        print(f"    {sid}  ->  {syms}")
    print()

    # 3. Check which are already in portfolio.yaml
    data = _load_portfolio_yaml()
    existing_ids = _get_existing_ids(data)

    # 4. Promote each base strategy
    results = {"portfolio_id": portfolio_id, "constituents": []}
    promoted = 0
    skipped = 0
    failed = 0

    for sid, members in strategy_groups.items():
        print(f"\n{'-' * 50}")
        print(f"  Constituent: {sid}")
        print(f"{'-' * 50}")

        # Check if already promoted (any symbol variant)
        syms = [m["symbol"] for m in members]
        already = []
        for sym in syms:
            entry_id = f"{sid}_{sym}" if len(syms) > 1 else sid
            if entry_id in existing_ids:
                already.append(entry_id)

        if already:
            print(f"  [SKIP] Already in portfolio.yaml: {already}")
            for a in already:
                results["constituents"].append({
                    "strategy_id": sid, "status": "SKIP", "reason": "already_in_portfolio"
                })
            skipped += 1
            continue

        # Run quality gate for this constituent
        qg = _compute_quality_gate(sid)
        _print_quality_gate(qg)

        if not skip_quality_gate and not qg["passed"]:
            print(f"  [BLOCKED] Quality gate HARD FAIL for {sid}")
            results["constituents"].append({
                "strategy_id": sid, "status": "FAIL",
                "reason": "; ".join(qg["hard_fails"]),
                "quality_gate": qg["metrics"],
            })
            _write_audit_log(sid, profile, "COMPOSITE_QG_FAIL",
                             dry_run=dry_run,
                             reason=f"composite={portfolio_id}; " + "; ".join(qg["hard_fails"]),
                             quality_gate=qg)
            failed += 1
            continue

        # Promote this constituent (symbols auto-detected by promote())
        try:
            result = promote(
                sid, profile, description=description or f"Constituent of {portfolio_id}",
                dry_run=dry_run, skip_quality_gate=True,  # already checked above
            )
            results["constituents"].append({
                "strategy_id": sid, "status": "OK",
                "vault_id": result.get("vault_id", ""),
                "entries_added": result.get("entries_added", 0),
                "symbols": result.get("symbols", []),
            })
            promoted += 1
        except SystemExit:
            # promote() calls sys.exit on abort — catch and record
            results["constituents"].append({
                "strategy_id": sid, "status": "FAIL", "reason": "promote_aborted"
            })
            failed += 1

    # 5. Summary
    total_attempted = promoted + failed
    print(f"\n{'=' * 60}")
    print(f"COMPOSITE PROMOTION SUMMARY: {portfolio_id}")
    print(f"{'=' * 60}")
    print(f"  Promoted:  {promoted}")
    print(f"  Skipped:   {skipped} (already in portfolio)")
    print(f"  Failed:    {failed}")
    print(f"  Total:     {len(strategy_groups)} base strategies")
    if total_attempted > 0:
        if failed == 0:
            print(f"\n  [VALIDATION] PASS ({promoted}/{total_attempted})")
        else:
            print(f"\n  [VALIDATION] BLOCKED ({failed}/{total_attempted})")

    # Audit log for composite operation
    _write_audit_log(portfolio_id, profile,
                     "COMPOSITE_DRY_RUN" if dry_run else "COMPOSITE_COMPLETE",
                     dry_run=dry_run,
                     reason=f"promoted={promoted} skipped={skipped} failed={failed}")

    return results
