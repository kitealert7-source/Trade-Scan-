"""
promote_to_burnin.py -- Promote strategy to TS_Execution/portfolio.yaml with
vault snapshot, explicit artifact linkage, and burn-in lifecycle metadata.

This is the ONLY tool that writes vault_id, profile, and lifecycle fields into
portfolio.yaml. It chains: run_id lookup -> vault snapshot -> portfolio.yaml edit.

Usage:
    python tools/promote_to_burnin.py <STRATEGY_ID> --profile PROFILE
    python tools/promote_to_burnin.py <STRATEGY_ID> --profile PROFILE --dry-run
    python tools/promote_to_burnin.py PF_XXXX --composite --profile PROFILE --dry-run
    python tools/promote_to_burnin.py --batch --profile PROFILE --dry-run

Requires:
    - TradeScan_State/strategies/{ID}/portfolio_evaluation/ exists
    - TradeScan_State/backtests/{ID}_*/ exist (determines symbols)
    - strategies/{ID}/strategy.py exists in Trade_Scan
    - Strategy NOT already in portfolio.yaml
    - A completed pipeline run exists in TradeScan_State/runs/

Multi-symbol: If backtests/{ID}_{SYMBOL1}/, {ID}_{SYMBOL2}/ exist, creates one
portfolio.yaml entry per symbol using per-symbol strategy copies.
"""
# Orchestration only — logic lives in `tools/promote/` submodules:
#   metadata, metrics, quality_gate, audit, strategy_files,
#   yaml_writer (portfolio.yaml authority), preflight, decomposition.

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import STATE_ROOT
from tools.pipeline_utils import find_run_id_for_directive

# ── Re-exports: preserve external import contract ────────────────────────────
#   tools/promote_readiness.py imports from this module path:
#     _compute_quality_gate, _load_portfolio_yaml, _get_existing_ids,
#     decompose_portfolio
#   Other callers may rely on: read_strategy_metadata, promote_composite,
#     preflight, promote.
from tools.promote.audit import _write_audit_log  # noqa: F401
from tools.promote.decomposition import decompose_portfolio, promote_composite  # noqa: F401
from tools.promote.metadata import (  # noqa: F401
    ARCHETYPE_RULES,
    _detect_symbols,
    _detect_timeframe,
    _filter_symbols_by_expectancy,
    _infer_archetype,
    _normalize_timeframe,
    _read_symbol_expectancy,
    read_strategy_metadata,
)
from tools.promote.metrics import _read_backtest_metrics, _read_profile_metrics  # noqa: F401
from tools.promote.preflight import _run_preflight, preflight  # noqa: F401
from tools.promote.quality_gate import _compute_quality_gate, _print_quality_gate  # noqa: F401
from tools.promote.strategy_files import (  # noqa: F401
    _recover_strategy_py,
    _snapshot_to_vault,
    _validate_strategy_files,
)
from tools.promote.yaml_writer import (  # noqa: F401
    BURN_IN_REGISTRY,
    DEFAULT_GATES,
    LIFECYCLE_BURN_IN,
    LIFECYCLE_DISABLED,
    LIFECYCLE_LEGACY,
    LIFECYCLE_LIVE,
    LIFECYCLE_WAITING,
    PORTFOLIO_YAML,
    TS_EXEC_ROOT,
    VAULT_ROOT,
    _build_comment_block,
    _build_yaml_entry,
    _compute_strategy_hash,
    _get_existing_ids,
    _load_portfolio_yaml,
    _update_burn_in_registry,
    _update_registry,
    _write_portfolio_yaml,
)


# ── Main promote orchestrator ────────────────────────────────────────────────

