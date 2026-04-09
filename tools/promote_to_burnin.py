"""
promote_to_burnin.py -- Promote strategy to TS_Execution/portfolio.yaml with
vault snapshot, explicit artifact linkage, and burn-in lifecycle metadata.

This is the ONLY tool that writes vault_id, profile, and lifecycle fields into
portfolio.yaml. It chains: run_id lookup -> vault snapshot -> portfolio.yaml edit.

Usage:
    python tools/promote_to_burnin.py <STRATEGY_ID> --profile PROFILE
    python tools/promote_to_burnin.py <STRATEGY_ID> --profile PROFILE --dry-run

Requires:
    - TradeScan_State/strategies/{ID}/portfolio_evaluation/ exists
    - TradeScan_State/backtests/{ID}_*/ exist (determines symbols)
    - strategies/{ID}/strategy.py exists in Trade_Scan
    - Strategy NOT already in portfolio.yaml
    - A completed pipeline run exists in TradeScan_State/runs/

Multi-symbol: If backtests/{ID}_{SYMBOL1}/, {ID}_{SYMBOL2}/ exist, creates one
portfolio.yaml entry per symbol using per-symbol strategy copies.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.asset_classification import classify_asset, EXP_FAIL_GATES
from config.state_paths import STATE_ROOT, BACKTESTS_DIR, STRATEGIES_DIR
from tools.pipeline_utils import find_run_id_for_directive

TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
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


# ── Portfolio YAML helpers ───────────────────────────────────────────────────

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


def read_strategy_metadata(strategy_id: str) -> dict:
    """Read vault_id, profile, lifecycle from portfolio.yaml for a strategy.

    Returns dict with keys: vault_id, profile, lifecycle, enabled.
    Returns empty dict if strategy not found.
    """
    data = _load_portfolio_yaml()
    strategies = (data.get("portfolio") or {}).get("strategies") or []
    for s in strategies:
        sid = s.get("id", "")
        # Match exact ID or base ID (for multi-symbol: base_SYMBOL)
        if sid == strategy_id or sid.startswith(strategy_id + "_"):
            return {
                "vault_id":  s.get("vault_id", ""),
                "profile":   s.get("profile", ""),
                "lifecycle": s.get("lifecycle", ""),
                "enabled":   s.get("enabled", False),
            }
    return {}


# ── Run ID lookup (delegated to pipeline_utils.find_run_id_for_directive) ────


# ── Symbol / timeframe detection ─────────────────────────────────────────────

def _detect_symbols(strategy_id: str) -> list[dict]:
    """Detect symbols from backtest folders. Returns list of {symbol, backtest_dir}."""
    bt_dirs = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*"))
    if not bt_dirs:
        print(f"[ABORT] No backtest folders found: {BACKTESTS_DIR / (strategy_id + '_*')}")
        sys.exit(1)
    symbols = []
    for d in bt_dirs:
        suffix = d.name[len(strategy_id) + 1:]
        symbols.append({"symbol": suffix, "backtest_dir": d})
    return symbols


def _detect_timeframe(strategy_id: str, symbols: list[dict]) -> str:
    """Read timeframe from run_metadata.json."""
    for sym_info in symbols:
        meta_path = sym_info["backtest_dir"] / "metadata" / "run_metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            tf = meta.get("timeframe", "")
            if tf:
                return tf
    # Fallback: parse from strategy ID
    m = re.search(r"_(\d+[MHDW])_", strategy_id)
    if m:
        tf_raw = m.group(1)
        if tf_raw[-1] in "MH" and tf_raw[:-1].isdigit():
            return tf_raw[-1] + tf_raw[:-1]
        if tf_raw.endswith("D"):
            return "D" + tf_raw[:-1]
    print(f"[WARN] Could not detect timeframe for {strategy_id}, defaulting to H1")
    return "H1"


# ── Metrics readers ──────────────────────────────────────────────────────────

def _read_backtest_metrics(strategy_id: str) -> dict:
    """Read aggregate metrics from portfolio_summary.json."""
    ps = STRATEGIES_DIR / strategy_id / "portfolio_evaluation" / "portfolio_summary.json"
    if ps.exists():
        data = json.loads(ps.read_text(encoding="utf-8"))
        return {
            "trades":      data.get("total_trades", "?"),
            "pf":          round(data.get("profit_factor", 0), 2),
            "sharpe":      round(data.get("sharpe_ratio", 0), 2),
            "max_dd_pct":  round(data.get("max_drawdown_pct", 0), 2),
            "pnl":         round(data.get("total_pnl", 0), 2),
            "ret_dd":      round(data.get("return_dd_ratio", 0), 2),
            "expectancy":  round(data.get("expectancy", 0), 4),
        }
    return {"trades": "?", "pf": "?", "sharpe": "?", "max_dd_pct": "?", "pnl": "?", "ret_dd": "?", "expectancy": "?"}


def _read_profile_metrics(strategy_id: str, profile: str) -> dict:
    """Read profile-specific metrics from profile_comparison.json."""
    pc = STRATEGIES_DIR / strategy_id / "deployable" / "profile_comparison.json"
    if not pc.exists():
        return {}
    data = json.loads(pc.read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    if profile in profiles:
        p = profiles[profile]
        return {
            "accepted":       p.get("accepted_trades", "?"),
            "rejected_pct":   round(p.get("rejection_pct", 0), 2),
            "profile_pf":     round(p.get("profit_factor", 0), 2),
            "recovery":       round(p.get("recovery_factor", 0), 2),
        }
    available = list(profiles.keys())
    if available:
        print(f"[WARN] Profile '{profile}' not in profile_comparison.json. Available: {available}")
    return {}


# ── Expectancy gate ──────────────────────────────────────────────────────────

def _check_expectancy_gate(strategy_id: str, metrics: dict) -> None:
    """Block promotion if expectancy is below the asset-class floor.

    Uses EXP_FAIL_GATES from config/asset_classification.py:
        FX: $0.15  |  XAU: $0.50  |  BTC: $0.50  |  INDEX: $0.50

    Aborts with [ABORT] if the gate fails. Call before any portfolio.yaml edit.
    """
    exp = metrics.get("expectancy")
    if exp == "?" or exp is None:
        print(f"[WARN] Expectancy not available for {strategy_id} — skipping gate check")
        return

    asset_class = classify_asset(strategy_id)
    gate = EXP_FAIL_GATES.get(asset_class, 0.0)
    exp_val = float(exp)

    print(f"  Expectancy gate: {exp_val:.4f} >= {gate} ({asset_class})  ", end="")
    if exp_val < gate:
        print("FAIL")
        print(f"\n[ABORT] Expectancy ${exp_val:.4f} is below the {asset_class} floor of ${gate:.2f}.")
        print(f"  This strategy would be classified FAIL by filter_strategies.py.")
        print(f"  Resolve the expectancy issue before promoting to BURN_IN.")
        sys.exit(1)
    print("OK")


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_strategy_files(strategy_id: str, symbols: list[dict]) -> None:
    """Verify all required files exist before modifying portfolio.yaml."""
    base_spy = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if not base_spy.exists():
        print(f"[ABORT] strategy.py not found: {base_spy}")
        sys.exit(1)
    pe = STRATEGIES_DIR / strategy_id / "portfolio_evaluation"
    if not pe.exists():
        print(f"[ABORT] portfolio_evaluation/ not found: {pe}")
        sys.exit(1)
    if len(symbols) > 1:
        for sym_info in symbols:
            sym_id = f"{strategy_id}_{sym_info['symbol']}"
            sym_spy = PROJECT_ROOT / "strategies" / sym_id / "strategy.py"
            if not sym_spy.exists():
                print(f"[ABORT] Per-symbol strategy.py not found: {sym_spy}")
                print(f"  Run: python tools/sync_multisymbol_strategy.py {strategy_id}")
                sys.exit(1)


# ── YAML block builders ─────────────────────────────────────────────────────

def _build_comment_block(strategy_id: str, profile: str, vault_id: str,
                         metrics: dict, profile_metrics: dict,
                         description: str) -> list[str]:
    """Generate the burn-in comment block for portfolio.yaml."""
    lines = []
    lines.append(f"    # --- BURN-IN: {strategy_id} / {profile} ---")
    lines.append(f"    # Vault: {vault_id}")
    lines.append(f"    # Profile: {profile}")
    if description:
        lines.append(f"    # {description}")

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
        lines.append(f"    # Backtest: {', '.join(parts)}")

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
            lines.append(f"    # {profile}: {', '.join(pp)}")

    lines.append(f"    # Burn-in: {DEFAULT_GATES['duration']}")
    lines.append(f"    # Pass gates: {DEFAULT_GATES['pass_gates']}")
    lines.append(f"    # Abort gates: {DEFAULT_GATES['abort_gates']}")
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"    # Started: {today} | Observation only -- NO parameter changes during burn-in")
    return lines


def _build_yaml_entry(entry_id: str, symbol: str, timeframe: str,
                      vault_id: str, profile: str) -> list[str]:
    """Build the YAML entry lines for one strategy slot.

    Includes vault_id, profile, lifecycle as structured fields.
    TS_Execution silently ignores unknown fields (permissive dict parsing).
    """
    return [
        f'    - id: "{entry_id}"',
        f'      path: "strategies/{entry_id}/strategy.py"',
        f"      symbol: {symbol}",
        f"      timeframe: {timeframe}",
        f"      enabled: true",
        f"      vault_id: {vault_id}",
        f"      profile: {profile}",
        f"      lifecycle: {LIFECYCLE_BURN_IN}",
    ]


# ── Main promote function ───────────────────────────────────────────────────

def promote(strategy_id: str, profile: str, description: str = "",
            dry_run: bool = False) -> dict:
    """Promote a strategy: lookup run_id -> vault snapshot -> portfolio.yaml edit.

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

    dupes = [eid for eid in entry_ids if eid in existing_ids]
    if dupes:
        # Report existing vault_id and lifecycle for each duplicate
        strategies = (data.get("portfolio") or {}).get("strategies") or []
        for eid in dupes:
            for s in strategies:
                if s.get("id") == eid:
                    existing_vault = s.get("vault_id", "none")
                    existing_lc = s.get("lifecycle", "none")
                    print(f"[ABORT] Already promoted: {eid}")
                    print(f"  vault_id:  {existing_vault}")
                    print(f"  lifecycle: {existing_lc}")
                    break
        print(f"\nTo re-promote, first remove existing entries from portfolio.yaml.")
        sys.exit(1)

    # 3. Validate files exist
    _validate_strategy_files(strategy_id, symbols)

    # 3b. Expectancy gate — hard block before any vault/yaml changes
    _metrics = _read_backtest_metrics(strategy_id)
    _check_expectancy_gate(strategy_id, _metrics)

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

    # 7. Run vault snapshot
    print(f"\n  --- Vault Snapshot ---")
    if dry_run:
        print(f"  [DRY RUN] Would create vault: {VAULT_ROOT / vault_id}")
    else:
        cmd = [
            sys.executable, str(PROJECT_ROOT / "tools" / "backup_dryrun_strategies.py"),
            "--strategies", strategy_id,
            "--run-id", run_id,
            "--profile", profile,
        ]
        # Check if vault already exists (idempotent)
        vault_path = VAULT_ROOT / vault_id
        if vault_path.exists():
            cmd.append("--append")
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=False)
        if result.returncode != 0:
            print(f"[ABORT] Vault snapshot failed (exit code {result.returncode})")
            sys.exit(1)

        # Verify vault was created
        if not (vault_path / strategy_id / "meta.json").exists():
            print(f"[ABORT] Vault verification failed: meta.json missing")
            sys.exit(1)

        # Verify run_id in meta.json
        meta = json.loads((vault_path / strategy_id / "meta.json").read_text(encoding="utf-8"))
        if meta.get("run_id", "unknown") == "unknown":
            print(f"[WARN] run_id not captured in vault meta.json")
        else:
            print(f"  Vault run_id verified: {meta['run_id'][:12]}...")

    # 8. HARD GATE: vault must exist before any portfolio.yaml mutation
    if not dry_run:
        vault_strat_path = VAULT_ROOT / vault_id / strategy_id
        required_files = ["meta.json", "strategy.py"]
        for rf in required_files:
            if not (vault_strat_path / rf).exists():
                print(f"[ABORT] Vault incomplete: {vault_strat_path / rf} missing")
                print(f"  Vault snapshot may have partially failed.")
                print(f"  portfolio.yaml was NOT modified.")
                sys.exit(1)
        print(f"  Vault gate PASSED: {vault_strat_path} verified")

    # 9. Build the YAML block
    comment_lines = _build_comment_block(
        strategy_id, profile, vault_id, metrics, profile_metrics, description
    )
    yaml_entries = []
    if is_multi:
        for sym_info in symbols:
            sym = sym_info["symbol"]
            entry_id = f"{strategy_id}_{sym}"
            yaml_entries.extend(_build_yaml_entry(entry_id, sym, timeframe, vault_id, profile))
            yaml_entries.append("")
    else:
        sym = symbols[0]["symbol"]
        yaml_entries.extend(_build_yaml_entry(strategy_id, sym, timeframe, vault_id, profile))

    block = "\n".join(comment_lines + yaml_entries)

    print(f"\n  --- Generated YAML block ---")
    print(block)
    print(f"  --- End block ---\n")

    if dry_run:
        print("[DRY RUN] No changes written to portfolio.yaml.")
        return {"vault_id": vault_id, "run_id": run_id, "entries_added": 0, "symbols": symbol_names}

    # 9. Append to portfolio.yaml (atomic: write tmp -> fsync -> rename)
    with open(PORTFOLIO_YAML, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.endswith("\n"):
        content += "\n"
    content += "\n" + block + "\n"
    tmp_yaml = PORTFOLIO_YAML.with_suffix(".yaml.tmp")
    with open(tmp_yaml, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_yaml), str(PORTFOLIO_YAML))

    entries_added = len(entry_ids)
    print(f"[OK] Appended {entries_added} entry/entries to {PORTFOLIO_YAML}")
    print(f"     IDs: {entry_ids}")
    print(f"     vault_id: {vault_id}")
    print(f"     profile: {profile}")
    print(f"     lifecycle: {LIFECYCLE_BURN_IN}")
    print(f"\n[NEXT] Restart TS_Execution to pick up new strategies.")

    return {
        "vault_id": vault_id,
        "run_id": run_id,
        "entries_added": entries_added,
        "symbols": symbol_names,
        "entry_ids": entry_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote strategy to burn-in: vault snapshot + portfolio.yaml edit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("strategy_id",
                        help="Base strategy ID (e.g., 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05)")
    parser.add_argument("--profile", required=True,
                        help="Capital profile name (MANDATORY)")
    parser.add_argument("--description", default="",
                        help="One-line strategy description for the comment block")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing vault or portfolio.yaml")

    args = parser.parse_args()
    promote(args.strategy_id, args.profile, args.description, args.dry_run)


if __name__ == "__main__":
    main()
