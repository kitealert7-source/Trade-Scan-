# Deployment Unification Plan

**Date:** 2026-04-03
**Updated:** 2026-04-12
**Status:** FULLY IMPLEMENTED — Phase 1-5 complete (2026-04-12). Phase 1: vault extension. Phase 2+2.1: runtime safety guards with two-tier validation + MismatchTracker. Phase 3: promotion flow (via promote_to_burnin.py). Phase 4: golive archived, validate_safety_layers rewritten. Phase 5: 6 verification tests pass. Section 8: write surface documented.
**Objective:** Eliminate deployment safety gaps. Unify promotion, burn-in, and execution into a single flow with no parallel systems.

---

## 1. Architecture: Before vs After

### BEFORE (current)

```
PIPELINE_COMPLETE
  |
  v
Step 8: capital_wrapper -> deployable/
  |                         (trade_log with signal_hash, equity curves)
  v
Step 8.5: profile_selector -> deployed_profile in ledger
  |
  v
filter_strategies.py -> candidate ledger (CORE/WATCH/FAIL)
  |
  |--- [MANUAL, OPTIONAL] backup_dryrun_strategies.py -> DRY_RUN_VAULT/
  |                        (directive, strategy.py, metrics, NO broker specs,
  |                         NO profile hash, NO signal index)
  |
  |--- [MANUAL] human edits portfolio.yaml
  |
  v
filter_strategies.py -> auto BURN_IN status
  |
  v
TS_Execution startup:
  main.py --phase 2
    load_strategies() -> strategy.py via importlib
    smoke_test_strategies()
    run_bar_loop():
      STEP 2: _dispatch(slot, ...) -> order_send()    <-- NO GUARD
      STEP 3: check_entry/check_exit -> pending_signal

  [ORPHANED, NEVER CALLED]
  generate_golive_package.py -> golive/ artifacts
  strategy_guard.py -> signal hash + kill-switch
```

**Gaps:**
- Vault snapshot is optional (can deploy without baseline)
- No broker spec freezing
- No profile hash verification at startup
- No signal hash verification before order
- No kill-switch (loss streak / WR / DD)
- Go-live package disconnected from everything

### AFTER (planned)

```
PIPELINE_COMPLETE
  |
  v
Step 8: capital_wrapper -> deployable/
  |                         (trade_log with signal_hash, equity curves)
  v
Step 8.5: profile_selector -> deployed_profile in ledger
  |
  v
filter_strategies.py -> candidate ledger (CORE/WATCH/FAIL)
  |
  v
[MANDATORY] backup_dryrun_strategies.py -> DRY_RUN_VAULT/
  |           EXTENDED with:
  |             selected_profile.json (SHA-256 hash)
  |             broker_specs_snapshot/ (per-symbol YAMLs)
  |             deployable/{PROFILE}/deployable_trade_log.csv (has signal_hash)
  |           = FULL DEPLOYMENT CONTRACT
  |
  v
[HUMAN] edits portfolio.yaml (vault_snapshot field required)
  |
  v
filter_strategies.py -> auto BURN_IN status
  |
  v
TS_Execution startup:
  main.py --phase 2
    load_strategies()
    smoke_test_strategies()
    [NEW] construct_guards(slots, vault_root)     <-- Phase 2 addition
      for each slot:
        locate vault snapshot
        verify profile hash vs portfolio.yaml params
        build signal index from trade log
        instantiate StrategyGuard
    run_bar_loop():
      STEP 2:
        [NEW] guard.verify_signal(slot)           <-- pre-trade hook
        _dispatch(slot, ...) -> order_send()
        [NEW] guard.record_trade(pnl)             <-- post-trade hook
      STEP 3: check_entry/check_exit -> pending_signal

  [RETIRED]
  generate_golive_package.py -> archived
```

**What changes:**
- Vault becomes mandatory before deployment (not optional)
- Vault extended with 3 artifacts (profile.json, broker specs, trade log)
- TS_Execution reads vault at startup, constructs guards
- Pre-trade: signal hash check
- Post-trade: kill-switch evaluation
- Go-live package retired (vault subsumes it)

---

## 2. File-Level Change List

### Phase 1 — Vault Extension (Trade_Scan) -- DONE

| File | Change | Detail |
|------|--------|--------|
| `tools/backup_dryrun_strategies.py` | MODIFY | Add 3 new artifact copies (see below) |

**New artifacts added to vault per strategy:**

**A. `selected_profile.json`**
- Source: `TradeScan_State/strategies/{ID}/deployable/profile_comparison.json` -> extract deployed profile
- Also read `PROFILES` dict from `capital_wrapper.py` for full params
- Compute SHA-256 of `{"enforcement": {...}, "sizing": {...}}` with `sort_keys=True, separators=(",",":")`
- Write as `{vault}/{ID}/selected_profile.json`
- Format matches existing `strategy_guard.py` expectation exactly

