"""Shared numeric coercion for ledger / portfolio writes.

`safe_float` was extracted 2026-06-06 from three byte-identical `_safe_float`
copies (profile_selector, reconcile_portfolio_master_sheet,
portfolio_profile_selection) to remove algorithm-drift risk across the ledger
write paths.

NOTE: the other `_safe_float` variants in the codebase are intentionally NOT
consolidated here because they behave differently and must stay separate:
  - metrics_core._safe_float        -> prints a STAGE2_COERCE_WARN on failure
  - basket_report._safe_float       -> numpy isnan/isinf (no pandas dependency)
  - idea_evaluation_gate._safe_float -> no `default` parameter
"""

import pandas as pd


def safe_float(value, default=0.0):
    """Best-effort numeric coercion for ledger writes.

    Returns `default` for None / NaN / unparseable input; otherwise float(value).
    """
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default
