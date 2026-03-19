# Directive Compatibility Audit

**Active Engine Snapshot:**
`engine_dev/universal_research_engine/v1_5_3`

**Expected Directive Schema:**
The current engine strictly requires a YAML-formatted mapping as the root structure.
Required structural nodes defined by the engine/pipeline logic:
1. `test:` wrapper block (flat directives are strictly forbidden by `pipeline_utils.py:155` "INVALID DIRECTIVE STRUCTURE: 'test:' wrapper block is required")
2. `indicators:` block (v2 schema logic per `REQUIRED_SIGNATURE_KEYS` in `directive_schema.py`)
3. `execution_rules:` block (v2 schema logic per `REQUIRED_SIGNATURE_KEYS` in `directive_schema.py`)

**Structural Mismatches in Legacy Directives (IDX22-IDX28):**

1. **Format Base Mismatch (Fatal):**
   The legacy `IDX22.txt` is written in plain text (Markdown/Custom human-readable format), not structured YAML. It looks like:
   ```text
   IDX22 — DIP BUYING (MEAN-REVERSION)
   Family: Index Family
   ...
   ```
   This immediately violates `pipeline_utils.py:128` (`yaml.load()`) and `pipeline_utils.py:134` (must be a YAML mapping).

2. **Missing `test:` Wrapper (Fatal):**
   Even if it were valid YAML, `pipeline_utils.py` line 156 mandates a root-level `test:` key. The legacy directives are completely flat.

3. **Missing `indicators` and `execution_rules` Blocks (Schema Violations):**
   `directive_schema.py` line 25 strictly enforces `REQUIRED_SIGNATURE_KEYS = frozenset({"indicators", "execution_rules"})`. The legacy file uses arbitrary human-readable headings like "Volatility Model", "Entry Logic", and "Exit Logic".

**Minimal Correction Required:**

To make these directives runnable, they must be converted into standard TradeScan YAML schema.
A bare-minimum functional version of IDX22 would require reshaping the rules into the standard blocks:

```yaml
directive_id: 10_IDX_AUS200_1D_DIP_MEANREV_S22_V1_P00
test:
  target:
    timeframe: 1d
  symbols:
    - AUS200
    - ESP35
    - EUSTX50
    - FRA40
    - GER40
    - JPN225
    - NAS100
    - SPX500
    - UK100
    - US30
  indicators:
    atr_volatility:
      type: atr
      length: 14
      smoothing: rma
    atr_percentile:
      type: percentile
      source: atr_volatility
      lookback: 100
    price_hh:
      type: highest
      source: high
      lookback: 5
  execution_rules:
    entry:
      long:
        - "close < (price_hh[1] - atr_volatility)"
        - "atr_percentile <= 75"
    exit:
      long:
        - "close > price_hh[1]"
        - "bars_held >= 5"
```
*(Note: Cooldown logic would also need engine-specific translation or wrapping depending on the exact strategy plugin standard).*
