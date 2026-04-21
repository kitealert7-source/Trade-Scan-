"""Capital deployment pipeline — decomposed from the original capital_wrapper.py.

Submodules (stable import order — leaf → core → orchestration):

  capital_events                — TradeEvent, OpenTrade, event loading/parsing/sorting,
                                   compute_signal_hash (trade-signal identity)
  capital_broker_spec           — broker spec YAML loading + cache (single location)
  capital_fx                    — FX currency parsing + ConversionLookup (dynamic USD conv)
  capital_portfolio_state       — PROFILES, PortfolioState (sizing + gate logic)
  capital_metrics               — compute_deployable_metrics
  capital_validation            — conservation + comparative/validation print helpers
  capital_plotting              — equity-curve + overlay comparison plots
  capital_artifacts             — emit_profile_artifacts + emit_comparison_json
  capital_directive_discovery   — directive-driven run_dir resolution

Dependency direction (strict, no reverse links):
  events ← broker_spec ← fx ← portfolio_state ← (metrics, validation, plotting, artifacts)
  directive_discovery is standalone.
"""
