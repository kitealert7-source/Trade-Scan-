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

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import shutil

import numpy as np
import pandas as pd

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.asset_classification import classify_asset, EXP_FAIL_GATES
from config.state_paths import STATE_ROOT, BACKTESTS_DIR, STRATEGIES_DIR, MASTER_FILTER_PATH, RUNS_DIR
from tools.pipeline_utils import find_run_id_for_directive

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


# ── Archetype inference (mirrors sync_burn_in_registry.py) ──────────────────
ARCHETYPE_RULES = [
    ("02_VOL_IDX",       "VOLATILITY"),
    ("03_TREND_XAUUSD",  "XAU_TREND"),
    ("33_TREND_BTCUSD",  "BTC_TREND"),
    ("11_REV_XAUUSD",    "XAU_MR"),
    ("27_MR_XAUUSD",     "XAU_MR"),
    ("23_RSI_XAUUSD",    "XAU_MR"),
    ("17_REV_XAUUSD",    "BREAKOUT"),
    ("18_REV_XAUUSD",    "BREAKOUT"),
    ("12_STR_FX",        "BREAKOUT"),
    ("15_MR_FX",         "FX_MR"),
    ("22_CONT_FX",       "FX_CONT"),
    ("35_PA_GER40",      "IDX_PA"),
]


def _infer_archetype(strategy_id: str) -> str:
    for prefix, archetype in ARCHETYPE_RULES:
        if strategy_id.startswith(prefix):
            return archetype
    return "UNKNOWN"


def _update_burn_in_registry(entry_ids: list[str]) -> str:
    """Add entry_ids to burn_in_registry.yaml. Returns original content for rollback.

    Preserves existing entries. New entries get COVERAGE if their archetype
    already has a PRIMARY, otherwise PRIMARY.
    """
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


_TF_TO_MT5: dict[str, str] = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1",
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "D1": "D1", "W1": "W1",
}


def _normalize_timeframe(tf: str) -> str:
    """Convert any timeframe format to MT5 format (H1, M15, etc.)."""
    return _TF_TO_MT5.get(tf, tf)


def _detect_timeframe(strategy_id: str, symbols: list[dict]) -> str:
    """Read timeframe from run_metadata.json, normalized to MT5 format."""
    for sym_info in symbols:
        meta_path = sym_info["backtest_dir"] / "metadata" / "run_metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            tf = meta.get("timeframe", "")
            if tf:
                return _normalize_timeframe(tf)
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
# Per-symbol expectancy is handled by _filter_symbols_by_expectancy() above.
# Gate thresholds: EXP_FAIL_GATES in config/asset_classification.py.


# ── Quality gate (6-metric edge quality check) ─────────────────────────────

# Thresholds from promote.md (industry literature calibration)
_QG_THRESHOLDS = {
    "top5_conc":   {"hard": 70.0, "warn": 50.0, "label": "Top-5 concentration (%)"},
    "wo5_pnl":     {"hard": 0.0,  "warn": 30.0, "label": "PnL w/o top 5 trades (%)"},
    "flat_pct":    {"hard": 40.0, "warn": 30.0, "label": "Flat period (%)"},
    "edge_ratio":  {"hard": 1.0,  "warn": 1.2,  "label": "Edge ratio (MFE/MAE)"},
    "trade_count": {"hard": 100,  "warn": 200,  "label": "Trade count"},
    "pf_minus5":   {"hard": 1.0,  "warn": 1.1,  "label": "PF after removing top 5%"},
}


