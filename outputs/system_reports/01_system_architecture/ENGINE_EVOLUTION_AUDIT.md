# Engine Evolution Audit — Research↔Execution Separation

> **Type:** read-only architecture audit. **No** implementation plan, **no** rewrite, **no** v2
> proposal. Produces analysis only. Freeze-compatible (analysis, not infra change).
>
> **Question audited:** *Can long-term evolution eliminate the need to promote research engines
> twice (research → execution), while preserving operational isolation?*
>
> **Authored** 2026-06-24 from a read-only multi-surface code sweep (research-compute layer +
> execution layer + the live signal bridge). Companion: [`SIGNAL_ABI_AND_XR_DESIGN.md`](SIGNAL_ABI_AND_XR_DESIGN.md).
> Upstream context (do **not** contradict — this audit *composes* with them, it does not supersede):
> [`UNIFIED_ENGINE_AUTHORITY_PLAN.md`](UNIFIED_ENGINE_AUTHORITY_PLAN.md) (selection layer, Trade_Scan-internal),
> [`V1_5_10_CANONICAL_FLIP_DESIGN.md`](V1_5_10_CANONICAL_FLIP_DESIGN.md) (compute/charge layer).
>
> **Terminology (per request):** **XR** = the execution-side component. **RE** = the research
> engine (the `engine_dev` compute + research-side signal substrate). **Signal ABI** = a stable
> contract surface between RE and XR. These names are used consistently below.
>
> **Source-grounding:** every load-bearing claim cites a file:line read **this session**. This is an
> audit of *code structure*, which is directly verifiable by reading the code — so its conclusions are
> not subject to the pipeline-authoritative gate (Invariant #31), which governs *backtest* claims.
> Inferences (vs. verified facts) are marked **[inferred]**.

---

## 0. Executive verdict (read this first)

**The architecture already contains *both* answers to the question — one per deployment path.** The
double-promotion burden is therefore **asymmetric, not uniform**, and the premise "engines are
promoted twice" is true for one path and *already false* for the other:

| Path | XR coupling to RE | Promoted twice? | Operational isolation |
|---|---|---|---|
| **Basket (live fleet today)** | **CONTRACT-ONLY** — XR reads a file; imports **zero** engine code | **No** — engine promoted **once** (research side); XR pairs via a locked contract | **Strong** (XR is stdlib-only; fail-closed on contract) |
| **Single-asset (stood down)** | **SHARED-COMPUTE** — XR imports the RE signal substrate live, cross-repo, from the running Trade_Scan tree | **Yes** — engine must be canonical in Trade_Scan **and** admitted to XR's pin/allow-list | **Adequate** (fail-closed allow-list + convergence gate), but weaker |

**So the question is not "can it be done" — the basket fleet proves it can, and is in production. The
real questions are (a) whether to generalize the basket model to single-asset, and (b) whether the
single-asset double-promotion burden is large enough to justify that.** This audit finds the burden
is **real but currently latent** (the research/live version split is *intentionally* deferred, so the
tax is paid only when single-asset live is actively advanced — and single-asset live is presently
stood down) and that the single-asset coupling, while *structurally* heavy, is *semantically* thin
(6 symbols, 5 of them version-agnostic). The honest conclusion is in §6–§7.

---

## 1. The current dependency map

### 1.1 The research-compute layer (Trade_Scan-internal)

A clean four-tier stack. The seam that matters for this audit is **tier 2 ↔ tier 4**: a *named,
manifest-governed ABI surface* sitting over *freely-versioned compute*.

```
  CONSUMERS      tools/basket_runner.py  (static: from engine_abi.v1_5_10 import …)   [basket research]
                 tools/run_stage1.py     (dynamic: engine_dev…{active}.main)          [single-asset research]
                        │
  ABI SURFACE    engine_abi/v1_5_9/   ─┐  pure re-export packages, manifest-verified at import
                 engine_abi/v1_5_10/  ─┤  (fail-closed on drift: RuntimeError)
                        │              │  BOTH currently re-export engine_dev.v1_5_10  ← note (a)
  SHARED SVCS    engines/  { regime_state_machine (apply_regime_model, REGIME_CACHE_DIR),
                 (version-   protocols (StrategyProtocol, ContextViewProtocol),
                  AGNOSTIC)  concurrency_gate (admit, validate_cap), execution_fill, filter_stack }
                        │
  COMPUTE        engine_dev/universal_research_engine/{v1_5_3 … v1_5_10}/
                 { evaluate_bar, execution_loop (ENGINE_VERSION="1.5.10", FROZEN 2026-06-17),
                   execution_emitter_stage1, stage2_compiler, main }
```

- **note (a):** `engine_abi/v1_5_9/__init__.py:20` and `engine_abi/v1_5_10/__init__.py:25` *both*
  import compute from `engine_dev.universal_research_engine.v1_5_10`. The ABI *package name* (`v1_5_9`)
  is decoupled from the *compute version* it re-exports (`v1_5_10`). This is the seam — and a live
  example of "stamp ≠ compute" being managed deliberately (`config/engine_authority.py:8-20`,
  doctrine `[[engine_identity_is_compute_not_stamp]]`).
- **The 16-symbol ABI surface** (`engine_abi/v1_5_9/__init__.py:39-56`): `evaluate_bar`, `ContextView`,
  `BarState`, `EngineConfig`, `resolve_engine_config`, `resolve_exit`, `finalize_force_close`,
  `ENGINE_ATR_MULTIPLIER`, `run_execution_loop`, `ENGINE_VERSION`, `ENGINE_STATUS`, `apply_regime_model`,
  `StrategyProtocol`, `admit`, `validate_cap`, `REGIME_CACHE_DIR`.
- **Signal vs. engine is already separated for baskets:** the *signal decision* lives in the recycle
  rule (`tools/recycle_rules/pine_ratio_zrev_v1.py` — computes `pine_zrev_signal`, owns LIQUIDATE/
  EQUILIBRIUM/TIMESTOP exits); the *fill/PnL mechanics* live in the engine (`evaluate_bar`). They are
  orthogonal layers. This matters: the thing XR actually needs live is the **signal**, not the fill
  simulator.

### 1.2 The two live deployment paths (the crux)

**Basket live path — CONTRACT-ONLY (the file-bridge):**

```
  RESEARCH SIDE (Trade_Scan)                    │  CONTRACT          │  EXECUTION SIDE (TS_Execution)
  tools/live_basket/basket_producer.py          │                    │  src/basket_shim.py
    imports recycle_strategies, basket_pipeline, │  target.jsonl      │    imports broker, basket_exec,
    live_basket.driver.StreamingBasketRunner     │  (state+legs+seq)  │    bridge.*, config.path_config
    → runs RE compute, emits target  ───────────▶│  + heartbeat.json  │──▶ reads target, reconciles
                                                  │  + executions.jsonl│    broker→target. NO engine import.
  parity locked by test_basket_producer_equiv.py │  LOCKED 2026-06-06 │    stdlib-only.
```

The engine lives **entirely on the research side**. XR is engine-free. Verified:
`src/basket_shim.py:36-54` imports only `broker`, `basket_exec`, `basket_live_broker`,
`basket_readiness`, `bridge.*`, `config.path_config` — **no `engine_abi`, no `engine_dev`, no
`recycle_rules`, no `indicators`.**

**Single-asset live path — SHARED-COMPUTE (cross-repo import):**

```
  EXECUTION SIDE (TS_Execution) imports the RE signal substrate FROM the live Trade_Scan tree:
    portfolio.yaml: research_root: ../Trade_Scan,  abi_version: v1_5_9
    portfolio_loader.py:75,316 — validates ../Trade_Scan is a real repo + engine_dev/<ver> present
    main.py:123      from engine_abi.v1_5_9 import ContextView, apply_regime_model
    execution_adapter.py:39-40  admit, validate_cap
    pipeline.py:130             REGIME_CACHE_DIR ; run_on_bar_close() calls apply_regime_model() per bar
    strategy_loader.py:154      StrategyProtocol  (loads strategy.py via importlib, validates interface)
```

XR **runs the RE signal substrate live**: every bar it calls `apply_regime_model(df)` then the
strategy's `check_entry`/`check_exit` against engine-computed context. The fill is the broker's (not
`evaluate_bar`). So even here, XR does **not** run the backtest fill/PnL engine — only the
*signal-generation half*.

---

## 2. Coupling inventory (quantified, classified)

Every XR→RE dependency, classified **SHARED-COMPUTE** (XR executes RE code) / **CONTRACT-ONLY** (XR
consumes a data/file contract) / **CONFIG-PIN** (XR names a version string but does not execute it).

| # | Site (TS_Execution) | Dependency | Class | Evidence |
|---|---|---|---|---|
| 1 | `src/main.py:123` | `engine_abi.v1_5_9: ContextView, apply_regime_model` | **SHARED-COMPUTE** | regime computed per bar; ContextView subclassed (`main.py:125`) |
| 2 | `src/execution_adapter.py:39-40` | `engine_abi.v1_5_9: admit, validate_cap` | **SHARED-COMPUTE** | concurrency gating in dispatch |
| 3 | `src/pipeline.py:130` | `engine_abi.v1_5_9: REGIME_CACHE_DIR` | **SHARED-COMPUTE** | regime cache dir; used in `run_on_bar_close` |
| 4 | `harness/replay.py:214` | `engine_abi.v1_5_9: ContextView, apply_regime_model` | **SHARED-COMPUTE** | replay harness (research-parity tool) |
| 5 | `src/strategy_loader.py:154` | `engine_abi.v1_5_9: StrategyProtocol` | **CONTRACT-ONLY** | interface validation of loaded strategy.py |
| 6 | `src/phase0_validation.py:63` | `import engine_abi.<ver>` (existence + `__all__`) | **CONFIG-PIN** | loads to verify, does not call compute |
| 7 | `src/phase0_validation.py:30` | allow-list `_SUPPORTED_ABIS=('v1_5_3','v1_5_9')` | **CONFIG-PIN** | fail-closed version gate |
| 8 | `src/portfolio_loader.py:39` | `EXPECTED_ENGINE_VERSION = "v1_5_9"` | **CONFIG-PIN** | string compare |
| 9 | `src/portfolio_loader.py:316` | `research_root/engine_dev/…/v1_5_9` must exist | **CONFIG-PIN** | startup presence check |
| 10 | `portfolio.yaml:6` | `abi_version: v1_5_9` | **CONFIG-PIN** | the pin of record |
| 11 | `portfolio.yaml:1` | `research_root: ../Trade_Scan` | **CONFIG-PIN** | makes the whole RE repo a runtime dependency |
| — | `src/basket_shim.py` (entire basket path) | `target.jsonl` / `descriptor.json` | **CONTRACT-ONLY** | reads files from `TradeScan_State`; zero engine import |

**Counts:** SHARED-COMPUTE = **4 sites / 6 symbols** (single-asset live only). CONTRACT-ONLY =
strategy-protocol validation + the entire basket bridge. CONFIG-PIN = **6 sites**.

**The sharp finding — the SHARED-COMPUTE surface is semantically thin and mostly version-stable:**
Of the 6 live-imported symbols, **5 originate in the version-agnostic `engines/` package**
(`apply_regime_model`, `REGIME_CACHE_DIR` ← `engines/regime_state_machine.py`; `StrategyProtocol` ←
`engines/protocols.py`; `admit`, `validate_cap` ← `engines/concurrency_gate.py`). Only `ContextView`
comes from versioned `engine_dev/v1_5_10/evaluate_bar`. **None** of the fill/PnL/exit compute
(`evaluate_bar`, `run_execution_loop`, `resolve_exit`, `finalize_force_close`, `EngineConfig`,
`BarState`) ever crosses into XR. So the whole-engine-version pin (`v1_5_9`) is **coarser than the
true coupling**: XR pins a 16-symbol bundle to consume a ~6-symbol, largely version-invariant subset.

---

## 3. The double-promotion burden, quantified

### 3.1 Promotion #1 — research-side canonicalization (within Trade_Scan)

The "make an engine canonical" workflow touches a fixed, gate-enforced set (enumerated from
`UNIFIED_ENGINE_AUTHORITY_PLAN.md §5`, `V1_5_10_CANONICAL_FLIP_DESIGN.md`, and the vault/abi machinery):

- **Code (≈5 files):** `engine_dev/…/<ver>/execution_loop.py` (ENGINE_VERSION/STATUS), the static
  `basket_runner.py:40` import + `:68` literal, `config/engine_authority.py:78-79` (two constants),
  charge sites if direction-aware.
- **Governance (2):** `governance/engine_abi_<ver>_manifest.yaml` (+ `abi_audit --rehash`),
  `engine_dev/…/<ver>/engine_manifest.json`.
- **Vault (1):** `vault/engines/Universal_Research_Engine/<ver>/` (DR snapshot, hash-verified).
- **Gates (3):** convergence gate (`tests/test_engine_identity_convergence.py`), ABI identity test,
  `verify_engine_integrity`.
- **Atomicity:** lands as **one commit**; the convergence gate makes a partial flip *impossible*
  (fail-closed). This is heavy but **bounded, mechanical, and self-protecting**.

### 3.2 Promotion #2 — execution-side admission (into TS_Execution), *single-asset only*

To advance the **single-asset live** engine you must additionally: bump `portfolio.yaml:abi_version`,
extend `_SUPPORTED_ABIS` (`phase0_validation.py:30`), bump `EXPECTED_ENGINE_VERSION`
(`portfolio_loader.py:39`), and guarantee the cross-repo import resolves (the new `engine_abi.<ver>`
and its `engine_dev` compute must be present + importable from the live Trade_Scan tree). Each is
fail-closed, so a mismatch aborts at boot — *correct*, but it is a second, separately-gated admission.

### 3.3 The burden is asymmetric and currently latent

- **Baskets pay promotion #2 = ZERO.** The live fleet's XR (`basket_shim.py`) never imports an
  engine. A new RE engine changes the *target the producer emits*; XR is unaffected by construction.
- **Single-asset pays promotion #2 — but not on every release.** `UNIFIED_ENGINE_AUTHORITY_PLAN.md`
  §Scope makes the **research(v1.5.10)/live(v1.5.9) split intentional** ("must be treated as designed
  — not a bug"). XR is deliberately *not* kept in lockstep; the tax is incurred only when single-asset
  live is actively moved forward — and single-asset live is **stood down** (`portfolio.yaml`
  `strategies: []`, 2026-06-03). So the double-promotion burden is, today, **deferred and dormant**.

**Parity burden (related):** basket parity is **research-internal** — the streaming producer must equal
the research backtest, enforced by one equivalence test (`test_basket_producer_equiv.py`) via *code
reuse on the research side*; XR has **no** parity obligation. Single-asset parity requires cross-repo
*code identity* of the signal substrate; fill parity is impossible by construction (broker fills ≠
simulated fills — consistent with `[[feedback_close_entry_is_backtest_fiction]]`) and is not
attempted. So "minimize parity" already has a worked example: **make the contract the output, not the
compute.**

---

## 4. Does the architecture already provide partial separation? — **YES, substantially.**

1. **An ABI re-export seam already decouples *name* from *compute*** (`engine_abi.*` over
   `engine_dev.*`). A consumer can pin a stable ABI name while the compute behind it advances
   (`engine_abi.v1_5_9` → `engine_dev.v1_5_10` is exactly this, live today).
2. **A signal substrate already lives in a version-agnostic package** (`engines/`). The live-relevant
   surface (regime, protocol, concurrency) is *already* separated from versioned fill compute — it
   just is not *named* as an independent contract.
3. **A production-grade Signal ABI already exists for baskets** — the LOCKED `bridge.py` target
   contract. XR consumes it with zero engine code. This is Option C (below) already realized for one
   path.
4. **The cross-repo boundary is already declared one-directional and fail-closed** — the authority is
   "Trade_Scan-internal … must never drive the live ABI" (`engine_authority.py:17-18`); XR pins via a
   fail-closed allow-list it owns (`phase0_validation.py:30`).

**What is *not* separated:** the single-asset live path still reaches across the repo boundary into the
running research tree (`research_root: ../Trade_Scan`; `main.py:123` imports from it). That is the one
place the "promote twice / shared compute" shape persists.

---

## 5. Evaluation of the three architectures

Scored against the system **as it actually is**, not in the abstract.

### A. Shared engine authority (one engine, imported by both sides)
- **What it is here:** the single-asset live path. One engine substrate, imported cross-repo into XR.
- **Pros:** maximal signal parity by construction (same code); no contract to design/maintain; lowest
  code volume.
- **Cons:** XR is coupled to the research working tree at runtime (`main.py:123` from `../Trade_Scan`);
  a research-tree state can perturb live execution; advancing the engine triggers promotion #2;
  isolation rests entirely on the allow-list + convergence gate, not on a structural firewall.
- **Verdict:** adequate for a *stood-down, low-churn* single-asset deployment; it is the weakest on
  isolation and the only path that pays the double-promotion tax.

### B. Shared core + separate ABIs (one compute, multiple named ABI surfaces)
- **What it is here:** **the present steady state.** One compute (`engine_dev/v1_5_10`); multiple
  manifest-governed ABI surfaces (`engine_abi.v1_5_9`, `engine_abi.v1_5_10`) that different consumers
  pin independently (XR pins `v1_5_9`; basket research pins `v1_5_10`).
- **Pros:** consumers decouple their *pin cadence* from compute churn; fail-closed manifest gate on
  every surface (`engine_abi/*/__init__.py:65-84`); already implemented and CI-governed.
- **Cons:** the ABI surface is a *compute* ABI (16 symbols incl. backtest-only fill machinery), so a
  consumer that needs only the signal subset still pins the whole bundle — coupling is coarser than
  need (the §2 finding). It separates *names*, not *responsibilities*.
- **Verdict:** the pragmatic middle the system already occupies; it softens but does not remove the
  single-asset cross-repo compute coupling.

### C. Independent Research Engines + stable Signal ABI + XR
- **What it is here:** **the basket live fleet, already in production.** RE evolves freely; a thin,
  LOCKED signal/target contract is the only stable object; XR reconciles and imports no engine.
- **Pros:** strongest isolation (XR stdlib-only, structurally immune to engine change); zero
  execution-side engine promotion; "minimize parity" satisfied (contract carries the *output*);
  fail-closed at the contract (`ContractError`) independent of RE.
- **Cons / honest limits:** the *contract* must express everything XR needs. A basket target is a
  *position* (`state ∈ {FLAT,IN}` + legs) — naturally thin, **no `direction` field needed**
  (`bridge.py:14`). A single-asset strategy with dynamic stops/TP/trailing/partial exits has **more
  live state to express** — so generalizing C to single-asset risks a *fatter* contract that re-imports
  complexity the basket bridge was able to avoid. C trades code-reuse for contract-design surface; for
  rich per-bar strategies that trade may be less favorable than it looks.
- **Verdict:** proven and dominant **for position-truth baskets**; promising but **unproven for
  stateful single-asset strategies**, where the contract-design cost is the open question.

**Summary:** the system is a **hybrid A+B+C**: C for baskets, A for single-asset, riding on B's shared
ABI seam. This hybrid is coherent, not accidental.

---

## 6. Challenging the preliminary philosophy (adversarial)

The brief asked not to assume the premises. Where they are *overstated* for this system:

1. **"Eliminate promoting twice."** Already eliminated where it is in production (baskets). For
   single-asset the second promotion is **latent and deferred**, not a per-release tax — the
   intentional version split absorbs it. The premise frames a uniform cost that is actually
   path-specific and currently dormant. **Don't solve a tax that isn't being paid.**
2. **"Coupling is expensive."** The single-asset coupling is *structurally* heavy (runtime cross-repo
   import of the research tree) but *semantically* thin and *version-stable* (6 symbols, 5 from
   `engines/`). The expense is concentrated in **packaging** (the signal subset is bundled with the
   fill engine under one version), not in genuine behavioral entanglement. A cheaper intervention than
   a Signal-ABI rebuild might simply be to *name the `engines/` substrate as its own surface* — but
   that is a B-flavored refinement, not a C migration, and is out of scope here (no proposal made).
3. **"The stable object may be the Signal ABI rather than engine parity."** Strongly supported **for
   baskets** (the contract is the stable object; parity is research-internal). For single-asset the
   "stable object" is currently the `engines/` substrate, which is *already* version-stable — so the
   benefit of formalizing a Signal ABI there is **isolation**, not **stability** (the stability is
   already present). Be precise about which property is being bought.
4. **"XR should remain simple, stable, boring."** The basket XR already is (stdlib-only shim). The
   single-asset XR is *not* boring — it runs regime compute + strategy logic live. The philosophy is
   sound; note it describes a *target state for single-asset*, not a description of today.
5. **"Favor operational isolation over code reuse."** Aligns with C. But observe the **cost ledger**:
   C buys isolation by paying contract-design + a producer per strategy family. For the **active**
   deployment (baskets) that cost is already sunk and the isolation already banked. For the **inactive**
   single-asset path, paying C's cost now optimizes a path nobody is currently flying.

**Net:** the philosophy is *correct as a direction* and *already instantiated where it pays*. Its
weakest assumption for this system is uniformity — treating a path-specific, currently-dormant burden
as a standing systemic cost.

---

## 7. Migration risks (if Option C were ever generalized to single-asset — risks only, **not a plan**)

Per constraints, this is a **risk register**, not a proposal or sequence.

- **R1 — Contract richness creep.** A single-asset signal contract must carry entry + dynamic exit
  intent (stop/TP/trailing/partial). If it grows to encode strategy state, XR stops being "boring" and
  the isolation benefit erodes. The basket bridge avoided this *only because a basket target is pure
  position truth*; that simplifier may not transfer.
- **R2 — Fill-semantics divergence.** Backtest fills are simulated (`evaluate_bar`); live fills are the
  broker's. Any contract that implies a fill price re-imports the "close-entry is backtest fiction"
  hazard (`[[feedback_close_entry_is_backtest_fiction]]`, `[[feedback_fill_model_assumption]]`). The
  contract must speak *intent* (target/position), never *fill*.
- **R3 — Two producers, two parities.** C requires a live *producer* per family (the basket model has
  `basket_producer.py`). A single-asset producer must be proven equal to the research backtest (the
  basket model locks this with `test_basket_producer_equiv.py`); without that, C trades a cross-repo
  import for an *unverified* duplicate compute — strictly worse.
- **R4 — Losing the convergence gate's teeth.** Today the single-asset live identity is bound by
  `run_stage1.py:410-420` + the convergence gate. A contract-based path needs an *equivalent*
  fail-closed identity check on the producer, or it regresses isolation-for-correctness.
- **R5 — Optimizing a dormant path.** Single-asset live is stood down. Building C for it spends infra
  budget on capability with no current consumer (cf. `[[feedback_infra_build_to_falsify]]`,
  `[[feedback_dont_over_defer]]` — and the active infra-freeze 2026-06-20→~06-27).
- **R6 — Fail-closed must be preserved end-to-end.** Any change must keep: ABI manifest gate
  (`engine_abi/*/__init__.py:84`), XR allow-list (`phase0_validation.py:30`), `ContractError`
  validation (`bridge.py`), and the convergence gate. None of these may be softened in the name of
  decoupling.

---

## 8. Conclusions (audit-level; decision rests with the operator)

1. **The architecture already provides substantial partial separation** — an ABI name/compute seam (B),
   a version-agnostic signal substrate (`engines/`), and a fully realized Signal-ABI path for baskets
   (C). It is a coherent A+B+C hybrid.
2. **The double-promotion burden is asymmetric and currently latent:** ZERO for the live basket fleet,
   deferred-and-dormant for the stood-down single-asset path.
3. **Long-term evolution *can* eliminate the second promotion for single-asset** — by generalizing the
   basket producer/target/XR model — **but** the decisive cost is **contract design for stateful
   strategies (R1/R2)**, not the engine seam, which is already favorable.
4. **The most defensible long-term posture is the one the system is already drifting toward:** let RE
   evolve freely behind the ABI seam (B), keep XR on the contract model where it already pays (C,
   baskets), and treat a single-asset Signal ABI as an *option to exercise if and only if single-asset
   live deployment becomes active again* — not as standing work. The responsibility model that such an
   option would instantiate is described in the companion [`SIGNAL_ABI_AND_XR_DESIGN.md`](SIGNAL_ABI_AND_XR_DESIGN.md).

---

## 9. Evidence index (read this session)

- **Authority/selection:** `config/engine_authority.py:8-20,78-79` (canonical = v1_5_10 both paths;
  scope excludes TS_Execution, pinned v1_5_9). `UNIFIED_ENGINE_AUTHORITY_PLAN.md` §Scope, §1, §4
  (intentional research/live split; 8 TS_Execution pin sites; promotion phases).
- **ABI seam:** `engine_abi/__init__.py`; `engine_abi/v1_5_9/__init__.py:20,39-56,65-84`;
  `engine_abi/v1_5_10/__init__.py:25` (both re-export engine_dev.v1_5_10; manifest fail-closed).
- **Compute:** `engine_dev/universal_research_engine/{v1_5_3..v1_5_10}/`; `…/v1_5_10/execution_loop.py:78`
  (ENGINE_VERSION="1.5.10", FROZEN). Shared services: `engines/{regime_state_machine,protocols,concurrency_gate}.py`.
- **Research consumers:** `tools/basket_runner.py:40,68,70-75`; `tools/run_stage1.py:372-427` (dynamic
  import + :410-420 stamp==module guard); `tools/recycle_rules/pine_ratio_zrev_v1.py` (signal vs engine).
- **XR single-asset:** `TS_Execution/src/main.py:114-136`; `execution_adapter.py:39-40`;
  `pipeline.py:130`; `strategy_loader.py:154`; `phase0_validation.py:30,63`;
  `portfolio_loader.py:39,75,316`; `portfolio.yaml:1,6`; `harness/replay.py:214`.
- **XR basket / Signal ABI:** `TS_Execution/bridge/bridge.py:1-170` (LOCKED contract, stdlib-only,
  Target/Leg, epoch reserved, no direction, seq gaps, heartbeat separate, `ContractError`);
  `TS_Execution/src/basket_shim.py:1-69` (engine-free imports). Producer:
  `Trade_Scan/tools/live_basket/{basket_producer.py, bridge.py, driver.py, test_basket_producer_equiv.py}`.
- **Promotion machinery:** `tools/abi_audit.py` (triple-gate); `governance/engine_abi_<ver>_manifest.yaml`;
  `vault/engines/Universal_Research_Engine/{…,v1_5_9,v1_5_10}/engine_manifest.json`;
  `tests/test_engine_identity_convergence.py`.

*End — read-only audit. No code, governance, or pipeline state was modified.*
