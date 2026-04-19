"""Deterministic portfolio math and normalized trade-loading utilities."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from config.state_paths import RUNS_DIR

def deterministic_portfolio_id(run_ids):
    sorted_ids = sorted(run_ids)
    joined = "|".join(sorted_ids)
    h = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return f"PF_{h.upper()}"


# ──────────────────────────────────────────────────────────────────────
# Canonical portfolio-folder-name factory
# ──────────────────────────────────────────────────────────────────────
#
# Format: PF_<HEX12>_<ID><FAMILY>_<ASSET_CLASS>_<SYMBOL>[_P<NN>]
#
# This is the SINGLE authoritative function that constructs a portfolio
# folder name. Every writer in the system must funnel through here — no
# string concatenation anywhere else.
#
# Guardrails (from #2 plan):
#   1. Single entry point — this function.
#   2. asset_class is DERIVED from `slot3` via classify_asset(); it is NOT
#      a parameter. The caller cannot pass asset_class directly.
#   3. No format flexibility — canonical output only.
#
# Parameters:
#   run_ids      — iterable of run_id strings; sorted + hashed to HEX12.
#   directive_id — 2-digit idea_id (e.g. "22", "53"). Leading zeros kept.
#   family       — canonical FAMILY token (e.g. "CONT", "MR", "STR").
#   slot3        — the directive's SLOT-3 token. MUST be an asset_class
#                  or symbol from token_dictionary.yaml; asset_class is
#                  derived from this and nowhere else.
#   symbol       — the execution symbol (e.g. "AUDJPY", "XAUUSD").
#   patch_id     — optional; accepts 3, "03", "P03", "p3". Emitted as "P<NN>".

# Enumerate canonical asset_class tokens so the parser can't mistake a legacy
# name like `PF_HEX_22CONT_AUDJPY_P03` (no asset_class) for canonical
# (it would otherwise read AUDJPY as the asset_class slot).
_CANONICAL_ASSET_CLASSES = ("FX", "XAU", "BTC", "INDEX", "MIXED")
_PORTFOLIO_NAME_RE = re.compile(
    r"^PF_(?P<hex>[0-9A-F]{12})_"
    r"(?P<id>\d{2})(?P<family>[A-Z0-9]+)_"
    r"(?P<asset_class>" + "|".join(_CANONICAL_ASSET_CLASSES) + r")_"
    r"(?P<symbol>[A-Z0-9]+)"
    r"(?:_P(?P<patch>\d{2}))?$"
)


def _assemble_canonical_portfolio_name(
    *,
    hex_id: str,
    directive_id: str,
    family: str,
    slot3: str,
    symbol: str,
    patch_id: int | str | None = None,
) -> str:
    """Internal: assemble the canonical format from already-validated parts.

    Separated from build_portfolio_name so the migration tool
    (tools/sanitize_portfolio_folders.py) can preserve a legacy HEX12
    verbatim while still funneling the rest of the format through ONE
    shared implementation. New-name writers MUST use build_portfolio_name —
    this helper is only for RENAMING existing folders.
    """
    # Lazy import to keep config/asset_classification.py as a peer — avoids
    # import-time circularity.
    from config.asset_classification import classify_asset

    if not (isinstance(hex_id, str) and hex_id.startswith("PF_") and len(hex_id) == 15):
        raise ValueError(
            f"_assemble_canonical_portfolio_name: hex_id must be 'PF_' + "
            f"12 hex chars; got {hex_id!r}"
        )

    did = str(directive_id).strip().zfill(2)
    if not (did.isdigit() and len(did) == 2):
        raise ValueError(
            f"build_portfolio_name: directive_id must be 2-digit numeric "
            f"(got {directive_id!r})"
        )
    fam = str(family).strip().upper()
    slot = str(slot3).strip().upper()
    sym = str(symbol).strip().upper()
    if not (fam and slot and sym):
        raise ValueError(
            f"build_portfolio_name: family, slot3, symbol all required "
            f"(got family={fam!r} slot3={slot!r} symbol={sym!r})"
        )

    # The ONLY source of asset_class. Not an argument of the public factory.
    # Not inferred from symbol. Not re-derived elsewhere.
    asset_class = classify_asset(slot).upper()

    parts = [hex_id, f"{did}{fam}", asset_class, sym]

    if patch_id is not None:
        p = str(patch_id).strip().upper()
        if p.startswith("P"):
            p = p[1:]
        if not p.isdigit():
            raise ValueError(
                f"build_portfolio_name: patch_id must be numeric "
                f"(e.g. 3, '03', 'P03'); got {patch_id!r}"
            )
        parts.append(f"P{p.zfill(2)}")

    return "_".join(parts)


def build_portfolio_name(
    run_ids: Sequence[str],
    directive_id: str,
    family: str,
    slot3: str,
    symbol: str,
    patch_id: int | str | None = None,
) -> str:
    """Build the canonical portfolio folder name.

    Canonical format: ``PF_<HEX12>_<ID><FAMILY>_<ASSET_CLASS>_<SYMBOL>[_P<NN>]``

    asset_class is derived ONLY from ``slot3`` via ``classify_asset`` — it
    is deliberately absent from this function's signature so no caller can
    bypass the single source of truth (token_dictionary SLOT-3 whitelist).

    Examples:
        >>> build_portfolio_name(["run_a", "run_b"], "22", "CONT", "FX",
        ...                      "AUDJPY", patch_id="P03")
        'PF_<HEX12>_22CONT_FX_AUDJPY_P03'
        >>> build_portfolio_name(["ra", "rb"], "11", "REV", "XAUUSD",
        ...                      "XAUUSD")
        'PF_<HEX12>_11REV_XAU_XAUUSD'
    """
    return _assemble_canonical_portfolio_name(
        hex_id=deterministic_portfolio_id(run_ids),
        directive_id=directive_id,
        family=family,
        slot3=slot3,
        symbol=symbol,
        patch_id=patch_id,
    )


def parse_portfolio_name(name: str) -> dict | None:
    """Inverse of build_portfolio_name for canonical names.

    Returns a dict of fields (hex, id, family, asset_class, symbol, patch)
    or None for non-canonical / legacy names. Patch may be None.

    Use this for READs. WRITES must always go through build_portfolio_name.
    """
    m = _PORTFOLIO_NAME_RE.fullmatch(str(name).strip())
    if not m:
        return None
    return {
        "hex": m.group("hex"),
        "directive_id": m.group("id"),
        "family": m.group("family"),
        "asset_class": m.group("asset_class"),
        "symbol": m.group("symbol"),
        "patch_id": (f"P{m.group('patch')}" if m.group("patch") else None),
    }


def load_trades_for_portfolio_analysis(run_ids, project_root: Path):
    """
    Legacy-compatible loader used by run_portfolio_analysis.py.
    Returns (trades_df, timeframes_set).
    """
    all_trades = []
    timeframes = set()

    for run_id in run_ids:
        trade_path = RUNS_DIR / run_id / "data" / "results_tradelevel.csv"
        if not trade_path.exists():
            raise FileNotFoundError(f"Trade file missing for run {run_id}")

        df_trades = pd.read_csv(trade_path)

        if "pnl_usd" in df_trades.columns:
            df_trades.rename(columns={"pnl_usd": "pnl"}, inplace=True)

        for col in ["entry_timestamp", "exit_timestamp", "pnl"]:
            if col not in df_trades.columns:
                raise ValueError(f"Missing column '{col}' in run {run_id}")

        df_trades["entry_timestamp"] = pd.to_datetime(df_trades["entry_timestamp"], utc=True).dt.tz_convert(None)
        df_trades["exit_timestamp"] = pd.to_datetime(df_trades["exit_timestamp"], utc=True).dt.tz_convert(None)

        meta_path = RUNS_DIR / run_id / "data" / "run_metadata.json"
        strat_name = f"RUN_{run_id}"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                strat_name = meta.get("strategy_name", strat_name)
                tf = meta.get("timeframe") or meta.get("TIMEFRAME")
                if tf:
                    timeframes.add(str(tf))
            except Exception:
                pass

        df_trades["strategy_id"] = strat_name
        df_trades["run_id"] = run_id
        all_trades.append(df_trades)

    trades = pd.concat(all_trades, ignore_index=True)
    trades.sort_values("exit_timestamp", inplace=True)
    trades.reset_index(drop=True, inplace=True)
    return trades, timeframes


def load_trades_for_portfolio_evaluator(run_ids, project_root: Path):
    """
    Legacy-compatible loader used by portfolio_evaluator.py.
    Returns (portfolio_df, symbol_trades, meta_records).
    """
    all_trades = []
    symbol_trades = {}
    meta_records = {}
    loaded_symbols = []

    for rid in run_ids:
        run_folder = RUNS_DIR / rid / "data"
        if not run_folder.exists():
            raise ValueError(f"Governance violation: run_data folder missing for {rid}")

        csv_path = run_folder / "results_tradelevel.csv"
        if not csv_path.exists():
            raise ValueError(f"Governance violation: results_tradelevel.csv missing for {rid}")

        strat_name = f"PORTFOLIO_CONSTITUENT_{rid}"
        symbol = f"SYM_{rid}"
        meta_dict = {}

        meta_path = run_folder / "run_metadata.json"
        try:
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    strat_name = meta.get("strategy_name", strat_name)
                    symbol = meta.get("symbol", symbol)
                    meta_dict = meta
        except Exception:
            pass

        meta_records[symbol] = meta_dict

        try:
            df = pd.read_csv(csv_path)
            df["source_run_id"] = rid
            df["strategy_name"] = strat_name
            df["exit_timestamp"] = pd.to_datetime(
                df["exit_timestamp"], errors="coerce", utc=True
            ).dt.tz_convert(None)
            df["entry_timestamp"] = pd.to_datetime(
                df["entry_timestamp"], errors="coerce", utc=True
            ).dt.tz_convert(None)
            df["symbol"] = symbol

            symbol_trades[symbol] = df
            all_trades.append(df)
            loaded_symbols.append(symbol)
        except Exception as e:
            raise ValueError(
                f"Governance violation: failed to load trade data for run_id {rid}: {e}"
            )

    if not all_trades:
        raise ValueError(f"No valid trade data loaded for run IDs {run_ids}")

    print(f"  Loaded explicit symbols: {loaded_symbols}")

    portfolio_df = pd.concat(all_trades, ignore_index=True)
    portfolio_df.sort_values("exit_timestamp", inplace=True)
    portfolio_df.reset_index(drop=True, inplace=True)
    return portfolio_df, symbol_trades, meta_records


def compute_equity_curve(trades, reference_capital):
    """Legacy-compatible equity progression used by run_portfolio_analysis.py."""
    equity = reference_capital
    equity_before_list = []
    equity_after_list = []
    return_list = []

    for _, row in trades.iterrows():
        equity_before_list.append(equity)
        pnl = row["pnl"]
        r = pnl / equity if equity != 0 else 0.0
        equity += pnl
        equity_after_list.append(equity)
        return_list.append(r)

    trades["equity_before_trade"] = equity_before_list
    trades["equity_after_trade"] = equity_after_list
    trades["return_t"] = return_list
    return trades


def compute_concurrency_series(portfolio_df):
    """
    Compute concurrency metrics using exact timestamp overlap.
    Returns:
      - series
      - max_concurrent
      - avg_concurrent (time weighted)
      - pct_time_at_max
      - pct_time_deployed
    """
    if portfolio_df.empty:
        return [], 0, 0.0, 0.0, 0.0

    df_sorted = portfolio_df.sort_values("entry_timestamp").copy()

    events = []
    for _, row in df_sorted.iterrows():
        events.append((row["entry_timestamp"], 1))
        events.append((row["exit_timestamp"], -1))

    events.sort(key=lambda x: (x[0], x[1]))  # exit first on tie

    current_concurrent = 0
    max_concurrent = 0
    weighted_sum = 0.0
    time_deployed = 0.0
    duration_by_count = defaultdict(float)

    last_time = events[0][0]
    total_duration = (events[-1][0] - events[0][0]).total_seconds()
    series = []

    for t, type_ in events:
        delta = (t - last_time).total_seconds()
        if delta > 0:
            weighted_sum += current_concurrent * delta
            duration_by_count[current_concurrent] += delta
            if current_concurrent > 0:
                time_deployed += delta

        if type_ == 1:
            current_concurrent += 1
            series.append(current_concurrent)
        else:
            current_concurrent -= 1

        if current_concurrent > max_concurrent:
            max_concurrent = current_concurrent

        last_time = t

    avg_concurrent = weighted_sum / total_duration if total_duration > 0 else 0.0
    pct_deployed = (time_deployed / total_duration) if total_duration > 0 else 0.0
    time_at_max = duration_by_count[max_concurrent]
    pct_at_max = (time_at_max / total_duration) if total_duration > 0 else 0.0

    return series, max_concurrent, avg_concurrent, pct_at_max, pct_deployed


def compute_drawdown(trades):
    """Legacy-compatible drawdown computation used by run_portfolio_analysis.py."""
    equity = trades["equity_after_trade"]
    rolling_peak = equity.cummax()
    drawdown = equity - rolling_peak

    max_dd = drawdown.min()
    trough_idx = drawdown.idxmin()
    peak_idx = equity.loc[:trough_idx].idxmax()

    peak_time = trades.loc[peak_idx, "exit_timestamp"]
    trough_time = trades.loc[trough_idx, "exit_timestamp"]
    max_dd_pct = max_dd / equity.loc[peak_idx] if equity.loc[peak_idx] != 0 else 0.0

    return max_dd, max_dd_pct, peak_time, trough_time


def build_run_portfolio_summary(
    *,
    portfolio_id: str,
    trades,
    max_dd,
    max_dd_pct,
    return_dd_ratio,
    sharpe,
    cagr,
    concurrency_data: dict,
    capital_overextension_ratio: float,
    avg_pairwise_corr: float,
    max_pairwise_corr_stress: float,
    reference_capital: float,
    low_pnl: float,
    normal_pnl: float,
    high_pnl: float,
    signal_timeframes_str: str,
    evaluation_timeframe: str,
    k_ratio: float,
    win_rate: float,
    profit_factor: float,
    expectancy: float,
    exposure_pct: float,
    equity_stability_k_ratio: float,
):
    """Legacy-compatible summary payload used by run_portfolio_analysis.py."""
    return {
        "portfolio_id": portfolio_id,
        "realized_pnl": float(trades["pnl"].sum()),
        "net_pnl_usd": float(trades["pnl"].sum()),
        "max_dd_usd": float(max_dd),
        "max_dd_pct": float(max_dd_pct),
        "return_dd_ratio": float(return_dd_ratio),
        "sharpe": float(sharpe),
        "cagr": float(cagr),
        "avg_concurrent": float(concurrency_data["avg_concurrent"]),
        "max_concurrent": int(concurrency_data["max_concurrent"]),
        "p95_concurrent": float(concurrency_data["p95_concurrent"]),
        "dd_max_concurrent": int(concurrency_data["dd_max_concurrent"]),
        "full_load_cluster": bool(concurrency_data["full_load_cluster"]),
        "peak_capital_deployed": float(concurrency_data["peak_capital_deployed"]),
        "capital_overextension_ratio": float(capital_overextension_ratio),
        "avg_pairwise_corr": float(avg_pairwise_corr),
        "max_pairwise_corr_stress": float(max_pairwise_corr_stress),
        "reference_capital_usd": reference_capital,
        "total_trades": len(trades),
        "portfolio_net_profit_low_vol": low_pnl,
        "portfolio_net_profit_normal_vol": normal_pnl,
        "portfolio_net_profit_high_vol": high_pnl,
        "signal_timeframes": signal_timeframes_str,
        "evaluation_timeframe": evaluation_timeframe,
        "k_ratio": float(k_ratio),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "expectancy": float(expectancy),
        "exposure_pct": float(exposure_pct),
        "equity_stability_k_ratio": float(equity_stability_k_ratio),
    }
