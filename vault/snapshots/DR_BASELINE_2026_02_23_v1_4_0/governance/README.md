# Trade_Scan — Overview

## NOTE ON AUTHORITY (IMPORTANT)

This document is **descriptive only**.

Authoritative system behavior is defined exclusively by:

- `trade_scan_invariants_state_gated.md`
- `SOP_TESTING.md`
- `SOP_OUTPUT.md`

If any inconsistency exists between this README and the documents above, **this README is wrong**.

---

## What Trade_Scan Is

**Trade_Scan** is a **research and backtesting system** designed to help humans:

- formulate trade ideas
- validate logic and assumptions
- stress-test ideas against economic reality
- review results in a structured, disciplined way

Trade_Scan operates strictly in **analysis mode**.
All outputs are **advisory** and **non-operational**.

---

## What Trade_Scan Is NOT

Trade_Scan is **not** a trading system.

It does **not**:

- place trades
- manage orders or positions
- connect to brokers or exchanges
- approve or promote strategies
- automate go-live decisions

Any system that executes trades is **out of scope**.

---

## High-Level System Shape

At a high level, Trade_Scan works as follows:

1. A human provides an explicit research directive
2. Trade_Scan executes a deterministic research run
3. Economic validation is applied using simulated capital
4. Results are emitted for human inspection
5. Trade_Scan stops

There is no autonomy, looping, or self-directed exploration.

---

## Governance Structure

Trade_Scan is governed by a strict hierarchy:

```
trade_scan_invariants_state_gated.md   → system laws (non-negotiable)
SOP_TESTING.md             → execution & validation procedure
SOP_OUTPUT.md              → results emission & human analysis
agent_rules/               → agent behavior enforcement
README.md                  → orientation only
```

- Invariants define what must **never** be violated
- SOPs define **how** work is performed
- Agent rules constrain **agent behavior**

---

## Data & Execution Boundaries

- Trade_Scan consumes **governed, research-grade market data** (read-only)
- All economics are modeled using **simulated capital**
- There is **no technical integration** with any trading or execution system

Any movement of ideas across system boundaries is **manual and human-only**.

---

## Results & Human Analysis

Trade_Scan produces artifacts intended for human reasoning:

- structured reports
- comparative summaries
- exploratory research views

Results are organized by artifact authority:

- Authoritative execution artifacts represent execution truth
- Derived presentation artifacts support structured human review
- Any exploratory analysis is non-authoritative and advisory only

Human judgment is encouraged, but it never feeds back into execution automatically.

---

## Intended Use

Trade_Scan exists to support:

- disciplined research
- repeatable backtesting
- clear separation between analysis and action

It is intentionally constrained to prevent:

- accidental automation
- authority creep
- execution coupling

---

## Final Note

If a proposed change would make Trade_Scan:

- more autonomous
- more authoritative
- closer to execution
- harder for humans to reason about

then that change likely belongs **outside** Trade_Scan.

---

**End of README**