def _compute_quality_gate(strategy_id: str) -> dict:
    """Compute 6-metric quality gate from trade-level CSVs.

    Returns dict with keys: metrics (dict of values), hard_fails (list),
    warns (list), passed (bool).
    """
    csvs = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*/raw/results_tradelevel.csv"))
    if not csvs:
        return {"metrics": {}, "hard_fails": ["No trade-level CSVs found"], "warns": [], "passed": False}

    frames = []
    for f in csvs:
        try:
            frames.append(pd.read_csv(f, encoding="utf-8"))
        except Exception:
            continue
    if not frames:
        return {"metrics": {}, "hard_fails": ["All CSVs unreadable"], "warns": [], "passed": False}

    df = pd.concat(frames, ignore_index=True)
    if "parent_trade_id" in df.columns and "symbol" in df.columns:
        df = df.drop_duplicates(subset=["parent_trade_id", "symbol"])

    n = len(df)
    pnls = df["pnl_usd"].sort_values(ascending=False)
    total = pnls.sum()

    # Gate 1: PnL without top 5 trades
    wo5 = pnls.iloc[5:].sum() if n > 5 else 0
    wo5_pct = (wo5 / total * 100) if total > 0 else -999

    # Gate 2: Top-5 concentration
    t5 = (pnls.iloc[:5].sum() / total * 100) if total > 0 else 999

    # Gate 3: Flat period
    flat_pct = 0.0
    try:
        exits = pd.to_datetime(df["exit_timestamp"])
        entries = pd.to_datetime(df["entry_timestamp"])
        bt_days = (exits.max() - entries.min()).days
        if bt_days > 0:
            cum = df.sort_values("exit_timestamp")["pnl_usd"].cumsum()
            rm = cum.cummax()
            hd = exits.loc[cum[cum == rm].index].sort_values()
            flat_d = int(hd.diff().dt.days.dropna().max()) if len(hd) > 1 else bt_days
            flat_pct = flat_d / bt_days * 100
    except Exception:
        flat_pct = 999

    # Gate 4: Edge ratio
    er = 0.0
    if "mfe_r" in df.columns and "mae_r" in df.columns:
        mae_mean = abs(df["mae_r"].mean())
        er = (df["mfe_r"].mean() / mae_mean) if mae_mean > 0 else 0.0

    # Gate 5: Trade count (n already computed)

    # Gate 6: PF after removing top 5% of trades
    top5pct_n = max(1, int(np.ceil(n * 0.05)))
    rem = pnls.iloc[top5pct_n:]
    w = rem[rem > 0].sum()
    l_val = abs(rem[rem <= 0].sum())
    pf_rem = (w / l_val) if l_val > 0 else 999

    metrics = {
        "top5_conc": round(t5, 1),
        "wo5_pnl": round(wo5_pct, 1),
        "flat_pct": round(flat_pct, 1),
        "edge_ratio": round(er, 2),
        "trade_count": n,
        "pf_minus5": round(pf_rem, 2),
    }

    hard_fails = []
    warns = []
    for key, thresh in _QG_THRESHOLDS.items():
        val = metrics[key]
        label = thresh["label"]
        if key in ("edge_ratio", "trade_count", "pf_minus5", "wo5_pnl"):
            # Lower is worse
            if val < thresh["hard"]:
                hard_fails.append(f"{label}: {val} < {thresh['hard']}")
            elif val < thresh["warn"]:
                warns.append(f"{label}: {val} < {thresh['warn']}")
        else:
            # Higher is worse (top5_conc, flat_pct)
            if val > thresh["hard"]:
                hard_fails.append(f"{label}: {val} > {thresh['hard']}")
            elif val > thresh["warn"]:
                warns.append(f"{label}: {val} > {thresh['warn']}")

    return {
        "metrics": metrics,
        "hard_fails": hard_fails,
        "warns": warns,
        "passed": len(hard_fails) == 0,
    }


def _print_quality_gate(qg: dict) -> None:
    """Print quality gate results in a formatted table."""
    print(f"\n  --- Quality Gate (6-metric edge check) ---")
    m = qg["metrics"]
    if not m:
        print(f"  [SKIP] No trade-level data available")
        return
    for key, thresh in _QG_THRESHOLDS.items():
        val = m.get(key, "?")
        label = thresh["label"]
        if key in ("edge_ratio", "trade_count", "pf_minus5", "wo5_pnl"):
            if val < thresh["hard"]:
                tag = "HARD FAIL"
            elif val < thresh["warn"]:
                tag = "WARN"
            else:
                tag = "OK"
        else:
            if val > thresh["hard"]:
                tag = "HARD FAIL"
            elif val > thresh["warn"]:
                tag = "WARN"
            else:
                tag = "OK"
        print(f"  {label:30s} {str(val):>8s}  {tag}")
    if qg["hard_fails"]:
        print(f"  RESULT: HARD FAIL ({len(qg['hard_fails'])} metric(s))")
    elif qg["warns"]:
        print(f"  RESULT: WARN ({len(qg['warns'])} metric(s))")
    else:
        print(f"  RESULT: PASS")


# ── Preflight check ─────────────────────────────────────────────────────────

