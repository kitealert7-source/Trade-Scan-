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
