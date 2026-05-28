"""Crypto/metal route to the broker-spec PnL path, not the FX currency path.

Regression for the "H2RecycleRuleV3: no USD reference defined for currency
'BTC'/'XAU'" fail-fast (2026-05-28). BTCUSD/ETHUSD/XAUUSD are 6-char all-alpha
USD-quoted instruments but NOT fiat/fiat FX pairs, so `_is_fx_symbol` must
return False and `_leg_pnl_usd_universal` must size them via broker-spec
`usd_per_pu_per_lot` (BTC=1, ETH=10, XAU=100) instead of the FX currency
decomposition (whose base-ccy lookup has no BTC/ETH/XAU entry).
"""
import pandas as pd
import pytest

from tools.basket_runner import BasketLeg
from tools.recycle_rules.cointegration_meanrev_v1_2 import (
    _is_fx_symbol,
    _leg_pnl_usd_universal,
)


def test_is_fx_symbol_classification():
    # real FX pairs (fiat/fiat) -> FX
    for fx in ("EURUSD", "USDJPY", "AUDNZD", "GBPCHF", "CADJPY"):
        assert _is_fx_symbol(fx), fx
    # crypto / metal: 6-char all-alpha but non-fiat base -> NOT FX
    for nonfx in ("BTCUSD", "ETHUSD", "XAUUSD"):
        assert not _is_fx_symbol(nonfx), nonfx
    # indices (contain digits) -> NOT FX
    for idx in ("JPN225", "US30", "SPX500", "AUS200", "UK100"):
        assert not _is_fx_symbol(idx), idx


def _leg(symbol: str, direction: int, lot: float, entry: float) -> BasketLeg:
    df = pd.DataFrame(
        {"close": [entry, entry]},
        index=pd.date_range("2024-01-01", periods=2, freq="1D"),
    )
    leg = BasketLeg(symbol=symbol, lot=lot, direction=direction, df=df, strategy=None)
    leg.state.in_pos = True
    leg.state.direction = direction
    leg.state.entry_price = entry
    return leg


@pytest.mark.parametrize(
    "symbol, entry, price, usd_per_pu",
    [
        ("BTCUSD", 50_000.0, 50_100.0, 1.0),    # +100 px * 1   = +100 USD
        ("ETHUSD", 3_000.0, 3_010.0, 10.0),     # +10  px * 10  = +100 USD
        ("XAUUSD", 2_000.0, 2_001.0, 100.0),    # +1   px * 100 = +100 USD
    ],
)
def test_nonfx_pnl_uses_broker_spec_path(symbol, entry, price, usd_per_pu):
    """Must NOT raise (old FX path raised on the non-fiat base) and must equal
    effective_direction * lot * dprice * usd_per_pu_per_lot."""
    expected = 1.0 * (price - entry) * usd_per_pu
    leg_long = _leg(symbol, +1, 1.0, entry)
    assert _leg_pnl_usd_universal(leg_long, price, {}) == pytest.approx(expected)
    leg_short = _leg(symbol, -1, 1.0, entry)
    assert _leg_pnl_usd_universal(leg_short, price, {}) == pytest.approx(-expected)
