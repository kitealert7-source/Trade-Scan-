# Signal ABI & Execution Reconciler (XR) — Responsibility & Stability Design

> **Type:** read-only design reference. It defines **responsibilities, boundaries, and stability
> invariants** for a research/signal/execution separation. It is **not** an implementation plan, **not**
> a rewrite, **not** a v2 proposal, and it authorizes no change. Freeze-compatible (analysis only).
>
> **Method:** this design is *not invented from scratch* — it is **abstracted from the contract the
> system already runs in production** (the LOCKED basket bridge, `TS_Execution/bridge/bridge.py`,
> locked 2026-06-06) and generalized to a reference model. Where the current system conforms or
> deviates is stated descriptively, never prescriptively.
>
> **Terminology (per request):** **RE** = Research Engine (`engine_dev` compute + the research-side
> signal substrate). **Signal ABI** = the stable contract surface between RE and XR. **XR** = the
> Execution Reconciler (the broker-facing consumer; runs NO compute). Used consistently throughout.
>
> Companion / upstream: [`ENGINE_EVOLUTION_AUDIT.md`](ENGINE_EVOLUTION_AUDIT.md) (the dependency map +
> burden quantification this design rests on), [`UNIFIED_ENGINE_AUTHORITY_PLAN.md`](UNIFIED_ENGINE_AUTHORITY_PLAN.md),
> [`V1_5_10_CANONICAL_FLIP_DESIGN.md`](V1_5_10_CANONICAL_FLIP_DESIGN.md). Related:
> [`project_live_basket_v0`], `[[immutable-deployment-descriptors]]`.

---

## 1. The model in one line

> **RE decides; the Signal ABI carries the decision; XR makes the broker match it.** The stable object
> is the *contract*, not engine parity. RE may evolve and even intentionally diverge behind that
> contract; XR never imports RE.

This is exactly what the basket fleet does today. This document states it as a reusable responsibility
model and pins the invariants that make it work.

---

## 2. The three roles and their responsibilities

| Role | Owns | Must NOT own | Concrete instance today |
|---|---|---|---|
| **Research Engine (RE)** | All signal *generation* (indicators, regime labels, strategy logic, basket recycle rules); all *backtest* fill/PnL simulation; deciding the **desired target/position**; producing the live target via a streaming producer that is **proven equal** to the backtest | Broker connectivity; order lifecycle; reconciliation; anything that must keep running when research is mid-edit | `engine_dev/*` + `engines/*` + `tools/recycle_rules/*` + `tools/live_basket/basket_producer.py` |
| **Signal ABI** | The **stable, versioned, fail-closed contract** between RE and XR: the *intent* (target/position) + liveness + an audit channel. The file format **is** the interface | Any executable logic; any import of RE or XR internals; any *fill price* or strategy *state* | `TS_Execution/bridge/bridge.py` (LOCKED 2026-06-06); `descriptor.json` (immutable deployment descriptor) |
| **Execution Reconciler (XR)** | Reading the contract; reading broker truth; **reconciling** broker→target; order placement/close; demo/risk guards; execution journaling | Signal generation; regime/indicator compute; knowledge of *why* a target is what it is; any RE import | `TS_Execution/src/basket_shim.py` + `bridge/reconcile.py` + `broker`/`basket_exec` (stdlib-only) |

**Design rule:** responsibilities are assigned so that **the only thing crossing the boundary is
data** (the contract), never code. XR's correctness must be checkable without RE present.

---

## 3. What must remain stable vs. what may evolve freely

The whole point of the separation is to make these two columns independent.

| May evolve **freely** (RE side) | Must remain **stable** (the Signal ABI) |
|---|---|
| Engine compute version (`engine_dev/v1_5_X`); fill/PnL/exit mechanics; spread/charge model | The **contract schema** (`schema_version`, field set, validation rules) |
| Indicators, regime model internals, recycle-rule logic, signal thresholds | The **semantics of `state`** (FLAT/IN) and **`legs` as position-truth** |
| Which strategy/basket is deployed; parameters; the research promotion machinery (§3.1 of the audit) | The **liveness channel** being *separate* from the target (heartbeat ≠ target age) |
| The producer's internal implementation (as long as output-equivalence holds) | **Monotone `seq`, gaps-allowed, current = max-seq** ordering semantics |
| Engine *naming/stamping* behind the ABI re-export seam | **Reserved evolution slots** (e.g. `epoch`) so future capability needs no schema break |
| XR's broker adapter, retry policy, journaling format (XR-internal) | **Fail-closed validation** (`ContractError`) on every read/write |

**Key consequence — "minimize parity":** because the stable object is the *output*, the **only parity
requirement is internal to RE**: the live producer's target must equal the backtest's target (locked
by `test_basket_producer_equiv.py`). **XR has no parity requirement at all** — it cannot drift from RE
because it never computes anything RE computes. This is the cheapest possible parity surface: one
equivalence test on the research side, zero cross-repo parity.

