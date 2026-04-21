"""Portfolio Evaluator package — decomposed from tools/portfolio_evaluator.py.

Authority invariants (never weaken):
  - portfolio_profile_selection  == sole owner of Step 7 deployed_profile selection
  - portfolio_ledger_writer      == sole writer of Master_Portfolio_Sheet.xlsx + ledger.db
                                    (portfolio_sheet table)

Dependency direction (strict, one-way):

  portfolio_config
      ↓
  portfolio_io
  portfolio_metrics         ← portfolio_config
  portfolio_charts          ← portfolio_config
  portfolio_tradelevel
  portfolio_snapshot        ← portfolio_config
  portfolio_profile_selection  (authority)
  portfolio_ledger_writer   ← portfolio_profile_selection, portfolio_config

The CLI entrypoint remains tools/portfolio_evaluator.py as a thin orchestrator
that re-exports the public+test surface (_compute_portfolio_status,
_per_symbol_realized_density, etc.) for back-compat.
"""