def promote(strategy_id: str, profile: str, description: str = "",
            dry_run: bool = False, symbols_filter: list[str] | None = None,
            upgrade_legacy: bool = False,
            skip_quality_gate: bool = False,
            skip_replay: bool = False) -> dict:
    """Promote a strategy: lookup run_id -> vault snapshot -> portfolio.yaml edit.

    Args:
        symbols_filter: If provided, only include these symbols in portfolio.yaml.
                        All symbols still go to vault (complete research record).
        upgrade_legacy: If True, replace existing LEGACY entries in-place
                        instead of aborting on duplicates.
        skip_quality_gate: If True, skip the 6-metric edge quality gate.

    Returns dict with vault_id, run_id, entries_added, symbols.
    """
    print(f"\n{'=' * 60}")
    print(f"PROMOTE TO BURN-IN: {strategy_id}")
    print(f"Profile: {profile}")
    print(f"{'=' * 60}\n")

    # 1. Load current portfolio.yaml and check duplicates
    data = _load_portfolio_yaml()
    existing_ids = _get_existing_ids(data)

    # 2. Detect symbols
    symbols = _detect_symbols(strategy_id)
    is_multi = len(symbols) > 1
    symbol_names = [s["symbol"] for s in symbols]

    if is_multi:
        entry_ids = [f"{strategy_id}_{s['symbol']}" for s in symbols]
    else:
        entry_ids = [strategy_id]

    _legacy_ids_to_remove = set()  # populated by --upgrade-legacy
    dupes = [eid for eid in entry_ids if eid in existing_ids]
    if dupes:
        strategies = (data.get("portfolio") or {}).get("strategies") or []
        legacy_dupes = []
        non_legacy_dupes = []
        for eid in dupes:
            for s in strategies:
                if s.get("id") == eid:
                    lc = s.get("lifecycle", "none")
                    if lc == "LEGACY" and upgrade_legacy:
                        legacy_dupes.append(eid)
                        print(f"  [UPGRADE] Will replace LEGACY entry: {eid}")
                    else:
                        non_legacy_dupes.append(eid)
                        print(f"[ABORT] Already promoted: {eid}")
                        print(f"  vault_id:  {s.get('vault_id', 'none')}")
                        print(f"  lifecycle: {lc}")
                    break
        if non_legacy_dupes:
            print(f"\nTo re-promote, first remove existing entries from portfolio.yaml,")
            print(f"or use --upgrade-legacy if the entries have lifecycle=LEGACY.")
            sys.exit(1)
        if legacy_dupes:
            _legacy_ids_to_remove = set(legacy_dupes)
            print(f"  Will upgrade {len(legacy_dupes)} LEGACY entries to BURN_IN")

    # 3. Validate files exist
    _validate_strategy_files(strategy_id, symbols)

    # 3b-3b2. Preflight: quality gate + freshness gate + pre-promote validator
    _qg = _run_preflight(strategy_id, profile, dry_run, skip_quality_gate, skip_replay)

    # 3c. Apply --symbols filter (restrict which symbols go to portfolio.yaml)
    if symbols_filter:
        allowed = set(s.upper() for s in symbols_filter)
        symbols = [s for s in symbols if s["symbol"].upper() in allowed]
        if not symbols:
            print(f"[ABORT] No matching symbols after --symbols filter: {symbols_filter}")
            sys.exit(1)
        symbol_names = [s["symbol"] for s in symbols]
        print(f"  Filtered symbols: {symbol_names}")

    # 3d. Per-symbol expectancy gate — REMOVED.
    #     Now covered by Layer 3 of pre_promote_validator.py (expectancy check
    #     per asset class, single source: results_standard.csv).
    _all_symbols_for_vault = _detect_symbols(strategy_id)  # full set for vault

    # 4. Lookup run_id from directive_id
    print(f"  Looking up run_id for directive: {strategy_id}")
    run_id = find_run_id_for_directive(strategy_id)
    if not run_id:
        print(f"[ABORT] No completed pipeline run found for {strategy_id}")
        print(f"  Searched: {STATE_ROOT / 'runs' / '*' / 'run_state.json'}")
        sys.exit(1)
    print(f"  Run ID:    {run_id}")

    # 5. Build vault_id: DRY_RUN_YYYY_MM_DD__{run_id[:8]}
    date_str = datetime.now().strftime("%Y_%m_%d")
    vault_id = f"DRY_RUN_{date_str}__{run_id[:8]}"
    print(f"  Vault ID:  {vault_id}")

    # 6. Detect timeframe and read metrics
    timeframe = _detect_timeframe(strategy_id, symbols)
    metrics = _read_backtest_metrics(strategy_id)
    profile_metrics = _read_profile_metrics(strategy_id, profile)

    print(f"  Symbols:   {symbol_names}")
    print(f"  Timeframe: {timeframe}")
    print(f"  Metrics:   {metrics}")
    if profile_metrics:
        print(f"  Profile:   {profile_metrics}")

    # 7-8. Vault snapshot + hard gate
    _snapshot_to_vault(strategy_id, run_id, profile, vault_id, dry_run)

    # 9. Build the YAML block
    comment_lines = _build_comment_block(
        strategy_id, profile, vault_id, metrics, profile_metrics, description
    )
    yaml_entries = []
    if is_multi:
        for sym_info in symbols:
            sym = sym_info["symbol"]
            entry_id = f"{strategy_id}_{sym}"
            yaml_entries.extend(_build_yaml_entry(entry_id, sym, timeframe, vault_id, profile, run_id=run_id))
            yaml_entries.append("")
    else:
        sym = symbols[0]["symbol"]
        yaml_entries.extend(_build_yaml_entry(strategy_id, sym, timeframe, vault_id, profile, run_id=run_id))

    block = "\n".join(comment_lines + yaml_entries)

    print(f"\n  --- Generated YAML block ---")
    print(block)
    print(f"  --- End block ---\n")

    if dry_run:
        print("[DRY RUN] No changes written to portfolio.yaml.")
        _write_audit_log(strategy_id, profile, "DRY_RUN", dry_run=True,
                         vault_id=vault_id, run_id=run_id, quality_gate=_qg)
        return {"vault_id": vault_id, "run_id": run_id, "entries_added": 0, "symbols": symbol_names}

    entries_added = len(entry_ids)

    # 9a-11a. Atomic write of portfolio.yaml (with optional LEGACY removal)
    _original_yaml = _write_portfolio_yaml(
        strategy_id, profile, vault_id, run_id, entry_ids, block, _legacy_ids_to_remove
    )

    # 11b. Update burn_in_registry.yaml (rollback portfolio.yaml on failure)
    _registry_entry_ids = _update_registry(strategy_id, is_multi, symbols, _original_yaml)

    print(f"[OK] Appended {entries_added} entry/entries to {PORTFOLIO_YAML}")
    print(f"     IDs: {entry_ids}")
    print(f"     vault_id: {vault_id}")
    print(f"     profile: {profile}")
    print(f"     lifecycle: {LIFECYCLE_BURN_IN}")
    print(f"     registry: {len(_registry_entry_ids)} entries added to burn_in_registry.yaml")

    # 10b. Export Excel from DB (Excel = read-only view, never edited directly)
    try:
        from tools.ledger_db import export_master_filter
        export_master_filter()
    except Exception as e:
        print(f"  [WARN] Excel export failed ({e}). Run: python tools/ledger_db.py --export-mf")

    # 11. Audit log (TS_Execution side)
    try:
        ts_exec_audit = TS_EXEC_ROOT / "tools" / "audit_log.py"
        if ts_exec_audit.exists():
            sys.path.insert(0, str(TS_EXEC_ROOT))
            from tools.audit_log import log_action
            extra = {"vault_id": vault_id, "profile": profile, "run_id": run_id}
            if _legacy_ids_to_remove:
                extra["upgraded_from_legacy"] = sorted(_legacy_ids_to_remove)
            log_action(
                "promote",
                entry_ids,
                reason=description or f"Promoted {strategy_id} to BURN_IN",
                tool="promote_to_burnin.py",
                extra=extra,
            )
            print(f"  Audit log entry written.")
    except Exception as e:
        print(f"  [WARN] Audit log failed: {e}")

    # 12. Portfolio integrity check
    integrity_script = PROJECT_ROOT / "tools" / "validate_portfolio_integrity.py"
    if integrity_script.exists():
        print(f"\n  --- Portfolio Integrity Check ---")
        integrity_result = subprocess.run(
            [sys.executable, str(integrity_script)],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        )
        for line in integrity_result.stdout.strip().splitlines():
            if line.startswith("["):
                print(f"  {line}")
        if integrity_result.returncode != 0:
            print(f"  [WARN] Portfolio integrity issues detected. Review above.")

    # Audit log (Trade_Scan side)
    _write_audit_log(strategy_id, profile, "SUCCESS", dry_run=False,
                     vault_id=vault_id, run_id=run_id, quality_gate=_qg)

    # 14. CONSISTENCY ASSERTION — portfolio.yaml must carry a run_id for every
    #     enabled entry, and they must be unique. (Post-2026-04-16 the DB no
    #     longer mirrors run_ids, so the cross-store check was retired.)
    print(f"\n  --- Consistency Check ---")
    try:
        _yaml_data = yaml.safe_load(Path(PORTFOLIO_YAML).read_text(encoding="utf-8"))
        _yaml_run_ids_list = []
        _missing_run_id = []
        for s in _yaml_data.get("portfolio", {}).get("strategies", []):
            if s.get("enabled", False):
                _rid = s.get("run_id", "")
                if _rid:
                    _yaml_run_ids_list.append(str(_rid))
                else:
                    _missing_run_id.append(s.get("id", "<no-id>"))
        _yaml_run_ids = set(_yaml_run_ids_list)

        if _missing_run_id:
            print(f"  [ERROR] {len(_missing_run_id)} enabled YAML entrie(s) "
                  f"missing run_id:")
            for _id in _missing_run_id:
                print(f"    - {_id}")

        if len(_yaml_run_ids_list) != len(_yaml_run_ids):
            _dupes = [r for r in _yaml_run_ids_list if _yaml_run_ids_list.count(r) > 1]
            print(f"  [ERROR] Duplicate run_ids in YAML: {sorted(set(_dupes))}")

        if not _missing_run_id and len(_yaml_run_ids_list) == len(_yaml_run_ids):
            print(f"  [OK] portfolio.yaml: {len(_yaml_run_ids)} enabled entries, "
                  f"all with unique run_ids.")
    except Exception as e:
        print(f"  [WARN] Consistency check failed ({e}).")

    print(f"\n[NEXT] Restart TS_Execution to pick up new strategies.")
    print(f"       Verify: cd ../TS_Execution && python src/main.py --phase 0")

    return {
        "vault_id": vault_id,
        "run_id": run_id,
        "entries_added": entries_added,
        "symbols": symbol_names,
        "entry_ids": entry_ids,
    }


