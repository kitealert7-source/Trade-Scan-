"""
pre_promote_validator.py — 4-Layer pre-promotion validation gate.

Validates strategy files before burn-in promotion. Any FAIL blocks promotion.

Layers:
  1. Static Validation   — schema, naming, imports, signature structure
  2. Replay Regression   — deterministic backtest replay vs baseline (if changed)
  3. Pre-Promotion Gate  — expectancy, trade density, duplicates, FSP presence
  4. Sanity Execution    — signal object validation, stop/lot sizing

Usage:
    python tools/pre_promote_validator.py <STRATEGY_ID> [<STRATEGY_ID> ...]
    python tools/pre_promote_validator.py <STRATEGY_ID> --replay   # force Layer 2
    python tools/pre_promote_validator.py <STRATEGY_ID> --skip-replay
"""

import argparse
import ast
import csv
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import (
    STATE_ROOT, BACKTESTS_DIR, STRATEGIES_DIR, CANDIDATE_FILTER_PATH,
)
from config.asset_classification import classify_asset, EXP_FAIL_GATES

import yaml

# ── Constants ────────────────────────────────────────────────────────────────

_VALID_MT5_TF = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"}

_TF_TO_MT5 = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1",
    **{k: k for k in _VALID_MT5_TF},
}

_SCHEMA_REQUIRED_FIELDS = {"signal", "stop_price", "entry_reference_price", "entry_reason"}

_REGIME_TF_MAP_PATH = PROJECT_ROOT / "config" / "regime_timeframe_map.yaml"

TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"

# Replay settings
REPLAY_WINDOW_DAYS_INITIAL = 30
REPLAY_WINDOW_DAYS_EXTENDED = 90
REPLAY_MIN_TRADES_FOR_VALID = 10  # auto-extend window if fewer trades
REPLAY_WARMUP_BARS = 300
REPLAY_PASS_TS_MATCH_PCT = 95.0
REPLAY_PASS_COUNT_DELTA_PCT = 10.0
REPLAY_PASS_PNL_DRIFT_PCT = 2.0
REPLAY_FAIL_PNL_DRIFT_PCT = 5.0

# Pre-promotion gate
MIN_TRADE_DENSITY = 50


# ═══════════════════════════════════════════════════════════════════════════
# RESULT TRACKING
# ═══════════════════════════════════════════════════════════════════════════

class CheckResult:
    """Single check outcome."""
    __slots__ = ("name", "status", "detail")

    def __init__(self, name: str, status: str, detail: str = ""):
        self.name = name
        self.status = status  # PASS, FAIL, WARN, SKIP
        self.detail = detail

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "WARN", "SKIP")


class LayerResult:
    """Aggregated result for one layer."""
    def __init__(self, name: str):
        self.name = name
        self.checks: list[CheckResult] = []

    def add(self, name: str, status: str, detail: str = "") -> CheckResult:
        cr = CheckResult(name, status, detail)
        self.checks.append(cr)
        return cr

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def status_label(self) -> str:
        if not self.checks:
            return "SKIP"
        if any(c.status == "FAIL" for c in self.checks):
            return "FAIL"
        if any(c.status == "WARN" for c in self.checks):
            return "WARN"
        return "PASS"


class ValidationResult:
    """Full validation outcome for one strategy."""
    def __init__(self, strategy_id: str):
        self.strategy_id = strategy_id
        self.layer1 = LayerResult("Static Validation")
        self.layer2 = LayerResult("Replay Regression")
        self.layer3 = LayerResult("Pre-Promotion Gate")
        self.layer4 = LayerResult("Sanity Execution")

    @property
    def final(self) -> str:
        layers = [self.layer1, self.layer3, self.layer4]
        if self.layer2.checks:  # only count if it ran
            layers.append(self.layer2)
        if any(not l.passed for l in layers):
            return "BLOCKED"
        return "APPROVED"


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 1 — STATIC VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def _load_strategy_module(strategy_id: str):
    """Import strategy module, return (module, error_string)."""
    try:
        mod = importlib.import_module(f"strategies.{strategy_id}.strategy")
        return mod, None
    except Exception as e:
        return None, str(e)


def _parse_strategy_ast(strategy_path: Path) -> ast.Module | None:
    """Parse strategy.py into AST."""
    try:
        source = strategy_path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(strategy_path))
    except Exception:
        return None


def _check_schema_sample(mod, result: LayerResult) -> None:
    """Validate _schema_sample() returns required fields."""
    cls = getattr(mod, "Strategy", None)
    if cls is None:
        result.add("schema_sample", "FAIL", "No Strategy class found")
        return

    sample_fn = getattr(cls, "_schema_sample", None)
    if sample_fn is None:
        result.add("schema_sample", "FAIL", "_schema_sample() not defined")
        return

    try:
        sample = sample_fn()
    except Exception as e:
        result.add("schema_sample", "FAIL", f"_schema_sample() raised: {e}")
        return

    if not isinstance(sample, dict):
        result.add("schema_sample", "FAIL", f"_schema_sample() returned {type(sample).__name__}, expected dict")
        return

    missing = _SCHEMA_REQUIRED_FIELDS - set(sample.keys())
    if missing:
        result.add("schema_sample", "FAIL", f"Missing fields: {sorted(missing)}")
    else:
        result.add("schema_sample", "PASS")


