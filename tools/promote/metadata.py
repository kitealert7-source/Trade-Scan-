"""Strategy metadata inference: archetype, symbol detection, timeframe normalization,
per-symbol expectancy filtering, and portfolio.yaml metadata reads.
"""

import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.asset_classification import classify_asset, EXP_FAIL_GATES
from config.state_paths import BACKTESTS_DIR


# ── Archetype inference ─────────────────────────────────────────────────────
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


# ── portfolio.yaml metadata read (lazy import of yaml_writer) ────────────────

def read_strategy_metadata(strategy_id: str) -> dict:
    """Read vault_id, profile, lifecycle from portfolio.yaml for a strategy.

    Returns dict with keys: vault_id, profile, lifecycle, enabled.
    Returns empty dict if strategy not found.
    """
    from tools.promote.yaml_writer import _load_portfolio_yaml

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