# ── Batch driver ────────────────────────────────────────────────────────────

def _run_batch(profile: str, dry_run: bool = False,
               core_only: bool = True,
               skip_quality_gate: bool = False) -> None:
    """Scan CORE (+ optionally WATCH) strategies and promote all that pass gates.

    Uses promote_readiness.py scanner to find candidates, then promotes each
    passing strategy individually.
    """
    from tools.promote_readiness import build_readiness_report

    label = "CORE" if core_only else "CORE + WATCH"
    print(f"\n{'=' * 60}")
    print(f"BATCH PROMOTION: {label} strategies")
    print(f"Profile: {profile}")
    print(f"Dry run: {dry_run}")
    print(f"{'=' * 60}\n")

    report = build_readiness_report(core_only=core_only)

    # Filter to promotable non-composite strategies
    candidates = [
        r for r in report
        if r["ready"] and not r.get("is_composite")
    ]

    # Also report blocked
    # Status string returned by promote_readiness._check_portfolio_yaml.
    # "IN_YAML" means the strategy is already deployed in portfolio.yaml —
    # nothing to promote. Renamed from the ambiguous "IN_PORTFOLIO" on
    # 2026-04-16 to avoid collision with the retired DB column of the
    # same name.
    blocked = [
        r for r in report
        if not r["ready"] and not r.get("is_composite")
        and r["checks"]["portfolio_yaml"] != "IN_YAML"
    ]
    in_portfolio = [
        r for r in report
        if not r.get("is_composite")
        and r["checks"]["portfolio_yaml"] == "IN_YAML"
    ]

    print(f"  Scan results:")
    print(f"    Ready to promote:     {len(candidates)}")
    print(f"    Already in portfolio: {len(in_portfolio)}")
    print(f"    Blocked:              {len(blocked)}")
    print()

    if not candidates:
        print("  No strategies ready for batch promotion.")
        return

    print(f"  Candidates:")
    for c in candidates:
        qg = c["checks"]["quality_gate"]
        print(f"    {c['classification']:5s}  {c['strategy_id']:55s}  QG={qg}")
    print()

    # Promote each candidate
    promoted = 0
    failed = 0
    for c in candidates:
        sid = c["strategy_id"]
        print(f"\n{'-' * 50}")
        print(f"  Batch promoting: {sid}")
        print(f"{'-' * 50}")

        try:
            result = promote(
                sid, profile, description="Batch promotion",
                dry_run=dry_run, skip_quality_gate=skip_quality_gate,
            )
            promoted += 1
        except SystemExit:
            print(f"  [BATCH] Promote aborted for {sid}")
            failed += 1

    total_attempted = promoted + failed
    print(f"\n{'=' * 60}")
    print(f"BATCH PROMOTION SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Promoted:  {promoted}")
    print(f"  Failed:    {failed}")
    print(f"  Skipped:   {len(in_portfolio)} (already in portfolio)")
    print(f"  Blocked:   {len(blocked)} (failed readiness checks)")
    print(f"  Total scanned: {len(report)} ({label})")
    if total_attempted > 0:
        if failed == 0:
            print(f"\n  [VALIDATION] PASS ({promoted}/{total_attempted})")
        else:
            print(f"\n  [VALIDATION] BLOCKED ({failed}/{total_attempted})")


