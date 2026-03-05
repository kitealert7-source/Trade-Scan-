"""
usd_stress_index.py — USD Stress Index Indicator

External Dependency:
    Requires USD_SYNTH daily return data at:
    USD_SYNTH_PATH (configurable constant below)

    Default: data_root/SYSTEM_FACTORS/USD_SYNTH/usd_synth_return_d1.csv

    Expected CSV columns: Date, USD_SYNTH_RET_D1

Output Scale: N/A (raw return for usd_stress; 0–1 rolling percentile for usd_stress_percentile)
"""

from pathlib import Path
import pandas as pd

# =============================================================================
# GOVERNANCE: External Dependency Isolation
# File path is declared here as a configurable constant.
# Override this constant in tests or alternative deployments.
# Do NOT hardcode paths inside function bodies.
# =============================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

USD_SYNTH_PATH = (
    _PROJECT_ROOT
    / "data_root"
    / "SYSTEM_FACTORS"
    / "USD_SYNTH"
    / "usd_synth_return_d1.csv"
)

# Rolling window for percentile computation (configurable)
USD_STRESS_PERCENTILE_WINDOW: int = 60


def apply(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    Joins USD stress index data to the input DataFrame.

    External dependency: USD_SYNTH_PATH must exist.
    Raises FileNotFoundError with descriptive message if file is missing.

    Output columns:
        usd_stress            : float — lagged daily USD synthetic return (D-1)
        usd_stress_percentile : float — 60-day rolling percentile of USD stress (0–1 scale)

    Output Scale:
        usd_stress            : unbounded float (log return)
        usd_stress_percentile : 0.0–1.0 rolling percentile

    Lookahead Safety:
        CRITICAL: 1-day lag applied (shift(1)) to prevent intraday lookahead.
        Intraday bars only see data from D-1 completed day.

    Args:
        df: DataFrame with timestamp/time column and any price columns
        params: unused (reserved for future parameterization)
    """

    df = df.copy()

    # -------------------------------------------------------------------------
    # GOVERNANCE: External Dependency Check
    # Raise descriptive error if file is missing — no silent failure.
    # -------------------------------------------------------------------------
    if not USD_SYNTH_PATH.exists():
        raise FileNotFoundError(
            f"usd_stress_index: Required data file not found at:\n"
            f"  {USD_SYNTH_PATH}\n"
            f"Ensure USD_SYNTH dataset is present under data_root/SYSTEM_FACTORS/USD_SYNTH/. "
            f"Run build_usd_synth.py to regenerate."
        )

    stress_df = pd.read_csv(USD_SYNTH_PATH)

    # Expect columns: Date, USD_SYNTH_RET_D1
    stress_df["Date"] = pd.to_datetime(stress_df["Date"])
    stress_df = stress_df.sort_values("Date").set_index("Date")

    # Base stress metric (daily log return)
    stress_df["usd_stress"] = stress_df["USD_SYNTH_RET_D1"]

    # 60-day rolling percentile (STRICTLY backward-looking)
    stress_df["usd_stress_percentile"] = (
        stress_df["usd_stress"]
        .rolling(USD_STRESS_PERCENTILE_WINDOW)
        .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])
    )

    # ---------------------------------------------------------
    # CRITICAL FIX: LAG DAILY VALUES BY 1 COMPLETED DAY
    # ---------------------------------------------------------
    # Ensures intraday bars on D only see completed data from D-1
    stress_df["usd_stress"] = stress_df["usd_stress"].shift(1)
    stress_df["usd_stress_percentile"] = stress_df["usd_stress_percentile"].shift(1)
    # ---------------------------------------------------------

    # Align to input dataframe
    ts_col = (
        "timestamp"
        if "timestamp" in df.columns
        else "time"
        if "time" in df.columns
        else df.columns[0]
    )

    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col)

    df = df.join(
        stress_df[["usd_stress", "usd_stress_percentile"]],
        how="left"
    )

    # Forward fill within intraday bars
    df["usd_stress"] = df["usd_stress"].ffill()
    df["usd_stress_percentile"] = df["usd_stress_percentile"].ffill()

    df = df.reset_index()

    return df