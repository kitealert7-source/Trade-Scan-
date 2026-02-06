# Execution Results Emitter — Design Specification

**Status:** APPROVED  
**Scope:** Stage-1 execution emission only  
**Governed by:** SOP_OUTPUT, SOP_TESTING

> **Scope Declaration:** This specification governs Stage-1 execution emission only. Stage-2 (presentation) and Stage-3 (aggregation) are conceptually separate systems that consume Stage-1 outputs and are explicitly out of scope.

---

## 1. Emitter Role Definition

### 1.1 Responsibilities

The Execution Results Emitter is responsible for:

| Responsibility | Description |
|----------------|-------------|
| **Receive** | Accept fully-formed execution outputs from engines |
| **Validate** | Verify inputs conform to declared schemas |
| **Write** | Emit authoritative execution artifacts to the strategy folder |
| **Atomicity** | Ensure all-or-nothing artifact creation |
| **Immutability** | Guarantee once-written artifacts are never modified |

### 1.2 Explicit Non-Responsibilities (FORBIDDEN)

The Emitter **MUST NEVER**:

| Forbidden Action | Rationale |
|------------------|-----------|
| Compute metrics | Metrics are computed by execution logic, not the emitter |
| Compute aggregates | Aggregation is performed by execution logic before emission |
| Derive yearwise/risk tables | These are execution outputs, passed to emitter fully-formed |
| Interpret results | Emitter is a conduit, not an analyst |
| Transform data | Input schema = output schema |
| Infer missing fields | No auto-repair; missing fields = validation failure |
| Read historical data | Emitter has no data access rights |
| Modify engine code | Emitter is execution-agnostic |
| Write outside strategy folder | Filesystem boundary is absolute |
| Append to existing artifacts | Immutability is non-negotiable |
| Retry on failure | Partial writes are forbidden; failure = abort |
| Generate presentation artifacts | Excel/summaries are Stage-2 concerns |

---

## 2. Input Schemas

> **Execution Responsibility:** All economics, risk metrics, and yearwise aggregation are computed by execution logic *before* the emitter is called. The emitter validates and writes; it does not derive.

### 2.1 Schema Versioning Strategy

| Field | Value |
|-------|-------|
| `schema_version` | Semantic versioning (e.g., `1.0.0`) |
| Compatibility | Breaking changes require major version increment |
| Validation | Schema version MUST be declared in metadata |

### 2.2 Trade-Level Table (`results_tradelevel.csv`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `strategy_name` | String | ✓ | Strategy identifier (denormalized for standalone interpretation) |
| `parent_trade_id` | Integer | ✓ | Groups multi-leg trades |
| `sequence_index` | Integer | ✓ | Zero-based leg order within parent |
| `entry_timestamp` | String (ISO8601 UTC) | ✓ | Entry time |
| `exit_timestamp` | String (ISO8601 UTC) | ✓ | Exit time |
| `direction` | Integer | ✓ | 1 = Long, -1 = Short |
| `entry_price` | Float | ✓ | Entry price |
| `exit_price` | Float | ✓ | Exit price |
| `net_pnl` | Float | ✓ | Net PnL in USD (2 decimal places) |
| `bars_held` | Integer | ○ | Duration in bars (nullable) |

### 2.3 Standard Metrics Table (`results_standard.csv`)

| Field | Type | Required | Description | Decimal Semantics |
|-------|------|----------|-------------|-------------------|
| `net_pnl_usd` | Float | ✓ | Net profit in USD | N/A |
| `win_rate` | Float | ✓ | Win rate | 0.0–1.0 |
| `profit_factor` | Float | ✓ | Gross profit / Gross loss | N/A |
| `trade_count` | Integer | ✓ | Total trades | N/A |

### 2.4 Risk Metrics Table (`results_risk.csv`)

