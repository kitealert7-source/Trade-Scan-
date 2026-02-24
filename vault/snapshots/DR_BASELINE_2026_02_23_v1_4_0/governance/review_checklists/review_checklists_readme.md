# Review Checklists — README

## Purpose

This folder contains **human review checklists** used **after** Trade_Scan has completed execution and results have been emitted.

These checklists exist to support **deliberate human judgment**, not system enforcement.

They help answer one question:
> *“Before I trust, act on, or build further on these results — what should I consciously verify?”*

---

## What These Checklists Are

- Aids for **slow, reflective human review**
- Memory of **lessons learned** during real research
- Protection against:
  - overfitting
  - confirmation bias
  - regime misinterpretation
  - false generalization

They are intentionally **judgment-based**, not mechanical.

---

## What These Checklists Are NOT

These checklists are **not**:
- SOPs
- invariants
- execution rules
- agent instructions

They must **never**:
- block a run
- invalidate results
- trigger re-execution
- modify artifacts
- override SOPs or invariants

---

## When to Use Them

Use these checklists:
- **After** `RUN_COMPLETE`
- **After** SOP_OUTPUT has emitted results
- **Before** accepting conclusions or forming convictions

They apply to:
- new indicators
- new scanners
- new signals
- novel research constructs

---

## How This Folder Evolves

This folder is expected to **grow slowly over time**.

Add a checklist when:
- a human mistake is discovered
- a bias is recognized in hindsight
- a misleading success is understood

Do **not** add items preemptively or theoretically.

Experience-driven growth only.

---

## Graduation Rule (Important)

If a checklist item becomes:
- fully objective
- repeatable
- enforceable by code

Then it **does not belong here anymore**.

It must graduate to:
- an SOP (if procedural), or
- an invariant (if non-negotiable)

---

## Authority Reminder

Authoritative behavior for Trade_Scan is defined by:
- `Trade_Scan_invariants.md`
- `SOP_TESTING.md`
- `SOP_OUTPUT.md`

If any checklist conflicts with those documents, **the checklist is wrong**.

---

**End of Review Checklists README**