**B. `broker_specs_snapshot/`**
- Source: `data_access/broker_specs/OctaFx/{SYMBOL}.yaml` for each symbol in the strategy
- Symbols extracted from backtest folder names: `{ID}_{SYMBOL}` glob
- Copy as `{vault}/{ID}/broker_specs_snapshot/{SYMBOL}.yaml`

**C. `deployable/{PROFILE}/deployable_trade_log.csv`**
- Source: `TradeScan_State/strategies/{ID}/deployable/{PROFILE}/deployable_trade_log.csv`
- Already contains `signal_hash` column (written by `emit_profile_artifacts`)
- Copy as `{vault}/{ID}/deployable/{PROFILE}/deployable_trade_log.csv`

**No changes to vault invariants.** Existing structure preserved. New artifacts are additive.

### Phase 2 — Runtime Safety (TS_Execution) -- DONE

| File | Change | Detail |
|------|--------|--------|
| `TS_Execution/src/main.py` | MODIFY | Add guard construction at startup + pre/post hooks in callback |
| `TS_Execution/src/guard_bridge.py` | NEW | Thin adapter: vault path -> StrategyGuard construction |
| `TS_Execution/portfolio.yaml` | MODIFY | Add `vault_snapshot` field per strategy (path to vault dated folder) |
| `execution_engine/strategy_guard.py` | MODIFY | Add `from_vault()` classmethod (reads vault layout instead of golive/) |

**main.py changes (3 insertion points):**

**Insertion 1: After `smoke_test_strategies()` (line ~112)**
```
construct_guards(all_slots, vault_root, exec_config)
  -> for each slot: build StrategyGuard from vault
  -> verify profile hash against portfolio.yaml params
  -> on mismatch: log FATAL, abort startup
```

**Insertion 2: Inside STEP 2 callback, before `_dispatch()` (line ~258)**
```
guard = slot.guard  # set during construct_guards
if guard and guard.signal_index:
    guard.verify_signal(
        trade_id, slot.symbol, entry_ts, direction, entry_price, risk_distance
    )
    # raises SignalMismatchError -> skip dispatch, log alert
```

**Insertion 3: Inside STEP 2 callback, after shadow logger (line ~278)**
```
if guard and pnl is not None:
    guard.record_trade(pnl)
    # raises StrategyHaltedError -> disable slot, log alert
```

**strategy_guard.py addition:**
```python
@classmethod
def from_vault(cls, vault_strategy_dir: Path, profile: str,
               config: Optional[GuardConfig] = None,
               alert_log: Optional[Path] = None) -> "StrategyGuard":
    """Construct guard from DRY_RUN_VAULT layout."""
    selected = vault_strategy_dir / "selected_profile.json"
    trade_log = vault_strategy_dir / "deployable" / profile / "deployable_trade_log.csv"
    # ... same logic as from_golive_package but with vault paths
```

**guard_bridge.py (new, ~60 lines):**
- `construct_guards(slots, vault_root, exec_config)` -> iterates slots, calls `StrategyGuard.from_vault()`
- `resolve_vault_path(strategy_id, vault_root)` -> finds latest vault snapshot containing the strategy
- On missing vault: FATAL if `exec_config.require_vault` is True, WARN if False

**portfolio.yaml change:**
```yaml
execution:
  vault_root: "C:/Users/faraw/Documents/DRY_RUN_VAULT"
  require_vault: true    # false = warn-only (for transition period)
```

No per-strategy vault path needed — the bridge resolves it by scanning vault folders.

### Phase 2.1 — Robust Signal Validation (TS_Execution) -- DONE

The exact-hash approach from Phase 2 is brittle. Research and live engines may produce slightly different floats for entry_price or risk_distance due to data source differences, bar alignment timing, or indicator warm-up divergence. Phase 2.1 replaces the binary pass/fail with a two-tier verification system.

**Files affected:**

| File | Change | Detail |
|------|--------|--------|
| `execution_engine/strategy_guard.py` | MODIFY | Replace `verify_signal()` with two-tier `validate_signal()` |
| `TS_Execution/src/guard_bridge.py` | MODIFY | Add mismatch rate tracker + alert threshold |

**Two-tier verification logic:**

