"""
Regime State Machine Module
TradeScan Professional Baseline

Implements a 3-axis market regime model (Direction, Structure, Volatility)
with stability filtering and legacy field preservation.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

__all__ = ["apply_regime_model"]

import pandas as pd
import numpy as np
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime
from indicators.trend.ema_regime import ema_regime
from indicators.trend.sha_regime import sha_regime
from indicators.trend.hurst_regime import hurst_regime
from indicators.structure.adx import adx
from indicators.stats.log_return_autocorr import log_return_autocorr
from indicators.volatility.realized_vol import realized_vol
from indicators.volatility.volatility_regime import volatility_regime
from indicators.volatility.atr_percentile import atr_percentile
from indicators.volatility.atr import atr as compute_atr

_ENGINE_ROOT = Path(__file__).resolve().parents[1]  # Trade_Scan/
REGIME_CACHE_DIR = _ENGINE_ROOT / ".cache" / "regime_cache"


def compute_indicator_stack(df: pd.DataFrame, resample_freq: str = "1D") -> pd.DataFrame:
    """
    Computes the full indicator stack required for regime detection.
    This replaces the scattered computations previously in execution_loop.py.

    Args:
        resample_freq: HTF resample frequency for linreg_regime_htf.
            '1D' for 1H/4H regime input, '1W' for 1D regime, '1ME' for 1W regime.
    """
    close = df['close']
    high = df['high']
    low = df['low']

    # 1. Directional Indicators
    df['regime_lr'] = linreg_regime(close, window=50)['regime']
    df['regime_lr_htf'] = linreg_regime_htf(close, window=200, resample_freq=resample_freq)['regime']
    df['regime_kalman'] = kalman_regime(df, price_col="close")['regime']
    df['regime_sha'] = sha_regime(df)['regime']
    df['regime_ema'] = ema_regime(close, window=20)['regime']

    # 2. Structure / Persistence Indicators
    df['regime_er'] = efficiency_ratio_regime(close)['regime']
    df['regime_tp'] = trend_persistence(close)['regime']
    df['regime_hurst'] = hurst_regime(close)['regime']
    
    # Safe ADX Assignment
    adx_out = adx(high, low, close)
    if isinstance(adx_out, pd.DataFrame):
        df["val_adx"] = adx_out["adx"]
    else:
        df["val_adx"] = adx_out
    df["val_adx"] = df["val_adx"].astype(float)

    df['regime_autocorr'] = log_return_autocorr(close)['regime']

    # 3. Volatility Indicators
    vol_out = volatility_regime(compute_atr(df, window=14))
    df['regime_vol_legacy'] = vol_out['regime']
    df['val_atr_percentile'] = vol_out['percentile']
    df['val_atr'] = vol_out['atr']
    
    rv_out = realized_vol(close)
    df['val_realized_vol'] = rv_out['realized_vol']
    df['val_rv_percentile'] = rv_out['rv_percentile']

    return df


def compute_axis_states(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates the three independent state axes.
    All axes normalized to consistent ranges.
    """
    # 1. Direction Axis (-1.0 to 1.0)
    direction_cols = ['regime_lr', 'regime_lr_htf', 'regime_kalman', 'regime_sha', 'regime_ema']
    df['direction_state'] = df[direction_cols].mean(axis=1)

    # 2. Structure Axis (0.0 to 1.0)
    # Map regimes/values to 0-1 scale where 1 = high structure/persistence
    er_score = df['regime_er'].map({1: 1.0, -1: 0.0})
    tp_score = df['regime_tp'].abs() # 1 if persistent (up or down), 0 if mixed
    hurst_score = df['regime_hurst'].map({1: 1.0, -1: 0.0, 0: 0.5})
    adx_score = (df['val_adx'] / 100.0).clip(0, 1)
    autocorr_score = df['regime_autocorr'].map({1: 1.0, -1: 0.0, 0: 0.5})
    
    structure_cols = [er_score, tp_score, hurst_score, adx_score, autocorr_score]
    df['structure_state'] = pd.concat(structure_cols, axis=1).mean(axis=1)

    # 3. Volatility Axis (0.0 to 1.0)
    vol_legacy_score = df['regime_vol_legacy'].map({-1: 0.0, 0: 0.5, 1: 1.0})
    df['volatility_state'] = pd.concat([
        vol_legacy_score, 
        df['val_atr_percentile'], 
        df['val_rv_percentile']
    ], axis=1).mean(axis=1)

    return df


