"""Backtest markdown-report package — decomposed from tools/report_generator.py.

Dependency direction:
  report_sessions ← report_insights / report_collector / report_news_policy
                  ← report_sections.* (all section builders)
  report_news_policy ← report_sections.news (news section builder)
  report_collector (SymbolPayloads + per-symbol collectors) — used by orchestrator
  report_writer — markdown file emit only

The public entrypoints (generate_backtest_report, generate_strategy_portfolio_report)
live in tools/report_generator.py and re-export from here.
"""
