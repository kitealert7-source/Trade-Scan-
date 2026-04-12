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


# ── Per-symbol expectancy gate ──────────────────────────────────────────────

def _read_symbol_expectancy(backtest_dir: Path) -> float | None:
    """Read per-symbol expectancy from results_standard.csv.

    Computes expectancy = net_pnl_usd / trade_count.
    Returns None if data is unavailable.
    """
    csv_path = backtest_dir / "raw" / "results_standard.csv"
    if not csv_path.exists():
        return None
    import csv
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pnl = float(row.get("net_pnl_usd", 0))
                trades = int(float(row.get("trade_count", 0)))
                if trades > 0:
                    return pnl / trades
            except (ValueError, TypeError):
                pass
    return None


def _filter_symbols_by_expectancy(
    strategy_id: str,
    symbols: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Filter multi-symbol list by per-symbol expectancy gate.

    Returns (passed, failed) symbol lists.
    """
    asset_class = classify_asset(strategy_id)
    gate = EXP_FAIL_GATES.get(asset_class, 0.0)
    if gate <= 0:
        return symbols, []

    passed = []
    failed = []
    for sym_info in symbols:
        exp = _read_symbol_expectancy(sym_info["backtest_dir"])
        sym = sym_info["symbol"]
        if exp is None:
            print(f"  [WARN] Expectancy unavailable for {sym} — including by default")
            passed.append(sym_info)
        elif exp >= gate:
            print(f"  {sym}: exp=${exp:.4f} >= ${gate:.2f}  PASS")
            passed.append(sym_info)
        else:
            print(f"  {sym}: exp=${exp:.4f} <  ${gate:.2f}  FAIL — excluded from portfolio.yaml")
            failed.append(sym_info)

    return passed, failed


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

def _recover_strategy_py(strategy_id: str, target_path: Path) -> bool:
    """Attempt to recover strategy.py from run snapshot if authority copy is missing.

    Searches TradeScan_State/runs/{run_id}/strategy.py using the fallback chain.
    If found, copies to the authority location and returns True.
    """
    from config.state_paths import RUNS_DIR as _RUNS_DIR
    run_id = find_run_id_for_directive(strategy_id)
    if not run_id:
        return False
    snapshot = _RUNS_DIR / run_id / "strategy.py"
    if snapshot.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(snapshot), str(target_path))
        print(f"  [RECOVERED] strategy.py from run snapshot: {run_id}")
        return True
    return False


def _validate_strategy_files(strategy_id: str, symbols: list[dict]) -> None:
    """Verify all required files exist before modifying portfolio.yaml.

    If the authority strategy.py is missing, attempts auto-recovery from
    the run snapshot in TradeScan_State/runs/{run_id}/strategy.py.
    For multi-symbol strategies, auto-syncs per-symbol folders if the base
    strategy.py exists but per-symbol copies are missing.
    """
    base_spy = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if not base_spy.exists():
        if not _recover_strategy_py(strategy_id, base_spy):
            print(f"[ABORT] strategy.py not found: {base_spy}")
            print(f"  Not in authority location and no run snapshot found.")
            sys.exit(1)
    pe = STRATEGIES_DIR / strategy_id / "portfolio_evaluation"
    if not pe.exists():
        print(f"[ABORT] portfolio_evaluation/ not found: {pe}")
        sys.exit(1)
    if len(symbols) > 1:
        missing_syms = []
        for sym_info in symbols:
            sym_id = f"{strategy_id}_{sym_info['symbol']}"
            sym_spy = PROJECT_ROOT / "strategies" / sym_id / "strategy.py"
            if not sym_spy.exists():
                missing_syms.append(sym_info["symbol"])
        if missing_syms:
            # Auto-sync: copy base strategy.py to per-symbol folders
            print(f"  [AUTO-SYNC] Creating per-symbol strategy.py for: {missing_syms}")
            import shutil
            for sym in missing_syms:
                sym_id = f"{strategy_id}_{sym}"
                sym_dir = PROJECT_ROOT / "strategies" / sym_id
                sym_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(base_spy), str(sym_dir / "strategy.py"))
                print(f"    Created: strategies/{sym_id}/strategy.py")
            print(f"  [AUTO-SYNC] {len(missing_syms)} per-symbol folder(s) created")


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


def _build_yaml_entry(entry_id: str, symbol: str, timeframe: str,
                      vault_id: str, profile: str) -> list[str]:
    """Build the YAML entry lines for one strategy slot.

    Includes vault_id, profile, lifecycle as structured fields.
    TS_Execution silently ignores unknown fields (permissive dict parsing).
    """
    return [
        f'  - id: "{entry_id}"',
        f'    path: "strategies/{entry_id}/strategy.py"',
        f"    symbol: {symbol}",
        f"    timeframe: {timeframe}",
        f"    enabled: true",
        f"    vault_id: {vault_id}",
        f"    profile: {profile}",
        f"    lifecycle: {LIFECYCLE_BURN_IN}",
    ]


# ── Main promote function ───────────────────────────────────────────────────

def promote(strategy_id: str, profile: str, description: str = "",
            dry_run: bool = False, symbols_filter: list[str] | None = None,
            upgrade_legacy: bool = False) -> dict:
    """Promote a strategy: lookup run_id -> vault snapshot -> portfolio.yaml edit.

    Args:
        symbols_filter: If provided, only include these symbols in portfolio.yaml.
                        All symbols still go to vault (complete research record).
        upgrade_legacy: If True, replace existing LEGACY entries in-place
                        instead of aborting on duplicates.

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

    # 3b. Expectancy gate (aggregate) — hard block before any vault/yaml changes
    _metrics = _read_backtest_metrics(strategy_id)
    _check_expectancy_gate(strategy_id, _metrics)

    # 3c. Apply --symbols filter (restrict which symbols go to portfolio.yaml)
    if symbols_filter:
        allowed = set(s.upper() for s in symbols_filter)
        symbols = [s for s in symbols if s["symbol"].upper() in allowed]
        if not symbols:
            print(f"[ABORT] No matching symbols after --symbols filter: {symbols_filter}")
            sys.exit(1)
        symbol_names = [s["symbol"] for s in symbols]
        print(f"  Filtered symbols: {symbol_names}")

    # 3d. Per-symbol expectancy gate (multi-symbol only)
    #     Vault gets ALL symbols; portfolio.yaml only gets those that pass.
    _all_symbols_for_vault = _detect_symbols(strategy_id)  # full set for vault
    if is_multi and len(symbols) > 1:
        print(f"\n  --- Per-Symbol Expectancy Gate ---")
        symbols, _exp_failed = _filter_symbols_by_expectancy(strategy_id, symbols)
        if _exp_failed:
            print(f"  Excluded {len(_exp_failed)} symbol(s) from portfolio.yaml")
            print(f"  (they will still be in the vault snapshot)")
        if not symbols:
            print(f"[ABORT] All symbols failed per-symbol expectancy gate")
            sys.exit(1)
        symbol_names = [s["symbol"] for s in symbols]
        # Update entry_ids to only include passing symbols
        entry_ids = [f"{strategy_id}_{s['symbol']}" for s in symbols]

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

    # 9a. Remove LEGACY entries if --upgrade-legacy (before appending new block)
    with open(PORTFOLIO_YAML, "r", encoding="utf-8") as f:
        content = f.read()

    if _legacy_ids_to_remove:
        print(f"\n  --- Removing {len(_legacy_ids_to_remove)} LEGACY entries ---")
        lines = content.splitlines()
        filtered = []
        skip_until_next = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- id:"):
                id_val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                if id_val in _legacy_ids_to_remove:
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

    # 9b. Append new BURN_IN block (atomic: write tmp -> fsync -> rename)
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

    # 10. Auto-sync portfolio flags (eliminates manual Step 2)
    print(f"\n  --- Sync Portfolio Flags ---")
    sync_result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "sync_portfolio_flags.py"), "--save"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if sync_result.returncode == 0:
        # Show relevant output lines
        for line in sync_result.stdout.strip().splitlines():
            if line.startswith("["):
                print(f"  {line}")
        print(f"  Portfolio flags synced automatically.")
    else:
        print(f"  [WARN] sync_portfolio_flags.py failed (exit {sync_result.returncode}).")
        print(f"  Run manually: python tools/sync_portfolio_flags.py --save")
        if sync_result.stderr:
            print(f"  stderr: {sync_result.stderr[:200]}")

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

    print(f"\n[NEXT] Restart TS_Execution to pick up new strategies.")
    print(f"       Verify: cd ../TS_Execution && python src/main.py --phase 0")

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
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbol filter (e.g., AUDJPY,EURUSD). "
                             "Only these symbols are added to portfolio.yaml; all "
                             "symbols still go to vault.")
    parser.add_argument("--upgrade-legacy", action="store_true",
                        help="Replace existing LEGACY entries with fresh BURN_IN entries. "
                             "Without this flag, duplicate IDs abort the promote.")

    args = parser.parse_args()
    symbols_filter = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    promote(args.strategy_id, args.profile, args.description, args.dry_run,
            symbols_filter=symbols_filter, upgrade_legacy=args.upgrade_legacy)


if __name__ == "__main__":
    main()