---

## 4. The Signal ABI specification (abstracted from the live contract)

The basket bridge is the worked instance. The *generalizable invariants* it embodies:

**4.1 Carry intent, never fill.** The contract states the **desired position** (`state` + `legs`),
not a price or a fill. Verified: `bridge.py:110-138` — `Target{basket_id, seq, state, legs, epoch,
bar_ts, emitted_at, schema_version}`; `Leg{symbol, side, lot}` (`:68-84`). A contract that named a
fill price would re-import the "close-entry is backtest fiction" hazard
(`[[feedback_close_entry_is_backtest_fiction]]`). **Invariant: the contract speaks position/intent;
the broker owns the fill.**

**4.2 One source of truth, no redundant interpretation.** `bridge.py:14` — *"NO `direction` field —
the legs ARE the position … derived when needed, never stored."* Redundant fields drift; derived
fields don't. **Invariant: store the minimal truth; derive the rest.**

**4.3 Liveness is a separate channel.** `bridge.py:21-23` — heartbeat (`runner_heartbeat.json`) is
updated every cycle even when the target is unchanged, so XR never infers "producer alive" from "target
fresh." **Invariant: never overload one signal with two meanings (target-change ≠ liveness).**

**4.4 Append-only, monotone, gap-tolerant ordering.** `bridge.py:16` — `seq` strictly increasing, gaps
allowed, current target = max-seq. XR tolerates missed emissions without desync. **Invariant: ordering
is recoverable from the stream alone.**

**4.5 Reserved evolution slots.** `bridge.py:10-13,118,130-131` — `epoch` is reserved and hard-guarded
to 0 in V0, "so a future basis-reset … needs no schema / broker-tag migration." **Invariant: pre-carve
space for the next capability so evolution doesn't break the schema.**

**4.6 Fail-closed at the boundary, independent of RE.** `bridge.py:54-55,75-81,123-133` — every
construction/parse validates and raises `ContractError`; an out-of-contract target is rejected, not
guessed. This guard lives **with the contract**, not in RE. **Invariant: the contract validates itself;
a malformed signal stops XR, it does not degrade it.**

**4.7 Stdlib-only, importable by both sides without coupling.** `bridge.py:6-8` — "STDLIB-ONLY by
design, so the reconcile core and these schemas port to the … shim without a Trade_Scan dependency."
Both sides *conform to* the contract; neither *imports* the other. **Invariant: the contract module has
no dependency that re-creates the coupling it exists to remove.**

> These seven invariants are the design. They are not basket-specific accidents; they are the reason
> the basket XR achieves the audit's "strong isolation." Any Signal ABI — for any instrument family —
> that holds all seven inherits the same isolation. (Whether a *stateful single-asset* contract can
> hold 4.1/4.2 while still expressing dynamic exits is the open question — see §8, R1/R2 of the audit.)

---

## 5. Operational isolation over code reuse — how the model delivers it

The brief asks to **favor isolation over reuse**. The model does so structurally, not by convention:

- **Structural firewall, not a policy.** XR's isolation is enforced by *what it can import*
  (stdlib + XR-local + the stdlib-only contract) — `basket_shim.py:36-54`. There is no `engine_abi`,
  no `engine_dev`, no `recycle_rules` on XR's import graph, so an RE change *cannot* reach XR through
  code. Compare the single-asset path, whose isolation rests on a *runtime allow-list*
  (`phase0_validation.py:30`) guarding a *real cross-repo import* (`main.py:123`) — a policy guard, not
  a firewall.
- **Reuse is confined to one side of the boundary.** The model does **not** forbid code reuse — it
  *locates* it. RE reuses freely *within* RE (the live producer reuses `basket_pipeline`/
  `basket_runner`, guaranteeing parity by construction). XR reuses freely *within* XR. The boundary
  carries no shared code. This is "favor isolation over reuse" read precisely: **reuse where it cannot
  couple the deployment surfaces; never across the RE↔XR seam.**
- **Divergence is safe by design.** Because RE↔XR share only the contract, RE may run a different
  engine version than the live system assumes — exactly the *intended* research(v1.5.10)/live(v1.5.9)
  split (`UNIFIED_ENGINE_AUTHORITY_PLAN.md` §Scope). Under the contract model that divergence is
  invisible to XR; under the shared-compute model it is governed only by the allow-list.

---

## 6. Fail-closed preservation (a hard constraint, enumerated)

The separation must **never** weaken fail-closed behavior. The model preserves it at four independent
layers, each owned by the correct role:

| Layer | Owner | Mechanism | Evidence |
|---|---|---|---|
| RE engine identity | RE | convergence gate + stamp==loaded-module guard | `tests/test_engine_identity_convergence.py`; `run_stage1.py:410-420` |
| RE ABI surface | RE | manifest match at import → `RuntimeError` | `engine_abi/*/__init__.py:65-84` |
| Signal ABI | Contract | `ContractError` on any schema/state/seq/tag violation | `bridge.py:54-55,123-133` |
| XR admission | XR | fail-closed version allow-list; demo/risk guards | `phase0_validation.py:30`; `basket_live_broker` demo guard |