```
def validate_signal(self, trade_id, symbol, entry_ts, direction,
                    entry_price, risk_distance,
                    price_tolerance=0.001, time_window_s=60) -> SignalResult:

    # Tier 1: Exact hash match (primary)
    live_hash = _compute_signal_hash(symbol, entry_ts, direction,
                                      entry_price, risk_distance)
    if live_hash in self.signal_index.values():
        return SignalResult(status="EXACT_MATCH", hash=live_hash)

    # Tier 2: Tolerant match (fallback)
    # Search signal index for any entry where:
    #   - symbol matches exactly
    #   - direction matches exactly
    #   - abs(live_price - research_price) / research_price <= price_tolerance
    #   - abs(live_ts - research_ts) <= time_window_s
    for ref_id, ref_hash in self.signal_index.items():
        ref = self._signal_details[ref_id]  # pre-parsed from trade log
        if (ref["symbol"] == symbol
            and ref["direction"] == direction
            and abs(entry_price - ref["entry_price"]) / ref["entry_price"] <= price_tolerance
            and abs((entry_ts - ref["entry_ts"]).total_seconds()) <= time_window_s):
            return SignalResult(status="SOFT_MATCH", hash=live_hash,
                                matched_ref=ref_id, price_delta=..., time_delta=...)

    # No match at all
    return SignalResult(status="HARD_FAIL", hash=live_hash)
```

**SignalResult dataclass:**
```python
@dataclass
class SignalResult:
    status: str             # "EXACT_MATCH" | "SOFT_MATCH" | "HARD_FAIL"
    hash: str               # live-computed hash
    matched_ref: str = ""   # trade_id of matched research signal (SOFT_MATCH only)
    price_delta: float = 0  # abs price difference (SOFT_MATCH only)
    time_delta: float = 0   # abs time difference in seconds (SOFT_MATCH only)
```

**Signal detail index:** `from_vault()` now pre-parses the trade log into `_signal_details`:
```python
_signal_details: Dict[str, dict]  # trade_id -> {symbol, direction, entry_price, entry_ts, risk_distance}
```
Built once at startup from `deployable_trade_log.csv`. Memory: ~50 bytes per trade x 1000 trades = ~50KB. Negligible.

**Mismatch rate tracking (in guard_bridge.py):**

```python
class MismatchTracker:
    def __init__(self, alert_threshold_pct=1.0):
        self.total = 0
        self.exact = 0
        self.soft = 0
        self.hard = 0
        self.alert_threshold = alert_threshold_pct

    def record(self, result: SignalResult):
        self.total += 1
        if result.status == "EXACT_MATCH": self.exact += 1
        elif result.status == "SOFT_MATCH": self.soft += 1
        else: self.hard += 1
        self._check_alert()

    def _check_alert(self):
        if self.total < 20: return  # minimum sample
        hard_rate = self.hard / self.total * 100
        soft_rate = self.soft / self.total * 100
        if hard_rate > self.alert_threshold:
            log.warning(f"[GUARD] HARD_FAIL rate {hard_rate:.1f}% > {self.alert_threshold}% "
                        f"({self.hard}/{self.total}) — possible data alignment issue")
        if soft_rate > 10.0:
            log.warning(f"[GUARD] SOFT_MATCH rate {soft_rate:.1f}% > 10% "
                        f"({self.soft}/{self.total}) — review price/time tolerances")
```

**Logging format (per signal):**

```
[GUARD] EXACT_MATCH  strategy=SPKFADE_S03 signal=abc123def456
[GUARD] SOFT_MATCH   strategy=SPKFADE_S03 signal=abc123def456 ref=xyz789 price_delta=0.00023 time_delta=5s
[GUARD] HARD_FAIL    strategy=SPKFADE_S03 signal=abc123def456 — TRADE BLOCKED
```

**Dispatch behavior:**

| Result | Action |
|--------|--------|
| `EXACT_MATCH` | Dispatch normally. No log beyond debug level. |
| `SOFT_MATCH` | Dispatch normally. Log at INFO with deltas. Increment soft counter. |
| `HARD_FAIL` | **Block trade.** Log at WARNING. Increment hard counter. Check alert threshold. |

**Updated per-bar flow (replaces Phase 2 insertion 2):**

```
STEP 2: execute previous signal
  for each slot with pending_signal:
    a. [NEW] result = guard.validate_signal(trade_id, symbol, ts, dir, price, risk_dist)
       if result.status == "HARD_FAIL":
         mismatch_tracker.record(result)
         log "[GUARD] HARD_FAIL {id} — TRADE BLOCKED"
         slot.pending_signal = None
         continue
       mismatch_tracker.record(result)
    b. _dispatch(slot) -> order_send() [unchanged]
    c. [NEW] guard.record_trade(pnl) [unchanged from Phase 2]
```

**Tolerances (configurable via GuardConfig):**

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `price_tolerance` | 0.001 (0.1%) | Covers rounding differences between research and live data feeds |
| `time_window_s` | 60 | Bar-close timestamp can differ by seconds between data sources |
| `alert_threshold_pct` | 1.0 | >1% HARD_FAIL rate signals systemic data misalignment |
| `soft_alert_pct` | 10.0 | >10% SOFT_MATCH rate means tolerances may be too loose |
| `min_sample` | 20 | Don't trigger alerts on small samples |

**Additional effort:** +2h (modify `validate_signal`, build `MismatchTracker`, add `_signal_details` index, update tests)

