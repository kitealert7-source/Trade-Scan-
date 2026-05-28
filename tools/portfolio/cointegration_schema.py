"""cointegration_schema.py -- single source of truth for the Cointegration ledger.

This module is the ONLY place the `cointegration_sheet` column set is defined.
tools/ledger_db.py (table DDL), the writer
(tools/portfolio/cointegration_ledger_writer.py), and the formatter
(tools/excel_format) all import from here -- so the 4-way schema drift that
affects basket_sheet cannot recur on this table.

DELIBERATE v1 EXCLUSIONS (do NOT "helpfully" add these back):
  - NO verdict_status / verdict_logic_version. v1 ranks by Ret/DD only. The
    prior CORE/WATCH/FAIL framing became suspect once screener/window
    assumptions changed; an empty verdict column creates gravitational pull
    toward prematurely rebuilding classification. Add verdict semantics ONLY
    after a meaningful B-compliant rerun corpus exists (operator gate).
  - NO stored research_rank. Rank is a VIEW concern, computed at export from
    the deterministic sort (canonical_ret_dd, completed_at_utc, run_id desc).
    Storing it would only go stale.

ONTOLOGY BOUNDARY (HARD): this table is for regime-conditioned cointegration
research. Operational/deployment baskets (H2 recycle, h3_spread) stay in
basket_sheet with their own schema + verdict. The two are never merged.

WRITER CONTRACT: the writer is a pure sink -- it reads only local run
artifacts (result object + parquet + a provenance dict). It MUST NOT read the
screener DB (cointegration.db). Regime provenance is captured upstream (at
admission + during the run) and passed in.
"""
from __future__ import annotations

SCHEMA_VERSION = "coint-1.0"
# Version of the metrics-derivation function (canonical_metrics). Bump when the
# metric computation changes; the assembler stamps it at write time and reenrich
# re-stamps it on recompute, so re-derived rows are distinguishable.
METRICS_FN_VERSION = "canonical-1"
PRIMARY_KEY = "run_id"

# Locked column order. Additive only (append at the right edge); never reorder
# or delete in place -- mirrors the append-only ledger invariant.
COINTEGRATION_SHEET_COLUMNS = [
    # --- identity & lineage (clean DB-native; populated, unlike basket_sheet) ---
    "run_id",
    "directive_id",
    "pair_a",
    "pair_b",
    "candidate_key",          # -> governance/cointegration_candidates.yaml (nullable)
    "leg_specs",              # "SYMBOL:lot:dir;..." (reuse basket convention)
    "completed_at_utc",
    "is_current",             # 1 = live, 0 = superseded
    "superseded_by",          # run_id of the replacement run
    "superseded_at",
    "supersede_reason",
    "supersede_kind",         # re-run | metric-recompute | methodology-bump | screener_change | data-refresh
    # --- construct / config ---
    "timeframe",
    "lookback_days",
    # --- run window (the executed backtest window) ---
    "test_start",
    "test_end",
    "n_obs",                  # exec-TF bars over [test_start, test_end]
    "stake_usd",
    # --- regime provenance (admission gate + run-loaded data; NOT read by the writer) ---
    "span_start",             # latest continuous cointegrated span start (gate)
    "span_end",               # latest continuous cointegrated span end (gate)
    "continuous_span_obs",    # aligned daily rows in the latest span (gate _Span.n_rows)
    "fragment_count",         # number of continuous spans in screener history
    "pct_cointegrated",
    "regime_state",           # regime as-of test_end (point-in-time provenance)
    "window_validation_status",  # PASS | OVERRIDE  (DB-only; not in the human view)
    "classifier_version",     # screener regime-classifier version (the real "generation")
    # --- reproducibility (so decisions become filters, not re-runs) ---
    "engine_version",
    "engine_abi",
    "strategy_code_sha256",
    "directive_sha256",
    "data_vintage",           # latest-bar / freshness ref of the input data
    "parquet_sha256",         # substrate hash (recompute integrity)
    "vault_path",             # retained immutable substrate copy
    "backtests_path",         # run folder (hyperlinked in the view)
    # --- metrics (reuse canonical_metrics; canonical is authoritative) ---
    "canonical_net_pct",
    "canonical_max_dd_pct",            # peak-relative (mark-to-market, incl. floating)
    "canonical_max_dd_pct_vs_stake",   # stake-relative sibling (DB-only)
    "canonical_ret_dd",
    "canonical_final_equity_usd",
    "cycle_win_rate_pct",
    "cycles_completed",
    "trades_total",
    # --- extensible metrics (registry-governed; flat, typed, namespaced, scalar-only) ---
    "metrics_json",           # see governance/research_metrics_registry.yaml
    "metrics_fn_version",
    # --- bookkeeping ---
    "schema_version",
    "enrichment_status",      # complete | no_canonical
]

# REAL-typed columns. Everything else is TEXT; is_current is special-cased in
# ledger_db._col_def (INTEGER DEFAULT 1). Defined here so the DDL derives types
# from this single source rather than a second hand-maintained list.
COINTEGRATION_NUMERIC_COLUMNS = {
    "lookback_days",
    "n_obs",
    "stake_usd",
    "continuous_span_obs",
    "fragment_count",
    "pct_cointegrated",
    "canonical_net_pct",
    "canonical_max_dd_pct",
    "canonical_max_dd_pct_vs_stake",
    "canonical_ret_dd",
    "canonical_final_equity_usd",
    "cycle_win_rate_pct",
    "cycles_completed",
    "trades_total",
}

__all__ = [
    "SCHEMA_VERSION",
    "METRICS_FN_VERSION",
    "PRIMARY_KEY",
    "COINTEGRATION_SHEET_COLUMNS",
    "COINTEGRATION_NUMERIC_COLUMNS",
]