**Design rule:** a Signal ABI must *add* a fail-closed layer (the contract), never *replace* an
existing one. In particular, a contract-based path must carry an identity/parity check on the **producer**
equivalent to the convergence gate it relaxes — otherwise decoupling trades a guarded cross-repo import
for an *unguarded* duplicate compute (audit R4), which is strictly worse.

---

## 7. Where the current system conforms / deviates (descriptive)

- **Basket fleet — conforms fully.** All seven §4 invariants hold; isolation is structural; promotion
  is single-sided (RE only). This is the reference instantiation.
- **Single-asset live — deviates (by history, not error).** It predates the bridge model and uses
  shared-compute (cross-repo import of the RE signal substrate). It is **not wrong** — it is the older
  Model-A path, fail-closed via the allow-list, and currently stood down. It simply does not get the
  structural firewall.
- **The latent enabler.** The signal substrate single-asset live actually consumes
  (`apply_regime_model`, `StrategyProtocol`, `ContextView`, concurrency) is *already* version-agnostic
  (`engines/*`), so the "stable object" for single-asset largely exists — it is just *imported as code*
  rather than *consumed as a contract*. Naming it as a contract would convert a policy-guarded coupling
  into a structural one. (Stated as a property, **not** a recommendation to do so.)

---

## 8. Long-term maintainability properties (why this model ages well)

- **Independent release cadences.** RE engines version on research time; XR versions on broker/ops time;
  the contract versions rarely (schema_version) and with reserved slots (`epoch`) to avoid breaks.
- **Bounded blast radius.** An RE bug cannot reach a contract-model XR through code; a broker/adapter
  bug cannot reach RE. Each side is debuggable in isolation.
- **Cheap parity.** One equivalence test per producer family; no cross-repo parity matrix.
- **Recovery-friendly.** XR depends on *files in the shared state store* (`TradeScan_State/…`) +
  immutable descriptors (`[[immutable-deployment-descriptors]]`), not on the research working tree's
  current checkout — removing a class of cold-start coupling.

---

## 9. Boundary conditions & non-goals (explicit)

- **Not a migration plan.** This document does **not** propose converting single-asset to a Signal ABI,
  does not sequence work, and authorizes nothing. Any such move is *conditional* on single-asset live
  becoming active again and on resolving the audit's **R1 (contract-richness creep)** and **R2
  (fill-semantics divergence)** — the open design risks for *stateful* strategies.
- **Do not fatten the contract.** The basket contract's power is its thinness (position-truth only).
  A single-asset contract that encoded dynamic exit *state* would forfeit invariants 4.1/4.2 and the
  isolation that follows. If a future contract cannot stay thin, the shared-compute model may remain
  the right choice for that family — the model does not assume C dominates everywhere.
- **Preserve all four fail-closed layers (§6).** Non-negotiable. Decoupling may add a layer; it may
  never remove one.
- **One-directional authority.** RE's engine authority is Trade_Scan-internal and must never drive the
  live ABI (`engine_authority.py:17-18`); XR owns its own admission. The Signal ABI does not change
  this — it *reinforces* it (the contract, not RE, is what XR trusts).

---

## 10. Evidence index (read this session)

- **Signal ABI (live contract):** `TS_Execution/bridge/bridge.py:1-170` — LOCKED 2026-06-06; stdlib-only
  (`:6-8`); `Target`/`Leg` (`:68-84,110-138`); intent-not-fill; no `direction` (`:14`); `epoch` reserved
  (`:10-13,118,130-131`); `seq` monotone/gap-tolerant (`:16`); heartbeat separate (`:21-23`);
  `ContractError` fail-closed (`:54-55,123-133`).
- **XR (engine-free reconciler):** `TS_Execution/src/basket_shim.py:1-69` (imports: broker, basket_exec,
  basket_live_broker, basket_readiness, bridge.*, config.path_config — no engine).
- **RE producer (parity by construction):** `Trade_Scan/tools/live_basket/{basket_producer.py,
  bridge.py, driver.py}`; equivalence lock `tools/live_basket/test_basket_producer_equiv.py`.
- **RE substrate (already version-agnostic):** `engines/{regime_state_machine,protocols,concurrency_gate}.py`;
  ABI seam `engine_abi/v1_5_9/__init__.py:20,39-56,65-84`.
- **Fail-closed layers:** `tests/test_engine_identity_convergence.py`; `tools/run_stage1.py:410-420`;
  `engine_abi/*/__init__.py:65-84`; `TS_Execution/src/phase0_validation.py:30`.
- **Authority boundary:** `config/engine_authority.py:17-18`; `UNIFIED_ENGINE_AUTHORITY_PLAN.md` §Scope.

*End — read-only design reference. No code, governance, or pipeline state was modified.*
