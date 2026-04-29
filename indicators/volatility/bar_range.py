import pandas as pd

# --- Semantic Contract (Phase 3) ---
SIGNAL_PRIMITIVE = "bar_hl_range"
PIVOT_SOURCE = "none"


def bar_range(df: pd.DataFrame) -> pd.Series:
    """Per-bar high-low range (stateless).

    Returns df['high'] - df['low']. Used as a proxy for per-bar volatility
    expansion; comparing bar_range_now vs bar_range_prev detects whether
    the current bar expanded (instability) or contracted (smooth decay)
    relative to the prior bar.
    """
    return df['high'].astype(float) - df['low'].astype(float)