---

### Phase 3 — Promotion Flow (Trade_Scan)

| File | Change | Detail |
|------|--------|--------|
| `.agents/workflows/portfolio-selection-add.md` | MODIFY | Add mandatory vault step before portfolio.yaml edit |
| `.agents/workflows/dry-run-vault.md` | MODIFY | Mark as mandatory (not optional) in "When to Run" |

**Enforced sequence:**
```
1. PORTFOLIO_COMPLETE (pipeline terminal state)
2. Human decides to promote
3. Run /dry-run-vault (MANDATORY — vault snapshot created)
4. Verify vault (Step 3 of workflow)
5. Edit portfolio.yaml (add strategy, vault_root set)
6. filter_strategies.py auto-detects BURN_IN
```

**Pre-execution gate (in guard_bridge.py):**
- If `require_vault: true` and no vault snapshot found for a strategy -> FATAL, refuse to start
- This enforces the sequence: no vault = no execution

### Phase 4 — Dead Code Removal (Trade_Scan)

| File | Change | Detail |
|------|--------|--------|
| `tools/generate_golive_package.py` | ARCHIVE | Move to `archive/tools/generate_golive_package.py` |
| `tests/test_generate_golive_package_helpers.py` | ARCHIVE | Move with it |
| `tools/validate_safety_layers.py` | REWRITE | Fix 2 bugs, repoint from golive/ to vault layout |

**validate_safety_layers.py fixes:**
1. Line 77/118/119: `emit_profile_artifacts(state, tmp)` -> add `total_runs=1, total_assets=1`
2. Line 30: `PROJECT_ROOT / "strategies"` -> `STATE_ROOT / "strategies"` (use `config.state_paths.STRATEGIES_DIR`)
3. Line 39: `PROJECT_ROOT / "backtests"` -> `STATE_ROOT / "backtests"` (use `config.state_paths.BACKTESTS_DIR`)
4. Repoint `GOLIVE` path to vault: resolve from `DRY_RUN_VAULT` instead of `strategies/.../golive/`
5. Parameterize strategy name (currently hardcoded to S08_P00)

**ENGINE_VERSION alignment:**
- Remove `ENGINE_VERSION = "1.6"` from `generate_golive_package.py` (archived)
- `strategy_guard.py` has no engine version reference (clean)

### Phase 5 — Verification Tests

| File | Change | Detail |
|------|--------|--------|
| `tools/validate_safety_layers.py` | REWRITE | 5 mandatory tests against vault layout |

---

## 3. Execution Flow (Step-by-Step)

### Promotion (one-time per strategy)

```
1. Pipeline completes -> PORTFOLIO_COMPLETE
2. Operator runs: python tools/backup_dryrun_strategies.py
   -> DRY_RUN_VAULT/DRY_RUN_{DATE}/{ID}/
      directive.txt, strategy.py, meta.json,
      portfolio_evaluation/, deployable/{PROFILE}/deployable_trade_log.csv,
      selected_profile.json, broker_specs_snapshot/
3. Operator verifies vault (Step 3 of workflow)
4. Operator edits TS_Execution/portfolio.yaml:
   - Adds strategy entry (enabled: true)
   - vault_root already set globally
5. filter_strategies.py detects portfolio.yaml -> sets BURN_IN
```

### Execution Startup (every market open)

```
1. startup_launcher.py -> main.py --phase 2
2. load_portfolio() -> parse portfolio.yaml
3. load_strategies() -> importlib each strategy.py
4. smoke_test_strategies() -> synthetic context validation
5. [NEW] construct_guards(slots, vault_root):
   for each enabled slot:
     a. resolve_vault_path(strategy_id) -> latest vault folder
     b. read selected_profile.json -> verify hash vs portfolio.yaml params
     c. read deployable_trade_log.csv -> build signal index
     d. instantiate StrategyGuard -> assign to slot.guard
   if require_vault and any slot missing vault: FATAL EXIT
6. MT5 connect, replay signals, write PID, pre-warm
7. Launch bar-loop threads
```

### Per-Bar Execution (every bar close)

```
1. STEP 1: reconcile_positions() [unchanged]
2. STEP 2: execute previous signal
   for each slot with pending_signal:
     a. [NEW] result = guard.validate_signal(trade_id, symbol, ts, dir, price, risk_dist)
        mismatch_tracker.record(result)
        if result.status == "HARD_FAIL":
          log "[GUARD] HARD_FAIL {id} — TRADE BLOCKED"
          slot.pending_signal = None
          continue
        if result.status == "SOFT_MATCH":
          log "[GUARD] SOFT_MATCH {id} ref={matched_ref} price_delta={d} time_delta={t}s"
        # EXACT_MATCH or SOFT_MATCH: proceed to dispatch
     b. _dispatch(slot) -> order_send() [unchanged]
     c. [NEW] if slot.guard and trade closed with pnl:
        guard.record_trade(pnl)
        -> StrategyHaltedError: set slot.enabled=False, log "[GUARD] HALT {rule}", continue
3. STEP 3: generate new signals [unchanged]
```

