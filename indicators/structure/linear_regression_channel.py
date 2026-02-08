"""
Linear Regression Channel Indicator

Pure function indicator for computing rolling linear regression with channel bands.
Extracted and generalized from AK62 implementation.
"""
import pandas as pd
import numpy as np


def linear_regression_channel(
    series: pd.Series,
    window: int,
    std_mult: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Compute Linear Regression Channel.
    
    Args:
        series: Input price series (typically close)
        window: Rolling window for regression
        std_mult: Standard deviation multiplier for channel width
        
    Returns:
        tuple of (lr_mid, lr_upper, lr_lower):
            lr_mid   : Linear regression midline (predicted value at last bar of window)
            lr_upper : Upper channel (midline + std_mult * std)
            lr_lower : Lower channel (midline - std_mult * std)
    """
    # Enforce numeric series
    series = series.astype(float)
    
    # Precompute constants for the regression window
    x = np.arange(window)
    sum_x = np.sum(x)
    sum_x_sq = np.sum(x ** 2)
    N = window
    
    # Rolling sums
    sum_y = series.rolling(window).sum()
    sum_xy = series.rolling(window).apply(lambda s: np.dot(s, x), raw=True)
    
    # Regression coefficients
    # m = (N * sum_xy - sum_x * sum_y) / (N * sum_x_sq - sum_x^2)
    num = (N * sum_xy) - (sum_x * sum_y)
    den = (N * sum_x_sq) - (sum_x ** 2)
    
    # Regression slope (den is constant and non-zero for window >= 2)
    m = num / den
    
    # c = (sum_y - m * sum_x) / N
    c = (sum_y - (m * sum_x)) / N
    
    # Predicted value at last bar of window (x = N-1)
    lr_mid = m * (N - 1) + c
    
    # Rolling standard deviation (explicit ddof=0 for population std)
    rolling_std = series.rolling(window).std(ddof=0)
    
    # NaN safety: replace zero std with NaN to avoid meaningless bands
    rolling_std_safe = rolling_std.replace(0, np.nan)
    
    # Channel bands
    lr_upper = lr_mid + (std_mult * rolling_std_safe)
    lr_lower = lr_mid - (std_mult * rolling_std_safe)
    
    return lr_mid, lr_upper, lr_lower
