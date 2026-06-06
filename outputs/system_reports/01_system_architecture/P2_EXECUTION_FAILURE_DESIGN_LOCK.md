# P2 Execution-Failure — Design Lock

**Status:** DESIGN-LOCK (for review). 2026-06-06. Scope is EXACTLY the four
decisions below — the gaps the P2 audit surfaced. **No new mechanics, no new
features, no architecture expansion, no code here.** When this review is clean,
the architecture phase is complete and P2 becomes implementation of a known
design. Companion to `COINTEGRATION_FIRST_LIVE_DEPLOYMENT_PROPOSAL.md` (Review #2)
and `tools/live_basket/CONTRACT.md`.

Decisions 1–2 MUST be in place before any MT5 demo. Decisions 3–4 are LOCKED here
and implemented as part of the demo slice.

---

## D1 — Partial-fill handling  (pre-demo; the boundary-truth fix)

**LOCK:** A leg's fill state is read from **broker position truth** — the leg's
open volume via `get_positions(magic=<leg magic>)` — and is **never inferred from
the order retcode.** The retcode (`DONE` / `DONE_PARTIAL` / reject / `None` /
timeout) only *triggers* the broker re-read; it is never the authority. A leg is
**coherent iff its broker volume == the requested lot** (within lot-step
tolerance). Volume `0` = not filled; any other non-equal volume = a **partial =
incoherent**, which is unwound (closed) — never left open and never mis-read as a
reject.

**Why:** today a `DONE_PARTIAL` (requested 0.02, filled 0.01) falls into the
`!= DONE → reject` branch while a position exists → a silently stranded naked leg.
That violates "reconcile from broker truth" at the one place it must hold. This
decision restores it at the execution boundary.

**Lands:** `broker.py` (recognize/export `DONE_PARTIAL`), `execution_adapter.py`
(post-send broker re-read + requested-vs-filled compare). No new concept — it
*applies* the existing MT5-as-truth doctrine to the send path.

---

## D2 — Per-leg magic  (pre-demo; reuse the proven path)

**LOCK:** Each leg gets its **own magic** = deterministic hash of
`"{basket_id}|L{leg_index}"` (31-bit, same shape as `strategy_magic`). The
existing **1 magic → 1 ticket → 1 slot** reconcile/slot path is reused
**unchanged, per leg.** Basket identity = the (derivable) pair of leg-magics; the
order **comment carries `e{epoch}L{leg}` for AUDIT/epoch only**, never as the
reconcile key. The "which two leg-slots form a basket" grouping lives in a thin
layer **above** the unchanged per-leg slots (for atomic open/close + naked-leg
logic).

**Why:** the basket design assumed `1 magic → 2 positions`, but `reconcile.py` is
`1 magic → 1 position` and *discards* the second (the `duplicate_magic` overwrite
— `reconcile.py:105-111`). Per-leg magic sidesteps that collision and reuses the
proven path instead of fighting it.

**Contract revision (clean — V0 is dry, tags untested):** `tools/live_basket/`
swaps `bridge.basket_magic(basket_id)` → `leg_magic(basket_id, leg_index)`;
`leg_comment` keeps `epoch+leg` (audit). The epoch-in-tag decision is unchanged.
Update `CONTRACT.md` "Order tags".

---

## D3 — Retry → HALT policy  (lock now; implement with demo)

**LOCK — entry vs exit asymmetry (Non-negotiable #1):**
- **Entry incoherence** (a leg not at its requested lot after an open): **unwind
  open legs → FLAT.** Harmless (you end flat); the reconcile loop retries the open
  on later cycles. No safety-HALT. *(A "back off opening after K consecutive open
  failures" is a cost knob only, not safety — may be deferred.)*
- **Exit incoherence / naked leg** (target FLAT but a leg is still open): **K fixed
  immediate close-retries** (close is idempotent — it re-reads first). If still
  naked after K → **`ORPHAN_UNRESOLVED` → HALT** (blocks NEW opens; **closes stay
  allowed**) + CRITICAL alert + operator-clear required. The reconcile loop keeps
  attempting the naked-leg close every cycle while halted.
- **K is a fixed constant; no discretion. Closes are never blocked** — the rescue
  path must always stay open.

**Why:** flat is safe (retry freely); a naked leg is unhedged risk (bounded, then
halt-but-keep-closing). Reuses `risk.evaluate`'s existing "halt entries, allow
closes" shape — adding only a position-driven trigger — and `alerts` CRITICAL.

---

## D4 — Persistent HALT semantics  (lock now; implement with demo)

**LOCK:** The `ORPHAN_UNRESOLVED` HALT is **file-persisted, basket-scoped** (e.g.
`TS_SIGNAL_STATE/h2_live/<basket_id>/halt.json`: basket_id, reason, the naked
leg's magic/ticket/symbol, timestamp). **Read at startup:** if present, the
process boots HALTED (no new opens; reconcile + closes still run to flatten the
naked leg) until **operator-clear = remove the file**. It composes with
restart-reconcile (Review #3): after a restart, broker-truth + the halt file
together define the state — keep closing the naked leg, open nothing new.

**Why:** the mandated watchdog restart wipes in-memory `risk._halted`
(`risk.py:42-44`, `supervisor.py:212`), so a naked-leg HALT must live on disk or
the safety evaporates on the very respawn that restart-reconcile relies on.
Basket-scoped so it generalises to multi-basket unchanged.

**Lands:** a new state file + a startup read in `main.py`; the trip set from D3.

---

## Non-goals (explicitly out)
No slippage/limit-order optimisation, no dynamic sizing, no multi-basket, no
recycle/epoch *logic* (the tag slot stays reserved), no validator. Only the four
decisions above. Everything else remains as the proposal already locked it.