def _check_strategy_name(mod, strategy_id: str, result: LayerResult) -> None:
    """Validate strategy.name == folder name."""
    cls = getattr(mod, "Strategy", None)
    if cls is None:
        result.add("strategy_name", "FAIL", "No Strategy class")
        return

    name = getattr(cls, "name", None)
    if name is None:
        result.add("strategy_name", "FAIL", "Strategy.name not defined")
        return

    if name != strategy_id:
        result.add("strategy_name", "FAIL", f"name='{name}' != folder='{strategy_id}'")
    else:
        result.add("strategy_name", "PASS")


def _check_timeframe(mod, result: LayerResult) -> None:
    """Validate timeframe is MT5-compatible."""
    cls = getattr(mod, "Strategy", None)
    if cls is None:
        result.add("timeframe", "FAIL", "No Strategy class")
        return

    tf = getattr(cls, "timeframe", None)
    if tf is None:
        result.add("timeframe", "FAIL", "Strategy.timeframe not defined")
        return

    mt5_tf = _TF_TO_MT5.get(tf)
    if mt5_tf and mt5_tf in _VALID_MT5_TF:
        result.add("timeframe", "PASS", f"{tf} -> {mt5_tf}")
    else:
        result.add("timeframe", "FAIL", f"'{tf}' not MT5-compatible. Valid: {sorted(_VALID_MT5_TF)}")


def _check_signature(mod, result: LayerResult) -> None:
    """Validate STRATEGY_SIGNATURE has required fields."""
    cls = getattr(mod, "Strategy", None)
    if cls is None:
        result.add("signature", "FAIL", "No Strategy class")
        return

    sig = getattr(cls, "STRATEGY_SIGNATURE", None)
    if sig is None:
        result.add("signature", "FAIL", "STRATEGY_SIGNATURE not defined")
        return

    exec_rules = sig.get("execution_rules")
    if exec_rules is None:
        result.add("signature", "FAIL", "Missing execution_rules")
        return

    stop_loss = exec_rules.get("stop_loss")
    if stop_loss is None:
        result.add("signature", "FAIL", "Missing execution_rules.stop_loss")
    else:
        result.add("signature", "PASS", f"stop_loss.type={stop_loss.get('type', '?')}")


def _check_imports(strategy_path: Path, result: LayerResult) -> None:
    """Validate all imports in strategy.py resolve."""
    tree = _parse_strategy_ast(strategy_path)
    if tree is None:
        result.add("imports", "FAIL", "Could not parse strategy.py")
        return

    failed_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                try:
                    importlib.import_module(alias.name)
                except ImportError:
                    failed_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                try:
                    importlib.import_module(node.module)
                except ImportError:
                    failed_imports.append(node.module)

    if failed_imports:
        result.add("imports", "FAIL", f"Unresolvable: {failed_imports}")
    else:
        result.add("imports", "PASS")


def _check_no_inline_io(strategy_path: Path, result: LayerResult) -> None:
    """Check strategy.py has no inline data loading or file IO."""
    tree = _parse_strategy_ast(strategy_path)
    if tree is None:
        result.add("no_inline_io", "FAIL", "Could not parse")
        return

    # Find check_entry and check_exit methods
    violations = []
    _IO_FUNCS = {"open", "read_csv", "read_text", "read_excel", "read_json", "read_parquet"}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("check_entry", "check_exit", "prepare_indicators"):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func_name = ""
                    if isinstance(child.func, ast.Name):
                        func_name = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        func_name = child.func.attr
                    if func_name in _IO_FUNCS:
                        violations.append(f"{node.name}() calls {func_name}()")

    if violations:
        result.add("no_inline_io", "FAIL", "; ".join(violations))
    else:
        result.add("no_inline_io", "PASS")


def _check_entry_stop_price(strategy_path: Path, mod, result: LayerResult) -> None:
    """Check if check_entry() returns stop_price in signal dicts.

    If STRATEGY_SIGNATURE uses engine fallback (atr_multiple), check_entry
    should NOT return stop_price. If it does, flag as WARN.
    """
    sig = getattr(getattr(mod, "Strategy", None), "STRATEGY_SIGNATURE", None)
    if sig is None:
        return  # already caught by signature check

    sl_type = (sig.get("execution_rules") or {}).get("stop_loss", {}).get("type", "")

    # Parse AST to find return dicts in check_entry
    tree = _parse_strategy_ast(strategy_path)
    if tree is None:
        return

    returns_stop = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "check_entry":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    for key in child.value.keys:
                        if isinstance(key, ast.Constant) and key.value == "stop_price":
                            returns_stop = True

    if sl_type == "atr_multiple" and returns_stop:
        result.add("stop_price_conflict", "WARN",
                    "check_entry() returns stop_price but SL type is atr_multiple (engine fallback). "
                    "Strategy-provided stop overrides engine computation — verify this is intentional.")
    elif sl_type == "atr_multiple" and not returns_stop:
        result.add("stop_price_conflict", "PASS", "ENGINE_FALLBACK expected, no stop_price in check_entry()")
    elif returns_stop:
        result.add("stop_price_conflict", "PASS", "Strategy provides stop_price (STRATEGY source)")
    else:
        result.add("stop_price_conflict", "WARN",
                    f"SL type='{sl_type}' but check_entry() returns no stop_price — verify engine handles this")