def preflight(strategy_id: str) -> dict:
    """Run all promote precondition checks and print a readiness report.

    Returns dict with overall pass/fail and per-check results.
    """
    print(f"\n{'=' * 60}")
    print(f"PREFLIGHT CHECK: {strategy_id}")
    print(f"{'=' * 60}\n")

    checks = {}

    # 1. strategy.py exists (or recoverable)
    base_spy = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if base_spy.exists():
        checks["strategy.py"] = ("PASS", str(base_spy))
    else:
        # Check if recoverable
        from config.state_paths import RUNS_DIR as _RUNS_DIR
        run_id = find_run_id_for_directive(strategy_id)
        snapshot = _RUNS_DIR / run_id / "strategy.py" if run_id else None
        if snapshot and snapshot.exists():
            checks["strategy.py"] = ("PASS", f"Recoverable from run {run_id}")
        else:
            checks["strategy.py"] = ("FAIL", "Not found and no run snapshot")

    # 2. Backtest folders exist
    bt_dirs = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*"))
    if bt_dirs:
        syms = [d.name[len(strategy_id) + 1:] for d in bt_dirs]
        checks["backtests"] = ("PASS", f"{len(bt_dirs)} symbol(s): {syms}")
    else:
        checks["backtests"] = ("FAIL", "No backtest folders found")

    # 3. Run ID resolvable
    run_id = find_run_id_for_directive(strategy_id)
    if run_id:
        checks["run_id"] = ("PASS", run_id)
    else:
        checks["run_id"] = ("FAIL", "No run_id found via fallback chain")

    # 4. portfolio_evaluation/ (warn-only for single-symbol)
    pe = STRATEGIES_DIR / strategy_id / "portfolio_evaluation"
    is_single = len(bt_dirs) <= 1
    if pe.exists():
        checks["portfolio_evaluation"] = ("PASS", str(pe))
    elif is_single:
        checks["portfolio_evaluation"] = ("WARN", "Missing (expected for single-symbol)")
    else:
        checks["portfolio_evaluation"] = ("FAIL", "Missing for multi-symbol strategy")

    # 5. deployable/ artifacts
    deploy = STRATEGIES_DIR / strategy_id / "deployable"
    if deploy.exists() and any(deploy.iterdir()):
        checks["deployable"] = ("PASS", f"{len(list(deploy.iterdir()))} files")
    elif is_single:
        checks["deployable"] = ("WARN", "Missing (single-symbol may skip)")
    else:
        checks["deployable"] = ("WARN", "Missing — Step 8/8.5 may not have run")

    # 6. Not already in portfolio.yaml
    data = _load_portfolio_yaml()
    existing = _get_existing_ids(data)
    in_portfolio = strategy_id in existing or any(
        eid.startswith(strategy_id + "_") for eid in existing
    )
    if not in_portfolio:
        checks["not_in_portfolio"] = ("PASS", "Not in portfolio.yaml")
    else:
        checks["not_in_portfolio"] = ("FAIL", "Already in portfolio.yaml")

    # 7. PORTFOLIO_COMPLETE state
    ds_file = STATE_ROOT / "runs" / strategy_id / "directive_state.json"
    if ds_file.exists():
        try:
            ds = json.loads(ds_file.read_text(encoding="utf-8"))
            latest = ds.get("latest_attempt", "attempt_01")
            status = ds.get("attempts", {}).get(latest, {}).get("status", "?")
            if status == "PORTFOLIO_COMPLETE":
                checks["directive_state"] = ("PASS", f"PORTFOLIO_COMPLETE (attempt: {latest})")
            else:
                checks["directive_state"] = ("WARN", f"Status: {status} (not PORTFOLIO_COMPLETE)")
        except Exception:
            checks["directive_state"] = ("WARN", "directive_state.json unreadable")
    else:
        checks["directive_state"] = ("WARN", "No directive_state.json found")

    # 8. Quality gate
    qg = _compute_quality_gate(strategy_id)
    if qg["passed"] and not qg["warns"]:
        checks["quality_gate"] = ("PASS", "All 6 metrics OK")
    elif qg["passed"]:
        checks["quality_gate"] = ("WARN", f"{len(qg['warns'])} warning(s)")
    else:
        checks["quality_gate"] = ("FAIL", f"{len(qg['hard_fails'])} hard fail(s)")

    # Print report
    has_fail = False
    has_warn = False
    for name, (status, detail) in checks.items():
        marker = {"PASS": "OK", "WARN": "!!", "FAIL": "XX"}[status]
        print(f"  [{marker}] {name:25s} {detail}")
        if status == "FAIL":
            has_fail = True
        if status == "WARN":
            has_warn = True

    # Quality gate detail
    _print_quality_gate(qg)

    overall = "FAIL" if has_fail else ("WARN" if has_warn else "PASS")
    print(f"\n  OVERALL: {overall}")
    if overall == "FAIL":
        print(f"  Resolve FAIL items before promoting.")
    elif overall == "WARN":
        print(f"  WARN items are advisory — promotion will proceed with --skip-quality-gate if needed.")

    return {"overall": overall, "checks": checks, "quality_gate": qg}


