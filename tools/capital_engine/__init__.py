"""Capital engine exports.

- portfolio_core: deterministic portfolio math and artifact loading
- capital_engine: capital deployment simulation and sizing logic
"""

from .simulation import (
    ConversionLookup,
    EVENT_TYPE_ENTRY,
    EVENT_TYPE_EXIT,
    EVENT_TYPE_PRIORITY,
    OpenTrade,
    PortfolioState,
    TradeEvent,
    _parse_fx_currencies,
    compute_signal_hash,
    get_usd_per_price_unit_dynamic,
    get_usd_per_price_unit_static,
    load_broker_spec,
    run_simulation,
)

__all__ = [
    "ConversionLookup",
    "EVENT_TYPE_ENTRY",
    "EVENT_TYPE_EXIT",
    "EVENT_TYPE_PRIORITY",
    "OpenTrade",
    "PortfolioState",
    "TradeEvent",
    "_parse_fx_currencies",
    "compute_signal_hash",
    "get_usd_per_price_unit_dynamic",
    "get_usd_per_price_unit_static",
    "load_broker_spec",
    "run_simulation",
]
