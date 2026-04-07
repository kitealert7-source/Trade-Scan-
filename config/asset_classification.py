"""
asset_classification.py — Single source of truth for asset class detection.

Replaces duplicated keyword-matching in portfolio_evaluator._detect_asset_class()
and filter_strategies._compute_candidate_status().

Classification uses token position 3 (SYMBOL) from the namespace convention,
NOT substring search on the full ID. This eliminates false-match risk
(e.g. a hypothetical "GERFX" strategy being classified as INDEX due to "GER").

For PF_ hash composites, returns "MIXED" — these encode no asset structure in
the name; downstream callers should inspect portfolio_metadata.json if needed.
"""

import re
from typing import Optional

# ──────────────────────────────────────────────────────────────────────
# KEYWORD REGISTRY — exhaustive mapping from symbol token to asset class
# ──────────────────────────────────────────────────────────────────────

_SYMBOL_TO_CLASS = {
    # Gold
    "XAU":     "XAU",
    "XAUUSD":  "XAU",
    # Crypto
    "BTC":     "BTC",
    "BTCUSD":  "BTC",
    "ETH":     "BTC",
    "ETHUSD":  "BTC",
    # Indices — abstract class tokens
    "IDX":     "INDEX",
    "APAC":    "INDEX",
    # Indices — specific instruments
    "SPX500":  "INDEX",
    "NAS100":  "INDEX",
    "US30":    "INDEX",
    "UK100":   "INDEX",
    "GER40":   "INDEX",
    "JPN225":  "INDEX",
    "FRA40":   "INDEX",
    "ESP35":   "INDEX",
    "AUS200":  "INDEX",
    "EUSTX50": "INDEX",
}

# Prefix fallback — for partial matches (e.g. "SPX" without "500")
_PREFIX_TO_CLASS = {
    "SPX": "INDEX",
    "NAS": "INDEX",
    "US3": "INDEX",
    "UK1": "INDEX",
    "GER": "INDEX",
    "JPN": "INDEX",
    "FRA": "INDEX",
    "ESP": "INDEX",
    "AUS": "INDEX",
    "EUS": "INDEX",
}

# Expectancy FAIL gates per asset class (min-lot basis).
# Logic-driven from broker spread/slippage ratios.
EXP_FAIL_GATES = {
    "FX":    0.15,
    "XAU":   0.50,
    "BTC":   0.50,
    "INDEX": 0.50,
    "MIXED": 0.0,
}


# ──────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────

def classify_asset(identifier: str) -> str:
    """Classify asset class from a strategy/portfolio ID or raw symbol string.

    Uses token-position-aware parsing for structured IDs:
      - PF_ prefix → "MIXED"
      - Structured name → extracts position-3 symbol token, checks exact then prefix
      - Raw symbol string (XAUUSD, GER40) → exact then prefix match

    Returns one of: "FX", "XAU", "BTC", "INDEX", "MIXED"
    """
    pid = str(identifier).strip().upper()
    if not pid:
        return "FX"

    # PF_ composites — no structure to parse
    if pid.startswith("PF_"):
        return "MIXED"

    # Try to extract the SYMBOL token at position 3 from structured names.
    # Pattern: <id>_<family>_<SYMBOL>_<tf>_...
    parts = pid.split("_")
    if len(parts) >= 4:
        symbol_token = parts[2]
    else:
        # Not structured — treat entire string as a symbol (e.g. "XAUUSD")
        symbol_token = pid

    # 1. Exact match
    cls = _SYMBOL_TO_CLASS.get(symbol_token)
    if cls:
        return cls

    # 2. Prefix match (handles truncated symbols like "SPX" without "500")
    for prefix, cls in _PREFIX_TO_CLASS.items():
        if symbol_token.startswith(prefix):
            return cls

    return "FX"


def classify_asset_series(symbols: "pd.Series") -> "pd.Series":
    """Vectorized asset classification for a pandas Series of symbol strings.

    Designed as a drop-in replacement for the inline keyword matching in
    filter_strategies._compute_candidate_status().

    Returns a Series of asset class strings ("FX", "XAU", "BTC", "INDEX").
    """
    return symbols.apply(lambda s: classify_asset(str(s)))


# ──────────────────────────────────────────────────────────────────────
# STRUCTURED NAME PARSER
# ──────────────────────────────────────────────────────────────────────

# Matches the namespace_gate.py NAME_PATTERN — kept in sync.
#
# SYSTEM INVARIANT (see governance/namespace/token_dictionary.yaml):
#   FILTER tokens MUST end with "FILT"; MODEL tokens MUST NOT contain "FILT".
#   The regex below relies on this: (?:_(?P<filter>[A-Z0-9]+FILT))? matches
#   the optional filter token unambiguously because no model can end in FILT.
_STRUCTURED_RE = re.compile(
    r"^(?:C_)?"
    r"(?P<idea_id>\d{2})_"
    r"(?P<family>[A-Z0-9]+)_"
    r"(?P<symbol>[A-Z0-9]+)_"
    r"(?P<timeframe>[A-Z0-9]+)_"
    r"(?P<model>[A-Z0-9]+)"
    r"(?:_(?P<filter>[A-Z0-9]+FILT))?"
    r"_S(?P<sweep>\d{2})"
    r"_V(?P<variant>\d+)"
    r"_P(?P<parent>\d{2})"
    r"(?:_(?P<symbol_suffix>[A-Z0-9]+))?$"
)


def parse_strategy_name(identifier: str) -> Optional[dict]:
    """Parse a structured strategy/portfolio ID into its component tokens.

    Returns a dict with keys:
        idea_id, family, symbol, timeframe, model, filter, sweep, variant,
        param_set, symbol_suffix, asset_class

    Returns None for PF_ hashes and non-conforming names.
    """
    pid = str(identifier).strip()
    if pid.upper().startswith("PF_"):
        return None

    m = _STRUCTURED_RE.fullmatch(pid.upper())
    if not m:
        return None

    return {
        "idea_id":       m.group("idea_id"),
        "family":        m.group("family"),
        "symbol":        m.group("symbol"),
        "timeframe":     m.group("timeframe"),
        "model":         m.group("model"),
        "filter":        m.group("filter") or "",
        "sweep":         f"S{m.group('sweep')}",
        "variant":       f"V{m.group('variant')}",
        "param_set":     f"P{m.group('parent')}",
        "symbol_suffix": m.group("symbol_suffix") or "",
        "asset_class":   classify_asset(pid),
    }
