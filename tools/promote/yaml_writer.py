"""portfolio.yaml + burn_in_registry.yaml authority.

This module is the ONLY writer of:
  - {TS_Execution}/portfolio.yaml       (via _write_portfolio_yaml)
  - {TS_Execution}/burn_in_registry.yaml (via _update_burn_in_registry + _update_registry)

All other modules must NOT write these files directly — route through this module.
Owns constants PORTFOLIO_YAML, BURN_IN_REGISTRY, VAULT_ROOT, LIFECYCLE_*, DEFAULT_GATES
that are shared across the promote package.
"""

import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Module-level constants (shared across the promote package).
PROJECT_ROOT = _PROJECT_ROOT
TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
BURN_IN_REGISTRY = TS_EXEC_ROOT / "burn_in_registry.yaml"
VAULT_ROOT = PROJECT_ROOT.parent / "DRY_RUN_VAULT"

# ── Lifecycle values ─────────────────────────────────────────────────────────
LIFECYCLE_LEGACY   = "LEGACY"
LIFECYCLE_BURN_IN  = "BURN_IN"
LIFECYCLE_WAITING  = "WAITING"
LIFECYCLE_LIVE     = "LIVE"
LIFECYCLE_DISABLED = "DISABLED"

# ── Default burn-in gates ────────────────────────────────────────────────────
DEFAULT_GATES = {
    "duration":   "90 trades OR 60 days (whichever first) at minimum lot",
    "pass_gates": "PF>=1.20 (soft>=1.10), WR>=50%, MaxDD<=10%, fill_rate>=85%",
    "abort_gates": "PF<1.10 after 50 trades, DD>12%, fill_rate<80%, 3 consec losing weeks",
}


# ── Portfolio YAML helpers (read-side) ──────────────────────────────────────

def _load_portfolio_yaml() -> dict:
    """Load existing portfolio.yaml. Abort if missing."""
    if not PORTFOLIO_YAML.exists():
        print(f"[ABORT] portfolio.yaml not found: {PORTFOLIO_YAML}")
        sys.exit(1)
    with open(PORTFOLIO_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_existing_ids(data: dict) -> set:
    """Return set of strategy IDs already in portfolio.yaml."""
    strategies = (data.get("portfolio") or {}).get("strategies") or []
    return {s["id"] for s in strategies if "id" in s}


# ── YAML block builders ─────────────────────────────────────────────────────

def _build_comment_block(strategy_id: str, profile: str, vault_id: str,
                         metrics: dict, profile_metrics: dict,
                         description: str) -> list[str]:
    """Generate the burn-in comment block for portfolio.yaml."""
    lines = []
    lines.append(f"  # --- BURN-IN: {strategy_id} / {profile} ---")
    lines.append(f"  # Vault: {vault_id}")
    lines.append(f"  # Profile: {profile}")
    if description:
        lines.append(f"  # {description}")

    parts = []
    if metrics.get("trades") != "?":
        parts.append(f"{metrics['trades']} trades")
    if metrics.get("pf") != "?":
        parts.append(f"PF {metrics['pf']}")
    if metrics.get("sharpe") != "?":
        parts.append(f"Sharpe {metrics['sharpe']}")
    if metrics.get("max_dd_pct") != "?":
        parts.append(f"Max DD {metrics['max_dd_pct']}%")
    if metrics.get("ret_dd") != "?":
        parts.append(f"Return/DD {metrics['ret_dd']}")
    if parts:
        lines.append(f"  # Backtest: {', '.join(parts)}")

    if profile_metrics:
        pp = []
        if profile_metrics.get("accepted") != "?":
            pp.append(f"{profile_metrics['accepted']} trades accepted")
        if profile_metrics.get("profile_pf") and profile_metrics["profile_pf"] != 0:
            pp.append(f"PF {profile_metrics['profile_pf']}")
        if profile_metrics.get("recovery") and profile_metrics["recovery"] != 0:
            pp.append(f"Recovery Factor {profile_metrics['recovery']}")
        if profile_metrics.get("rejected_pct") is not None:
            pp.append(f"rejection {profile_metrics['rejected_pct']}%")
        if pp:
            lines.append(f"  # {profile}: {', '.join(pp)}")

    lines.append(f"  # Burn-in: {DEFAULT_GATES['duration']}")
    lines.append(f"  # Pass gates: {DEFAULT_GATES['pass_gates']}")
    lines.append(f"  # Abort gates: {DEFAULT_GATES['abort_gates']}")
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"  # Started: {today} | Observation only -- NO parameter changes during burn-in")
    return lines


