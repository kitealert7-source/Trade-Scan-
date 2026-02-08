# Trade_Scan — System Orientation (Research-Only)

## Purpose

Trade_Scan is a **research execution and evaluation system**.  
It is designed to test strategy hypotheses under **strict governance**, **deterministic scope**, and **zero automation authority**.

Trade_Scan is **not** a trading system.  
It does **not** place live orders, schedule runs, or self-modify.

---

## Core Principles (Non-Negotiable)

1. **Research Only**
   - Human-directed execution only
   - No live trading, no automation authority
   - No silent defaults or inferred behavior

2. **Separation of Concerns**
   - Execution ≠ Metrics ≠ Aggregation
   - Each stage has a single, narrow responsibility

3. **Determinism First**
   - Explicit scope (symbols, broker, dates, timeframe)
   - No dynamic resolution (e.g., no “PRESENT”)
   - Identical inputs must produce identical outputs

4. **Governance Over Convenience**
   - Engines are immutable once validated
   - Strategies are plugins, not engine branches
   - Any ambiguity must fail fast

---

## System Architecture (High Level)

```
Directive
   ↓
Preflight (authority)
   ↓
Stage‑1: Engine Execution (raw trades only)
   ↓
Stage‑2: Metrics Compilation
   ↓
Stage‑3: Aggregation & Comparison
```

---

## Key Components

### 1. Directives
Human-authored markdown files that define:
- Strategy ID
- Broker
- Symbols
- Timeframe
- Start / End dates

Directives contain **intent**, not code.

---

### 2. Preflight (Authoritative)
- Validates directives
- Resolves execution scope
- Enforces governance rules
- Blocks execution on ambiguity

Preflight is the **only component allowed to parse directives**.

---

### 3. Universal_Research_Engine (Stage‑1)
- Executes strategies against historical data
- Loads strategies dynamically as plugins
- Emits **raw trade records only**
- Computes **no metrics**

Each engine version is immutable once validated.

---

### 4. Strategy Plugins
Located at:
```
Trade_Scan/strategies/<STRATEGY_ID>/strategy.py
```

Responsibilities:
- Indicator computation
- Entry / exit signal logic only

Strategies:
- Do NOT define scope
- Do NOT know brokers
- Do NOT compute PnL or metrics

---

### 5. Stage‑2 Compiler (Metrics)
- Consumes Stage‑1 artifacts only
- Computes all performance and risk metrics
- Buy & Hold is contextual, not competitive

No execution logic is permitted here.

---

### 6. Stage‑3 Compiler (Aggregation)
- Combines results across runs
- Produces comparison tables
- Never recomputes metrics

---

## What Trade_Scan Will Never Do

- Place live trades
- Schedule or automate runs
- Infer missing parameters
- Modify validated engines
- Blend execution and analytics

---

## Typical Workflow

1. Write / update directive
2. Run Preflight
3. Execute Stage‑1 (engine)
4. Compile Stage‑2 metrics
5. Aggregate in Stage‑3
6. Review results
7. Decide next hypothesis

---

## Mental Model

> **Trade_Scan is a laboratory, not a machine.**  
> Every run is intentional, inspectable, and reproducible.

---

## Status

- Engine v1.2.0: Generic, plugin-based, locked
- Preflight: Authoritative, locked
- Reporting Pipeline: Stable

This document is for **orientation only** and does not override SOPs.
