"""
Research Data Reader — Handles data loading for backtests.
Located in data_access/, NOT in engine.

Responsibilities:
- Load data from MASTER_DATA/*/RESEARCH/
- Skip # comment lines in CSV
- Map timeframes (Daily → 1d)
- Concatenate yearly files
"""

import pandas as pd
from pathlib import Path
from typing import Optional


# Timeframe normalization map
TIMEFRAME_MAP = {
    "Daily": "1d",
    "daily": "1d",
    "D1": "1d",
    "1D": "1d",
    "1d": "1d",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "30m": "30m",
}


def load_research_data(
    symbol: str,
    timeframe: str,
    broker: str,
    start_date: str,
    end_date: str,
    data_root: Optional[Path] = None
) -> pd.DataFrame:
    """
    Load research-grade data from MASTER_DATA.
    
    Args:
        symbol: Symbol name (e.g., SPX500)
        timeframe: Timeframe string (e.g., Daily, 1d)
        broker: Broker name (e.g., OctaFX)
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        data_root: Optional override for data root path
        
    Returns:
        DataFrame with OHLCV data, filtered by date range
        
    Raises:
        FileNotFoundError: If no matching data files found
        ValueError: If required columns missing
    """
    # Normalize timeframe
    tf = TIMEFRAME_MAP.get(timeframe, timeframe)
    
    # Determine data root
    if data_root is None:
        # Default: Trade_Scan/data_root/MASTER_DATA
        data_root = Path(__file__).parent.parent.parent / "data_root" / "MASTER_DATA"
    
    # Search for RESEARCH files matching symbol and timeframe
    pattern = f"*{symbol}*{tf}*RESEARCH.csv"
    matches = list(data_root.rglob(pattern))
    
    if not matches:
        # Try without RESEARCH suffix
        pattern2 = f"*{symbol}*{tf}*.csv"
        matches = [m for m in data_root.rglob(pattern2) if "RESEARCH" in str(m)]
    
    if not matches:
        raise FileNotFoundError(
            f"No data file found for {symbol} {tf} {broker} in {data_root}"
        )
    
    # Load and concatenate all matching files
    dfs = []
    for data_file in sorted(matches):
        df_part = pd.read_csv(data_file, comment='#')
        dfs.append(df_part)
    
    df = pd.concat(dfs, ignore_index=True)
    
    # Normalize column names
    df.columns = [c.lower() for c in df.columns]
    
    # Ensure required columns
    required = ['open', 'high', 'low', 'close']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Handle timestamp column
    time_cols = ['timestamp', 'time', 'date', 'datetime']
    time_col = None
    for tc in time_cols:
        if tc in df.columns:
            time_col = tc
            break
    
    if time_col:
        df['timestamp'] = pd.to_datetime(df[time_col])
        df = df.sort_values('timestamp').reset_index(drop=True)
        df = df.set_index('timestamp', drop=False)
        
        # Filter by date range
        df = df.loc[start_date:end_date]
    
    df = df.reset_index(drop=True)
    
    return df
