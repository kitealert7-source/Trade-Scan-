# Sweep Registry Hash Invariant

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

The sweep registry `signature_hash`/`signature_hash_full` is the SHA256 of `normalize_signature(parse_directive(<file>))`. It changes when any non-NON_SIGNATURE_KEY in the directive changes.

NON_SIGNATURE_KEYS (do NOT trigger hash change):
- `start_date`, `end_date`, `repeat_override_reason`, `stop_contract_guard`
- All keys under `test:` block that mirror identity: `name`, `strategy`, `broker`, `timeframe`, `description`

Keys that DO trigger hash change (require registry update):
- `indicators:` list (any addition or removal)
- `signal_version:` (bumping for SIGNAL category)
- Any `execution_rules:`, `volatility_filter:`, `trend_filter:`, etc. change

**Never use `new_pass.py --rehash` for patches that already exist in the registry** — it appends a duplicate YAML key instead of updating the existing one. Use `_write_yaml_atomic` directly.