| Field | Type | Required | Description | Decimal Semantics |
|-------|------|----------|-------------|-------------------|
| `max_drawdown_usd` | Float | ✓ | Maximum drawdown in USD | N/A |
| `max_drawdown_pct` | Float | ✓ | Maximum drawdown | 0.0–1.0 |
| `sharpe_ratio` | Float | ○ | Risk-adjusted return | N/A |
| `sortino_ratio` | Float | ○ | Downside risk-adjusted return | N/A |
| `return_dd_ratio` | Float | ○ | Net profit / Max drawdown | N/A |

### 2.5 Yearwise Metrics Table (`results_yearwise.csv`)

| Field | Type | Required | Description | Decimal Semantics |
|-------|------|----------|-------------|-------------------|
| `year` | Integer | ✓ | Calendar year | N/A |
| `net_pnl_usd` | Float | ✓ | Net profit for year | N/A |
| `trade_count` | Integer | ✓ | Trades in year | N/A |
| `win_rate` | Float | ✓ | Win rate for year | 0.0–1.0 |
| `max_drawdown_pct` | Float | ○ | Max drawdown for year | 0.0–1.0 |

### 2.6 Metrics Glossary Table (`metrics_glossary.csv`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric_key` | String | ✓ | Metric identifier |
| `full_name` | String | ✓ | Human-readable name |
| `definition` | String | ✓ | Metric definition |
| `unit` | String | ✓ | Unit of measure |

### 2.7 Run-Level Metadata Fields (`run_metadata.json`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `run_id` | String (UUID) | ✓ | Unique run identifier |
| `strategy_name` | String | ✓ | Strategy identifier |
| `symbol` | String | ✓ | Instrument symbol |
| `timeframe` | String | ✓ | Execution timeframe |
| `date_range.start` | String (ISO8601) | ✓ | Backtest start date |
| `date_range.end` | String (ISO8601) | ✓ | Backtest end date |
| `execution_timestamp_utc` | String (ISO8601) | ✓ | When execution occurred |
| `engine_name` | String | ✓ | Engine identifier |
| `engine_version` | String | ✓ | Engine version |
| `directive_hash` | String | ✓ | SHA256 of directive file |
| `engine_hash` | String | ✓ | SHA256 of engine code |
| `data_fingerprint` | String | ✓ | Hash of input data context |
| `schema_version` | String | ✓ | Emitter schema version |

---

## 3. Output Artifacts (Authoritative Execution Artifacts)

### 3.1 Artifact Manifest

| Artifact | Filename | Format | Description |
|----------|----------|--------|-------------|
| Trade-level results | `results_tradelevel.csv` | CSV | Authoritative trade execution record |
| Standard metrics | `results_standard.csv` | CSV | Core run-level performance metrics |
| Risk metrics | `results_risk.csv` | CSV | Risk and drawdown metrics |
| Yearwise metrics | `results_yearwise.csv` | CSV | Per-year performance breakdown |
| Metrics glossary | `metrics_glossary.csv` | CSV | Metric definitions |
| Run metadata | `run_metadata.json` | JSON | Run-level execution context |
| Directive copy | `<directive_filename>` | Markdown | Immutable copy of executed directive |

### 3.2 Directory Structure (Per Run)

```
backtests/<strategy_name>/
├── execution/
│   ├── results_tradelevel.csv
│   ├── results_standard.csv
│   ├── results_risk.csv
│   ├── results_yearwise.csv
│   └── metrics_glossary.csv
├── metadata/
│   └── run_metadata.json
└── <directive_filename>
```

### 3.3 One-Run → One-Folder Guarantee

| Rule | Specification |
|------|---------------|
| Folder naming | `backtests/<strategy_name>/` |
| Uniqueness | One strategy folder per completed run |
| Pre-existence check | If folder exists → validation failure → abort |
| Cleanup on failure | If emission fails mid-write → delete entire folder |

---

## 4. Invocation Model

### 4.1 Invocation Contract

Engines invoke the emitter via a single function call:

```
emit_results(
    trades: List[TradeRecord],
    standard_metrics: StandardMetrics,
    risk_metrics: RiskMetrics,
    yearwise_metrics: List[YearwiseRecord],
    metrics_glossary: List[GlossaryEntry],
    metadata: RunMetadata,
    directive_content: String,
    directive_filename: String
) → EmissionResult
```

