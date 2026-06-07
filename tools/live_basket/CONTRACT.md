# Live-Basket Target-State Bridge — CONTRACT (V0)

**Status:** LOCKED 2026-06-06 (operator-ratified). The file format below is the
cross-process / cross-repo interface between the Trade_Scan-side **runner** and
the **shim**. Neither side imports the other; both conform to this document.
`bridge.py` + `reconcile.py` are **stdlib-only** so the reconcile core ports to
the TS_Execution shim verbatim (TS_Execution's only governed dependency stays
`engine_abi`).

Companion to `outputs/system_reports/01_system_architecture/COINTEGRATION_FIRST_LIVE_DEPLOYMENT_PROPOSAL.md`
(V0 file-bridge architecture; Reviews #1–#5).

---

## Ratified decisions (the load-bearing ones)

1. **No `direction` field.** The `legs` ARE the position (one source of truth).
   Basket direction is *derived* when needed, never stored — so `direction=+1`
   can never disagree with `legs=[short, long]`.
2. **`epoch` reserved from day one, fixed `0` in V0.** It rides in the order tag
   so a future basis-reset recycle (`soft_reset_basket` / `realize_winner`) needs
   **no schema or broker-tag migration**. `bridge.Target` hard-guards `epoch != 0`.
3. **`seq` strictly increasing, GAPS ALLOWED.** Current target = the record with
   the **max `seq`**; the shim ignores any seq ≤ last processed. (`41, 42, 45` is
   valid.) Gaps-allowed keeps recovery and any future distributed writer simple.
4. **`target_hash` = semantic fingerprint, DIAGNOSTIC ONLY.** Over `state` +
   `epoch` + `legs` (sorted), **excluding** the envelope (`seq`, `bar_ts`,
   `emitted_at`). V0 logic never branches on it; the runner's append-on-change
   uses `semantic_key` (its structured mirror). It exists so a 3 AM operator can
   line up `target.jsonl` ↔ `executions.jsonl` ↔ broker.
5. **Heartbeat is a SEPARATE channel** (`runner_heartbeat.json`), written every
   runner cycle even when the target is unchanged. Runner-death detection keys on
   heartbeat staleness, never on target age (a HOLD and a dead runner look
   identical on the target alone — Review #4).

---

## Files

Under `bridge_dir = <TradeScan_State>/TS_SIGNAL_STATE/h2_live/<basket_id>/`.
Single writer per file; **every mutation is a whole-file atomic replace**
(`tmp` + `fsync` + `os.replace`), so a reader never sees a torn file. Under a
24/5 daemon the `os.replace` retries transient Windows locks (winerror 5/32 from
AV / Explorer-preview scanning the destination) with backoff — semantics
unchanged, the final file is still one atomic replace. A hard-kill between
`mkstemp` and `replace` can leave `*.tmp` debris; each writer sweeps it at
startup (`bridge.cleanup_orphan_tmp`) **scoped to the files it owns** (producer →
`target.jsonl`/`runner_heartbeat.json`, shim → `executions.jsonl`), so a sweep
can never delete the other writer's in-flight tmp on the shared dir. The contract
guarantees the *final* file is never torn, not that no `.tmp` survives a crash.

| File | Writer | Semantics |
|---|---|---|
| `target.jsonl` | runner | append **on desired-state change only**; current = max-`seq` line |
| `runner_heartbeat.json` | runner | overwritten **every cycle** (liveness ≠ target age) |
| `executions.jsonl` | shim | append one record per reconcile decision |

---

## Schemas (`schema_version: 1`)

**Target** (runner → shim):
```json
{ "schema_version": 1, "basket_id": "COINTREV_EURUSD_USDJPY_GP",
  "seq": 42, "epoch": 0, "state": "IN",
  "bar_ts": "2026-06-05T13:55:00Z", "emitted_at": "2026-06-05T13:55:02.314Z",
  "target_hash": "c861a1a6baf84bf3",
  "legs": [ {"symbol":"EURUSD","side":"long","lot":0.02},
            {"symbol":"USDJPY","side":"short","lot":0.01} ] }
```
- `state ∈ {FLAT, IN}`. `FLAT` ⇒ `legs == []`; `IN` ⇒ `legs` non-empty.
- `bar_ts` = closed 5m bar the decision is "as of" (the freshness anchor for the
  future both-legs-fresh + regime-freshness gates). `emitted_at` = wall-clock of
  this change (audit/latency, **not** liveness).

**Heartbeat** (separate liveness):
```json
{ "schema_version": 1, "basket_id": "…", "bar_ts": "…",
  "beat_at": "2026-06-05T14:00:01.9Z", "last_target_seq": 43 }
```

**Execution record** (shim → log):
```json
{ "schema_version": 1, "basket_id": "…", "acted_on_seq": 42, "epoch": 0,
  "decision": "NEED_OPEN", "action": "OPEN_GROUP", "mode": "DRY",
  "observed": "FLAT", "result": "WOULD_OPEN", "target_hash": "c861a1a6baf84bf3",
  "at": "…", "detail": "target IN, broker flat" }
```

---

## Reconcile vocabulary (pure: desired-set vs broker-set)

Identity of a position = `(symbol, side, lot, epoch)` — `epoch` recovered from
the order tag. Wrong lot is INCOHERENT, not MATCH (a different lot = a different
hedge ratio = a different spread; Non-negotiable #3).

| Class | Condition | V0 action |
|---|---|---|
| `MATCH` | actual == desired, or both FLAT | `NOOP` |
| `NEED_OPEN` | target IN, broker flat | `OPEN_GROUP` (dry: `WOULD_OPEN`) |
| `NEED_CLOSE` | target FLAT, broker non-empty | `CLOSE_GROUP` (dry: `WOULD_CLOSE`) |
| `INCOHERENT` | target IN, broker non-empty ≠ desired (partial / wrong side / lot / epoch) | `FLATTEN_INCOHERENT` (dry: `WOULD_FLATTEN`) → reopen next cycle |

INCOHERENT never "completes" a half-open basket — its entry price is now stale;
flatten and reopen cleanly (Review #3).

---

## Order tags (self-identifying positions ⇒ stateless shim)

- `magic` = deterministic 31-bit int **PER LEG** = `hash("{basket_id}|L{leg}")`
  (`bridge.leg_magic`). Per-leg (not per-basket) magic reuses TS_Execution's proven
  1 magic → 1 ticket → 1 slot reconcile path UNCHANGED per leg (P2 Design-Lock D2);
  a shared basket magic would trip its duplicate-magic discard.
- `comment` = `e{epoch}L{leg_index}` within MT5's 31-char limit
  (`bridge.leg_comment` / `parse_leg_comment`) — **audit / epoch tag only**, never
  the reconcile key.
- Basket identity = the (derivable) pair of leg magics; `(epoch, leg)` from the
  comment. The reconcile loop holds **no durable state** (Review #3 linchpin).
  **Epoch is in the comment tag from day one** (migration-avoidance).

---

## Invariants

1. Single writer per file; atomic whole-file replace.
2. `target.jsonl` append-on-change; current = max-`seq`.
3. Heartbeat every cycle; liveness ≠ target age.
4. `seq` strictly increasing, gaps allowed; shim takes max, ignores ≤ last.
5. Shim holds **no durable state** — each cycle re-derives from (latest target) +
   (tag-filtered broker positions). Restart = first cycle with empty memory.
6. `epoch` present in schema + tag from day one; V0 never increments it.

---

## Slice-1 scope (this commit) vs deferred

**In Slice 1 (proven, broker-mocked, no MT5):** the contract above; atomic I/O;
the stateless reconcile loop (`shim.run_once`); restart-statelessness;
incoherent→flatten→reopen; dry end-to-end convergence. Runner = a thin **scripted
emitter** (`runner.ScriptedRunner`); broker = `mock_broker.MockBroker` behind the
`read_positions` seam.

**Deferred (later slices, in order):**
- Real `basket_pipeline` runner (emit target-state from the live mechanic).
- **Regime-break exit folded into the runner** (Track B2) — enable
  `coint_break_exit=True` + ensure `coint_regime` is on the runner's bars, then a
  regime break → the mechanic emits `FLAT` → the shim closes the group.
- **Regime-freshness gate** (Track B3) — assert the `coint_regime` `as_of` is
  recent before a regime-driven FLAT may drive a live close (the feed is daily; a
  regime exit is a daily safety net, not an intraday stop).
- TS_Execution shim port + the real `dispatch_group`/`close_group` MT5 primitive
  with the entry/exit-partial failure protocol (P2 demo → L0 live).
