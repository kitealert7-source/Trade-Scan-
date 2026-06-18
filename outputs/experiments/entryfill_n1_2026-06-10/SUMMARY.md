# ZCRS entry-fill timing: N+1 vs N+2 — decision record (2026-06-10)

**Question:** ZCRS filled entries at bar **N+2**. Is that intended, and does the
Pine-faithful **N+1** fill beat it on the deployable universe?

**Decision: ADOPT N+1 for the deployed baskets (ZCRS v2).** N+2 was a porting
artifact, not the intended timing; N+1 is aggregate- and risk-adjusted-better on
the canonical sweep and the correct implementation. Global default stays
`next_bar_open` (N+2) for parity; the 5 deployed baskets opt into
`entry_fill_timing: current_bar_open` (N+1). This is a **research/version change
(v2), not a bugfix** — the strategy was promoted on N+2.

## The artifact (why N+2 happened)
Cross on closed bar N → leg PROPOSES (N) → rule `_maybe_approve` APPROVES (N,
unconditionally — only gates regime/r_bar/sizing, **never re-checks the signal**)
→ leg FIRES (N+1) → engine fills next-bar-open (**N+2**). The N→N+1 hop is a pure
deferral of the leg's fire (so the rule's approval gate can run between propose
and fire), with **zero confirmation value**. Pine intent: decide on closed bar N,
fill at next open **N+1**. The extra bar is one bar of entry-edge decay.

## Verification gate (insisted before changing)
- **Promotion was on N+2** — the deployed rule + `run_basket_pipeline` engine
  (used for both promotion backtests and the live producer) implement the N+2
  handshake. So this is v2, not a bugfix. ✓
- **N+1 carries no lookahead** — direction/sizing/r_bar all lock at bar N; the
  fire on N+1 carries no N+1 information, so filling at N+1's own open is the
  correct next tradeable price after the N-close decision. ✓

## Implementation (opt-in, parity-preserving)
- Engine `evaluate_bar.py`: pending-entry fill extracted to `_fill_from_pending`;
  when `execution_timing == "current_bar_open"`, the entry is consumed on the
  fire bar (N+1) instead of deferring (N+2). Default path unchanged.
- `PineZRevLegStrategy.execution_timing` (default `next_bar_open`); fire-phase
  dict carries it only when non-default → default byte-identical.
- Threaded via `recycle_rule.params.entry_fill_timing` in both the backtest
  builder (`run_pipeline`) and the **live producer** (`basket_producer`).
- **Parity gate 16/16** (default byte-identical); N+1 validated to fill exactly
  one aligned bar earlier; engine ABI audit OK (`engine_abi.v1_5_9`, no bump).
  Capability committed default-off in `910c4a84`.

## Canonical sweep (the authoritative evidence)
20 deployable pairs × {N+2 (`EFTN2`), N+1 (`EFTN1`)} = **40 full `run_pipeline`
runs, 40/40 complete, 0 failures**, all real data. Artifacts: per-run folders
`TradeScan_State/backtests/…_EFT{N1,N2}__…`, MPS Cointegration rows
(`series=GP_ZCRS_EFTN1/EFTN2`), run-registry entries. In-memory preview agreed
within ±0.63pp on 19/20 (one run-to-run drift, ruled out as a gen bug).

| Aggregate (20 pairs) | N+2 | N+1 |
|---|---|---|
| median Ret/DD | 1.36 | **1.77** (+30% rel) |
| sum net % | 125.7 | **143.3** (+17.6pp) |
| median win % | 58.3 | **61.1** |
| pairs N+1 Ret/DD > N+2 | — | 12/20 |
| pairs N+1 net > N+2 | — | 11/20 |

## Findings
- N+1 wins on **all three** aggregate metrics. Mechanism: entering one bar
  earlier (more-extreme z) captures bigger reversions → higher net + Ret/DD.
- **Not robust per-pair** — 8–9/20 regress, some sharply (GBPUSDUSDCHF
  2.25→0.26, EURGBPGBPNZD 1.38→−1.72). N+1 is **not universally better**.
- **The 5 deployed baskets gain ~+7.1pp net** (CADJPYUSDCHF +3.96, EURJPYUSDJPY
  +4.22; CHFJPYEURUSD/EURJPYGBPJPY/GBPAUDUSDCHF marginal −0.3/−0.4/−0.4) with
  **no sharp regressions** — the sharp-regression pairs are all non-deployed.

## Scope of the decision
- Adopt N+1 on the **5 deployed baskets** (the demo runs ZCRS v2 from 2026-06-10).
- Global default remains N+2 (parity; all committed fixtures byte-identical).
- **Future onboarding must check N+1 per-pair** — the aggregate edge is real but
  not universal; a new candidate basket should confirm N+1 ≥ N+2 for its pair
  before adopting v2 timing.

## Authoritative artifacts
Canonical `EFTN1`/`EFTN2` run folders + MPS Cointegration rows + run-registry
entries (the promotion evidence). The demo's per-cycle `DemoOutcomeLedger.jsonl`
now records the live N+1 outcomes for forward validation.
