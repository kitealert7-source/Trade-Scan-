"""Promote package — decomposed from tools/promote_to_burnin.py.

Public API is re-exported from the top-level shim `tools/promote_to_burnin.py`
to preserve backward-compatible imports (e.g. `from tools.promote_to_burnin
import decompose_portfolio`).

Module responsibilities:
    metadata.py        — archetype inference, symbol/TF detection, per-symbol filters
    metrics.py         — backtest + profile metric readers
    quality_gate.py    — 6-metric edge quality gate (compute + print)
    audit.py           — audit log writer
    strategy_files.py  — file validation, recovery, strategy.py hash, vault snapshot
    yaml_writer.py     — portfolio.yaml + burn_in_registry.yaml authority
    preflight.py       — outer preflight report + inner _run_preflight step
    decomposition.py   — composite portfolio decomposition + per-constituent promote
"""
