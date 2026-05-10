"""
validate_portfolio_integrity.py — Audit TS_Execution/portfolio.yaml for governance violations.

Detects:
  1. LIVE entries missing vault_id (manual additions that bypassed promote_to_live.py)
  2. vault_id references pointing to non-existent vault directories
  3. Vault directories missing required files (meta.json, strategy.py)
  4. LIVE entries missing lifecycle field (ambiguous state)
  5. LIVE entries missing profile field
  6. Entries with enabled=true but no lifecycle (LEGACY without explicit marking)
  7. strategy.py missing for any enabled entry
  8. Enabled entries missing promotion_source='promote_to_live' (ungated addition)
  9. Enabled entries missing promotion_timestamp (no audit trail)
 10. promotion_run_id ↔ vault_id lineage mismatch (mismatched snapshots)
 11. strategy_hash drift — strategy.py modified after promotion

Exit codes:
  0 — all checks passed
  1 — violations found (printed to stdout)
  2 — portfolio.yaml not found or unparseable

Usage:
  python tools/validate_portfolio_integrity.py           # full audit
  python tools/validate_portfolio_integrity.py --fix     # report + suggest fixes
"""

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys as _sys
if str(PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(PROJECT_ROOT))
from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT, DRY_RUN_VAULT as VAULT_ROOT
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"


