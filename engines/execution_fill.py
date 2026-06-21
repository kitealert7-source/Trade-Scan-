"""Shared direction-aware execution-fill helper — OctaFx addendum line-17 restoration.

RESEARCH OHLC are ASK-based. Execution restores the addendum's stated intent
(ASK for BUY, BID for SELL): a BUY fills at the ask (raw price, unchanged); a
SELL fills at the bid (= ask - per-bar embedded spread from the RESEARCH `spread`
column). The P&L formula is unchanged — only the fill price fed into it becomes
side-correct.

`spread == 0` (all RESEARCH until the CLEAN->RESEARCH embed regen, and live data
which has no embedded spread) makes both helpers a no-op, so this is
byte-identical to the pre-restoration behavior on existing data.

Used by the basket stack (basket_runner + recycle rules). The single-asset
engine v1_5_10 carries its own self-contained copy of the same two functions;
a future direction-aware evaluate_bar version may import from here.

Side convention (same for single-asset and basket legs):
    entry: long = BUY, short = SELL   -> is_sell = (direction == -1)
    exit : long = SELL, short = BUY   -> is_sell = (direction == 1)
"""
from __future__ import annotations

import pandas as pd


# --- OctaFx cost model: NO overnight financing (swap-free broker). ---
# OctaFx/Octa charges no overnight swap/financing on any account or instrument
# (FX, indices, metals, crypto, stocks), with no holding-time limit and no admin
# fee (Sharia-compliant default, all countries, since 2022-06). The complete
# OctaFx backtest cost model is therefore the embedded direction-aware spread
# applied by the fills below (+ slippage, currently unmodelled); the financing
# term is structurally zero.
#
# This constant documents that omission as INTENTIONAL, not a TODO: the fills
# below deliberately charge spread only. Do NOT add a swap / carry / financing
# term to any OctaFx fill or P&L path without a documented broker-policy change.
# The assertion is doc-only -- the helpers below do not read it -- so it changes
# no behaviour; it exists so a future "improvement" cannot silently re-add a swap.
#
# Source: vault sources/octafx-swap-free-cost-model.md (owner-confirmed
# 2026-06-21). Scope: all instruments, any holding duration. Locked by INVAR-003
# (INVARIANT_PROPOSALS.md); doctrine: RESEARCH_MEMORY.md 2026-06-21 decision.
OVERNIGHT_FINANCING = 0  # OctaFx swap-free; financing never charged (INVAR-003)


def bar_spread(row) -> float:
    """Per-bar embedded spread (PRICE units) from the RESEARCH `spread` column.
    Returns 0.0 when absent / NaN / <= 0 — so the fills are a no-op on spread=0
    data. `row` is anything with a .get (pd.Series / dict)."""
    s = row.get("spread", 0.0) if hasattr(row, "get") else 0.0
    if s is None or pd.isna(s):
        return 0.0
    s = float(s)
    return s if s > 0.0 else 0.0


def exec_fill(raw_ask_price: float, is_sell: bool, spread: float) -> float:
    """Direction-aware execution price. BUY -> ask (raw); SELL -> bid (ask - spread)."""
    return (raw_ask_price - spread) if is_sell else raw_ask_price
