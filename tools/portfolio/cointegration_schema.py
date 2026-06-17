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
METRICS_FN_VERSION = "canonical-3"  # canonical-3 (2026-06-05): adds realized_net_pct
# (Σ strategy-cycle PnL / stake — excludes open-position floating + the DATA_END
# boundary force-close) so 0-strategy-cycle "phantom" runs read realized 0 while
# net_pct stays mark-to-market. canonical-2: variant-agnostic LIQUIDATE-convention
# cycle counting (fixed GP_ZOPP 0-cycle bug). See canonical_metrics._cycle_pnl_robust.
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
    # --- methodology cohort (2026-05-30, C2) ---
    "methodology_version",    # v1_raw_adf (legacy) | v2_log_eg (post-C3) | ...
    # --- realized performance (2026-06-05, canonical-3) ---
    "realized_net_pct",       # Σ strategy-cycle PnL / stake (excl. floating + DATA_END boundary)
    # --- effective input identity (data-provenance hardening, 2026-06-16) ---
    # Single deterministic DECISION witness. Two rows answer "did these runs
    # consume the same effective input DATA?" via WHERE effective_input_sha256=?
    # -- in seconds, with NO manifest, run folder, or JSON parse. Folded SOLELY
    # from the already-computed per-leg leg_data_sha256 values (canonical sorted
    # "SYM=hash" -> sha256; see tools/basket_provenance.effective_input_sha256);
    # the per-leg breakdown stays in runs/<id>/manifest.json for forensic detail.
    # SCOPE LIMIT (do NOT over-read as "reproducible"): attests DATA identity
    # ONLY. It does NOT prove rule-code identity (strategy_code_sha256 is NULL for
    # baskets) or sizing identity (broker_spec_sha256) -- both DELIBERATELY remain
    # manifest-only (adjacent gaps, out of scope for this change). For full
    # effective-input identity, combine with directive_sha256 + engine_version +
    # engine_abi. Nullable: pre-2026-06-16 rows and provenance-failed runs are NULL.
    "effective_input_sha256",
    # --- cost-regime self-identification (R9 self-ID half, 2026-06-17) ---
    # Closes "runs don't record which cost regime applied": the basket engine
    # charges purely off the per-bar `spread` column, but nothing recorded
    # whether that column was POPULATED (data axis) or whether the COMPUTE even
    # charges it (engine axis) -- the prior `execution_model_version` lived in
    # the RESEARCH preamble (CSV `comment="#"`) with 0 code readers. These two
    # make a run self-describing on cost:
    #   spread_coverage_pct  -- MEASURED min-across-legs % of consumed bars with
    #                           spread>0 (catches the XAU spread=0 acquisition
    #                           gap that silently zero-charged a leg -- the exact
    #                           failure that motivated R9). REAL, nullable.
    #   execution_cost_model -- DERIVED from the imported compute ABI via the
    #                           basket_runner SSOT (override-inert, as honest as
    #                           engine_abi -- NOT an independently-set stamp):
    #                           spread_uncosted_roundtrip_v1_5_9 vs
    #                           spread_charged_diraware_v1_5_10. Makes "did this
    #                           row charge?" a direct query, not v1_5_9=uncharged
    #                           tribal knowledge. TEXT, nullable. (The uncharged
    #                           token avoids the substring "charged" so the
    #                           charged filter below cannot match it.)
    # Together: WHERE execution_cost_model LIKE 'spread_charged%' AND
    # spread_coverage_pct >= 99  ==  the "genuinely charged, decision-grade"
    # filter the v1.5.10 canonical flip must certify rows against. Nullable:
    # pre-2026-06-17 rows and provenance-failed runs are NULL ("pre-self-ID").
    "spread_coverage_pct",
    "execution_cost_model",
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
    "realized_net_pct",
    "spread_coverage_pct",
}

__all__ = [
    "SCHEMA_VERSION",
    "METRICS_FN_VERSION",
    "PRIMARY_KEY",
    "COINTEGRATION_SHEET_COLUMNS",
    "COINTEGRATION_NUMERIC_COLUMNS",
]
