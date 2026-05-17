"""basket_hypothesis — modules supporting the /basket-hypothesis-testing skill.

Cycle-aware reporting + metrics for basket strategies (H2_recycle@4/@5 and
future cycle-mechanic variants). Distinct from `tools/basket_report.py`
(legacy trade-level reporter); these modules read the per-bar parquet
emitter as source of truth and understand the cycle-event taxonomy.

Modules
-------
canonical_metrics : single canonical formula for net%, max_dd%, ret/DD,
                    per-event counts, cycle-level breakdowns. Used by
                    basket_report.py, basket_ledger_writer.py, and the
                    basket-hypothesis-testing orchestrator's at-a-glance.
basket_report     : generates BASKET_REPORT.md alongside the legacy
                    REPORT.md. The legacy file stays for backward compat;
                    this one is authoritative for cycle-mechanic baskets.
"""
from tools.basket_hypothesis.basket_report import render_basket_report, write_basket_report
from tools.basket_hypothesis.canonical_metrics import canonical_metrics

__all__ = ["canonical_metrics", "render_basket_report", "write_basket_report"]