# ── Promote audit log ───────────────────────────────────────────────────────

def _write_audit_log(strategy_id: str, profile: str, outcome: str,
                     dry_run: bool = False, vault_id: str = "",
                     run_id: str = "", reason: str = "",
                     quality_gate: dict | None = None) -> None:
    """Append a promote attempt record to TradeScan_State/logs/promote_audit.jsonl."""
    log_dir = STATE_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "promote_audit.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_id": strategy_id,
        "profile": profile,
        "outcome": outcome,
        "dry_run": dry_run,
        "vault_id": vault_id,
        "run_id": run_id,
        "reason": reason,
    }
    if quality_gate:
        entry["quality_gate_metrics"] = quality_gate.get("metrics", {})
        entry["quality_gate_hard_fails"] = quality_gate.get("hard_fails", [])
        entry["quality_gate_warns"] = quality_gate.get("warns", [])

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"  [WARN] Audit log write failed: {e}")


# ── Composite portfolio decomposition ────────────────────────────────────────

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
        if len(symbols) <= 1:
            print(f"  [WARN] portfolio_evaluation/ not found (expected for single-symbol): {pe}")
        else:
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


def _compute_strategy_hash(entry_id: str) -> str:
    """SHA-256 of strategy.py at promotion time. Proves strategy logic at promotion."""
    import hashlib
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


