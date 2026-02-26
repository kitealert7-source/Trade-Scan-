from pathlib import Path
import pandas as pd

def apply(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:

    df = df.copy()

    # Resolve project root deterministically
    project_root = Path(__file__).resolve().parents[2]

    data_path = (
        project_root
        / "data_root"
        / "SYSTEM_FACTORS"
        / "USD_SYNTH"
        / "usd_synth_return_d1.csv"
    )

    if not data_path.exists():
        raise FileNotFoundError(f"USD stress file not found: {data_path}")

    stress_df = pd.read_csv(data_path)

    # Expect columns: Date, USD_SYNTH_RET_D1
    stress_df["Date"] = pd.to_datetime(stress_df["Date"])
    stress_df = stress_df.sort_values("Date").set_index("Date")

    # Base stress metric (daily log return)
    stress_df["usd_stress"] = stress_df["USD_SYNTH_RET_D1"]

    # 60-day rolling percentile (STRICTLY backward-looking)
    window = 60
    stress_df["usd_stress_percentile"] = (
        stress_df["usd_stress"]
        .rolling(window)
        .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])
    )

    # ---------------------------------------------------------
    # CRITICAL FIX: LAG DAILY VALUES BY 1 COMPLETED DAY
    # ---------------------------------------------------------
    # Ensures intraday bars on D only see completed data from D-1
    stress_df["usd_stress"] = stress_df["usd_stress"].shift(1)
    stress_df["usd_stress_percentile"] = stress_df["usd_stress_percentile"].shift(1)
    # ---------------------------------------------------------

    # Align to 4H dataframe
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