---

## 4. Risk Assessment

**Risk 1: Signal hash mismatch false positives.**
The signal hash uses `entry_price:.5f` and `risk_distance:.5f`. If TS_Execution computes slightly different float values than the research engine (different data source, different bar alignment), hashes won't match. **Mitigation:** Phase 2.1 adds two-tier validation: exact hash (primary) with tolerant fallback (price within 0.1%, time within 60s). Only HARD_FAIL (no match at either tier) blocks the trade. Mismatch rate tracking alerts at >1% HARD_FAIL rate, signaling data alignment issues. Additionally, `require_vault: false` (warn-only) for 1 week during initial rollout.

**Risk 2: Vault path resolution brittleness.**
`resolve_vault_path()` scans vault folders by date, finds the latest containing the strategy. If the operator runs the vault script twice (pre and post cohort change), the latest might not be the correct one. **Mitigation:** Exact dated folder can be pinned in portfolio.yaml per-strategy as override. Default: latest.

**Risk 3: Guard adds latency to execution path.**
`verify_signal()` is a dict lookup + SHA-256 hash computation (~0.1ms). `record_trade()` updates counters + checks 3 rules (~0.01ms). Both are negligible vs MT5 network round-trip (~50-200ms). **Mitigation:** None needed. Measured overhead < 0.5ms.

---

## 5. Estimated Effort

| Phase | Scope | Hours |
|-------|-------|-------|
| Phase 1: Vault extension | Modify `backup_dryrun_strategies.py` (3 artifact additions) | 2-3h |
| Phase 2: Runtime safety | `guard_bridge.py` (new, ~60 lines), `strategy_guard.py` (`from_vault` classmethod, ~30 lines), `main.py` (3 insertions, ~25 lines total) | 4-5h |
| Phase 2.1: Robust signal validation | Two-tier `validate_signal()`, `SignalResult`, `MismatchTracker`, `_signal_details` index | 2h |
| Phase 3: Promotion flow | Workflow doc edits (2 files), `portfolio.yaml` schema addition | 1h |
| Phase 4: Dead code | Archive 2 files, rewrite `validate_safety_layers.py` | 2-3h |
| Phase 5: Verification | 5 tests in rewritten validate script + mismatch rate test | 2-3h |
| **Total** | | **13-17h** |

### Suggested Implementation Order

```
Day 1 (5-6h): Phase 1 + Phase 4
  - Extend vault script (test by running backup)
  - Archive golive, fix validate script
  - Verify: vault now contains full deployment contract

Day 2 (6-7h): Phase 2 + Phase 2.1
  - Add from_vault() to strategy_guard.py
  - Implement two-tier validate_signal() + SignalResult + _signal_details
  - Write guard_bridge.py with MismatchTracker
  - Insert 3 hooks in main.py
  - Test with require_vault: false (warn-only)

Day 3 (2-4h): Phase 3 + Phase 5
  - Update workflow docs
  - Run 6 verification tests (5 original + mismatch rate test)
  - Monitor mismatch rates for 1 week
  - Switch require_vault: true after clean run
```

---

## 6. Acceptance Criteria

### Test 1: Signal Integrity
- Construct guard from vault
- Call `verify_signal()` with correct params -> no exception
- Call `verify_signal()` with entry_price + 1.0 -> `SignalMismatchError`
- Automated: yes (validate_safety_layers.py test 3)

### Test 2: Kill-Switch (Loss Streak)
- Construct guard from vault
- Call `record_trade(-10.0)` N times where N > max_historical_streak * 1.5
- Expect `StrategyHaltedError` with reason containing "LOSS_STREAK"
- Automated: yes (validate_safety_layers.py test 4)

### Test 3: Profile Tamper Detection
- Construct guard from vault
- Read `selected_profile.json`, change `sizing.fixed_risk_usd` from 50 to 75
- Reconstruct guard -> expect `RuntimeError` at profile hash verification
- Automated: yes (validate_safety_layers.py test 5 - new)

### Test 4: Reproducibility
- Run vault backup for a strategy
- Compare `meta.json:config_hash` vs `directive.txt` SHA-256[:16]
- Compare `selected_profile.json:profile_hash` vs recomputed hash from PROFILES dict
- Both must match
- Automated: yes (validate_safety_layers.py test 1 - extended)

### Test 5: End-to-End Promotion
- Run pipeline for test strategy -> PORTFOLIO_COMPLETE
- Run vault backup -> verify all 3 new artifacts exist
- Start TS_Execution with `require_vault: true` -> guard constructs successfully
- Inject one bar -> dispatch fires with guard active
- Automated: partial (startup portion yes, full bar-loop requires MT5 connection)

