# INVARIANT_PROPOSALS.md

Stable, append-only ledger for codified system invariants that originate as
proposals and graduate to implementation. Code and memory can cite entries
here by ID — unlike `SYSTEM_STATE.md`, this file is NOT regenerated.

**Rules:**
- Entries are append-only. Never delete or renumber.
- Status transitions: `PROPOSED → IMPLEMENTED | REJECTED`
- Each entry must name the enforcement artifact (test, gate, lint rule, or
  code comment) that makes the invariant machine-checkable.
- Code comments, RESEARCH_MEMORY, and auto-memory should cite this file
  by entry ID (e.g. `INVAR-001`), not `SYSTEM_STATE.md`.

---

## INVAR-001 — Leg-strategy dispatch completeness

**Proposed:** 2026-06-01  
**Status:** IMPLEMENTED  
**Enforcement:** `tools/run_pipeline.py::LEG_STRATEGY_DISPATCH` + `CONTINUOUS_HOLD_RULES`; runtime `LegDispatchError`  

Every recycle rule registered in `governance/recycle_rules/registry.yaml` must
appear in exactly ONE of:
- `LEG_STRATEGY_DISPATCH` — proposal-based legs (fire entry signals)
- `CONTINUOUS_HOLD_RULES` — always-open legs (rule handles the mechanic)

A registered rule absent from both raises `LegDispatchError` at dispatch
time — the failure is loud, not a silent fallthrough. This invariant was
proposed after the ZBND silent-fallthrough bug (2026-06-01) where an unrouted
rule produced no trades and no error.

**See also:** `[[mechanism-port-integration-points]]` memory entry.

---

## INVAR-002 — Corpus prune must not delete artifacts other systems depend on

**Proposed:** 2026-06-19  
**Status:** PROPOSED  
**Enforcement:** (proposed) a pre-delete guard in the corpus-prune tool that, for each
candidate path, refuses deletion if the artifact is referenced by a live promotion descriptor
(`strategy_pool/*/descriptor.json` `directive_id` / `run_id`) or required by a golden test
(`tests/.../test_promote_basket.py` EXEMPLARS run receipts). Protected Infra (invariant 6):
plan + approval before implementation — do NOT self-apply.

The corpus prune is a RESEARCH-lifecycle operation, but its delete set is not partitioned by who
depends on the artifact. The 2026-06-16 prune deleted all 5 live baskets' directives from
`backtest_directives/completed/` AND the 3 promotion run receipts, with no cross-check. Three
dependency classes must be distinguished before any prune:

- **Runtime dependencies** — artifacts a LIVE deployment reads at cold-start (directives).
  *Mitigated 2026-06-19* by `[[immutable-deployment-descriptors]]` (the producer now reads the
  prune-immune `strategy_pool/<ID>/directive.txt`), so the live path no longer breaks — but the
  prune still has no awareness of the dependency.
- **Reproducibility dependencies** — artifacts a golden / anti-drift test needs to reproduce a
  promotion (`runs/<run_id>/manifest.json` receipts). *Still exposed*: the receipt loss left
  `test_at_least_one_exemplar_reproducible` permanently red.
- **Research dependencies** — corpus rows / dirs the prune legitimately manages. Freely prunable.

