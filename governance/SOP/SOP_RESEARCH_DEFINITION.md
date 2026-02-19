# SOP_RESEARCH_DEFINITION — VERSION 2.0 (PHASE 14)

**Status:** AUTHORITATIVE | PRE-EXECUTION  
**Applies to:** Trade_Scan Research & Development  
**Precedence:**  
TRADE_SCAN_DOCTRINE  
→ SOP_RESEARCH_DEFINITION  
→ SOP_TESTING  
→ SOP_OUTPUT

---

## 1. Purpose

This SOP governs the **deterministic definition** of research hypotheses and experiments.
It transitions research tracking from narrative documents to machine-readable YAML artifacts to support:

1. Automated validation of experiment parameters.
2. Programmatic comparison of results against baselines.
3. Deterministic lineage tracking of strategy evolution.

---

## 2. Research Artifacts

All research initiatives MUST be defined in a YAML file located at:
`research/<DIRECTIVE_ID>.yaml`

The `directive_id` in the filename MUST match the `id` field within the YAML.

---

## 3. Schema Definition (Strict)

### 3.1 Root Fields

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | string | YES | Unique ID (e.g. `Strat_Variant_v1`). Matches filename. |
| `researcher` | string | YES | Author of the hypothesis. |
| `created_at` | string | YES | ISO 8601 Date (YYYY-MM-DD). |
| `base_strategy` | string | YES | Name of the parent strategy. |
| `engine_version` | string | YES | Target Engine Version (e.g. `1.2.0`). |

### 3.2 Baseline Reference (`baseline`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | string | YES | The `directive_id` of the control run. |
| `manifest_hash` | string | **YES** | **MANDATORY**. SHA256 of baseline code snapshot. |

* **Rule**: If `baseline.id` is present, `manifest_hash` MUST be provided.
* **Rule**: Baseline Drift is PROHIBITED.

### 3.3 Hypothesis & Validation (`hypothesis` / `mechanism_validation`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `mechanism` | string | YES | Description of the logic change. |
| `validation` | object | YES | Causal check (Qualitative only). |

* `mechanism_validation` (Qualitative Check - Does not affect score):
  * `expected_trade_count`: `increase` / `decrease` / `neutral`
  * `expected_drawdown`: `increase` / `decrease` / `neutral`
  * `expected_volatility_exp`: `increase` / `decrease` / `neutral`

### 3.4 Design (`design`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `independent_variable` | string | YES | The primary parameter/logic being changed. |
| `other_changes` | list | NO | List of any secondary changes (discouraged). |

### 3.5 Test Scope (`test_scope`)

*Must align with Directive File inputs.*

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `symbols` | list | YES | List of ticker symbols. |
| `timeframe` | string | YES | Bar timeframe (e.g. `5m`, `1h`). |
| `start_date` | string | YES | YYYY-MM-DD. |
| `end_date` | string | YES | YYYY-MM-DD. |

### 3.6 Evaluation Model (`evaluation`)

*FIXED 10-Metric Binary Scoring Model.*

* **Promotion Threshold**: **7 / 10** (Global Governance Rule).
* **Score Calculation**: Sum(Pass = 1, Fail = 0).

**MANDATORY METRICS (Fixed Schema):**

1. `sharpe_min`
2. `return_to_drawdown_min` (Net Profit / MaxDD)
3. `expectancy_min`
4. `profit_factor_min`
5. `max_drawdown_pct_max`
6. `equity_stability_rule` (Qualitative: `true`/`false`)
7. `trade_count_min`
8. `win_rate_min`
9. `avg_concurrent_max`
10. `exposure_pct_max`

### 3.7 Operational Constraints (`constraints`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `max_concurrency` | int | YES | Hard limit on simultaneous positions. |

### 3.8 Decision (`decision`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `status` | string | YES | `PENDING` / `ADVANCE` / `REJECT` / `REFINE`. |
| `score` | int | YES | Final Score (0-10). |
| `notes` | string | NO | Explanation. |

---

## 4. Governance & Linkage Rules

### 4.1 Directive ↔ Research Linkage

1. **Existence**: Directive execution is **GOVERNANCE-INVALID** without a matching `research/<DIRECTIVE_ID>.yaml`.
2. **Naming**: YAML `id` MUST match the directive filename (excluding `.txt`).
3. **Baseline**: The `baseline.id` directive MUST exist and be valid (or archived).

### 4.2 Immutability

1. **Promotion Lock**: Once `status: ADVANCE`, the research file is **LOCKED**.
2. **Versioning**: Any logic change requires a new `Directive ID` and new YAML file.
3. **Notes**: Only `notes` field may be appended to after final decision.

---

## 5. Lifecycle Protocol

1. **Drafting**: Create `<ID>.yaml`. Fill `test_scope` and `evaluation` thresholds.
2. **Execution**: Run pipeline.
3. **Scoring**: Compare Stage-4 outputs against the 10 metrics.
    * Pass = 1, Fail = 0.
    * Total Score = Sum.
4. **Decision**:
    * If Score >= 7: **ADVANCE** (Promote to Master).
    * If Score < 7: **REJECT** or **REFINE** (New ID).

---

## 6. Naming Conventions

* **ID Format**: `{Strategy}_{Variant}_{Version}`
  * Example: `Range_Breakout_VolFilter_v2`
* **Variant**: Short, descriptive PascalCase (e.g. `MaCrossover`, `StopLossTight`).
* **Version**: `v1`, `v2` (integer increment).
