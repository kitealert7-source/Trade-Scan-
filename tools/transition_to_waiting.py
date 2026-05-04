"""
transition_to_waiting.py -- Move a strategy from BURN_IN to WAITING lifecycle.

Creates a lightweight WAITING snapshot in DRY_RUN_VAULT/WAITING/{ID}_{date}/
containing only reference + summary (NO baseline copy -- the vault_id points to
the full snapshot). Updates portfolio.yaml: enabled=false, lifecycle=WAITING.

Usage:
    python tools/transition_to_waiting.py <STRATEGY_ID> --decision PASS
    python tools/transition_to_waiting.py <STRATEGY_ID> --decision PASS --notes "strong edge"
    python tools/transition_to_waiting.py <STRATEGY_ID> --decision PASS --dry-run

Requires:
    - Strategy in portfolio.yaml with lifecycle: BURN_IN and a vault_id
    - Valid vault snapshot at DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT, DRY_RUN_VAULT as VAULT_ROOT

PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
WAITING_ROOT = VAULT_ROOT / "WAITING"


def _load_portfolio_yaml_raw() -> str:
    """Load portfolio.yaml as raw text."""
    with open(PORTFOLIO_YAML, "r", encoding="utf-8") as f:
        return f.read()


def _load_portfolio_yaml() -> dict:
    """Load portfolio.yaml as parsed dict."""
    with open(PORTFOLIO_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _find_strategy_entries(data: dict, strategy_id: str) -> list[dict]:
    """Find all portfolio.yaml entries matching strategy_id (base or per-symbol)."""
    strategies = (data.get("portfolio") or {}).get("strategies") or []
    matches = []
    for s in strategies:
        sid = s.get("id", "")
        if sid == strategy_id or sid.startswith(strategy_id + "_"):
            matches.append(s)
    return matches


def _validate_burnin_state(entries: list[dict], strategy_id: str) -> tuple[str, str]:
    """Validate entries are in BURN_IN lifecycle with vault_id.

    Returns (vault_id, profile). Exits on failure.
    """
    if not entries:
        print(f"[ABORT] Strategy '{strategy_id}' not found in portfolio.yaml")
        sys.exit(1)

    first = entries[0]
    vault_id = first.get("vault_id", "")
    profile = first.get("profile", "")
    lifecycle = first.get("lifecycle", "")

    if not vault_id:
        print(f"[ABORT] Strategy '{strategy_id}' has no vault_id in portfolio.yaml")
        print(f"  This strategy was promoted before vault_id tracking was implemented.")
        print(f"  Re-promote with: python tools/promote_to_burnin.py {strategy_id} --profile <PROFILE>")
        sys.exit(1)

    if lifecycle != "BURN_IN":
        print(f"[ABORT] Strategy '{strategy_id}' lifecycle is '{lifecycle}', expected 'BURN_IN'")
        sys.exit(1)

    # Validate vault exists
    vault_strat_path = VAULT_ROOT / vault_id / strategy_id
    if not vault_strat_path.exists():
        print(f"[ABORT] Vault snapshot not found: {vault_strat_path}")
        sys.exit(1)

    meta_path = vault_strat_path / "meta.json"
    if not meta_path.exists():
        print(f"[ABORT] Vault meta.json not found: {meta_path}")
        sys.exit(1)

    return vault_id, profile


def _validate_waiting_invariant(strategy_id: str) -> bool:
    """Check if a valid WAITING snapshot exists for a strategy.

    Validates both vault_ref.json (vault linkage) AND decision.json (operator
    decision record).  An incomplete snapshot — one that has a vault ref but
    no decision — is treated as invalid to prevent silent promotion gaps.

    Returns True if valid, False if missing/invalid.
    """
    if not WAITING_ROOT.exists():
        return False
    for d in WAITING_ROOT.iterdir():
        if d.is_dir() and d.name.startswith(strategy_id + "_"):
            ref_path = d / "vault_ref.json"
            decision_path = d / "decision.json"
            if not ref_path.exists():
                continue
            if not decision_path.exists():
                print(f"[WARN] Incomplete WAITING snapshot for {strategy_id}: missing decision.json in {d.name}")
                continue
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
            vault_id = ref.get("vault_id", "")
            if vault_id and (VAULT_ROOT / vault_id / strategy_id).exists():
                return True
    return False


def validate_waiting_strategies() -> list[str]:
    """Hard invariant check: every WAITING strategy must have a valid snapshot.

    Returns list of strategy IDs that FAIL the check.
    Can be called at startup or by workflow.
    """
    data = _load_portfolio_yaml()
    strategies = (data.get("portfolio") or {}).get("strategies") or []
    failures = []

    seen_bases = set()
    for s in strategies:
        lifecycle = s.get("lifecycle", "")
        if lifecycle != "WAITING":
            continue

        sid = s.get("id", "")
        # For multi-symbol entries, extract base ID
        # Match on the first entry only (all share same vault)
        vault_id = s.get("vault_id", "")
        if not vault_id:
            failures.append(f"{sid}: no vault_id")
            continue

        # Determine base strategy ID (strip _SYMBOL suffix if present)
        # We check the WAITING folder using base ID
        base_id = sid
        # Heuristic: if the vault has this exact ID, use it; otherwise try stripping suffix
        if not (VAULT_ROOT / vault_id / sid).exists():
            # Try without last _SYMBOL suffix
            parts = sid.rsplit("_", 1)
            if len(parts) == 2 and (VAULT_ROOT / vault_id / parts[0]).exists():
                base_id = parts[0]

        if base_id in seen_bases:
            continue
        seen_bases.add(base_id)

        # Check vault snapshot exists
        if not (VAULT_ROOT / vault_id / base_id / "meta.json").exists():
            failures.append(f"{base_id}: vault snapshot missing ({vault_id})")
            continue

        # Check WAITING snapshot exists
        if not _validate_waiting_invariant(base_id):
            failures.append(f"{base_id}: WAITING snapshot missing")

    return failures


def transition(strategy_id: str, decision: str, notes: str = "",
               burnin_trades: int = 0, burnin_pf: float = 0.0,
               burnin_wr: float = 0.0, burnin_dd: float = 0.0,
               dry_run: bool = False) -> dict:
    """Transition a strategy from BURN_IN to WAITING.

    Creates WAITING/{ID}_{date}/ with vault_ref.json + decision.json.
    Updates portfolio.yaml: enabled=false, lifecycle=WAITING.
    """
    print(f"\n{'=' * 60}")
    print(f"TRANSITION TO WAITING: {strategy_id}")
    print(f"Decision: {decision}")
    print(f"{'=' * 60}\n")

    # 1. Validate current state
    data = _load_portfolio_yaml()
    entries = _find_strategy_entries(data, strategy_id)
    vault_id, profile = _validate_burnin_state(entries, strategy_id)

    # Read run_id from vault meta
    meta_path = VAULT_ROOT / vault_id / strategy_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    run_id = meta.get("run_id", "unknown")

    print(f"  Vault ID:  {vault_id}")
    print(f"  Run ID:    {run_id}")
    print(f"  Profile:   {profile}")
    print(f"  Entries:   {len(entries)} (in portfolio.yaml)")

    # 2. Create WAITING snapshot directory
    date_str = datetime.now().strftime("%Y_%m_%d")
    waiting_id = f"{strategy_id}_{date_str}"
    waiting_dir = WAITING_ROOT / waiting_id

    if waiting_dir.exists():
        print(f"[ABORT] WAITING snapshot already exists: {waiting_dir}")
        sys.exit(1)

    # 3. Build vault_ref.json (pointer to full vault, NO data copy)
    vault_ref = {
        "strategy_id": strategy_id,
        "vault_id": vault_id,
        "run_id": run_id,
        "profile": profile,
        "vault_path": str(VAULT_ROOT / vault_id / strategy_id),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }

    # 4. Build decision.json
    decision_data = {
        "strategy_id": strategy_id,
        "decision": decision.upper(),
        "decided_by": "human",
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "vault_id": vault_id,
        "run_id": run_id,
        "profile": profile,
        "notes": notes,
    }

    # 5. Build burnin_summary.json
    burnin_summary = {
        "strategy_id": strategy_id,
        "vault_id": vault_id,
        "burnin_start": "",
        "burnin_end": datetime.now().strftime("%Y-%m-%d"),
        "total_trades": burnin_trades,
        "profit_factor": burnin_pf,
        "win_rate": burnin_wr,
        "max_drawdown_pct": burnin_dd,
        "source": "manual (provide via --burnin-* flags or edit after creation)",
    }

    print(f"\n  --- WAITING snapshot ---")
    print(f"  Location:  {waiting_dir}")
    print(f"  vault_ref.json -> {vault_id}")
    print(f"  decision.json  -> {decision.upper()}")
    print(f"  burnin_summary.json")

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return {"waiting_id": waiting_id, "vault_id": vault_id}

    # 6. Write WAITING snapshot (3 files only -- no data copy)
    waiting_dir.mkdir(parents=True)
    (waiting_dir / "vault_ref.json").write_text(
        json.dumps(vault_ref, indent=2), encoding="utf-8"
    )
    (waiting_dir / "decision.json").write_text(
        json.dumps(decision_data, indent=2), encoding="utf-8"
    )
    (waiting_dir / "burnin_summary.json").write_text(
        json.dumps(burnin_summary, indent=2), encoding="utf-8"
    )
    print(f"  [OK] 3 files written to {waiting_dir}")

    # 7. Update portfolio.yaml: enabled=false, lifecycle=WAITING
    raw = _load_portfolio_yaml_raw()
    # Find all entry IDs for this strategy
    entry_ids = [e["id"] for e in entries]
    for eid in entry_ids:
        # Replace enabled: true -> enabled: false for this entry
        # Match the id line and then find the enabled/lifecycle lines after it
        # Use line-by-line approach for safety
        pass

    # Line-by-line portfolio.yaml update
    lines = raw.split("\n")
    in_target = False
    changes_made = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Detect if we're entering a target entry
        for eid in entry_ids:
            if stripped == f'- id: "{eid}"' or stripped == f"- id: {eid}":
                in_target = True
                break
        # Detect if we've left the entry (next entry or end)
        if in_target and stripped.startswith("- id:") and not any(
            stripped.endswith(f'"{eid}"') or stripped.endswith(eid) for eid in entry_ids
        ):
            in_target = False

        if in_target:
            if stripped.startswith("enabled:"):
                lines[i] = line.replace("enabled: true", "enabled: false")
                changes_made += 1
            elif stripped.startswith("lifecycle:"):
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}lifecycle: WAITING"
                changes_made += 1

    tmp_yaml = PORTFOLIO_YAML.with_suffix(".yaml.tmp")
    with open(tmp_yaml, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_yaml), str(PORTFOLIO_YAML))

    print(f"  [OK] portfolio.yaml updated ({changes_made} field changes across {len(entry_ids)} entries)")
    print(f"       enabled: false, lifecycle: WAITING")

    # 8. Validate invariant — hard fail if the snapshot we just created is incomplete.
    #    This catches partial writes, missing decision.json, or vault linkage gaps.
    failures = validate_waiting_strategies()
    if failures:
        print(f"\n[FATAL] WAITING invariant check FAILED after transition:")
        for f_msg in failures:
            print(f"  - {f_msg}")
        raise RuntimeError(
            f"WAITING snapshot incomplete after transition for {strategy_id}. "
            f"{len(failures)} invariant violation(s). Snapshot may need regeneration."
        )
    else:
        print(f"\n  [OK] WAITING invariant check passed")

    print(f"\n{'=' * 60}")
    print(f"WAITING snapshot: {waiting_id}")
    print(f"Vault reference:  {vault_id}")
    print(f"Decision:         {decision.upper()}")
    print(f"{'=' * 60}")

    return {
        "waiting_id": waiting_id,
        "vault_id": vault_id,
        "run_id": run_id,
        "decision": decision.upper(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transition strategy from BURN_IN to WAITING.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("strategy_id", nargs="?", default=None,
                        help="Base strategy ID")
    parser.add_argument("--decision", choices=["PASS", "FAIL", "HOLD"],
                        help="Burn-in decision (PASS/FAIL/HOLD)")
    parser.add_argument("--notes", default="",
                        help="Decision rationale")
    parser.add_argument("--burnin-trades", type=int, default=0,
                        help="Total trades observed during burn-in")
    parser.add_argument("--burnin-pf", type=float, default=0.0,
                        help="Burn-in profit factor")
    parser.add_argument("--burnin-wr", type=float, default=0.0,
                        help="Burn-in win rate (0-1)")
    parser.add_argument("--burnin-dd", type=float, default=0.0,
                        help="Burn-in max drawdown pct")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only run WAITING invariant check, no transition")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing")

    args = parser.parse_args()

    if args.validate_only:
        failures = validate_waiting_strategies()
        if failures:
            print(f"[FAIL] {len(failures)} WAITING invariant violation(s):")
            for f_msg in failures:
                print(f"  - {f_msg}")
            sys.exit(1)
        else:
            print("[OK] All WAITING strategies have valid snapshots and vault references.")
            sys.exit(0)

    if not args.strategy_id:
        parser.error("strategy_id is required (unless using --validate-only)")
    if not args.decision:
        parser.error("--decision is required (unless using --validate-only)")

    transition(
        args.strategy_id,
        decision=args.decision,
        notes=args.notes,
        burnin_trades=args.burnin_trades,
        burnin_pf=args.burnin_pf,
        burnin_wr=args.burnin_wr,
        burnin_dd=args.burnin_dd,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