### Test 6: Mismatch Rate Tracking
- Construct guard from vault
- Call `validate_signal()` with 100 signals: 95 exact, 3 with price_delta=0.0005 (SOFT), 2 with price_delta=5.0 (HARD)
- Verify: `tracker.exact == 95`, `tracker.soft == 3`, `tracker.hard == 2`
- Verify: HARD rate = 2% > 1% threshold -> alert logged
- Verify: SOFT rate = 3% < 10% threshold -> no soft alert
- Automated: yes (validate_safety_layers.py test 6)

---

## 7. Backwards Compatibility Assessment

Audit date: 2026-04-03. Every planned change was traced against all consumers in both Trade_Scan and TS_Execution.

### 7.1 Phase 1 — Vault Extension: FULLY COMPATIBLE

| Change | Consumers | Impact |
|--------|-----------|--------|
| Add `selected_profile.json` to vault | `dry-run-vault.md` Step 3 inline script | NONE -- reads only `index.json` and `meta.json` by specific keys; ignores unknown files |
| Add `broker_specs_snapshot/` dir | None | NONE -- no code enumerates vault subdirectories |
| Add `deployable/{PROFILE}/` dir | None | NONE -- `deployable/` already exists in vault (profile_comparison.json); new files are additive |
| Add new keys to `meta.json` | `dry-run-vault.md` Step 3 | NONE -- accesses `code_version.git_commit` and `config_hash` only; Python dicts ignore extra keys |
| Add new keys to `index.json` | `dry-run-vault.md` Step 3 | NONE -- accesses `git_commit` and `strategies` only |

**Zero programmatic consumers** of vault exist in TS_Execution. The `guard_bridge.py` (Phase 2) will be written against the new layout from scratch.

### 7.2 Phase 2 + 2.1 — Strategy Guard: REQUIRES COMPAT SHIM

**Breaking change identified:** The plan originally proposed renaming `verify_signal()` to `validate_signal()` with a different return type (`SignalResult` instead of `None`/raise).

**Consumers of `verify_signal()`:**

| File | Lines | Call Pattern |
|------|-------|-------------|
| `tools/validate_safety_layers.py` | 162, 169 | `guard.verify_signal(...)` expecting `None` return or `SignalMismatchError` |

**Resolution: Keep `verify_signal()` as a backwards-compatible wrapper.**

```python
# strategy_guard.py — backwards-compatible approach

def validate_signal(self, trade_id, symbol, entry_timestamp, direction,
                    entry_price, risk_distance,
                    price_tolerance=0.001, time_window_s=60) -> SignalResult:
    """Two-tier verification. Returns SignalResult (never raises)."""
    # ... new two-tier logic ...
    return SignalResult(status=..., ...)

def verify_signal(self, trade_id, symbol, entry_timestamp, direction,
                  entry_price, risk_distance) -> None:
    """Original API. Raises SignalMismatchError on exact-hash mismatch.
    DEPRECATED: use validate_signal() for two-tier matching."""
    result = self.validate_signal(
        trade_id, symbol, entry_timestamp, direction,
        entry_price, risk_distance,
        price_tolerance=0.0, time_window_s=0  # exact-only mode
    )
    if result.status == "HARD_FAIL":
        raise SignalMismatchError(
            f"Signal hash mismatch for {trade_id}: {result.hash}"
        )
```

This preserves:
- `verify_signal()` signature unchanged (6 positional args)
- `SignalMismatchError` still raised on mismatch
- Return type still `None` on success
- Existing tests in `validate_safety_layers.py` pass without modification

New code (guard_bridge, main.py hooks) uses `validate_signal()` exclusively.

**Other strategy_guard.py additions — all pure additive:**

| Addition | Breaking? |
|----------|-----------|
| `from_vault()` classmethod | NO -- `from_golive_package()` preserved |
| `SignalResult` dataclass | NO -- new name, no collision |
| `_signal_details` attribute | NO -- private, underscore-prefixed |
| `MismatchTracker` class (in guard_bridge.py) | NO -- new file |

### 7.3 Phase 2 — TS_Execution main.py: REQUIRES DESIGN CORRECTIONS

The audit identified 5 issues with the original insertion plan. All are solvable without breaking existing behavior.

**Issue 1 (HIGH): Unhandled guard exception leaves `pending_signal` set forever.**

If `validate_signal()` or any guard code raises an uncaught exception before line 278 (`slot.pending_signal = None`), the signal is never cleared and re-fires every bar indefinitely.

**Fix:** Wrap guard calls in try/except. On any guard exception, clear `pending_signal` and log:

