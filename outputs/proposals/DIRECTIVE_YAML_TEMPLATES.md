# Directive YAML Templates — Field Reference (v2)

> Updated for Signature Schema v2 (`tools/directive_schema.py`).
> Single authority: `normalize_signature()`. No duplicate definitions.

## Infrastructure Requirements

| Field | Required? | In Signature? | Notes |
|---|---|---|---|
| `test:` (wrapper) | **MANDATORY** | No | Flat YAML rejected by `parse_directive()` |
| `name` | Yes | No | Inside `test:` block |
| `family` | Yes | No | Inside `test:` block |
| `strategy` | **Yes** | No | Identity — used by provisioner + validator |
| `broker` | Yes | No | Inside `test:` block |
| `timeframe` | **Yes** | No | Identity — matched by validator |
| `session_time_reference` | Recommended | No | Inside `test:` block |
| `start_date` / `end_date` | Yes | No | Inside `test:` block |
| `symbols` | Yes | No | Root-level, not in signature |
| `indicators` | **HARD REQUIRED** | **Yes** | Must be list of dotted module paths |
| `execution_rules` | **HARD REQUIRED** | **Yes** | All entry/exit/stop logic goes here |
| `order_placement` | Optional | **Yes** | Default-injected: `{type: market, execution_timing: next_bar_open}` |
| `volatility_filter` | Optional | **Yes** | Only if strategy uses volatility gating |
| `range_definition` | Optional | **Yes** | Only for range-breakout strategies |
| `trade_management` | Optional | **Yes** | Direction, reentry, max trades |

> [!IMPORTANT]
> **Rule**: Any root-level key NOT in `NON_SIGNATURE_KEYS` enters the signature.
> Do NOT add ad-hoc root-level keys (e.g. `entry_logic`, `direction`).
> Nest behavioral parameters inside one of the recognized blocks.

---

## Template 1 — Generic (Strategy-Agnostic)

```yaml
# ============================================================
# DIRECTIVE TEMPLATE — GENERIC (Schema v2)
# ============================================================
# test: wrapper is MANDATORY.
# order_placement: auto-injected if omitted.
# volatility_filter / range_definition / trade_management: optional.
# ============================================================

test:
  name: <DIRECTIVE_NAME>
  family: <FAMILY>
  strategy: <STRATEGY_NAME>

  broker: OctaFX
  timeframe: <1h|4h|1d>
  session_time_reference: UTC

  start_date: <YYYY-MM-DD>
  end_date: <YYYY-MM-DD>

  research_mode: <hypothesis_validation|portability_validation>
  tuning_allowed: false
  parameter_mutation: prohibited

# ---- SYMBOLS (not in signature) ----

symbols:
  - <SYMBOL_1>
  - <SYMBOL_2>

# ---- INDICATORS (HARD REQUIRED) ----

indicators:
  - indicators.volatility.volatility_regime
  - indicators.volatility.atr
  # Add strategy-specific indicators here

# ---- EXECUTION RULES (HARD REQUIRED) ----
# All entry/exit/stop behavioral parameters go HERE.

execution_rules:
  entry_logic:
    type: <entry_type>
    # ... strategy-specific parameters
  exit_logic:
    type: <exit_type>
    # ... strategy-specific parameters
  stop_loss:
    type: none
  trailing_stop:
    enabled: false

# ---- ORDER PLACEMENT (optional — default-injected if omitted) ----

# order_placement:
#   type: market
#   execution_timing: next_bar_open

# ---- VOLATILITY FILTER (optional) ----

# volatility_filter:
#   enabled: false

# ---- TRADE MANAGEMENT (optional) ----

# trade_management:
#   direction_restriction: none
#   max_trades_per_session: 1
#   reentry:
#     allowed: false
```

---

## Template 2 — SPX02_MR (Adapted)

```yaml
# ============================================================
# DIRECTIVE: SPX02_MR — Schema v2
# Family: SPX — Volatility Pullback Mean Reversion
# Mode: GENESIS_MODE (new strategy, no prior strategy.py)
# ============================================================

test:
  name: SPX02_MR
  family: SPX
  strategy: SPX02_MR

  broker: OctaFX
  timeframe: 1d
  session_time_reference: UTC

  start_date: 2015-01-01
  end_date: 2026-01-31

symbols:
  - SPX500

# ---- INDICATORS ----

indicators:
  - indicators.structure.highest_high
  - indicators.trend.linreg_regime
  - indicators.trend.linreg_regime_htf
  - indicators.trend.kalman_regime
  - indicators.trend.trend_persistence
  - indicators.volatility.volatility_regime
  - indicators.volatility.atr

# ---- EXECUTION RULES ----

execution_rules:
  pyramiding: false
  entry_when_flat_only: true
  reset_on_exit: true
  entry_logic:
    type: volatility_pullback
    lookback_bars: 5
    atr_length: 10
    atr_multiplier: 1.5
    condition: close_less_than_hh_minus_atr
  exit_logic:
    type: dynamic_or_time
    price_exit: close_greater_than_hh_prev
    time_exit_bars: 4
  stop_loss:
    type: none
  trailing_stop:
    enabled: false

# order_placement omitted — default-injected as:
#   {type: market, execution_timing: next_bar_open}

# ---- VOLATILITY FILTER ----

volatility_filter:
  enabled: false

# ---- TRADE MANAGEMENT ----

trade_management:
  direction: long_only
  reentry:
    allowed: false
```

---

## Key Changes from v1

| v1 (legacy) | v2 (current) |
|---|---|
| `SIGNATURE_SCHEMA_VERSION = 1` | `SIGNATURE_SCHEMA_VERSION = 2` |
| Validator hardcodes 5 keys | Validator calls `normalize_signature()` |
| Provisioner has inline exclusion list | Both import from `directive_schema.py` |
| `order_placement` hard required | Default-injected if absent |
| Flat YAML accepted | `test:` wrapper mandatory |
| Key order = insertion order | Keys sorted deterministically |
