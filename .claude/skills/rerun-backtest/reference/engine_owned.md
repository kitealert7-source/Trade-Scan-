# ENGINE_OWNED Indicator Removal Pattern

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

Engine-owned indicators (`volatility_regime`, `trend_regime`, `vol_regime`) are injected by the execution engine at runtime. Strategies must NOT import or call them in `prepare_indicators`. The ENGINE_OWNED_FIELDS guard at Stage-0.5 will block the run with a hard error.

**When removing an engine-owned indicator from a rerun:**

1. Remove from directive `indicators:` list (changes directive hash — update sweep registry)
2. Remove `from indicators.volatility.volatility_regime import ...` from strategy.py imports
3. Remove the call site in `prepare_indicators` (the `vr = volatility_regime(...)` line)
4. Remove from STRATEGY_SIGNATURE `indicators:` array in strategy.py
5. Recompute SIGNATURE_HASH using `_hash_sig_dict` from `tools/strategy_provisioner.py`
6. Update sweep registry hash using `_write_yaml_atomic` (not `new_pass.py --rehash`)
7. If the directive's `volatility_filter` uses `required_regime:`, the Classifier Gate will classify this as SIGNAL (not COSMETIC) — bump `signal_version`

The FilterStack reads `volatility_regime` from the engine context (via `ctx.require('volatility_regime')`), not from the strategy's DataFrame column. Removing the strategy's redundant computation is safe — filter behaviour is unchanged.