```python
# STEP 2, before _dispatch:
try:
    result = slot.guard.validate_signal(...)
    if result.status == "HARD_FAIL":
        slot.pending_signal = None  # clear BEFORE continue
        continue
except Exception as exc:
    log.error(f"[GUARD] Exception in validate_signal: {exc}")
    slot.pending_signal = None
    continue  # fail-open: skip this signal, don't dispatch
```

**Issue 2 (HIGH): PnL not available after dispatch — only after reconcile on a future bar.**

`_dispatch()` sends the order but returns `None`. PnL is only known when `reconcile_positions()` detects the close on a later bar. The original plan called `guard.record_trade(pnl)` immediately after dispatch, which is impossible.

**Fix:** Deferred kill-switch evaluation. Two options:

**Option A (recommended): Hook into reconcile exit detection.**
When `reconcile_positions()` detects a closed position (RECONCILE_CLOSED), it has the exit price and can compute PnL. Add `guard.record_trade(pnl)` there. This is STEP 1 of the next bar, not STEP 2 of the current bar.

**Option B: Shadow trade logger already captures PnL.** The `ShadowTradeLogger` at line 275-277 appends entry data. On close (detected in reconcile), it logs PnL. The guard could subscribe to the shadow logger's close events.

Revised per-bar flow (corrected):

```
1. STEP 1: reconcile_positions()
   [NEW] for each newly closed position:
     pnl = (exit_price - entry_price) * direction * lot
     slot.guard.record_trade(pnl)
     -> StrategyHaltedError: set slot.enabled=False, log HALT
2. STEP 2: execute previous signal
   for each slot with pending_signal:
     a. [NEW] result = slot.guard.validate_signal(signal_hash, symbol, ...)
        [wrapped in try/except, clears pending_signal on any failure]
        if HARD_FAIL: clear pending_signal, continue
     b. _dispatch(slot) -> order_send()
3. STEP 3: generate new signals [unchanged]
```

**Issue 3 (MEDIUM): No `trade_id` in `pending_signal` — only `signal_hash`.**

`pending_signal` contains `signal_hash` (hex string) but no `trade_id`. MT5 ticket is assigned post-dispatch. The guard's `validate_signal()` expects `trade_id` as its first arg.

**Fix:** Use `signal_hash` as the correlation key. The `validate_signal()` call can pass `signal_hash` instead of `trade_id` for the exact-match tier. For the tolerant tier, it uses `symbol + direction + entry_price + timestamp` which are all available on the slot.

**Issue 4 (MEDIUM): Guard veto drops signal with no audit trail.**

If the guard blocks a dispatch, the signal disappears silently (no shadow trade logged, no executed_signals entry).

**Fix:** Log GUARD_BLOCKED to `ShadowTradeLogger` so blocked signals are auditable:
```python
if result.status == "HARD_FAIL":
    shadow_logger.append_guard_blocked(slot, result)
    slot.pending_signal = None
    continue
```

**Issue 5 (MEDIUM): Thread safety.**

Each `TimeframeGroup` runs in its own thread. Guards are per-slot (assigned in `construct_guards()`), and each slot belongs to exactly one group. **No cross-thread sharing of guard state.** The `MismatchTracker` in `guard_bridge.py` is the only potentially shared object (if global). **Fix:** Use one tracker per group, or use a thread-safe counter (`threading.Lock` on increment).

### 7.4 Phase 3 — portfolio.yaml: FULLY COMPATIBLE

The `load_portfolio()` parser uses `yaml.safe_load()` + `config.get("execution", {})`. Individual keys accessed via `.get()` with defaults. **No strict schema validation.** Adding `vault_root` (string) and `require_vault` (bool) to the `execution:` block is safe — unknown keys are silently ignored by all existing code.

**One defensive note:** YAML parses `require_vault: 1` as integer, not bool. Guard code should use `bool(exec_config.get("require_vault", False))` for robustness.

### 7.5 Phase 4 — Dead Code: FULLY COMPATIBLE

| Change | Consumers | Impact |
|--------|-----------|--------|
| Archive `generate_golive_package.py` | Zero Python importers | NONE |
| Archive `test_generate_golive_package_helpers.py` | Zero (test file, not imported) | NONE |
| Rewrite `validate_safety_layers.py` | Zero importers; standalone script | NONE — already broken, rewrite improves state |

**Vault snapshot concern:** `vault/snapshots/DR_BASELINE_2026_03_23_v1_5_3/tools/validate_safety_layers.py` is a frozen copy. It will remain broken (pre-existing). Vault snapshots are immutable — do not modify.