def _compute_strategy_hash(entry_id: str) -> str:
    """SHA-256 of strategy.py at promotion time. Proves strategy logic at promotion."""
    strat_path = PROJECT_ROOT / "strategies" / entry_id / "strategy.py"
    if not strat_path.exists():
        return ""
    content = strat_path.read_bytes()
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _build_yaml_entry(entry_id: str, symbol: str, timeframe: str,
                      vault_id: str, profile: str,
                      run_id: str = "") -> list[str]:
    """Build the YAML entry lines for one strategy slot.

    Includes vault_id, profile, lifecycle, run_id, and promotion lineage fields.
    TS_Execution silently ignores unknown fields (permissive dict parsing).

    Lineage fields (enforced by TS_Execution startup invariant):
      - promotion_source: always "promote_to_burnin" (required for startup)
      - promotion_timestamp: ISO-8601 UTC time of promotion
      - promotion_run_id: backtest run_id that was promoted (audit trail)
      - strategy_hash: SHA-256 of strategy.py at promotion time (provenance)
    """
    if not run_id:
        raise ValueError(f"run_id missing for portfolio entry '{entry_id}' — cannot write YAML without identity key")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    strat_hash = _compute_strategy_hash(entry_id)
    lines = [
        f'  - id: "{entry_id}"',
        f'    path: "strategies/{entry_id}/strategy.py"',
        f"    symbol: {symbol}",
        f"    timeframe: {timeframe}",
        f"    enabled: true",
        f"    vault_id: {vault_id}",
        f"    profile: {profile}",
        f"    lifecycle: {LIFECYCLE_BURN_IN}",
        f"    run_id: {run_id}",
        f"    promotion_source: promote_to_burnin",
        f"    promotion_timestamp: {ts}",
        f"    promotion_run_id: {run_id}",
    ]
    if strat_hash:
        lines.append(f"    strategy_hash: {strat_hash}")
    return lines


# ── burn_in_registry.yaml writer (atomic) ────────────────────────────────────

def _update_burn_in_registry(entry_ids: list[str]) -> str:
    """Add entry_ids to burn_in_registry.yaml. Returns original content for rollback.

    Preserves existing entries. New entries get COVERAGE if their archetype
    already has a PRIMARY, otherwise PRIMARY.
    """
    from tools.promote.metadata import _infer_archetype

    original = ""
    existing: dict[str, tuple[str, str]] = {}  # id -> (layer, archetype)

    if BURN_IN_REGISTRY.exists():
        original = BURN_IN_REGISTRY.read_text(encoding="utf-8")
        data = yaml.safe_load(original) or {}
        for entry in data.get("primary", []):
            existing[entry["id"]] = ("PRIMARY", entry["archetype"])
        for entry in data.get("coverage", []):
            existing[entry["id"]] = ("COVERAGE", entry["archetype"])

    primary_archetypes = {arch for _, (layer, arch) in existing.items() if layer == "PRIMARY"}

    for eid in entry_ids:
        if eid in existing:
            continue
        archetype = _infer_archetype(eid)
        if archetype not in primary_archetypes:
            existing[eid] = ("PRIMARY", archetype)
            primary_archetypes.add(archetype)
        else:
            existing[eid] = ("COVERAGE", archetype)

    primary_entries = [{"id": sid, "archetype": arch}
                       for sid in sorted(existing) if existing[sid][0] == "PRIMARY"
                       for _, arch in [existing[sid]]]
    coverage_entries = [{"id": sid, "archetype": arch}
                        for sid in sorted(existing) if existing[sid][0] == "COVERAGE"
                        for _, arch in [existing[sid]]]

    header = (
        "# burn_in_registry.yaml -- Auto-synced by promote_to_burnin.py\n"
        "# Maps strategy_id -> burn-in layer + archetype for shadow_logger metadata.\n"
        "# Do NOT edit manually.\n"
        "#\n"
        "# Layers:\n"
        "#   PRIMARY   -- first representative per archetype\n"
        "#   COVERAGE  -- additional pairs/variants for the same archetype\n\n"
    )

    output = {"primary": primary_entries, "coverage": coverage_entries}
    tmp = BURN_IN_REGISTRY.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(output, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(BURN_IN_REGISTRY))

    return original


# ── portfolio.yaml writer (atomic + rollback-aware) ──────────────────────────

