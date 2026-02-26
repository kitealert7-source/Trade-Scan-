"""
Schema validation for Robustness Engine.
Ensures DataFrames comply with contract before computations run.
"""
import pandas as pd

REQUIRED_TRADE_COLUMNS = [
    "symbol",
    "entry_timestamp",
    "exit_timestamp",
    "direction",
    "pnl_usd",
]

REQUIRED_EQUITY_COLUMNS = [
    "timestamp",
    "equity",
]

def validate_trade_df(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_TRADE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Trade DataFrame missing required columns: {missing}")

def validate_equity_df(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_EQUITY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Equity DataFrame missing required columns: {missing}")