### 4.2 Data Passed

| Parameter | Description |
|-----------|-------------|
| `trades` | List of trade-level records (per §2.2 schema) |
| `standard_metrics` | Run-level standard metrics (per §2.3 schema) |
| `risk_metrics` | Run-level risk metrics (per §2.4 schema) |
| `yearwise_metrics` | Per-year metrics breakdown (per §2.5 schema) |
| `metrics_glossary` | Metric definitions (per §2.6 schema) |
| `metadata` | Run-level metadata (per §2.7 schema) |
| `directive_content` | Raw text of the directive file |
| `directive_filename` | Original filename of the directive |

### 4.3 Atomicity Enforcement

| Phase | Action | Rollback on Failure |
|-------|--------|---------------------|
| 1. Validate | Schema validation of all inputs | Abort before any writes |
| 2. Stage | Write to temporary staging location | Delete staging folder |
| 3. Commit | Atomic rename to final location | Delete staging folder |
| 4. Seal | Mark artifacts as immutable | N/A (success state) |

### 4.4 Return Contract

| Return Value | Meaning |
|--------------|---------|
| `EmissionResult.SUCCESS` | All artifacts written successfully |
| `EmissionResult.VALIDATION_FAILED` | Input schema validation failed |
| `EmissionResult.WRITE_FAILED` | Filesystem error during write |
| `EmissionResult.FOLDER_EXISTS` | Strategy folder already exists |

---

## 5. Validation Rules

### 5.1 What Is Validated

| Validation | Scope | Failure Behavior |
|------------|-------|------------------|
| Schema version present | Metadata | Hard abort |
| All required fields present | All inputs | Hard abort |
| Field types match schema | All inputs | Hard abort |
| ISO8601 date format | Timestamps | Hard abort |
| Decimal range (0.0–1.0) | Percentage fields | Hard abort |
| Non-empty trade list | Trades | Hard abort |
| Non-empty yearwise list | Yearwise metrics | Hard abort |
| Strategy folder does not exist | Filesystem | Hard abort |

### 5.2 When Validation Happens

| Phase | Timing |
|-------|--------|
| Pre-write | Before any filesystem operations |
| All-or-nothing | Single validation pass; no partial acceptance |

### 5.3 Hard Abort Conditions

Any of the following causes immediate abort with no artifacts emitted:

- Missing required field
- Type mismatch
- Invalid date format
- Percentage value outside 0.0–1.0
- Empty trade list
- Empty yearwise metrics list
- Strategy folder already exists
- Filesystem write error
- Schema version mismatch

---

## 6. Out of Scope (Future Stages)

The following are explicitly **out of scope** for this Stage-1 emitter and will be handled by separate, downstream systems:

| Future Stage | Responsibility |
|--------------|----------------|
| **Stage-2** | Presentation artifacts (Excel reports, formatted summaries) |
| **Stage-2** | AK_Trade_Report generation |
| **Stage-3** | Cross-run aggregation (Strategy_Master_Filter) |
| **Stage-3** | Ranking, comparison, and advisory analysis |

> **Constraint:** Stage-2 and Stage-3 systems MUST consume Stage-1 authoritative execution artifacts as their sole input. They MUST NOT access engines, historical data, or execution logic directly.

---

## 7. Explicit Non-Goals

The Execution Results Emitter **will never support**:

| Non-Goal | Rationale |
|----------|-----------|
| Presentation artifacts (Excel) | Stage-2 concern |
| Metric computation | Execution logic computes; emitter writes |
| Cross-run aggregation | Stage-3 concern |
| Schema inference | Explicit schemas only |
| Auto-repair of malformed input | Garbage in = validation failure |
| Retry logic | Atomic execution; no partial recovery |
| Logging to external systems | Filesystem-only scope |
| Multi-run batching | One invocation = one run = one folder |
| Historical data access | Read-only boundary is absolute |
| Engine modification | Emitter is decoupled from execution logic |
| Backward compatibility shims | Breaking changes require new schema version |

---

## End of Design Specification