def _write_portfolio_yaml(strategy_id: str, profile: str, vault_id: str,
                          run_id: str, entry_ids: list[str], block: str,
                          legacy_ids_to_remove: set) -> str:
    """Remove LEGACY entries (if any) + atomic write of portfolio.yaml.

    Emits PORTFOLIO_YAML_ADD event on success; TRANSACTION_FAILED + sys.exit
    on failure. Returns the pre-write portfolio.yaml content (used by
    _update_registry for rollback).

    This is the SOLE writer of portfolio.yaml from the promote flow.
    """
    # 9a. Remove LEGACY entries if --upgrade-legacy (before appending new block)
    with open(PORTFOLIO_YAML, "r", encoding="utf-8") as f:
        content = f.read()

    if legacy_ids_to_remove:
        print(f"\n  --- Removing {len(legacy_ids_to_remove)} LEGACY entries ---")
        lines = content.splitlines()
        filtered = []
        skip_until_next = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- id:"):
                id_val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                if id_val in legacy_ids_to_remove:
                    skip_until_next = True
                    print(f"    Removed: {id_val}")
                    continue
                else:
                    skip_until_next = False
            elif skip_until_next:
                # Skip continuation lines of the LEGACY entry (indented fields)
                if stripped == "" or stripped.startswith("#"):
                    filtered.append(line)
                    continue
                if stripped.startswith("- id:"):
                    skip_until_next = False
                elif not stripped.startswith("-") and ":" in stripped:
                    continue  # field of the entry being removed
                else:
                    skip_until_next = False
            filtered.append(line)
        content = "\n".join(filtered)

    # 9b. Prepare YAML in memory (don't write yet)
    _original_yaml = Path(PORTFOLIO_YAML).read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    _new_yaml = content + "\n" + block + "\n"

    # 10. [RETIRED 2026-04-16] Previously: write IN_PORTFOLIO to ledger.db.
    #     Retired along with the IN_PORTFOLIO column — authority is now
    #     portfolio.yaml alone. Master Filter exposes a transient
    #     Analysis_selection flag for FSP-driven composite analysis, which
    #     is unrelated to deployment state and must not be touched here.

    # 11. ATOMIC COMMIT: portfolio.yaml + burn_in_registry.yaml.
    #     Both must succeed. If either fails, rollback all changes.

    # 11a. Write portfolio.yaml
    try:
        tmp_yaml = PORTFOLIO_YAML.with_suffix(".yaml.tmp")
        with open(tmp_yaml, "w", encoding="utf-8") as f:
            f.write(_new_yaml)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_yaml), str(PORTFOLIO_YAML))
        try:
            from tools.event_log import log_event
            log_event(
                action="PORTFOLIO_YAML_ADD",
                target=f"strategy:{strategy_id}",
                actor="promote_to_burnin",
                after={
                    "entry_ids": entry_ids,
                    "profile": profile,
                    "vault_id": vault_id,
                    "run_id": run_id,
                    "lifecycle": LIFECYCLE_BURN_IN,
                },
            )
        except Exception:
            pass  # observational only
    except Exception as e:
        print(f"  [FATAL] portfolio.yaml write failed ({e}).")
        print(f"  [ABORT] No state change. Promotion aborted.")
        try:
            from tools.event_log import log_event
            log_event(
                action="TRANSACTION_FAILED",
                target=f"strategy:{strategy_id}",
                actor="promote_to_burnin",
                reason=f"portfolio.yaml write failed: {e}",
                stage="11a_portfolio_yaml_write",
            )
        except Exception:
            pass
        sys.exit(1)
    return _original_yaml


def _update_registry(strategy_id: str, is_multi: bool, symbols: list[dict],
                     original_yaml: str) -> list[str]:
    """Write burn_in_registry.yaml (step 11b). On failure, rollback
    portfolio.yaml using `original_yaml` and sys.exit.

    Returns the list of registry entry_ids written.
    """
    # 11b. Write burn_in_registry.yaml (normalized entry_ids with symbol suffix)
    _registry_entry_ids = []
    if is_multi:
        for sym_info in symbols:
            _registry_entry_ids.append(f"{strategy_id}_{sym_info['symbol']}")
    else:
        _sym = symbols[0]["symbol"]
        _eid = strategy_id if strategy_id.endswith(f"_{_sym}") else f"{strategy_id}_{_sym}"
        _registry_entry_ids.append(_eid)
    try:
        _registry_original = _update_burn_in_registry(_registry_entry_ids)
        print(f"  [REGISTRY] burn_in_registry.yaml updated: added {_registry_entry_ids}")
    except Exception as e:
        print(f"  [FATAL] burn_in_registry.yaml write failed ({e}).")
        print(f"  [ROLLBACK] Reverting portfolio.yaml.")
        # Rollback portfolio.yaml
        with open(PORTFOLIO_YAML, "w", encoding="utf-8") as f:
            f.write(original_yaml)
            f.flush()
            os.fsync(f.fileno())
        print(f"  [ROLLBACK] portfolio.yaml reverted. Promotion aborted.")
        try:
            from tools.event_log import log_event
            log_event(
                action="TRANSACTION_FAILED",
                target=f"strategy:{strategy_id}",
                actor="promote_to_burnin",
                reason=f"burn_in_registry.yaml write failed: {e}",
                stage="11b_burn_in_registry_write",
            )
        except Exception:
            pass
        sys.exit(1)
    return _registry_entry_ids