### 7.6 Summary: Required Compatibility Measures

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| 1 | `verify_signal()` rename breaks `validate_safety_layers.py` | Keep as deprecated wrapper calling `validate_signal()` | 15 min |
| 2 | Guard exception leaves `pending_signal` set forever | try/except wrapper, clear on any failure | 15 min |
| 3 | PnL not available after dispatch | Move `record_trade()` to reconcile exit path (STEP 1) | 30 min |
| 4 | No `trade_id` in `pending_signal` | Use `signal_hash` as correlation key | 15 min |
| 5 | Guard veto drops signal silently | Log GUARD_BLOCKED to shadow_logger | 15 min |
| 6 | Thread safety on MismatchTracker | Per-group tracker or Lock on increment | 15 min |
| 7 | `require_vault` type coercion | `bool(exec_config.get(...))` | 5 min |
| **Total additional effort** | | | **~2h** |

**Final verdict:** All changes are backwards compatible provided the 7 measures above are applied. No existing test, workflow, or production code path will break. The `verify_signal()` shim preserves the existing exception-based API while the new `validate_signal()` provides the two-tier return-value API for new code.

---

---

## 8. TS_Execution Write Surface (Documented 2026-04-12)

All TS_Execution writes stay within `TS_Execution/` — there are **zero backward writes** to TradeScan_State.

### 8.1 Core Execution Writes (`TS_Execution/outputs/`)

| File | Writer | Purpose | Pattern |
|------|--------|---------|---------|
| `outputs/logs/heartbeat.log` | `src/heartbeat.py` | Periodic heartbeat timestamps (60s) + RUN_START/RUN_END | Append |
| `outputs/logs/execution_state.json` | `src/main.py` | `{run_id, last_bar_time, bar_count}` per bar | Atomic replace |
| `outputs/logs/execution.pid` | `src/main.py` | Execution process PID | Overwrite |
| `outputs/logs/pending_signals.json` | `src/state_persistence.py` | Pending signals, shadow positions (survives restarts) | Atomic replace |
| `outputs/journal/SignalJournal.jsonl` | `src/signal_journal.py` | Pre-dispatch signals (write-before-send, fsync'd) | Append + fsync |
| `outputs/journal/ExecutedSignals.jsonl` | `src/signal_journal.py` | Post-fill trades (MT5 confirmed) | Append |
| `outputs/shadow_trades.jsonl` | Shadow logger | Shadow trade journal | Append |
| `outputs/run_registry.json` | `src/main.py` | Active burn-in run registry | Atomic replace |
| `outputs/symbol_specs_mt5.json` | Symbol spec cache | Cached MT5 symbol specifications | Overwrite |

### 8.2 Orchestration Writes (from `Trade_Scan/tools/orchestration/`)

These tools run from Trade_Scan but write into TS_Execution. This is **by design** — they are operational launchers, not research tools.

| File | Writer | Purpose | Pattern |
|------|--------|---------|---------|
| `outputs/logs/startup_launcher.log` | `startup_launcher.py` | Launch attempt timestamps (rotates at 5MB) | Append |
| `outputs/logs/watchdog_daemon.log` | `watchdog_daemon.py` | 60s polling cycle log (rotates at 5MB) | Append |
| `outputs/logs/watchdog_guard.json` | `watchdog_daemon.py` | Kill-switch state (restart count, loss streak) | Atomic replace |
| `outputs/logs/watchdog.pid` | `watchdog_daemon.py` | Watchdog process PID | Overwrite |

### 8.3 Burn-in Monitoring (`TS_Execution/outputs/burnin/`)

| File | Writer | Purpose | Pattern |
|------|--------|---------|---------|
| `outputs/burnin/BURNIN_*.md` | `tools/burnin_monitor.py` | Daily burn-in metrics appended to governance doc | Read-modify-write |

**History:** Previously wrote to `TradeScan_State/strategies/{ID}/BURNIN_*.md` (backward write violation V6). Relocated to `TS_Execution/outputs/burnin/` on 2026-04-12. One-time migration copies existing doc on first run.

### 8.4 What TS_Execution Does NOT Write

- **TradeScan_State/** — read-only consumer (portfolio_evaluation, deployable, run metadata)
- **Trade_Scan/** — never accessed at runtime
- **DRY_RUN_VAULT/** — read-only (vault snapshots are immutable)
- **portfolio.yaml** — only modified by `promote_to_burnin.py` (Trade_Scan tool), never by TS_Execution runtime

---

### Cross-References (2026-04-12)

- **Classification gates**: `CLASSIFICATION_REFERENCE.md` — CORE/WATCH/FAIL thresholds across filter_strategies, portfolio_evaluator, and promote quality gate
- **Promotion friction audit**: `PROMOTION_FRICTION_AUDIT.md` — all 7 friction points + R6-R10 robustness recommendations (FULLY IMPLEMENTED)
- **Promote workflow**: `.agents/workflows/promote.md` — updated with `--composite`, `--batch`, `--batch-all`, readiness dashboard, all-or-nothing per-symbol gate

*Generated: 2026-04-03 | Compatibility audit: 2026-04-03 | Write surface documented: 2026-04-12 | Status updated: 2026-04-12*
