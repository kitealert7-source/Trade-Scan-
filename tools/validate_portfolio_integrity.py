"""
validate_portfolio_integrity.py — Audit TS_Execution/portfolio.yaml for governance violations.

Detects:
  1. BURN_IN entries missing vault_id (manual additions that bypassed promote_to_burnin.py)
  2. vault_id references pointing to non-existent vault directories
  3. Vault directories missing required files (meta.json, strategy.py)
  4. BURN_IN entries missing lifecycle field (ambiguous state)
  5. BURN_IN entries missing profile field
  6. Entries with enabled=true but no lifecycle (LEGACY without explicit marking)
  7. strategy.py missing for any enabled entry

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
TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
VAULT_ROOT = PROJECT_ROOT.parent / "DRY_RUN_VAULT"
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
                f"Was this manually added? Set lifecycle explicitly (LEGACY/BURN_IN)."
            )

        # --- Check 2: BURN_IN without vault_id ---
        if lifecycle == "BURN_IN" and not vault_id:
            violations.append(
                f"[NO_VAULT_ID] {sid}: lifecycle=BURN_IN but missing vault_id. "
                f"This entry bypassed promote_to_burnin.py. "
                f"Re-promote via: python tools/promote_to_burnin.py {sid} --profile <PROFILE>"
            )

        # --- Check 3: BURN_IN without profile ---
        if lifecycle == "BURN_IN" and not profile:
            violations.append(
                f"[NO_PROFILE] {sid}: lifecycle=BURN_IN but missing profile field. "
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
    burn_in = sum(1 for s in strategies if s.get("lifecycle") == "BURN_IN")
    legacy = sum(1 for s in strategies if s.get("lifecycle") == "LEGACY")
    waiting = sum(1 for s in strategies if s.get("lifecycle") == "WAITING")
    live = sum(1 for s in strategies if s.get("lifecycle") == "LIVE")
    no_lc = sum(1 for s in strategies if s.get("enabled") and not s.get("lifecycle"))

    print(f"  Total entries: {total} ({enabled} enabled)")
    print(f"  BURN_IN: {burn_in}  LEGACY: {legacy}  WAITING: {waiting}  LIVE: {live}")
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