The guard must protect the first two classes while leaving the third prunable. Catching only the
runtime class (as this session's fix did) is insufficient — the reproducibility class proves the
gap remains.

**See also:** `[[immutable-deployment-descriptors]]`, `[[corpus-prune-2026-06-16]]`,
FAILURE_PLAYBOOK "Live Basket Directive Loss / Config Drift".

---

## INVAR-003 — OctaFX cost model is spread-only (financing = 0)

**Proposed:** 2026-06-21  
**Status:** IMPLEMENTED  
**Enforcement:** documented constant `OVERNIGHT_FINANCING = 0` in
`engines/execution_fill.py` (the shared direction-aware fill helper imported by
`basket_runner` + the recycle rules) + the `RESEARCH_MEMORY.md` 2026-06-21
"OctaFX is swap-free" decision (read at session start). Soft lock (documentation
+ session-start doctrine), not a runtime gate — no swap term exists to assert
against today.

OctaFX/Octa is swap-free — it charges NO overnight swap/financing on any account
or instrument (FX, indices, metals, crypto, stocks), with no holding-time limit
and no admin fee (Sharia-compliant default, all countries, since 2022-06;
owner-confirmed 2026-06-21). The complete OctaFX backtest cost model is therefore
the embedded direction-aware spread (+ slippage, currently unmodelled); the
financing term is structurally zero.

No swap / carry / financing term may be added to any OctaFX fill, cost model, or
P&L path without a documented broker-policy change. **This invariant is
SUBORDINATE to canonical broker terms:** if OctaFX's swap-free policy ever
changes, the broker terms govern and this invariant is revised accordingly.

Verified 2026-06-21: the live cost layer applies spread only — no financing term
exists in `engines/execution_fill.py`, `tools/basket_runner.py`,
`tools/recycle_rules/pine_ratio_zrev_v1.py`, or the frozen single-asset engine
(`engine_dev/universal_research_engine/v1_5_10/`). Codifying this therefore
changed no behaviour (documentation-only; no engine-flip / ABI governance).

**See also:** vault `sources/octafx-swap-free-cost-model.md`,
`[[reference_octafx_backtest_cost_model]]`,
`[[reference_octafx_uniform_ask_spread_uncharged]]`, RESEARCH_MEMORY.md
2026-06-21.

---

## INVAR-004 — Directive metadata-key registration completeness

**Proposed:** 2026-06-24
**Status:** PROPOSED  *(plan only — NOT implemented this session; Protected-Infra, needs plan+approval per Invariant #6)*
**Proposed enforcement:** extend `tests/test_informational_keys_superset.py` (today asserts only `INFORMATIONAL_KEYS ⊇ NON_SIGNATURE_KEYS`) into a 4-way consistency gate, or a new `tests/test_directive_metadata_key_registries_agree.py`.

**Motivation (observed 2026-06-24):** the rerun tool injects `test.rerun_of` (F1, 2026-06-14) on the author's assumption that "it's under `test:`, so NON_SIGNATURE_KEYS tolerates it." The assumption was false — the admission validators check **individual** `test:` sub-keys — and the field was registered in **0 of its 4 surfaces**, so a single unregistered metadata key was rejected by **four admission gates in sequence**, each surfacing only at a pipeline run (5 failed PSBRK-P17 reruns before success). The lone existing invariant test covered 2 of the 4. This is the **same failure class as Tax C** (one concept registered in N places with no agreement check) but in the admission path instead of engine dispatch.

**The invariant:** a directive key that is *non-strategy metadata* (provenance / audit / identity — `repeat_override_reason`, `rerun_of`, `signal_version`, …) must be registered **consistently across all four admission surfaces**, or none:
1. `tools/canonical_schema.ALLOWED_NESTED_KEYS["test"]` — Stage -0.25 accepts it.
2. `tools/directive_schema.NON_SIGNATURE_KEYS` — inert to the signature hash (Stage -0.35).
3. `governance/semantic_coverage_checker.INFORMATIONAL_KEYS` — excluded from the PREFLIGHT "declared but not referenced" coverage check (already required ⊇ NON_SIGNATURE_KEYS).
4. `tools/directive_diff_classifier._COSMETIC_KEYS`/`_IDENTITY_KEYS` — a delta in it is not mis-read as structural (Stage -0.21).

The gate asserts the metadata-key sets agree; a key present in one but missing from another **fails at commit time** — instead of as a sequence of opaque runtime admission failures. Cheap (a set-membership test) vs the cost (a multi-run debugging marathon per half-integrated field).

**Out of scope of the proposal:** the separate question of whether `rerun_of` should be injected at all (it is write-only/redundant). The invariant is about *consistency*, not *which keys exist*.

---

## INVAR-005 — Single monetary model: all price→USD conversion consumes the MT5 calibration

**Proposed:** 2026-07-02  
**Status:** IMPLEMENTED  
**Enforcement:** `tools/capital/capital_broker_spec.py::validate_monetary_consistency` — HARD gate
(raises, "Refusing execution") wired into all three spec-load paths (`_load_broker_spec_cached`,
`load_broker_spec`, and `tools/run_stage1.py::load_broker_spec`). Negative-tested: re-introducing
the SPX500 defect in-memory is refused; full 31-spec sweep passes.

No component may independently compute monetary value from broker specifications.
The flow is:

```
Broker YAML → MT5 calibration (usd_pnl_per_price_unit_0p01 = tick_value/tick_size × 0.01)
            → canonical monetary representation
            → ALL consumers
```

Never per-component models (`run_stage1` → contract_size; `capital_wrapper` → calibration;
bootstrap → deprecated dynamic path). Two components pricing the same trade differently is a
silent-divergence class, not a tolerable approximation.

Enforcement mechanics: top-level `contract_size` (profit-ccy/pt/lot) must agree with the
calibration via implied FX = `usd_per_pu_per_lot / contract_size`, checked against wide
per-currency sanity bands (tolerate FX drift; catch scale errors). Specs without a calibration
block pass through (no authoritative reference).

**Origin (2026-07-02):** dual monetary models produced (a) a 10× Stage-1 $-inflation on every
SPX500 run (`contract_size: 10` vs MT5-verified $1/pt/lot — repaired runs e5bb72dd / 66462f1d
confirmed exact 10×: $404.99→$40.46, $164.37→$16.41), and (b) a 12.6× mispricing in the
Section-14 block bootstrap (deprecated dynamic path vs canonical static; fixed to consume
`get_usd_per_price_unit_static`, parity-verified 1614.34 == 1614.34 vs the wrapper's own run).

**See also:** RESEARCH_MEMORY 2026-07-02 infrastructure entry; `feedback_mechanism_port_check`
(mechanism must exist at EVERY integration point).