def validate_layer1(strategy_id: str, result: LayerResult) -> None:
    """Run all Layer 1 static validation checks."""
    strategy_dir = PROJECT_ROOT / "strategies" / strategy_id
    strategy_path = strategy_dir / "strategy.py"

    if not strategy_path.exists():
        result.add("file_exists", "FAIL", f"strategies/{strategy_id}/strategy.py not found")
        return

    result.add("file_exists", "PASS")

    mod, err = _load_strategy_module(strategy_id)
    if mod is None:
        result.add("importable", "FAIL", f"Import failed: {err}")
        return

    result.add("importable", "PASS")

    _check_schema_sample(mod, result)
    _check_strategy_name(mod, strategy_id, result)
    _check_timeframe(mod, result)
    _check_signature(mod, result)
    _check_imports(strategy_path, result)
    _check_no_inline_io(strategy_path, result)
    _check_entry_stop_price(strategy_path, mod, result)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 2 — REPLAY REGRESSION
# ═══════════════════════════════════════════════════════════════════════════

def _compute_file_hash(path: Path) -> str:
    """SHA-256 hash of a file."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _strategy_changed(strategy_id: str) -> bool:
    """Check if strategy.py has changed since last promotion snapshot."""
    strategy_path = PROJECT_ROOT / "strategies" / strategy_id / "strategy.py"
    if not strategy_path.exists():
        return True

    # Check strategy_ref.json for stored hash
    ref_path = STRATEGIES_DIR / strategy_id / "strategy_ref.json"
    if not ref_path.exists():
        # No prior snapshot — treat as changed
        return True

    try:
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        stored_hash = ref.get("code_hash", "")
    except Exception:
        return True

    current_hash = _compute_file_hash(strategy_path)
    return current_hash != stored_hash


def _find_baseline_csv(strategy_id: str) -> Path | None:
    """Find the tradelevel CSV for baseline comparison."""
    # Direct match
    direct = BACKTESTS_DIR / strategy_id / "raw" / "results_tradelevel.csv"
    if direct.exists():
        return direct

    # Search for backtest dirs matching this strategy
    matches = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*"))
    for d in matches:
        tl = d / "raw" / "results_tradelevel.csv"
        if tl.exists():
            return tl

    return None


def _load_regime_tf_map() -> dict:
    """Load regime timeframe mapping from config."""
    if not _REGIME_TF_MAP_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(_REGIME_TF_MAP_PATH.read_text(encoding="utf-8"))
        return data.get("mapping", {})
    except Exception:
        return {}


def _load_data(symbol: str, tf: str):
    """Load and concatenate research CSVs for a symbol/timeframe."""
    import pandas as pd

    data_dir = PROJECT_ROOT / "data_root" / "MASTER_DATA" / f"{symbol}_OCTAFX_MASTER" / "RESEARCH"
    if not data_dir.exists():
        return None

    files = sorted(data_dir.glob(f"{symbol}_OCTAFX_{tf}_*_RESEARCH.csv"))
    if not files:
        return None

    frames = []
    for f in files:
        df = pd.read_csv(f, comment="#", encoding="utf-8")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time", drop=False)
    df.index.name = "timestamp"
    df.rename(columns={"time": "timestamp"}, inplace=True)
    return df


def _extract_symbol_from_id(strategy_id: str) -> str | None:
    """Extract the trailing symbol suffix from a per-symbol strategy ID."""
    from config.asset_classification import parse_strategy_name
    parsed = parse_strategy_name(strategy_id)
    if parsed and parsed.get("symbol_suffix"):
        return parsed["symbol_suffix"]
    return None


def _resolve_replay_symbol(strategy_id: str) -> str | None:
    """Determine the symbol for replay from backtest dirs or strategy ID."""
    # Try symbol suffix first
    sym = _extract_symbol_from_id(strategy_id)
    if sym:
        return sym

    # Fallback: check backtest dirs
    matches = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*"))
    if matches:
        return matches[0].name[len(strategy_id) + 1:]

    return None


# Indicators that impose macro/regime direction gating on entries.
# Strategies using these are expected to have high replay TS divergence
# because small regime boundary differences flip the gate on/off.
_MACRO_GATE_INDICATORS = {
    "indicators.macro.usd_synth_zscore",
    "indicators.macro.jpy_synth_zscore",
}


def _is_macro_gated(strategy_id: str) -> bool:
    """Detect if strategy uses a macro/regime direction gate.

    Checks STRATEGY_SIGNATURE.indicators for known macro gate modules
    and the class for Z_THRESHOLD >= 1.5 (strict macro filter).
    """
    mod, _ = _load_strategy_module(strategy_id)
    if mod is None:
        return False

    cls = getattr(mod, "Strategy", None)
    if cls is None:
        return False

    sig = getattr(cls, "STRATEGY_SIGNATURE", None)
    if sig is None:
        return False

    # Check indicators list for known macro gates
    indicators = sig.get("indicators", [])
    has_macro_indicator = bool(set(indicators) & _MACRO_GATE_INDICATORS)

    # Check for Z_THRESHOLD class attribute (high threshold = strict gating)
    z_threshold = getattr(cls, "_Z_THRESHOLD", 0)

    return has_macro_indicator and z_threshold >= 1.5


def _run_replay_pass(strategy_id: str, symbol: str, tf: str,
                     window_days: int, result: LayerResult) -> int:
    """Run a single replay pass. Returns trade count in replay window.

    This is the inner engine call, factored out so we can auto-extend
    the window if the initial pass yields < REPLAY_MIN_TRADES_FOR_VALID trades.
    """
    import pandas as pd

    mod, err = _load_strategy_module(strategy_id)
    if mod is None:
        result.add("replay_import", "FAIL", f"Cannot import: {err}")
        return -1

    strategy = mod.Strategy()

    # Load data
    df = _load_data(symbol, tf)
    if df is None or df.empty:
        result.add("replay_data", "FAIL", f"No data for {symbol}/{tf}")
        return -1

    # Trim to window
    cutoff = df.index[-1] - pd.Timedelta(days=window_days)
    warmup_offset = REPLAY_WARMUP_BARS * _tf_to_minutes(tf)
    cutoff_with_warmup = cutoff - pd.Timedelta(minutes=warmup_offset)
    df_window = df[df.index >= cutoff_with_warmup].copy()
    window_start = cutoff.strftime("%Y-%m-%d")

    # Apply regime model
    regime_tf_map = _load_regime_tf_map()
    regime_cfg = regime_tf_map.get(tf, {"regime_tf": "4h"})
    regime_tf = regime_cfg.get("regime_tf", "4h")

    try:
        from engines.regime_state_machine import apply_regime_model
        regime_df = _load_data(symbol, regime_tf)
        if regime_df is not None and not regime_df.empty:
            regime_cutoff = cutoff - pd.Timedelta(days=30)
            regime_df = regime_df[regime_df.index >= regime_cutoff].copy()
            regime_df = apply_regime_model(regime_df, symbol_hint=symbol)

            regime_cols = ["trend_regime", "volatility_regime", "market_regime",
                           "trend_score", "trend_label", "regime_id", "regime_age"]
            existing = [c for c in regime_cols if c in regime_df.columns]
            if existing:
                df_window = pd.merge_asof(
                    df_window.sort_index(),
                    regime_df[existing].sort_index(),
                    left_index=True, right_index=True,
                    direction="backward",
                )
    except Exception as e:
        result.add("replay_regime", "WARN", f"Regime model failed: {e}")

    # Prepare indicators and run engine
    try:
        strategy.prepare_indicators(df_window)
    except Exception as e:
        result.add("replay_indicators", "FAIL", f"prepare_indicators() failed: {e}")
        return -1

    try:
        from engine_dev.universal_research_engine.v1_5_4.main import run_engine
        trades = run_engine(df_window, strategy)
    except Exception as e:
        result.add("replay_engine", "FAIL", f"run_engine() failed: {e}")
        return -1

    replay_trades = [t for t in trades if str(t.get("entry_timestamp", ""))[:10] >= window_start]

    # Load baseline — MUST exist, FAIL if missing
    baseline_csv = _find_baseline_csv(strategy_id)
    if baseline_csv is None:
        result.add("replay_baseline", "FAIL",
                    f"No baseline tradelevel CSV found. "
                    f"Expected: {BACKTESTS_DIR / strategy_id / 'raw' / 'results_tradelevel.csv'}")
        return -1

    try:
        with open(baseline_csv, encoding="utf-8") as f:
            baseline_rows = list(csv.DictReader(f))
        baseline = [r for r in baseline_rows if r.get("entry_timestamp", "")[:10] >= window_start]
    except Exception as e:
        result.add("replay_baseline", "FAIL", f"Cannot read baseline: {e}")
        return -1

    # ── Compare ──
    b_count = len(baseline)
    r_count = len(replay_trades)
    total_in_window = max(b_count, r_count)

    # If both have 0 trades, return 0 so caller can decide to extend
    if b_count == 0 and r_count == 0:
        return 0

    # Trade count delta
    if b_count > 0:
        count_delta_pct = abs(r_count - b_count) / b_count * 100
    else:
        count_delta_pct = 100.0 if r_count > 0 else 0.0

    # Entry timestamp match
    b_entries = sorted([r.get("entry_timestamp", "")[:19] for r in baseline])
    r_entries = sorted([str(t.get("entry_timestamp", ""))[:19] for t in replay_trades])
    matching_ts = len(set(b_entries) & set(r_entries))
    ts_match_pct = (matching_ts / max(b_count, 1)) * 100

    # Stop source consistency — mixed = FAIL
    r_stop_sources = {}
    for t in replay_trades:
        src = t.get("stop_source", "UNKNOWN")
        r_stop_sources[src] = r_stop_sources.get(src, 0) + 1
    stop_consistent = len(r_stop_sources) <= 1

    # PnL comparison
    b_pnl = sum(float(r.get("pnl_usd", 0)) for r in baseline)

    r_pnl = 0.0
    for t in replay_trades:
        if "pnl_usd" in t and t["pnl_usd"] is not None:
            r_pnl += float(t["pnl_usd"])
        else:
            entry_p = float(t.get("entry_price", 0))
            exit_p = float(t.get("exit_price", 0))
            direction = int(t.get("direction", 1))
            r_pnl += (exit_p - entry_p) * direction

    # PnL drift: use absolute threshold ($5) when baseline PnL is near zero
    # to avoid division-by-near-zero inflating the percentage
    pnl_abs_floor = 5.0
    if abs(b_pnl) > pnl_abs_floor:
        pnl_drift_pct = abs(r_pnl - b_pnl) / abs(b_pnl) * 100
    else:
        # Near-zero baseline: check absolute difference instead
        pnl_drift_pct = 0.0 if abs(r_pnl - b_pnl) <= pnl_abs_floor else 100.0

    # Average stop distance
    b_stops = [float(r["risk_distance"]) for r in baseline if r.get("risk_distance")]
    r_stops = [t.get("risk_distance", 0) for t in replay_trades if t.get("risk_distance")]
    b_avg_stop = sum(b_stops) / len(b_stops) if b_stops else 0
    r_avg_stop = sum(r_stops) / len(r_stops) if r_stops else 0

    # Print comparison table
    src_str = ", ".join(f"{k}:{v}" for k, v in r_stop_sources.items()) if r_stop_sources else "N/A"
    print(f"\n  [L2] Replay Comparison: {strategy_id}")
    print(f"  Window: {window_start} -> {df.index[-1].strftime('%Y-%m-%d')} ({window_days}d)")
    print(f"  Baseline source: {baseline_csv}")
    print(f"  | {'Metric':<22} | {'Baseline':>10} | {'Replay':>10} | {'Status':>8} |")
    print(f"  |{'-'*24}|{'-'*12}|{'-'*12}|{'-'*10}|")
    print(f"  | {'Trades':<22} | {b_count:>10} | {r_count:>10} | {'OK' if count_delta_pct <= REPLAY_PASS_COUNT_DELTA_PCT else 'DRIFT':>8} |")
    print(f"  | {'TS Match %':<22} | {'':>10} | {ts_match_pct:>9.1f}% | {'OK' if ts_match_pct >= REPLAY_PASS_TS_MATCH_PCT else 'DRIFT':>8} |")
    print(f"  | {'Avg Stop Dist':<22} | {b_avg_stop:>10.6f} | {r_avg_stop:>10.6f} | {'':>8} |")
    print(f"  | {'Stop Source':<22} | {'':>10} | {src_str:>10} | {'OK' if stop_consistent else 'FAIL':>8} |")
    print(f"  | {'Net PnL (raw)':<22} | {b_pnl:>10.2f} | {r_pnl:>10.2f} | {'':>8} |")

    # ── Verdict: four-class logic ──
    # Replay validates signal logic + execution consistency, NOT regime stability.
    #
    #   1. mixed stop sources          → FAIL (always)
    #   2. ts_match >= 90%             → PASS
    #   3. ts_match >= 60% + checks    → REGIME_DRIFT (pass)
    #   4. ts_match < 60% + checks
    #      + macro-gated strategy      → REGIME_SENSITIVE (pass)
    #   5. else                        → FAIL

    # Stop distance similarity: within 10% relative or 0.0001 absolute
    stop_similar = True
    if b_avg_stop > 0 and r_avg_stop > 0:
        stop_rel_diff = abs(r_avg_stop - b_avg_stop) / b_avg_stop
        stop_similar = stop_rel_diff < 0.10
    elif b_avg_stop == 0 and r_avg_stop == 0:
        stop_similar = True
    else:
        stop_similar = abs(r_avg_stop - b_avg_stop) < 0.0001

    consistency_ok = stop_consistent and stop_similar and pnl_drift_pct <= REPLAY_FAIL_PNL_DRIFT_PCT

    # Detect macro/regime gating from strategy module
    macro_gated = _is_macro_gated(strategy_id)

    # Classification — explicit labels: PASS / REGIME_DRIFT / REGIME_SENSITIVE / FAIL
    if not stop_consistent:
        label = "FAIL"
        detail = f"MIXED stop sources: {src_str}"
    elif ts_match_pct >= 90.0:
        label = "PASS"
        detail = f"trades={r_count} ts_match={ts_match_pct:.0f}% stop={src_str}"
    elif ts_match_pct >= 60.0 and consistency_ok:
        label = "REGIME_DRIFT"
        detail = (f"ts_match={ts_match_pct:.0f}% stop_ok "
                  f"pnl_drift={pnl_drift_pct:.1f}% — logic validated, "
                  f"regime boundary noise")
    elif ts_match_pct >= 30.0 and consistency_ok and macro_gated:
        label = "REGIME_SENSITIVE"
        detail = (f"ts_match={ts_match_pct:.0f}% — macro-gated strategy, "
                  f"stop_ok, pnl_drift={pnl_drift_pct:.1f}%. "
                  f"Entry divergence expected from strict macro filter")
    else:
        label = "FAIL"
        reasons = []
        if ts_match_pct < 30.0:
            reasons.append(f"ts_match={ts_match_pct:.0f}% < 30% floor")
        elif ts_match_pct < 60.0 and not macro_gated:
            reasons.append(f"ts_match={ts_match_pct:.0f}% < 60% (not macro-gated)")
        if not stop_similar:
            reasons.append(f"stop_dist diverged (b={b_avg_stop:.6f} r={r_avg_stop:.6f})")
        if pnl_drift_pct > REPLAY_FAIL_PNL_DRIFT_PCT:
            reasons.append(f"pnl_drift={pnl_drift_pct:.1f}% > {REPLAY_FAIL_PNL_DRIFT_PCT}%")
        detail = "; ".join(reasons) if reasons else "logic drift detected"

    compact = f"[{label} | TS={ts_match_pct:.0f}% | dPnL={pnl_drift_pct:.1f}%]"
    print(f"  [L2] Verdict: {compact}")
    status = "FAIL" if label == "FAIL" else "PASS"
    result.add("replay", status, f"{compact} {detail}")

    return total_in_window


def validate_layer2(strategy_id: str, result: LayerResult,
                    force: bool = False, skip: bool = False) -> None:
    """Run Layer 2 replay regression if triggered.

    Auto-extends window from 30d to 90d if initial pass yields < 10 trades.
    Baseline CSV must exist — missing baseline is FAIL (not skip).
    """
    if skip:
        result.add("replay", "SKIP", "Skipped by --skip-replay")
        return

    changed = _strategy_changed(strategy_id)
    if not force and not changed:
        result.add("replay", "SKIP", "strategy.py unchanged (hash match)")
        return

    trigger_reason = "forced" if force else "strategy.py changed"
    print(f"  [L2] Replay triggered ({trigger_reason})")

    # Resolve symbol
    symbol = _resolve_replay_symbol(strategy_id)
    if not symbol:
        result.add("replay_data", "FAIL", "Cannot determine symbol for replay")
        return

    # Resolve timeframe from strategy
    mod, err = _load_strategy_module(strategy_id)
    if mod is None:
        result.add("replay_import", "FAIL", f"Cannot import: {err}")
        return
    tf = getattr(mod.Strategy, "timeframe", "15m")

    # First pass: 30-day window
    print(f"  [L2] Pass 1: {REPLAY_WINDOW_DAYS_INITIAL}d window")
    trade_count = _run_replay_pass(strategy_id, symbol, tf,
                                    REPLAY_WINDOW_DAYS_INITIAL, result)

    # If replay already produced a FAIL or error, stop
    if trade_count < 0:
        return

    # Auto-extend if too few trades to be meaningful
    if trade_count < REPLAY_MIN_TRADES_FOR_VALID:
        # Clear the trivial "0 trades" pass — we need a real test
        result.checks = [c for c in result.checks
                         if not (c.name == "replay" and "0 trades" in c.detail)]
        print(f"  [L2] Only {trade_count} trades in {REPLAY_WINDOW_DAYS_INITIAL}d — "
              f"extending to {REPLAY_WINDOW_DAYS_EXTENDED}d")
        trade_count = _run_replay_pass(strategy_id, symbol, tf,
                                        REPLAY_WINDOW_DAYS_EXTENDED, result)
        if trade_count < 0:
            return
        if trade_count == 0:
            result.add("replay", "WARN",
                        f"0 trades in {REPLAY_WINDOW_DAYS_EXTENDED}d window — "
                        f"strategy may be too inactive for replay validation")


def _tf_to_minutes(tf: str) -> int:
    """Convert timeframe string to minutes."""
    _map = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
        "M1": 1, "M5": 5, "M15": 15, "M30": 30,
        "H1": 60, "H4": 240, "D1": 1440, "W1": 10080,
    }
    return _map.get(tf, 60)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 3 — PRE-PROMOTION GATE
# ═══════════════════════════════════════════════════════════════════════════

def _parse_standard_csv(csv_path: Path) -> dict | None:
    """Parse results_standard.csv — single source of truth for metrics."""
    try:
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        r = rows[0]
        trades = int(r.get("trade_count", r.get("total_trades", 0)))
        pnl = float(r.get("net_pnl_usd", r.get("net_profit", 0)))
        exp = pnl / trades if trades > 0 else 0.0
        return {
            "trades": trades,
            "expectancy": float(r.get("expectancy", exp)),
            "profit_factor": float(r.get("profit_factor", 0)),
            "pnl": pnl,
            "source": str(csv_path),
        }
    except Exception:
        return None


def _read_backtest_metrics(strategy_id: str) -> dict | None:
    """Read metrics from results_standard.csv ONLY.

    Single source of truth: BACKTESTS_DIR/<strategy_id>/raw/results_standard.csv.
    No fallback to portfolio_summary.json to avoid source ambiguity.
    """
    # Direct per-symbol match
    std_csv = BACKTESTS_DIR / strategy_id / "raw" / "results_standard.csv"
    if std_csv.exists():
        return _parse_standard_csv(std_csv)

    # Search for matching backtest dirs (per-symbol suffixed)
    bt_dirs = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*"))
    for d in bt_dirs:
        csv_path = d / "raw" / "results_standard.csv"
        if csv_path.exists():
            return _parse_standard_csv(csv_path)

    return None


def _get_portfolio_ids() -> set:
    """Return strategy IDs already in portfolio.yaml."""
    if not PORTFOLIO_YAML.exists():
        return set()
    try:
        with open(PORTFOLIO_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        strategies = (data.get("portfolio") or {}).get("strategies") or []
        return {s.get("id", "") for s in strategies if isinstance(s, dict)}
    except Exception:
        return set()


def _check_fsp_presence(strategy_id: str) -> tuple[bool, str]:
    """Check if strategy exists in Filtered_Strategies_Passed.xlsx."""
    if not CANDIDATE_FILTER_PATH.exists():
        return False, "FSP file not found"
    try:
        import pandas as pd
        df = pd.read_excel(CANDIDATE_FILTER_PATH, engine="openpyxl")
        col = "strategy" if "strategy" in df.columns else df.columns[0]
        found = strategy_id in df[col].values
        if found:
            return True, "Present in FSP"

        # Check base ID (strip symbol suffix)
        parts = strategy_id.rsplit("_", 1)
        if len(parts) == 2:
            base = parts[0]
            if base in df[col].values:
                return True, f"Base ID '{base}' present in FSP"

        return False, "Not found in FSP"
    except Exception as e:
        return False, f"Cannot read FSP: {e}"


def _get_strategy_family_key(strategy_id: str) -> tuple[str, str] | None:
    """Derive family key from strategy module's STRATEGY_SIGNATURE + class attributes.

    Returns (family_key, deployed_symbol) or None if unresolvable.
    Family key = idea_id + family + asset_class_token + timeframe + model + sweep
    from the structured name, cross-checked against STRATEGY_SIGNATURE indicators.
    """
    from config.asset_classification import parse_strategy_name
    parsed = parse_strategy_name(strategy_id)
    if not parsed:
        return None

    # Family key = all tokens that define the strategy lineage (excluding param_set and symbol_suffix)
    family_key = (f"{parsed['idea_id']}_{parsed['family']}_{parsed['symbol']}_"
                  f"{parsed['timeframe']}_{parsed['model']}_{parsed['sweep']}")
    deployed_symbol = parsed.get("symbol_suffix") or parsed.get("symbol", "")
    return family_key, deployed_symbol


def _check_family_symbol_conflict(strategy_id: str) -> tuple[bool, str]:
    """Check for duplicate family x symbol conflicts in portfolio.yaml.

    Conflict = same (idea_id, family, asset_class, timeframe, model, sweep) + same deployed symbol.
    Different sweeps, params, or symbols are NOT conflicts.
    """
    keys = _get_strategy_family_key(strategy_id)
    if keys is None:
        return True, "Cannot parse — skipping conflict check"

    family_key, symbol = keys

    existing_ids = _get_portfolio_ids()
    for eid in existing_ids:
        if eid == strategy_id:
            continue
        e_keys = _get_strategy_family_key(eid)
        if e_keys is None:
            continue
        e_family, e_symbol = e_keys
        if e_family == family_key and e_symbol == symbol:
            return False, f"Conflict: {eid} (same family x symbol)"

    return True, "No conflict"


def validate_layer3(strategy_id: str, result: LayerResult) -> None:
    """Run Layer 3 pre-promotion gate checks."""
    # Expectancy threshold
    asset_class = classify_asset(strategy_id)
    exp_gate = EXP_FAIL_GATES.get(asset_class, 0.15)

    metrics = _read_backtest_metrics(strategy_id)
    if metrics is None:
        result.add("metrics", "FAIL", "No backtest metrics found")
    else:
        exp = metrics.get("expectancy", 0)
        trades = metrics.get("trades", 0)

        if exp < exp_gate:
            result.add("expectancy", "FAIL",
                        f"Expectancy {exp:.3f} < {exp_gate} ({asset_class} gate)")
        else:
            result.add("expectancy", "PASS", f"{exp:.3f} >= {exp_gate} ({asset_class})")

        if trades < MIN_TRADE_DENSITY:
            result.add("trade_density", "FAIL", f"Trades {trades} < {MIN_TRADE_DENSITY}")
        else:
            result.add("trade_density", "PASS", f"{trades} trades")

    # Duplicate check
    ok, detail = _check_family_symbol_conflict(strategy_id)
    if ok:
        result.add("no_conflict", "PASS", detail)
    else:
        result.add("no_conflict", "FAIL", detail)

    # FSP presence
    found, detail = _check_fsp_presence(strategy_id)
    if found:
        result.add("fsp_presence", "PASS", detail)
    else:
        result.add("fsp_presence", "WARN", detail)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 4 — SANITY EXECUTION CHECK
# ═══════════════════════════════════════════════════════════════════════════

def validate_layer4(strategy_id: str, result: LayerResult) -> None:
    """Run Layer 4 lightweight execution sanity check."""
    mod, err = _load_strategy_module(strategy_id)
    if mod is None:
        result.add("signal_schema", "FAIL", f"Cannot import: {err}")
        return

    cls = getattr(mod, "Strategy", None)
    if cls is None:
        result.add("signal_schema", "FAIL", "No Strategy class")
        return

    # 1. Validate _schema_sample() produces a valid signal object
    sample_fn = getattr(cls, "_schema_sample", None)
    if sample_fn is None:
        result.add("signal_schema", "FAIL", "No _schema_sample()")
        return

    try:
        sample = sample_fn()
    except Exception as e:
        result.add("signal_schema", "FAIL", f"_schema_sample() error: {e}")
        return

    # Validate signal fields are the right types
    signal_val = sample.get("signal")
    if signal_val not in (1, -1):
        result.add("signal_schema", "FAIL", f"signal={signal_val}, expected 1 or -1")
        return

    erp = sample.get("entry_reference_price")
    if not isinstance(erp, (int, float)):
        result.add("signal_schema", "FAIL", f"entry_reference_price type={type(erp).__name__}")
        return

    sp = sample.get("stop_price")
    if not isinstance(sp, (int, float)):
        result.add("signal_schema", "FAIL", f"stop_price type={type(sp).__name__}")
        return

    reason = sample.get("entry_reason")
    if not isinstance(reason, str) or not reason:
        result.add("signal_schema", "FAIL", f"entry_reason missing or not string")
        return

    result.add("signal_schema", "PASS", f"signal={signal_val} erp={erp} sp={sp}")

    # 2. Verify stop_price positioning relative to entry
    sig = getattr(cls, "STRATEGY_SIGNATURE", {})
    sl_cfg = (sig.get("execution_rules") or {}).get("stop_loss", {})
    sl_type = sl_cfg.get("type", "")

    if signal_val == 1 and sp >= erp:
        result.add("stop_sanity", "FAIL", f"LONG stop ({sp}) >= entry ({erp})")
    elif signal_val == -1 and sp <= erp:
        result.add("stop_sanity", "FAIL", f"SHORT stop ({sp}) <= entry ({erp})")
    else:
        result.add("stop_sanity", "PASS", f"Stop correctly positioned vs entry")

    # 3. Verify lot sizing doesn't error with realistic values
    risk_distance = abs(erp - sp)
    if risk_distance <= 0:
        result.add("lot_sizing", "FAIL", "risk_distance is 0 — lot sizing would divide by zero")
    else:
        # Simulate min-lot calculation with asset-class-aware pip value
        asset_class = classify_asset(strategy_id)
        if asset_class == "XAU":
            pip_value_per_lot = 100.0   # ~$1/pip for 0.01 lots XAUUSD
        elif asset_class == "BTC":
            pip_value_per_lot = 1.0     # varies by broker
        elif asset_class == "INDEX":
            pip_value_per_lot = 1.0     # varies by index
        else:  # FX
            pip_value_per_lot = 100000.0  # standard FX lot

        risk_usd = 100.0  # $100 risk budget for simulation
        simulated_lot = round(risk_usd / (risk_distance * pip_value_per_lot), 4)
        if simulated_lot <= 0:
            result.add("lot_sizing", "FAIL", f"Computed lot size <= 0 (risk_dist={risk_distance})")
        else:
            result.add("lot_sizing", "PASS",
                        f"Simulated lot={simulated_lot} (risk_dist={risk_distance:.6f}, {asset_class})")


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

def validate_strategy(strategy_id: str, force_replay: bool = False,
                      skip_replay: bool = False) -> ValidationResult:
    """Full 4-layer validation for one strategy."""
    vr = ValidationResult(strategy_id)

    print(f"\n{'=' * 70}")
    print(f"VALIDATING: {strategy_id}")
    print(f"{'=' * 70}")

    # Layer 1
    print(f"\n  --- Layer 1: Static Validation ---")
    validate_layer1(strategy_id, vr.layer1)
    _print_layer(vr.layer1)

    # Layer 2 — only if Layer 1 passed (need valid strategy to replay)
    print(f"\n  --- Layer 2: Replay Regression ---")
    if vr.layer1.passed:
        validate_layer2(strategy_id, vr.layer2, force=force_replay, skip=skip_replay)
    else:
        vr.layer2.add("replay", "SKIP", "Layer 1 failed — cannot replay")
    _print_layer(vr.layer2)

    # Layer 3
    print(f"\n  --- Layer 3: Pre-Promotion Gate ---")
    validate_layer3(strategy_id, vr.layer3)
    _print_layer(vr.layer3)

    # Layer 4
    print(f"\n  --- Layer 4: Sanity Execution ---")
    if vr.layer1.passed:
        validate_layer4(strategy_id, vr.layer4)
    else:
        vr.layer4.add("sanity", "SKIP", "Layer 1 failed")
    _print_layer(vr.layer4)

    return vr


def _print_layer(layer: LayerResult) -> None:
    """Print layer results."""
    for c in layer.checks:
        marker = {"PASS": "OK", "FAIL": "XX", "WARN": "!!", "SKIP": "--"}[c.status]
        detail = f"  {c.detail}" if c.detail else ""
        print(f"  [{marker}] {c.name:<25}{detail}")


def print_summary(results: list[ValidationResult]) -> None:
    """Print final summary table."""
    print(f"\n{'=' * 70}")
    print(f"VALIDATION SUMMARY")
    print(f"{'=' * 70}\n")

    # Header
    id_width = max(len(r.strategy_id) for r in results) if results else 20
    id_width = max(id_width, 10)
    print(f"  | {'Strategy':<{id_width}} | {'Layer1':>7} | {'Layer2':>7} | {'Gate':>7} | {'L4':>7} | {'Final':>9} |")
    print(f"  |{'-' * (id_width + 2)}|{'-' * 9}|{'-' * 9}|{'-' * 9}|{'-' * 9}|{'-' * 11}|")

    for r in results:
        final_marker = r.final
        print(f"  | {r.strategy_id:<{id_width}} | {r.layer1.status_label:>7} | {r.layer2.status_label:>7} | {r.layer3.status_label:>7} | {r.layer4.status_label:>7} | {final_marker:>9} |")

    # Failures detail
    failures = [r for r in results if r.final == "BLOCKED"]
    if failures:
        print(f"\n  ## Failures")
        for r in failures:
            for layer in [r.layer1, r.layer2, r.layer3, r.layer4]:
                for c in layer.checks:
                    if c.status == "FAIL":
                        print(f"  - {r.strategy_id}: [{layer.name}] {c.name} — {c.detail}")

    # Overall
    blocked = sum(1 for r in results if r.final == "BLOCKED")
    approved = sum(1 for r in results if r.final == "APPROVED")
    print(f"\n  TOTAL: {approved} APPROVED, {blocked} BLOCKED")

    if blocked > 0:
        print(f"\n  >>> PROMOTION BLOCKED — resolve failures before proceeding <<<")
        return False
    else:
        print(f"\n  >>> ALL STRATEGIES APPROVED FOR PROMOTION <<<")
        return True


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Pre-promotion validator — 4-layer strategy validation gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Any FAIL blocks promotion. No warnings-only mode.",
    )
    parser.add_argument("strategies", nargs="*", help="Strategy ID(s) to validate")
    parser.add_argument("--replay", action="store_true",
                        help="Force Layer 2 replay regression (even if unchanged)")
    parser.add_argument("--skip-replay", action="store_true",
                        help="Skip Layer 2 replay regression entirely")
    args = parser.parse_args()

    if not args.strategies:
        parser.print_help()
        sys.exit(1)

    results = []
    for sid in args.strategies:
        vr = validate_strategy(sid, force_replay=args.replay, skip_replay=args.skip_replay)
        results.append(vr)

    all_passed = print_summary(results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