def _load_portfolio() -> list[dict]:
    """Load strategy entries from portfolio.yaml."""
    if not PORTFOLIO_YAML.exists():
        print(f"[ABORT] portfolio.yaml not found: {PORTFOLIO_YAML}")
        sys.exit(2)
    with open(PORTFOLIO_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return (data.get("portfolio") or {}).get("strategies") or []


def validate() -> list[str]:
    """Run all integrity checks. Returns list of violation strings."""
    strategies = _load_portfolio()
    violations = []

    for entry in strategies:
        sid = entry.get("id", "<unknown>")
        enabled = entry.get("enabled", False)
        lifecycle = entry.get("lifecycle", "")
        vault_id = entry.get("vault_id", "")
        profile = entry.get("profile", "")

        # --- Check 1: Enabled entry without lifecycle field ---
        if enabled and not lifecycle:
            violations.append(
                f"[NO_LIFECYCLE] {sid}: enabled=true but no lifecycle field. "
                f"Was this manually added? Set lifecycle explicitly (LEGACY/LIVE)."
            )

        # --- Check 2: LIVE without vault_id ---
        if lifecycle == "LIVE" and not vault_id:
            violations.append(
                f"[NO_VAULT_ID] {sid}: lifecycle=LIVE but missing vault_id. "
                f"This entry bypassed promote_to_live.py. "
                f"Re-promote via: python tools/promote_to_live.py {sid} --profile <PROFILE>"
            )

        # --- Check 2b: Enabled entry without promotion_source ---
        promo_src = entry.get("promotion_source", "")
        if enabled and promo_src != "promote_to_live":
            violations.append(
                f"[NO_PROMOTION_SOURCE] {sid}: promotion_source={promo_src!r} "
                f"(expected 'promote_to_live'). "
                f"This entry was not created by the promotion gate."
            )

        # --- Check 2c: Enabled entry without promotion_timestamp ---
        promo_ts = entry.get("promotion_timestamp", "")
        if enabled and not promo_ts:
            violations.append(
                f"[NO_PROMOTION_TIMESTAMP] {sid}: missing promotion_timestamp. "
                f"No audit trail for when this entry was promoted."
            )

        # --- Check 2d: promotion_run_id ↔ vault_id cross-check ---
        promo_run_id = entry.get("promotion_run_id", "")
        if enabled and promo_run_id and vault_id and "__" in vault_id:
            vault_run_prefix = vault_id.split("__", 1)[1]
            if not promo_run_id.startswith(vault_run_prefix):
                violations.append(
                    f"[LINEAGE_MISMATCH] {sid}: promotion_run_id={promo_run_id[:12]}... "
                    f"does not match vault_id run prefix={vault_run_prefix}. "
                    f"Vault snapshot was created from a different run."
                )

        # --- Check 2e: strategy_hash drift detection ---
        strat_hash = entry.get("strategy_hash", "")
        if enabled and strat_hash and strat_hash.startswith("sha256:"):
            import hashlib
            strat_path = STRATEGIES_DIR / sid / "strategy.py"
            if strat_path.exists():
                current_hash = "sha256:" + hashlib.sha256(
                    strat_path.read_bytes()
                ).hexdigest()
                if current_hash != strat_hash:
                    violations.append(
                        f"[STRATEGY_HASH_DRIFT] {sid}: strategy.py has changed since promotion. "
                        f"Promoted: {strat_hash[:30]}... Current: {current_hash[:30]}... "
                        f"Strategy logic no longer matches the validated version."
                    )

        # --- Check 3: LIVE without profile ---
        if lifecycle == "LIVE" and not profile:
            violations.append(
                f"[NO_PROFILE] {sid}: lifecycle=LIVE but missing profile field. "
                f"Cannot track capital allocation without profile."
            )

        # --- Check 4: vault_id points to non-existent vault ---
        if vault_id:
            vault_path = VAULT_ROOT / vault_id
            if not vault_path.exists():
                violations.append(
                    f"[VAULT_MISSING] {sid}: vault_id={vault_id} but "
                    f"vault directory not found at {vault_path}"
                )
            else:
                # --- Check 5: Vault directory missing required files ---
                # For multi-symbol, base ID is the part before the last _SYMBOL
                # Try exact ID first, then strip trailing _SYMBOL
                base_id = sid
                vault_strat_path = vault_path / base_id
                if not vault_strat_path.exists():
                    # Try stripping symbol suffix (multi-symbol: base_SYMBOL)
                    parts = sid.rsplit("_", 1)
                    if len(parts) == 2:
                        vault_strat_path = vault_path / parts[0]

                if vault_strat_path.exists():
                    for required in ["meta.json", "strategy.py"]:
                        if not (vault_strat_path / required).exists():
                            violations.append(
                                f"[VAULT_INCOMPLETE] {sid}: vault exists but "
                                f"missing {required} at {vault_strat_path}"
                            )
                else:
                    violations.append(
                        f"[VAULT_NO_STRATEGY] {sid}: vault {vault_id} exists but "
                        f"no strategy folder found (tried {sid} and base ID)"
                    )

        # --- Check 6: strategy.py exists for enabled entries ---
        if enabled:
            spy = STRATEGIES_DIR / sid / "strategy.py"
            if not spy.exists():
                violations.append(
                    f"[NO_STRATEGY_PY] {sid}: enabled=true but "
                    f"strategy.py not found at {spy}"
                )

    return violations


def main() -> None:
    print(f"[INTEGRITY] Auditing {PORTFOLIO_YAML.name}...")
    strategies = _load_portfolio()

    # Summary counts
    total = len(strategies)
    enabled = sum(1 for s in strategies if s.get("enabled", False))
    live = sum(1 for s in strategies if s.get("lifecycle") == "LIVE")
    retired = sum(1 for s in strategies if s.get("lifecycle") == "RETIRED")
    legacy = sum(1 for s in strategies if s.get("lifecycle") == "LEGACY")
    no_lc = sum(1 for s in strategies if s.get("enabled") and not s.get("lifecycle"))

    print(f"  Total entries: {total} ({enabled} enabled)")
    print(f"  LIVE: {live}  RETIRED: {retired}  LEGACY: {legacy}")
    if no_lc:
        print(f"  No lifecycle: {no_lc} (governance gap)")

    violations = validate()

    if not violations:
        print(f"[INTEGRITY] ALL CHECKS PASSED — {total} entries clean.")
        sys.exit(0)

    print(f"\n[INTEGRITY] {len(violations)} VIOLATION(S) FOUND:\n")
    for v in violations:
        print(f"  {v}")

    # Categorize
    categories = {}
    for v in violations:
        tag = v.split("]")[0] + "]"
        categories[tag] = categories.get(tag, 0) + 1

    print(f"\n  Summary: {', '.join(f'{tag} x{n}' for tag, n in sorted(categories.items()))}")
    print(f"\n[INTEGRITY] Fix these violations before promoting new strategies.")
    sys.exit(1)


if __name__ == "__main__":
    main()
