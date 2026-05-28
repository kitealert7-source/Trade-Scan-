"""Unit tests for the cointegration corpus aggregator's classification logic."""
import math

from tools.cointegration_aggregator import _pair_class, _verdict


def test_pair_class():
    assert _pair_class("EURUSD", "USDJPY") == "FX-FX"
    assert _pair_class("AUS200", "US30") == "IDX-IDX"
    assert _pair_class("CADJPY", "UK100") == "FX-IDX"
    assert _pair_class("BTCUSD", "JPN225") == "CRYPTO/METAL"
    assert _pair_class("AUS200", "XAUUSD") == "CRYPTO/METAL"
    assert _pair_class("BTCUSD", "XAUUSD") == "CRYPTO/METAL"


def test_verdict_buckets():
    assert _verdict(5.0, 10.0) == "WINNER"
    assert _verdict(-5.0, 10.0) == "LOSER"
    assert _verdict(0.5, 10.0) == "NEUTRAL"
    assert _verdict(5.0, 35.0) == "BLOWUP"      # dd>30 trumps a positive net
    assert _verdict(-5.0, 35.0) == "BLOWUP"
    assert _verdict(math.nan, 10.0) == "MISSING"
