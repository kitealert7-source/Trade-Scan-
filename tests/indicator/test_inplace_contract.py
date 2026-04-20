"""Guardrail: in-place mutator indicators must preserve the caller's df identity.

The Stage-1 contract requires that indicators declared as in-place mutators
(i.e. the docstring says "Mutates df in place") add their columns to the
caller's DataFrame — not a copy. Returning a new object silently strips the
columns if a caller forgets to reassign.

This test iterates over a known registry of in-place mutators, calls each
against a small synthetic OHLCV frame, and asserts the returned object is
the same Python object that was passed in.

Transformer-style indicators (keltner_channel, usd_stress_index,
range_breakout_session — which use set_index/join/shape-changing ops) are
intentionally excluded. They do not claim the in-place contract and callers
must reassign their return value.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.price.candle_state import apply as candle_state_apply
from indicators.price.consecutive_closes import consecutive_closes
from indicators.price.previous_bar_breakout import apply as previous_bar_breakout_apply


IN_PLACE_MUTATORS = [
    ("candle_state", candle_state_apply),
    ("consecutive_closes", consecutive_closes),
    ("previous_bar_breakout", previous_bar_breakout_apply),
]


def _ohlcv(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    close = 100 + rng.normal(0, 1, n).cumsum()
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC"),
        "open": close + rng.normal(0, 0.1, n),
        "high": close + rng.uniform(0.1, 0.5, n),
        "low": close - rng.uniform(0.1, 0.5, n),
        "close": close,
        "volume": rng.integers(100, 1000, n),
    })


@pytest.mark.parametrize("name,fn", IN_PLACE_MUTATORS, ids=[n for n, _ in IN_PLACE_MUTATORS])
def test_indicator_preserves_df_identity(name, fn):
    df = _ohlcv()
    before_id = id(df)
    before_cols = set(df.columns)
    out = fn(df)

    assert id(out) == before_id, (
        f"Indicator '{name}' violated in-place contract: returned a new "
        f"DataFrame instead of mutating the caller's df. "
        f"Check for 'df = df.copy()' or pandas ops that return new frames."
    )

    # Column persistence: new columns must land on the caller's df, and no
    # existing column may be dropped. Catches the case where an indicator
    # mutates a local/temporary frame instead of the passed-in object.
    after_cols = set(df.columns)
    assert after_cols >= before_cols, (
        f"Indicator '{name}' dropped columns from the caller's df: "
        f"missing={sorted(before_cols - after_cols)}"
    )
    assert after_cols > before_cols, (
        f"Indicator '{name}' returned caller's df but added no columns — "
        f"mutation landed on a temporary object instead of the input."
    )


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