def main() -> None:
    # --- Direct CLI gate: all production usage goes through portfolio_interpreter ---
    if "--allow-direct" not in sys.argv:
        print("ERROR: Direct CLI usage disabled.")
        print("Use Control Panel (Control_Panel.bat) -> option 4 to promote.")
        print("Pass --allow-direct to override (advanced/debug only).")
        return
    sys.argv = [a for a in sys.argv if a != "--allow-direct"]

    parser = argparse.ArgumentParser(
        description="Promote strategy to burn-in: vault snapshot + portfolio.yaml edit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("strategy_id", nargs="?", default=None,
                        help="Strategy ID or PF_* composite portfolio ID "
                             "(not required for --batch)")
    parser.add_argument("--profile", default="RAW_MIN_LOT_V1",
                        help="Capital profile name (default: RAW_MIN_LOT_V1, the active "
                             "deployment policy). Multi-profile research comparison stays "
                             "in capital_wrapper / Step 7 selector — production sizing is "
                             "always 0.01 fixed lot via TS_Execution fixed_lot config.")
    parser.add_argument("--description", default="",
                        help="One-line strategy description for the comment block")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing vault or portfolio.yaml")
    parser.add_argument("--preflight", action="store_true",
                        help="Run all precondition checks and print readiness report. "
                             "Does not promote.")
    parser.add_argument("--composite", action="store_true",
                        help="Decompose a PF_* composite portfolio and promote each "
                             "constituent strategy individually. Requires a PF_* ID.")
    parser.add_argument("--batch", action="store_true",
                        help="Scan all CORE strategies from FSP, run quality gate, "
                             "and promote all passing strategies. Requires --profile.")
    parser.add_argument("--batch-all", action="store_true",
                        help="Like --batch but includes WATCH strategies too.")
    parser.add_argument("--skip-quality-gate", action="store_true",
                        help="Bypass the 6-metric quality gate (not recommended). "
                             "Gate results are still printed for review.")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbol filter (e.g., AUDJPY,EURUSD). "
                             "Only these symbols are added to portfolio.yaml; all "
                             "symbols still go to vault.")
    parser.add_argument("--upgrade-legacy", action="store_true",
                        help="Replace existing LEGACY entries with fresh BURN_IN entries. "
                             "Without this flag, duplicate IDs abort the promote.")
    parser.add_argument("--skip-replay", action="store_true",
                        help="Skip Layer 2 (replay regression) of the pre-promote validator. "
                             "Layers 1, 3, 4 always run and cannot be bypassed.")

    args = parser.parse_args()

    # Deployment policy: RAW_MIN_LOT_V1 is the only production profile.
    # Allow override for research/diagnostic promotions but make the deviation
    # visible in the promotion log.
    if args.profile != "RAW_MIN_LOT_V1":
        print(f"  [WARN] --profile={args.profile} differs from deployment policy "
              f"RAW_MIN_LOT_V1. Production sizing in TS_Execution is fixed-lot 0.01 "
              f"regardless of this label; the slot's profile field is metadata only.")

    # -- Batch mode -------------------------------------------------------
    if args.batch or args.batch_all:
        if not args.profile:
            parser.error("--profile is required for batch promotion")
        _run_batch(args.profile, args.dry_run,
                   core_only=not args.batch_all,
                   skip_quality_gate=args.skip_quality_gate)
        return

    # All other modes require strategy_id
    if not args.strategy_id:
        parser.error("strategy_id is required (or use --batch)")

    if args.preflight:
        preflight(args.strategy_id)
        return

    if args.composite:
        if not args.strategy_id.startswith("PF_"):
            parser.error("--composite requires a PF_* portfolio ID")
        if not args.profile:
            parser.error("--profile is required for composite promotion")
        promote_composite(args.strategy_id, args.profile, args.description,
                          args.dry_run, skip_quality_gate=args.skip_quality_gate)
        return

    if not args.profile:
        parser.error("--profile is required for promotion (not needed with --preflight)")

    symbols_filter = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    promote(args.strategy_id, args.profile, args.description, args.dry_run,
            symbols_filter=symbols_filter, upgrade_legacy=args.upgrade_legacy,
            skip_quality_gate=args.skip_quality_gate,
            skip_replay=args.skip_replay)


if __name__ == "__main__":
    main()