def resolve_market_regime(direction, structure, volatility, autocorr_regime):
    """
    Maps 3-axis state space to 6 frozen deterministic regimes.
    """
    abs_dir = abs(direction)
    
    # 1. Trending Regimes (High Directional Conviction)
    if abs_dir > 0.4:
        if structure > 0.6:
            if volatility > 0.6:
                return "trend_expansion"
            else:
                return "trend_compression"
        else:
            return "unstable_trend"
            
    # 2. Ranging/Reverting Regimes (Low Directional Conviction)
    else:
        # High persistence in range usually indicates mean reversion (autocorr -1)
        if structure > 0.6 and autocorr_regime == -1:
            return "mean_reversion"
        
        if volatility < 0.4:
            return "range_low_vol"
        else:
            return "range_high_vol"


def apply_regime_model(df: pd.DataFrame, resample_freq: str = "1D",
                       symbol_hint: str = "") -> pd.DataFrame:
    """
    Main entry point for the execution engine.
    Applied once per dataset before bar iteration.

    Args:
        resample_freq: HTF resample frequency passed to linreg_regime_htf.
            Driven by config/regime_timeframe_map.yaml via run_stage1.py.
        symbol_hint: Symbol identifier included in cache key to prevent
            cross-symbol cache collisions.  Callers should pass this whenever
            possible.  When empty, a content-derived fallback is used.
    """
    # 1. Validation Guard
    required_columns = ["close", "high", "low", "open"]
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise RuntimeError(f"REGIME_MODEL_INPUT_ERROR: missing {missing}")

    # --- BUILD CACHE KEY (v1.5.4: stable across consecutive bars) ---
    # Key = (symbol_hint, resample_freq, last_bar_time, bar_count)
    # This avoids full-DataFrame hashing which causes cache miss every new bar.
    # Falls back to content hash if timestamp column is missing.
    if "timestamp" in df.columns:
        last_ts = str(df["timestamp"].iloc[-1])
    elif isinstance(df.index, pd.DatetimeIndex):
        last_ts = str(df.index[-1])
    else:
        # Fallback: content hash (legacy behavior)
        hash_series = pd.util.hash_pandas_object(
            df[['open', 'high', 'low', 'close']], index=True
        ).values
        last_ts = hashlib.md5(hash_series.tobytes()).hexdigest()
    # Include OHLC boundary fingerprint: catches data corrections that don't
    # change row count or timestamps (e.g. price fixes, gap fills).
    _ohlc_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    _boundary = ""
    if _ohlc_cols and len(df) > 0:
        _first = df[_ohlc_cols].iloc[0].values
        _last = df[_ohlc_cols].iloc[-1].values
        _boundary = f"|{_first.tobytes().hex()}|{_last.tobytes().hex()}"
    cache_key = hashlib.md5(
        f"{symbol_hint}|{last_ts}|{len(df)}|{resample_freq}{_boundary}".encode()
    ).hexdigest()
    cache_path = REGIME_CACHE_DIR / f"{cache_key}.parquet"

    # --- CACHE HIT (SAFE LOAD) ---
    if cache_path.exists():
        try:
            regime_cols = pd.read_parquet(cache_path)
            if len(regime_cols) == len(df):
                for col in regime_cols.columns:
                    if col not in df.columns:
                        df[col] = regime_cols[col].values
                return df
            else:
                print(f"  REGIME_CACHE_LEN_MISMATCH  key={cache_key[:12]}..."
                      f"  cache={len(regime_cols)}  df={len(df)}  recomputing")
        except (OSError, IOError) as e:
            # Disk error or corrupt parquet (ArrowInvalid wraps as OSError) — delete and recompute
            print(f"  REGIME_CACHE_IO_ERROR  key={cache_key[:12]}...  {type(e).__name__}: {e}")
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass
        except (ValueError, TypeError, KeyError) as e:
            # Corrupted parquet structure (ArrowInvalid subclasses ValueError) — delete and recompute
            print(f"  REGIME_CACHE_CORRUPT  key={cache_key[:12]}...  {type(e).__name__}: {e}")
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as e:
            # Unexpected error — log loudly, delete corrupt file, recompute
            print(f"  REGIME_CACHE_ERROR  key={cache_key[:12]}...  {type(e).__name__}: {e}"
                  f"  — deleting and recomputing")
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass

    # --- CACHE MISS: snapshot columns before computation ---
    original_cols = set(df.columns)

    # 2. Compute Indicator Stack
    df = compute_indicator_stack(df, resample_freq=resample_freq)

    # 3. Compute Axis States
    df = compute_axis_states(df)

    # 4. Resolve Market Regime with Stability Filter (3-bar confirm)
    regime_confirm_bars = 3
    market_regimes = []
    regime_ids = []
    regime_ages = []
    regime_transitions = []
    
    current_regime = None
    candidate_regime = None
    confirm_counter = 0
    current_regime_id = 0
    current_regime_age = 0
    
    for i in range(len(df)):
        # Calculate raw (candidate) regime for this bar
        raw_regime = resolve_market_regime(
            df['direction_state'].iloc[i],
            df['structure_state'].iloc[i],
            df['volatility_state'].iloc[i],
            df['regime_autocorr'].iloc[i]
        )
        
        # Initialization
        if current_regime is None:
            current_regime = raw_regime
            candidate_regime = raw_regime
            confirm_counter = 0
            current_regime_id = 1
            current_regime_age = 0
            transition = False
        else:
            transition = False
            # Check if raw regime wants to change
            if raw_regime != current_regime:
                if raw_regime == candidate_regime:
                    confirm_counter += 1
                else:
                    candidate_regime = raw_regime
                    confirm_counter = 1
                
                # Check confirmation
                if confirm_counter >= regime_confirm_bars:
                    current_regime = raw_regime
                    current_regime_id += 1
                    current_regime_age = 0
                    confirm_counter = 0
                    transition = True
                else:
                    current_regime_age += 1
            else:
                # Still in current regime
                candidate_regime = current_regime
                confirm_counter = 0
                current_regime_age += 1
        
        market_regimes.append(current_regime)
        regime_ids.append(current_regime_id)
        regime_ages.append(current_regime_age)
        regime_transitions.append(transition)

    df['market_regime'] = market_regimes
    df['regime_id'] = regime_ids
    df['regime_age'] = regime_ages
    df['regime_transition'] = regime_transitions

    # --- STRUCTURAL INTEGRITY ENFORCEMENT ---
    # Confirm exactly one regime state per bar (no nulls/NAs)
    if not df["regime_id"].notnull().all():
        missing_bars = len(df) - df["regime_id"].count()
        raise RuntimeError(f"REGIME_CONTRACT_VIOLATION: {missing_bars} bars missing regime_id.")
    
    if not df["market_regime"].notnull().all():
        raise RuntimeError("REGIME_CONTRACT_VIOLATION: market_regime contains nulls.")

    # 5. Legacy Field Lock (Absolute Replication)
    # Original formulas from execution_loop.py logic (Indicator Vote Sum)
    df['trend_score'] = (
        df['regime_lr'].fillna(0).astype(int) +
        df['regime_lr_htf'].fillna(0).astype(int) +
        df['regime_kalman'].fillna(0).astype(int) +
        df['regime_tp'].fillna(0).astype(int) +
        df['regime_er'].fillna(0).astype(int)
    )

    def get_trend_regime_legacy(score):
        if score >= 3:  return  2
        if score >= 1:  return  1
        if score == 0:  return  0
        if score >= -2: return -1
        return -2

    def get_trend_label_legacy(regime):
        if regime ==  2: return "strong_up"
        if regime ==  1: return "weak_up"
        if regime ==  0: return "neutral"
        if regime == -1: return "weak_down"
        return "strong_down"

    df['trend_regime'] = df['trend_score'].apply(get_trend_regime_legacy)
    df['trend_label']  = df['trend_regime'].apply(get_trend_label_legacy)
    
    df['volatility_regime'] = df['regime_vol_legacy']
    df['atr'] = df['val_atr']

    # --- SAVE CACHE (atomic: tmp → fsync → replace) ---
    regime_cols_to_save = [c for c in df.columns if c not in original_cols]
    if len(regime_cols_to_save) > 0:
        REGIME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        try:
            df[regime_cols_to_save].to_parquet(tmp_path)
            with open(tmp_path, "r+b") as f:
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(cache_path))
        except Exception as e:
            print(f"  REGIME_CACHE_WRITE_ERROR  key={cache_key[:12]}...  {type(e).__name__}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return df