# ── Main promote function ───────────────────────────────────────────────────

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

    # 3b. Quality gate (6-metric edge check)
    _metrics = _read_backtest_metrics(strategy_id)
    _qg = _compute_quality_gate(strategy_id)
    _print_quality_gate(_qg)
    if not skip_quality_gate:
        if not _qg["passed"]:
            _write_audit_log(strategy_id, profile, "QUALITY_GATE_FAIL",
                             dry_run=dry_run, reason="; ".join(_qg["hard_fails"]),
                             quality_gate=_qg)
            print(f"\n[ABORT] Quality gate HARD FAIL — promotion blocked.")
            print(f"  Use --skip-quality-gate to override (not recommended).")
            sys.exit(1)
        if _qg["warns"]:
            print(f"\n  [WARN] Quality gate has {len(_qg['warns'])} warning(s) — proceeding.")
    else:
        if not _qg["passed"]:
            print(f"\n  [OVERRIDE] Quality gate HARD FAIL bypassed (--skip-quality-gate)")

    # 3b1b. Baseline Freshness Gate — blocks stale baselines from reaching Layer 2.
    #        Threshold: 14 days. Cannot be bypassed (no --skip flag by design).
    from tools.baseline_freshness_gate import check_freshness, format_blocked_message
    print(f"\n  --- Baseline Freshness Gate (threshold=14 days) ---")
    _fr = check_freshness(strategy_id, threshold_days=14)
    if _fr.status != "OK":
        print(format_blocked_message(_fr))
        _write_audit_log(strategy_id, profile, "FRESHNESS_BLOCKED",
                         dry_run=dry_run, reason=_fr.message)
        sys.exit(1)
    print(f"  [OK] Baseline age: {_fr.worst_age_days}d (worst across {len(_fr.per_symbol)} symbol(s))")

    # 3b2. Pre-promote validation gate (4-layer) — always runs.
    #       --skip-replay only skips Layer 2 (replay regression).
    #       Layers 1, 3, 4 are mandatory and cannot be bypassed.
    from tools.pre_promote_validator import validate_strategy, print_summary
    print(f"\n  --- Pre-Promote Validation (4-layer) ---")
    vr = validate_strategy(strategy_id, skip_replay=skip_replay)
    if vr.final == "BLOCKED":
        print_summary([vr])
        _write_audit_log(strategy_id, profile, "VALIDATION_BLOCKED",
                         dry_run=dry_run, reason="Pre-promote validation BLOCKED")
        print(f"\n  [VALIDATION] BLOCKED")
        print(f"\n[ABORT] Pre-promote validation BLOCKED — resolve failures before promoting.")
        print(f"  Layers 1, 3, 4 are mandatory. Use --skip-replay to skip Layer 2 only.")
        sys.exit(1)
    elif skip_replay:
        print(f"\n  [VALIDATION] SKIP_REPLAY")
    else:
        print(f"\n  [VALIDATION] PASS")

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

    # 9b. Prepare YAML in memory (don't write yet)
    _original_yaml = Path(PORTFOLIO_YAML).read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    _new_yaml = content + "\n" + block + "\n"

    entries_added = len(entry_ids)

    # 10. DB FIRST — write IN_PORTFOLIO to ledger.db (must succeed)
    print(f"\n  --- Update IN_PORTFOLIO (DB) ---")
    from tools.ledger_db import set_in_portfolio, _connect as _ldb_connect, create_tables as _ldb_ct
    _ldb = _ldb_connect()
    _ldb_ct(_ldb)
    _previous_ids = {
        r[0] for r in _ldb.execute(
            'SELECT run_id FROM master_filter WHERE "IN_PORTFOLIO" = 1'
        ).fetchall()
    }
    _ldb.close()
    _new_ids = _previous_ids | {run_id}
    synced = set_in_portfolio(_new_ids)
    print(f"  [DB] IN_PORTFOLIO: {synced} run_id(s) flagged (added {run_id[:12]}...).")

    # 11. ATOMIC COMMIT: portfolio.yaml + burn_in_registry.yaml
    #     Both must succeed. If either fails, rollback all changes.

    # 11a. Write portfolio.yaml
    try:
        tmp_yaml = PORTFOLIO_YAML.with_suffix(".yaml.tmp")
        with open(tmp_yaml, "w", encoding="utf-8") as f:
            f.write(_new_yaml)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_yaml), str(PORTFOLIO_YAML))
    except Exception as e:
        print(f"  [FATAL] portfolio.yaml write failed ({e}).")
        print(f"  [ROLLBACK] Reverting DB to previous state.")
        set_in_portfolio(_previous_ids)
        print(f"  [ROLLBACK] DB reverted. Promotion aborted.")
        sys.exit(1)

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
        print(f"  [ROLLBACK] Reverting portfolio.yaml and DB.")
        # Rollback portfolio.yaml
        with open(PORTFOLIO_YAML, "w", encoding="utf-8") as f:
            f.write(_original_yaml)
            f.flush()
            os.fsync(f.fileno())
        # Rollback DB
        set_in_portfolio(_previous_ids)
        print(f"  [ROLLBACK] All reverted. Promotion aborted.")
        sys.exit(1)

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

    # 14. CONSISTENCY ASSERTION — DB run_ids must match YAML run_ids (exact identity)
    print(f"\n  --- Consistency Check ---")
    try:
        _yaml_data = yaml.safe_load(Path(PORTFOLIO_YAML).read_text(encoding="utf-8"))
        _yaml_run_ids_list = []
        for s in _yaml_data.get("portfolio", {}).get("strategies", []):
            if s.get("enabled", False):
                _rid = s.get("run_id", "")
                if _rid:
                    _yaml_run_ids_list.append(str(_rid))
        _yaml_run_ids = set(_yaml_run_ids_list)

        if len(_yaml_run_ids_list) != len(_yaml_run_ids):
            _dupes = [r for r in _yaml_run_ids_list if _yaml_run_ids_list.count(r) > 1]
            print(f"  [ERROR] Duplicate run_ids in YAML: {sorted(set(_dupes))}")

        from tools.ledger_db import _connect as _ck_conn
        _ck = _ck_conn()
        _db_rows = _ck.execute(
            'SELECT run_id FROM master_filter WHERE "IN_PORTFOLIO" = 1'
        ).fetchall()
        _ck.close()
        _db_run_ids = {str(r[0]) for r in _db_rows}

        if _db_run_ids == _yaml_run_ids:
            print(f"  [OK] DB run_ids == YAML run_ids ({len(_db_run_ids)}) — consistent.")
        else:
            _missing_in_yaml = _db_run_ids - _yaml_run_ids
            _missing_in_db = _yaml_run_ids - _db_run_ids
            print(f"  [MISMATCH] run_id sets differ.")
            if _missing_in_yaml:
                print(f"    Missing in YAML: {sorted(_missing_in_yaml)}")
            if _missing_in_db:
                print(f"    Missing in DB:   {sorted(_missing_in_db)}")
            if not _yaml_run_ids:
                print(f"    [HINT] YAML entries may be missing run_id fields. Backfill needed.")
            print(f"  Run: python tools/sync_portfolio_flags.py --save  to reconcile.")
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
    from collections import OrderedDict
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
    blocked = [
        r for r in report
        if not r["ready"] and not r.get("is_composite")
        and r["checks"]["portfolio_yaml"] != "IN_PORTFOLIO"
    ]
    in_portfolio = [
        r for r in report
        if not r.get("is_composite")
        and r["checks"]["portfolio_yaml"] == "IN_PORTFOLIO"
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
    parser.add_argument("--profile", default=None,
                        help="Capital profile name (required for promote, not for preflight)")
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
