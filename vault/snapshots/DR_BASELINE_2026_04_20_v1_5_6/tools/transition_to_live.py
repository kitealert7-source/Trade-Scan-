"""
transition_to_live.py -- Move a strategy from WAITING to LIVE lifecycle.

Validates that the strategy has passed through the full lifecycle:
BURN_IN -> WAITING (with snapshot) -> LIVE. No artifact mutation.

Usage:
    python tools/transition_to_live.py <STRATEGY_ID>
    python tools/transition_to_live.py <STRATEGY_ID> --dry-run

Guards:
    - Strategy must be in portfolio.yaml with lifecycle: WAITING
    - Strategy must have a vault_id
    - WAITING/{ID}_*/vault_ref.json must exist and reference a valid vault
    - Vault snapshot must exist at DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
VAULT_ROOT = PROJECT_ROOT.parent / "DRY_RUN_VAULT"
WAITING_ROOT = VAULT_ROOT / "WAITING"


def _load_portfolio_yaml() -> dict:
    with open(PORTFOLIO_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_portfolio_yaml_raw() -> str:
    with open(PORTFOLIO_YAML, "r", encoding="utf-8") as f:
        return f.read()


def _find_strategy_entries(data: dict, strategy_id: str) -> list[dict]:
    """Find all portfolio.yaml entries matching strategy_id (base or per-symbol)."""
    strategies = (data.get("portfolio") or {}).get("strategies") or []
    return [
        s for s in strategies
        if s.get("id") == strategy_id or s.get("id", "").startswith(strategy_id + "_")
    ]


def _find_waiting_snapshot(strategy_id: str) -> Path | None:
    """Find WAITING/{ID}_*/vault_ref.json. Returns snapshot dir or None."""
    if not WAITING_ROOT.exists():
        return None
    for d in sorted(WAITING_ROOT.iterdir()):
        if d.is_dir() and d.name.startswith(strategy_id + "_"):
            if (d / "vault_ref.json").exists():
                return d
    return None


def to_live(strategy_id: str, dry_run: bool = False) -> dict:
    """Transition strategy from WAITING to LIVE.

    No artifact mutation -- only portfolio.yaml state change.
    """
    print(f"\n{'=' * 60}")
    print(f"TRANSITION TO LIVE: {strategy_id}")
    print(f"{'=' * 60}\n")

    # ── Guard 1: strategy exists in portfolio.yaml ───────────────────────
    data = _load_portfolio_yaml()
    entries = _find_strategy_entries(data, strategy_id)
    if not entries:
        print(f"[ABORT] Strategy '{strategy_id}' not found in portfolio.yaml")
        sys.exit(1)

    # ── Guard 2: lifecycle must be WAITING ────────────────────────────────
    first = entries[0]
    lifecycle = first.get("lifecycle", "")
    if lifecycle != "WAITING":
        print(f"[ABORT] Strategy '{strategy_id}' lifecycle is '{lifecycle}', expected 'WAITING'")
        print(f"  Lifecycle transitions: BURN_IN -> WAITING -> LIVE")
        if lifecycle == "BURN_IN":
            print(f"  Use /to-waiting first: python tools/transition_to_waiting.py {strategy_id} --decision PASS")
        elif lifecycle == "LIVE":
            print(f"  Strategy is already LIVE.")
        elif lifecycle == "LEGACY":
            print(f"  LEGACY entries were promoted before the lifecycle system.")
            print(f"  Re-promote with: python tools/promote_to_burnin.py {strategy_id} --profile <PROFILE>")
        sys.exit(1)

    # ── Guard 3: vault_id must exist ─────────────────────────────────────
    vault_id = first.get("vault_id", "")
    if not vault_id:
        print(f"[ABORT] Strategy '{strategy_id}' has no vault_id in portfolio.yaml")
        sys.exit(1)

    # ── Guard 4: vault snapshot must exist ───────────────────────────────
    vault_strat_path = VAULT_ROOT / vault_id / strategy_id
    if not vault_strat_path.exists():
        print(f"[ABORT] Vault snapshot not found: {vault_strat_path}")
        sys.exit(1)
    if not (vault_strat_path / "meta.json").exists():
        print(f"[ABORT] Vault meta.json not found: {vault_strat_path / 'meta.json'}")
        sys.exit(1)

    # ── Guard 5: WAITING snapshot with valid vault_ref must exist ────────
    waiting_dir = _find_waiting_snapshot(strategy_id)
    if not waiting_dir:
        print(f"[ABORT] No WAITING snapshot found for '{strategy_id}'")
        print(f"  Expected: {WAITING_ROOT / (strategy_id + '_*') / 'vault_ref.json'}")
        print(f"  Use /to-waiting first: python tools/transition_to_waiting.py {strategy_id} --decision PASS")
        sys.exit(1)

    # Validate vault_ref points to correct vault
    vault_ref = json.loads((waiting_dir / "vault_ref.json").read_text(encoding="utf-8"))
    ref_vault_id = vault_ref.get("vault_id", "")
    if ref_vault_id != vault_id:
        print(f"[ABORT] WAITING vault_ref.json vault_id mismatch:")
        print(f"  portfolio.yaml: {vault_id}")
        print(f"  vault_ref.json: {ref_vault_id}")
        sys.exit(1)

    # Check decision was PASS — decision.json MUST exist (written by transition_to_waiting)
    decision_path = waiting_dir / "decision.json"
    if not decision_path.exists():
        print(f"[ABORT] decision.json missing from WAITING snapshot: {waiting_dir}")
        print(f"  Incomplete snapshot — re-run: python tools/transition_to_waiting.py {strategy_id} --decision PASS")
        sys.exit(1)
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    dec = decision.get("decision", "")
    if dec != "PASS":
        print(f"[ABORT] WAITING decision is '{dec}', expected 'PASS'")
        print(f"  Only strategies with decision=PASS can transition to LIVE")
        sys.exit(1)

    profile = first.get("profile", "")

    print(f"  Vault ID:        {vault_id}")
    print(f"  Profile:         {profile}")
    print(f"  WAITING snapshot: {waiting_dir.name}")
    print(f"  Decision:        PASS")
    print(f"  Entries:         {len(entries)}")
    print()
    print(f"  All 5 guards PASSED")

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return {"vault_id": vault_id, "lifecycle": "LIVE"}

    # ── Update portfolio.yaml: enabled=true, lifecycle=LIVE ──────────────
    raw = _load_portfolio_yaml_raw()
    entry_ids = [e["id"] for e in entries]

    lines = raw.split("\n")
    in_target = False
    changes_made = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        for eid in entry_ids:
            if stripped == f'- id: "{eid}"' or stripped == f"- id: {eid}":
                in_target = True
                break
        if in_target and stripped.startswith("- id:") and not any(
            stripped.endswith(f'"{eid}"') or stripped.endswith(eid) for eid in entry_ids
        ):
            in_target = False

        if in_target:
            if stripped.startswith("enabled:"):
                lines[i] = line.replace("enabled: false", "enabled: true")
                changes_made += 1
            elif stripped.startswith("lifecycle:"):
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}lifecycle: LIVE"
                changes_made += 1

    tmp_yaml = PORTFOLIO_YAML.with_suffix(".yaml.tmp")
    with open(tmp_yaml, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_yaml), str(PORTFOLIO_YAML))

    print(f"\n[OK] portfolio.yaml updated ({changes_made} field changes)")
    print(f"     enabled: true, lifecycle: LIVE")
    print(f"\n[NEXT] Restart TS_Execution to activate with full capital allocation.")

    return {
        "vault_id": vault_id,
        "profile": profile,
        "lifecycle": "LIVE",
        "entries_updated": len(entry_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transition strategy from WAITING to LIVE.",
    )
    parser.add_argument("strategy_id", help="Base strategy ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing")
    args = parser.parse_args()
    to_live(args.strategy_id, args.dry_run)


if __name__ == "__main__":
    main()
