"""Master Portfolio Sheet writer — SOLE WRITER for portfolio_sheet table + XLSX.

CRITICAL INVARIANTS:
  - This module is the only path that mutates Master_Portfolio_Sheet.xlsx or
    writes to ledger.db's portfolio_sheet table during Step 7.
  - Ordering: schema resolution → load existing → migrate → recompute existing
    → resolve new profile → density → status → row build → idempotent guard →
    DB write → XLSX write → formatter → notes.
  - Append-only: an existing portfolio_id either matches exactly (skip) or
    aborts with FATAL (no silent overwrite).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

import pandas as pd
from filelock import FileLock

from tools.pipeline_utils import ensure_xlsx_writable
from tools.portfolio.portfolio_config import (
    PORTFOLIO_ENGINE_VERSION,
    PROJECT_ROOT,
    STRATEGIES_ROOT,
)
from tools.portfolio.portfolio_profile_selection import (
    _compute_portfolio_status,
    _empty_selection_debug,
    _get_deployed_profile_metrics,
    _parse_strategy_name,
    _per_symbol_realized_density,
    _safe_float,
)


# Schema — shared base columns for both sheets
_LEDGER_BASE_COLUMNS = [
    # Identity
    "portfolio_id",
    "source_strategy",

    # Capital & Performance
    "reference_capital_usd",
    "portfolio_status",
    "evaluation_timeframe",
    "symbol_count",
    "trade_density_total",
    "trade_density_min",
    "profile_trade_density_total",
    "profile_trade_density_min",
    "theoretical_pnl",
    "realized_pnl",
    "sharpe",
    "max_dd_pct",
    "return_dd_ratio",
    "win_rate",
    "profit_factor",
    "expectancy",
    "total_trades",
    "exposure_pct",
    "equity_stability_k_ratio",

    # Deployed Profile
    "deployed_profile",
    "trades_accepted",
    "trades_rejected",
    "rejection_rate_pct",
    "realized_vs_theoretical_pnl",

    # Capital Utilization
    "peak_capital_deployed",
    "capital_overextension_ratio",

    # Concurrency
    "avg_concurrent",
    "max_concurrent",
    "p95_concurrent",
    "dd_max_concurrent",
]

# Multi-asset: edge_quality (not sqn) + correlation columns
_LEDGER_MULTI_ASSET_TAIL = [
    "edge_quality",
    "full_load_cluster",
    "avg_pairwise_corr",
    "max_pairwise_corr_stress",
    "portfolio_net_profit_low_vol",
    "portfolio_net_profit_normal_vol",
    "portfolio_net_profit_high_vol",
    "parsed_fields",
    "portfolio_engine_version",
    "creation_timestamp",
    "constituent_run_ids",
]

# Single-asset: sqn (not edge_quality), n_strategies
_LEDGER_SINGLE_ASSET_TAIL = [
    "sqn",
    "n_strategies",
    "portfolio_net_profit_low_vol",
    "portfolio_net_profit_normal_vol",
    "portfolio_net_profit_high_vol",
    "parsed_fields",
    "portfolio_engine_version",
    "creation_timestamp",
    "constituent_run_ids",
]


def _ledger_schema(is_single_asset):
    """Return (columns, target_sheet, other_sheet) for the sheet dispatch."""
    target_sheet = "Single-Asset Composites" if is_single_asset else "Portfolios"
    other_sheet = "Portfolios" if is_single_asset else "Single-Asset Composites"
    tail = _LEDGER_SINGLE_ASSET_TAIL if is_single_asset else _LEDGER_MULTI_ASSET_TAIL
    columns = _LEDGER_BASE_COLUMNS + tail
    return columns, target_sheet, other_sheet


def _ledger_load_frames(target_sheet, other_sheet, columns):
    """Load target + other sheets via ledger_db. Returns (df_ledger, df_other)."""
    from tools.ledger_db import read_mps as _read_mps_ledger
    df_ledger = _read_mps_ledger(sheet=target_sheet)
    if df_ledger.empty:
        df_ledger = pd.DataFrame(columns=columns)
    df_other = _read_mps_ledger(sheet=other_sheet)
    if df_other.empty:
        df_other = None
    return df_ledger, df_other


def _ledger_apply_column_fixups(df_ledger, is_single_asset):
    """Column migration for existing sheets (rename/remove legacy headers)."""
    _HEADER_FIXUPS = {"sharpe (ann.)": "sharpe", "k_ratio (log)": "equity_stability_k_ratio",
                      "realized_pnl_usd": "edge_quality" if not is_single_asset else "sqn"}
    for old_name, canonical in _HEADER_FIXUPS.items():
        if old_name in df_ledger.columns and canonical not in df_ledger.columns:
            df_ledger.rename(columns={old_name: canonical}, inplace=True)
    # Drop ghost columns from pandas dedup (.1, .2, .3 suffixes)
    ghost = [c for c in df_ledger.columns if any(c.startswith(p) for p in
             ("sharpe (ann.).", "k_ratio (log)."))]
    if ghost:
        df_ledger.drop(columns=ghost, inplace=True, errors="ignore")
    if "realized_pnl" not in df_ledger.columns and "net_pnl_usd" in df_ledger.columns:
        df_ledger["realized_pnl"] = df_ledger["net_pnl_usd"]
    if "theoretical_pnl" not in df_ledger.columns:
        if "net_pnl_usd" in df_ledger.columns:
            df_ledger["theoretical_pnl"] = pd.to_numeric(df_ledger["net_pnl_usd"], errors="coerce")
        else:
            df_ledger["theoretical_pnl"] = pd.to_numeric(df_ledger.get("realized_pnl"), errors="coerce")


def _ledger_recompute_existing_statuses(df_ledger, is_single_asset):
    """Recompute portfolio_status for ALL rows (expectancy + quality gates may reclassify)."""
    df_ledger["portfolio_status"] = df_ledger.apply(
        lambda row: _compute_portfolio_status(
            row.get("realized_pnl", 0.0),
            row.get("trades_accepted", row.get("total_accepted", 0)),
            row.get("rejection_rate_pct", 0.0),
            expectancy=row.get("expectancy", 0.0),
            portfolio_id=row.get("portfolio_id", ""),
            trade_density_min=row.get("trade_density_min",
                                     row.get("trade_density", None)),
            edge_quality=row.get("edge_quality", None),
            sqn=row.get("sqn", None),
            is_single_asset=is_single_asset,
        ),
        axis=1,
    )


def _ledger_recompute_existing_profiles(df_ledger, strategy_id):
    """Recompute deployed_profile for ALL existing rows (except the row being appended)."""
    _recomputed = 0
    for idx in df_ledger.index:
        pid = str(df_ledger.at[idx, "portfolio_id"])
        if pid == str(strategy_id):
            continue  # Skip the row we're about to append — it gets fresh selection below
        dep = _get_deployed_profile_metrics(pid, df_ledger)
        if dep is None or dep.get("profile_name") is None:
            df_ledger.at[idx, "deployed_profile"] = None
            df_ledger.at[idx, "realized_vs_theoretical_pnl"] = 0.0
            continue
        df_ledger.at[idx, "deployed_profile"] = dep["profile_name"]
        df_ledger.at[idx, "realized_pnl"] = dep["realized_pnl"]
        df_ledger.at[idx, "trades_accepted"] = dep["trades_accepted"]
        df_ledger.at[idx, "trades_rejected"] = dep["trades_rejected"]
        df_ledger.at[idx, "rejection_rate_pct"] = dep["rejection_rate_pct"]
        theo = _safe_float(df_ledger.at[idx, "theoretical_pnl"], 0.0)
        if abs(theo) > 1e-12:
            df_ledger.at[idx, "realized_vs_theoretical_pnl"] = round(dep["realized_pnl"] / theo, 4)
        _recomputed += 1
    if _recomputed:
        print(f"  [LEDGER] Recomputed deployed_profile for {_recomputed} existing rows.")


def _ledger_resolve_new_profile(strategy_id, metrics, df_ledger):
    """Compute deployed-profile fields for THIS strategy. Returns dict of injected values."""
    theoretical_pnl = round(_safe_float(metrics.get("net_pnl_usd"), 0.0), 2)
    realized_pnl = theoretical_pnl
    deployed_profile = None
    trades_accepted = None
    trades_rejected = None
    rejection_rate_pct = None

    deployed = _get_deployed_profile_metrics(strategy_id, df_ledger)
    selection_debug = deployed.get("selection_debug") if isinstance(deployed, dict) else _empty_selection_debug()
    if deployed is not None and deployed.get("profile_name") is not None:
        deployed_profile = deployed["profile_name"]
        realized_pnl = deployed["realized_pnl"]
        trades_accepted = deployed["trades_accepted"]
        trades_rejected = deployed["trades_rejected"]
        rejection_rate_pct = deployed["rejection_rate_pct"]

    if abs(theoretical_pnl) > 1e-12:
        ratio_realized_vs_theoretical = round(realized_pnl / theoretical_pnl, 4)
    else:
        ratio_realized_vs_theoretical = 0.0

    return {
        "theoretical_pnl": theoretical_pnl,
        "realized_pnl": realized_pnl,
        "deployed_profile": deployed_profile,
        "trades_accepted": trades_accepted,
        "trades_rejected": trades_rejected,
        "rejection_rate_pct": rejection_rate_pct,
        "ratio_realized_vs_theoretical": ratio_realized_vs_theoretical,
        "selection_debug": selection_debug,
        "simulation_years": (deployed.get("simulation_years") if isinstance(deployed, dict) else None),
    }


def _ledger_compute_trade_density(strategy_id, constituent_run_ids, rejection_rate_pct,
                                  sim_years):
    """Compute td_total/td_min/symbol_count + profile-adjusted variants."""
    td_total = None
    td_min = None
    symbol_count = None
    if isinstance(constituent_run_ids, list) and len(constituent_run_ids) > 0:
        try:
            from tools.ledger_db import read_master_filter
            ms_df = read_master_filter()
            if (not ms_df.empty
                    and 'run_id' in ms_df.columns
                    and 'trade_density' in ms_df.columns
                    and 'symbol' in ms_df.columns):
                valid = ms_df[ms_df['run_id'].astype(str)
                              .isin([str(x) for x in constituent_run_ids])]
                valid = valid.dropna(subset=['trade_density'])
                if not valid.empty:
                    per_sym = valid.groupby('symbol')['trade_density'].max()
                    td_total = int(per_sym.sum())
                    td_min = int(per_sym.min())
                    symbol_count = int(per_sym.size)
        except Exception as e:
            print(f"  [WARN] Failed to aggregate component trade density: {e}")

    # Profile-adjusted per-symbol density.
    # Preferred: derive from portfolio_tradelevel.csv (true realized per-symbol
    # density under the deployed profile). Fallback: raw × (1 - portfolio_rejection).
    profile_td_total = None
    profile_td_min = None
    realized_map = _per_symbol_realized_density(
        strategy_id, sim_years, rejection_rate_pct=rejection_rate_pct)
    if realized_map:
        vals = list(realized_map.values())
        profile_td_total = int(sum(vals))
        profile_td_min = int(min(vals))
    else:
        effective_rejection = rejection_rate_pct if rejection_rate_pct is not None else 0.0
        profile_td_total = (int(round(td_total * (1.0 - effective_rejection / 100.0)))
                            if td_total is not None else None)
        profile_td_min = (int(round(td_min * (1.0 - effective_rejection / 100.0)))
                          if td_min is not None else None)

    return {
        "td_total": td_total,
        "td_min": td_min,
        "symbol_count": symbol_count,
        "profile_td_total": profile_td_total,
        "profile_td_min": profile_td_min,
    }


def _ledger_compute_single_asset_extras(strategy_id, metrics, constituent_run_ids):
    """Single-asset sheet extras: n_strategies, sqn, readable_alias, regime placeholders."""
    n_strats = len(constituent_run_ids) if isinstance(constituent_run_ids, list) else 1
    extras = {
        "n_strategies": n_strats,
        "sqn": metrics.get("sqn", 0.0),
        "regime_gate_enabled": False,
        "activation_rate_pct": None,
        "regime_blocked_trades": None,
        "blocked_pnl_raw": None,
    }
    if strategy_id.upper().startswith("PF_"):
        _alias_parts = []
        _eval_dir = STRATEGIES_ROOT / strategy_id / "portfolio_evaluation"
        _alias_sym = None
        for _fn in ("portfolio_metadata.json", "portfolio_summary.json"):
            _fp = _eval_dir / _fn
            if _fp.exists():
                try:
                    with open(_fp, encoding="utf-8") as _f:
                        _d = json.load(_f)
                    _ea = _d.get("evaluated_assets")
                    if _ea and isinstance(_ea, list):
                        _alias_sym = _ea[0].upper()
                        break
                except Exception:
                    pass
        _alias_tf = metrics.get("signal_timeframes", "")
        if _alias_sym:
            _alias_parts.append(_alias_sym)
        _alias_parts.append(f"{n_strats}S")
        if _alias_tf and _alias_tf != "UNKNOWN":
            _alias_parts.append(_alias_tf.replace("|", "_"))
        extras["readable_alias"] = "_".join(_alias_parts) if _alias_parts else None
    else:
        extras["readable_alias"] = None
    return extras


def _compute_ledger_row(strategy_id, metrics, corr_data, max_stress_corr,
                        concurrency_data, constituent_run_ids, n_assets,
                        is_single_asset, run_ids_str, profile_injection,
                        density):
    """Build the complete row_data dict for MPS append.

    Pure transform — takes precomputed inputs, returns dict. No I/O.
    """
    row_data = {
        "portfolio_id": strategy_id,
        "creation_timestamp": datetime.utcnow().isoformat(),
        "constituent_run_ids": run_ids_str,
        "source_strategy": strategy_id,
        # OWNER: Step 7 only. All other steps read-only.
        # Effective capital = max concurrent positions × $1,000 per asset.
        "reference_capital_usd": concurrency_data["max_concurrent"] * 1000,
        "portfolio_status": profile_injection["portfolio_status"],
        "theoretical_pnl": profile_injection["theoretical_pnl"],
        "realized_pnl": profile_injection["realized_pnl"],
        "sharpe": metrics["sharpe"],
        "max_dd_pct": metrics["max_dd_pct"] * 100,  # convert fraction to percentage
        "return_dd_ratio": metrics["return_dd_ratio"],
        "peak_capital_deployed": metrics.get("peak_capital_deployed", 0.0),
        "capital_overextension_ratio": metrics.get("capital_overextension_ratio", 0.0),
        "avg_concurrent": concurrency_data["avg_concurrent"],
        "max_concurrent": concurrency_data["max_concurrent"],
        "p95_concurrent": concurrency_data["p95_concurrent"],
        "dd_max_concurrent": concurrency_data["dd_max_concurrent"],
        "full_load_cluster": concurrency_data["full_load_cluster"],
        "total_trades": metrics["total_trades"],

        # Per-symbol density fields.
        "symbol_count": density["symbol_count"] if density["symbol_count"] is not None else "NA",
        "trade_density_total": density["td_total"] if density["td_total"] is not None else "NA",
        "trade_density_min": density["td_min"] if density["td_min"] is not None else "NA",
        "profile_trade_density_total": density["profile_td_total"] if density["profile_td_total"] is not None else "NA",
        "profile_trade_density_min": density["profile_td_min"] if density["profile_td_min"] is not None else "NA",

        "portfolio_engine_version": PORTFOLIO_ENGINE_VERSION,
        "portfolio_net_profit_low_vol": metrics.get("portfolio_net_profit_low_vol", 0.0),
        "portfolio_net_profit_normal_vol": metrics.get("portfolio_net_profit_normal_vol", 0.0),
        "portfolio_net_profit_high_vol": metrics.get("portfolio_net_profit_high_vol", 0.0),
        "evaluation_timeframe": metrics.get("signal_timeframes", "UNKNOWN"),
        "signal_timeframes": metrics.get("signal_timeframes", "UNKNOWN"),
        "win_rate": metrics.get("win_rate", 0.0),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "expectancy": metrics.get("expectancy", 0.0),
        "exposure_pct": metrics.get("exposure_pct", 0.0),
        "equity_stability_k_ratio": metrics.get("equity_stability_k_ratio", 0.0),
        "deployed_profile": profile_injection["deployed_profile"],
        "edge_quality": metrics.get("edge_quality", 0.0),
        "peak_dd_ratio": metrics.get("peak_dd_ratio", 0.0),
        "trades_accepted": profile_injection["trades_accepted"],
        "trades_rejected": profile_injection["trades_rejected"],
        "rejection_rate_pct": profile_injection["rejection_rate_pct"],
        "realized_vs_theoretical_pnl": profile_injection["ratio_realized_vs_theoretical"],
        "selection_debug": profile_injection["selection_debug"],
    }

    parsed = _parse_strategy_name(strategy_id)
    row_data["parsed_fields"] = json.dumps(parsed) if parsed else None

    if is_single_asset:
        row_data.update(_ledger_compute_single_asset_extras(
            strategy_id, metrics, constituent_run_ids
        ))
    else:
        row_data["avg_pairwise_corr"] = corr_data["avg_pairwise_corr"]
        row_data["max_pairwise_corr_stress"] = max_stress_corr

    return row_data


def _serialize_ledger_row(row_data, columns):
    """Project row_data into a single-row DataFrame aligned with the target columns.

    Missing columns are filled with None (they become NaN in the final DataFrame).
    """
    new_row = pd.DataFrame([row_data])
    for c in columns:
        if c not in new_row.columns:
            new_row[c] = None
    return new_row[columns]


def _ledger_check_idempotent(df_ledger, strategy_id, row_data):
    """If the strategy already exists in the ledger, decide whether to skip or fail.

    Returns True  = row is identical, caller should no-op.
    Raises        = row differs, must abort before any write.
    Returns False = strategy not present; caller should append.
    """
    if strategy_id not in df_ledger["portfolio_id"].astype(str).values:
        return False
    existing_row = df_ledger[df_ledger["portfolio_id"].astype(str) == strategy_id].iloc[-1]
    is_identical = True
    for k, v in row_data.items():
        if k in ["creation_timestamp", "portfolio_engine_version", "selection_debug"]:
            continue
        old_val = existing_row.get(k)
        if pd.isna(old_val) and (v is None or pd.isna(v)):
            continue
        try:
            if abs(float(old_val) - float(v)) > 1e-4:
                is_identical = False
                break
        except Exception:
            if str(old_val) != str(v):
                is_identical = False
                break
    if is_identical:
        print(f"  [LEDGER] Portfolio '{strategy_id}' already exists and is identical. Skipping append (idempotent).")
        return True
    raise ValueError(
        f"[FATAL] Attempted modification of existing portfolio entry '{strategy_id}'.\n"
        f"Explicit human authorization required. No automatic overwrite allowed."
    )


def _append_ledger_row(ledger_path, df_ledger, df_other, new_row_df,
                       target_sheet, other_sheet):
    """Persist the ledger: DB first, Excel second, then formatter/notes best-effort."""
    df_final = pd.concat([df_ledger, new_row_df], ignore_index=True)
    _lock_path = ledger_path.with_suffix(".lock")
    with FileLock(str(_lock_path), timeout=120):
        ensure_xlsx_writable(ledger_path)
        # DB FIRST (mandatory) — SQLite is the source of truth
        from tools.ledger_db import (
            _connect as _db_connect,
            create_tables as _db_create,
            upsert_mps_df as _db_upsert,
        )
        _db_conn = _db_connect()
        _db_create(_db_conn)
        _db_upsert(_db_conn, df_final, sheet=target_sheet)
        if df_other is not None and not df_other.empty:
            _db_upsert(_db_conn, df_other, sheet=other_sheet)
        _db_conn.close()
        print(f"  [LEDGER_DB] Synced {len(df_final)} {target_sheet} rows to ledger.db")

        # EXCEL SECOND (derived view, best-effort)
        _preserve = {}
        _data_names = {target_sheet, other_sheet}
        if ledger_path.exists():
            with pd.ExcelFile(ledger_path) as _xls:
                for _sn in _xls.sheet_names:
                    if _sn not in _data_names:
                        try:
                            _preserve[_sn] = pd.read_excel(_xls, sheet_name=_sn)
                        except Exception:
                            pass
        try:
            _tmp_ledger = ledger_path.with_suffix(".xlsx.tmp")
            with pd.ExcelWriter(_tmp_ledger, engine="openpyxl", mode="w") as writer:
                df_final.to_excel(writer, sheet_name=target_sheet, index=False)
                if df_other is not None and not df_other.empty:
                    df_other.to_excel(writer, sheet_name=other_sheet, index=False)
                for _sn, _sdf in _preserve.items():
                    _sdf.to_excel(writer, sheet_name=_sn, index=False)
            import os as _os_atomic
            with open(_tmp_ledger, "r+b") as _fh:
                _os_atomic.fsync(_fh.fileno())
            _os_atomic.replace(str(_tmp_ledger), str(ledger_path))
        except Exception as _xl_err:
            print(f"  [WARN] Excel export failed ({_xl_err}). Run: python tools/ledger_db.py --export-mps")

        # Call Unified Formatter (best-effort)
        _formatter = PROJECT_ROOT / "tools" / "format_excel_artifact.py"
        try:
            subprocess.run(
                [sys.executable, str(_formatter), "--file", str(ledger_path), "--profile", "portfolio"],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Formatting failed: {e}")

        try:
            subprocess.run(
                [sys.executable, str(_formatter), "--file", str(ledger_path), "--notes-type", "portfolio"],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Notes sheet failed: {e}")


def update_master_portfolio_ledger(strategy_id, metrics, corr_data, max_stress_corr,
                                    concurrency_data, constituent_run_ids, n_assets=1):
    """
    Append portfolio result to Master_Portfolio_Sheet.xlsx (SOP 8).

    Orchestrator — delegates schema, profile resolution, density, row building,
    idempotency, and persistence to dedicated helpers.

    Routes rows into two sheets based on asset count:
      - "Portfolios"               (multi-asset, n_assets > 1)
      - "Single-Asset Composites"  (single-asset, n_assets == 1)
    """
    ledger_path = STRATEGIES_ROOT / "Master_Portfolio_Sheet.xlsx"
    is_single_asset = (n_assets <= 1)

    columns, target_sheet, other_sheet = _ledger_schema(is_single_asset)

    # Process constituent_run_ids (list -> string)
    if isinstance(constituent_run_ids, list):
        run_ids_str = ",".join(str(x) for x in constituent_run_ids)
    else:
        run_ids_str = str(constituent_run_ids)

    # Load + migrate existing state
    df_ledger, df_other = _ledger_load_frames(target_sheet, other_sheet, columns)
    _ledger_apply_column_fixups(df_ledger, is_single_asset)
    _ledger_recompute_existing_statuses(df_ledger, is_single_asset)
    _ledger_recompute_existing_profiles(df_ledger, strategy_id)

    # Resolve deployed profile for THIS row
    profile_injection = _ledger_resolve_new_profile(strategy_id, metrics, df_ledger)
    rejection_rate_pct = profile_injection["rejection_rate_pct"]
    sim_years = profile_injection["simulation_years"]

    # Per-symbol density (computed BEFORE status so density gate applies to new row)
    density = _ledger_compute_trade_density(
        strategy_id, constituent_run_ids, rejection_rate_pct, sim_years
    )

    # Portfolio status for the NEW row
    profile_injection["portfolio_status"] = _compute_portfolio_status(
        profile_injection["realized_pnl"], profile_injection["trades_accepted"],
        rejection_rate_pct,
        expectancy=metrics.get("expectancy", 0.0),
        portfolio_id=strategy_id,
        trade_density_min=density["td_min"],
        edge_quality=metrics.get("edge_quality", None),
        sqn=metrics.get("sqn", None),
        is_single_asset=is_single_asset,
    )

    # Build the full row dict
    row_data = _compute_ledger_row(
        strategy_id, metrics, corr_data, max_stress_corr,
        concurrency_data, constituent_run_ids, n_assets,
        is_single_asset, run_ids_str, profile_injection, density,
    )

    # Idempotent guard (raises if differs, returns True if identical)
    if _ledger_check_idempotent(df_ledger, strategy_id, row_data):
        return

    # Project + persist
    new_row_df = _serialize_ledger_row(row_data, columns)
    _append_ledger_row(ledger_path, df_ledger, df_other, new_row_df,
                       target_sheet, other_sheet)
