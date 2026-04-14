"""Validate the asset-class gate semantics used by Stage -0.22 admission
and by the MODEL+ASSET_CLASS filter in idea_evaluation_gate.

Validation matrix (single-directive cases):
    1. forex symbol (USDJPY)   -> FX
    2. crypto symbol (BTCUSD)  -> BTC
    3. gold symbol (XAUUSD)    -> XAU
    4. mixed (USDJPY+BTCUSD)   -> MixedAssetClassError
    5. unknown symbol          -> UnknownSymbolError (strict), FX (lax)
"""
import pytest

from config.asset_classification import (
    infer_asset_class_from_symbols,
    MixedAssetClassError,
    UnknownSymbolError,
    classify_asset,
    parse_strategy_name,
)


def test_forex_single_symbol():
    assert infer_asset_class_from_symbols(["USDJPY"]) == "FX"


def test_crypto_single_symbol():
    assert infer_asset_class_from_symbols(["BTCUSD"]) == "BTC"


def test_gold_single_symbol():
    assert infer_asset_class_from_symbols(["XAUUSD"]) == "XAU"


def test_index_single_symbol():
    assert infer_asset_class_from_symbols(["GER40"]) == "INDEX"


def test_mixed_forex_and_crypto_raises():
    with pytest.raises(MixedAssetClassError):
        infer_asset_class_from_symbols(["USDJPY", "BTCUSD"])


def test_unknown_symbol_strict_raises():
    with pytest.raises(UnknownSymbolError):
        infer_asset_class_from_symbols(["FOOBAR123"], strict_unknown=True)


def test_unknown_symbol_lax_falls_back_to_fx():
    assert infer_asset_class_from_symbols(["FOOBAR123"], strict_unknown=False) == "FX"


def test_empty_list_raises():
    with pytest.raises(ValueError):
        infer_asset_class_from_symbols([])


def test_classify_asset_from_strategy_id():
    assert classify_asset("43_STR_FX_1H_CHOCH_S01_V1_P00") == "FX"
    assert classify_asset("44_STR_BTC_1H_CHOCH_S01_V1_P00") == "BTC"
    assert classify_asset("26_STR_XAU_1H_CHOCH_S01_V1_P00") == "XAU"
    assert classify_asset("PF_abcdef1234567890") == "MIXED"


def test_parse_strategy_name_asset_class():
    parsed = parse_strategy_name("43_STR_FX_1H_CHOCH_S01_V1_P00")
    assert parsed is not None
    assert parsed["asset_class"] == "FX"
    assert parsed["model"] == "CHOCH"
    assert parsed["timeframe"] == "1H"
