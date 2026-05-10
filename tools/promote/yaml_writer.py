"""portfolio.yaml authority.

This module is the ONLY writer of:
  - {TS_Execution}/portfolio.yaml       (via _write_portfolio_yaml)

All other modules must NOT write portfolio.yaml directly — route through this module.
Owns constants PORTFOLIO_YAML, VAULT_ROOT, LIFECYCLE_* shared across the promote package.
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

from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT, DRY_RUN_VAULT as VAULT_ROOT

# Module-level constants (shared across the promote package).
PROJECT_ROOT = _PROJECT_ROOT
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"

# Lifecycle values aligned with TS_Execution ALLOWED_LIFECYCLES = {LIVE, RETIRED}.
# LEGACY/DISABLED retained for portfolio.yaml read-side classification of stale
# entries that predate the doctrine; new entries are always written as LIVE.
LIFECYCLE_LEGACY   = "LEGACY"
LIFECYCLE_LIVE     = "LIVE"
LIFECYCLE_RETIRED  = "RETIRED"
LIFECYCLE_DISABLED = "DISABLED"


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
    """Generate the deploy comment block for portfolio.yaml."""
    lines = []
    lines.append(f"  # --- DEPLOY: {strategy_id} / {profile} ---")
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

    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"  # Deployed: {today} | Production sizing: 0.01 fixed lot")
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
      - promotion_source: always "promote_to_live" (required for startup)
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
        f"    lifecycle: {LIFECYCLE_LIVE}",
        f"    run_id: {run_id}",
        f"    promotion_source: promote_to_live",
        f"    promotion_timestamp: {ts}",
        f"    promotion_run_id: {run_id}",
    ]
    if strat_hash:
        lines.append(f"    strategy_hash: {strat_hash}")
    return lines


# ── portfolio.yaml writer (atomic) ───────────────────────────────────────────

def _write_portfolio_yaml(strategy_id: str, profile: str, vault_id: str,
                          run_id: str, entry_ids: list[str], block: str,
                          legacy_ids_to_remove: set) -> str:
    """Remove LEGACY entries (if any) + atomic write of portfolio.yaml.

    Emits PORTFOLIO_YAML_ADD event on success; TRANSACTION_FAILED + sys.exit
    on failure. Returns the pre-write portfolio.yaml content.

    This is the SOLE writer of portfolio.yaml from the promote flow.
    """
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
                if stripped == "" or stripped.startswith("#"):
                    filtered.append(line)
                    continue
                if stripped.startswith("- id:"):
                    skip_until_next = False
                elif not stripped.startswith("-") and ":" in stripped:
                    continue
                else:
                    skip_until_next = False
            filtered.append(line)
        content = "\n".join(filtered)

    _original_yaml = Path(PORTFOLIO_YAML).read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    _new_yaml = content + "\n" + block + "\n"

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
                actor="promote_to_live",
                after={
                    "entry_ids": entry_ids,
                    "profile": profile,
                    "vault_id": vault_id,
                    "run_id": run_id,
                    "lifecycle": LIFECYCLE_LIVE,
                },
            )
        except Exception:
            pass
    except Exception as e:
        print(f"  [FATAL] portfolio.yaml write failed ({e}).")
        print(f"  [ABORT] No state change. Promotion aborted.")
        try:
            from tools.event_log import log_event
            log_event(
                action="TRANSACTION_FAILED",
                target=f"strategy:{strategy_id}",
                actor="promote_to_live",
                reason=f"portfolio.yaml write failed: {e}",
                stage="portfolio_yaml_write",
            )
        except Exception:
            pass
        sys.exit(1)
    return _original_yaml
