# Adversarial Infrastructure Audit

**Date:** 2026-05-03
**Anchors:** `FRAMEWORK_BASELINE_2026_05_03` / `EVENT_READY_BASELINE_2026_05_03`
**Type:** Read-only adversarial scan. No code modified, no tests run, no patches authored.
**Scope:** `tools/`, `governance/`, `engines/`, `tests/`, current backlog, manifests, SOPs.
**Method:** Five parallel category audits, synthesized below.

---

## Executive summary

The framework's race-class surface (admission, classifier, approval markers, sweep collisions, hook routing) is materially better than 30 days ago. **23 distinct findings** remain across five categories. The dominant pattern across the strongest findings is the same as the issues we just closed: **silent degradation paths that look like success at the orchestrator level**, often involving filesystem state (mtime, cache, locks) or cross-platform behavior (encoding, timezone, worktree path resolution).

Three findings are **CRITICAL**, six are **HIGH**, eight are **MEDIUM**, six are **LOW**.

The single highest-leverage fix is documented at the end of this report.

---

## CRITICAL (3)

### C1 — `PROJECT_ROOT.parent` worktree divergence in state_paths

**File:** [config/state_paths.py:29](config/state_paths.py:29)
```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"
```

**Reproduction:** From a git worktree at `Trade_Scan/.claude/worktrees/<NAME>/`, `__file__` resolves to `.claude/worktrees/<NAME>/config/state_paths.py`, so `parents[1]` = `<NAME>/`, and `STATE_ROOT` becomes `worktrees/TradeScan_State` (which doesn't exist) instead of the shared sibling `Trade_Scan/../TradeScan_State`. **Every downstream state read/write silently routes to a different (or empty) location.**

**Why current tests missed it:** Tests run from the main checkout cwd; `PROJECT_ROOT.parent` happens to resolve correctly there. There is no test that loads `state_paths.py` from a worktree's perspective.

**Affects:** research integrity (results land in wrong dir), execution integrity (pipeline can't find its state), governance integrity (registries diverge between worktree and main).

**Suggested fix:** Replace with `git rev-parse --show-toplevel` resolution OR add an environment-variable override (`TRADE_SCAN_ROOT`) and a startup assertion that `PROJECT_ROOT/strategies/` exists. Single-file change, ~5 lines.

---

### C2 — Manifest integrity gate uses mtime instead of hash

**File:** [tools/run_pipeline.py:403](tools/run_pipeline.py:403)
```python
if filepath.stat().st_mtime > manifest_mtime:
    raise PipelineExecutionError(
        f"Tool modified after manifest generation: {filename}. "
```

**Reproduction:** (a) Modify a tool. (b) Run `python tools/generate_guard_manifest.py` to regenerate manifest. (c) Pipeline accepts the modified tool because its mtime is now ≤ the new manifest mtime — even though the manifest's recorded hash is stale relative to whatever was checked in. (d) Or: on Windows NTFS with sub-second mtime precision, two near-simultaneous writes can race the comparison.

**Why current tests missed it:** No regression test catches the "regenerate-then-pass" loop. The whole point of the manifest is content integrity, but the run-time check is timestamp-only. The framework race we already fixed (admission marker mtime race) was the same class of bug; this is the same disease in a different file.

**Affects:** governance integrity (drift can be re-baselined silently), execution integrity (race-prone on Windows).

**Suggested fix:** Replace mtime check with sha256 comparison against the manifest's recorded hash. Pattern is identical to what `tools/approval_marker.py::is_approval_current` already does for strategies. `tools/generate_guard_manifest.py` already records hashes — just consume them at gate time.

---

### C3 — Direct sweep_registry write bypassing the lock-protected API

**File:** [tools/orchestration/pre_execution.py:227](tools/orchestration/pre_execution.py:227)
```python
registry_path.write_text("\n".join(lines), encoding="utf-8")
```

**Reproduction:** `enforce_signature_consistency` (the auto-consistency gate) updates `sweep_registry.yaml` via direct `read_text` → string-replace → `write_text`, **without** acquiring `SWEEP_LOCK_PATH`. Concurrent invocation (rare but possible: parallel orchestrators, retry-after-crash) corrupts the registry; the second writer clobbers the first's signature_hash_full updates.

**Why current tests missed it:** This is exactly the class of bug INFRA-NEWS-009 (sweep slot collision) closed at one entry point, but the auto-consistency gate is a SECOND entry point with the same vulnerability. Our fix didn't audit for additional bypasses.

**Affects:** governance integrity (registry corruption), research integrity (silent loss of hash records).

**Suggested fix:** Refactor `_update_sweep_registry_hash` to call `tools/sweep_registry_gate.py::reserve_sweep_identity` (or a sibling helper that takes the lock). Aligns with the canonical API enforced by `register_sweep_stub.py`.

---

## HIGH (6)

### H1 — Identical STRATEGY_SIGNATURE blocks across distinct strategies (PORT/MACDX-class)

**Already partially documented** as INFRA-NEWS-006 ([outputs/PORT_MACDX_DUPLICATION_DIAGNOSIS.md](outputs/PORT_MACDX_DUPLICATION_DIAGNOSIS.md)). The audit found this is not isolated: the architecture (signature_hash as identity) is fundamentally vulnerable to two strategies producing byte-identical signatures, which makes them indistinguishable in `sweep_registry_gate`'s idempotency lookup.

**Affects:** research integrity (one strategy "shadows" another in registry lookups), discovery accuracy (NEWS_AMPLIFIED bucket double-counted PORT and MACDX).

**Suggested fix:** Salt the signature hash with the strategy's full file path (or canonical name), so two strategies with identical SIGNATURE blocks but different names produce different hashes. ~3-line change in `tools/strategy_provisioner.py`.

---

### H2 — Encoding default cp1252 on Windows for state files

Six instances of `open()` / `json.load()` without `encoding="utf-8"`:

- [tools/orchestration/watchdog_daemon.py:159](tools/orchestration/watchdog_daemon.py:159), [:175](tools/orchestration/watchdog_daemon.py:175), [:252](tools/orchestration/watchdog_daemon.py:252), [:263](tools/orchestration/watchdog_daemon.py:263)
- [tools/create_audit_snapshot.py:105](tools/create_audit_snapshot.py:105), [:109](tools/create_audit_snapshot.py:109)
- [tools/capital/capital_broker_spec.py:87](tools/capital/capital_broker_spec.py:87)
- [tools/robustness/loader.py:40](tools/robustness/loader.py:40), [:54](tools/robustness/loader.py:54)

**Reproduction:** Windows defaults to cp1252; Linux defaults to utf-8. A JSON state file written on one platform with any non-ASCII byte (em-dash in a comment, currency symbol, etc.) can fail to parse on the other. Already burned us in this session at `tools/run_stage1.py` (CSV with mixed-format timestamps from a multi-locale environment).

**Why current tests missed it:** `tools/lint_encoding.py` exists but its scan is not exhaustive — it misses some `with open(...)` patterns and doesn't follow nested module imports. Watchdog state files are not exercised by unit tests.

**Affects:** execution integrity, reproducibility across machines, watchdog reliability (state file write failures stall startup).

**Suggested fix:** Tighten `tools/lint_encoding.py` to grep more aggressively, add CI check that fails on any new `open(*, "r")` without `encoding=`. Then sweep-fix the 6 known instances.

---

### H3 — Naive `datetime` / `pd.to_datetime` without `utc=True`

- [tools/create_audit_snapshot.py:95](tools/create_audit_snapshot.py:95): `datetime.utcnow().isoformat()` — naive, no tz
- [tools/robustness/loader.py:29-30](tools/robustness/loader.py:29-30), [:37](tools/robustness/loader.py:37): `pd.to_datetime(...)` without `utc=True`
- [governance/preflight.py:108](governance/preflight.py:108), [:110](governance/preflight.py:110): naive parse, then compared to `pd.Timestamp.now()` (aware, **local TZ**) at line 112
- [data_access/readers/research_data_reader.py:139](data_access/readers/research_data_reader.py:139)

**Reproduction:** A naive timestamp compared to a tz-aware one in pandas raises silently inconsistent results depending on pandas version (sometimes warns, sometimes returns False blanket-comparing all rows). Different machines on different local TZs interpret the same CSV's "2025-06-01 12:00" differently relative to "now".

**Why current tests missed it:** No tz-mismatched test fixtures. Pre-flight DATA_RANGE checks use machine-local "now" silently.

**Affects:** research integrity (data-coverage gate can pass/fail differently across machines), reproducibility.

**Suggested fix:** Sweep replace `datetime.utcnow()` → `datetime.now(timezone.utc)` and `pd.to_datetime(...)` → `pd.to_datetime(..., utc=True)`. Mechanical, low-risk.

---

### H4 — Engine v1.5.8 hash anomaly preserved as "HISTORICAL ANOMALY, NO MUTATION"

**File:** [governance/engine_lineage.yaml:73-102](governance/engine_lineage.yaml:73-102)

The vaulted v1.5.8 manifest's recorded hash for `execution_loop.py` does not match either the canonical hash of the vaulted file OR the engine_dev source at any commit. The discrepancy is documented as a historical anomaly with no root-cause explanation.

**Reproduction:** `python tools/verify_engine_integrity.py` against v1.5.8 should fail or warn. Either the manifest is wrong or the file is. We don't know which.

**Why current tests missed it:** Tests treat the recorded hash as authoritative; they don't cross-check vault contents against any external authority (e.g., git tree-of-record).

**Affects:** governance integrity. If we ever need to legally / compliance-wise certify "this is the engine that ran this strategy," we cannot — the hash chain is broken at v1.5.8 and the issue is undocumented beyond "historical."

**Suggested fix:** Forensic dig — check git history for v1.5.8 manifest and execution_loop.py contemporaneous; if no clean reconstruction exists, formally write off v1.5.8 as untrusted in `engine_lineage.yaml` (don't rely on it for any active strategy). v1.5.8a (the active engine) is unaffected — but the lineage chain has a broken link.

---

### H5 — Stranded PID files block startup with no TTL

- [tools/orchestration/watchdog_daemon.py:342-343](tools/orchestration/watchdog_daemon.py:342-343): `WDOG_PID` cleanup via `atexit` only (lost on SIGKILL)
- [tools/orchestration/watchdog_daemon.py:189-223](tools/orchestration/watchdog_daemon.py:189-223): `EXEC_PID` (written by external TS_Execution) has no cleanup hook in this codebase
- [tools/state_lifecycle/lineage_pruner.py:40-46](tools/state_lifecycle/lineage_pruner.py:40-46): hard `sys.exit(1)` on corrupt PID file content (e.g., from kill -9 mid-write)

**Reproduction:** Force-kill the watchdog or TS_Execution mid-run. Re-launch. Stale PID file persists; cleanup logic relies on `psutil`/`tasklist` succeeding within timeout. On Windows with hung subprocess, blocks indefinitely.

**Why current tests missed it:** No chaos-test that kills the orchestrator mid-flight. Tests assume clean exits.

**Affects:** execution integrity (operator intervention required to recover; can't be self-healing).

**Suggested fix:** PID files include UTC timestamp; readers reject PIDs older than N hours OR PIDs whose process clearly doesn't exist (after a bounded timeout). `lineage_pruner` should treat corrupt PID as "process likely dead" not as a hard sys.exit.

---

### H6 — Broker spec cached forever in process; no invalidation

**File:** [tools/capital/capital_broker_spec.py:21-34](tools/capital/capital_broker_spec.py:21-34)
```python
_BACKTEST_BROKER_SPECS: dict = {}

def _load_broker_spec_cached(symbol: str) -> dict | None:
    if symbol in _BACKTEST_BROKER_SPECS:
        return _BACKTEST_BROKER_SPECS[symbol]
```

**Reproduction:** Within a Python session that runs multiple capital wrapper invocations, broker spec YAML edits between invocations are NOT reflected — the cache returns the first-loaded value forever.

**Why current tests missed it:** Tests usually run each test in a fresh process. Long-running orchestrator (which DOES reuse Python session across multiple directives) would hit this.

**Affects:** execution integrity. If a broker spec changes mid-session (rare but possible during research iteration), trades are sized against stale lot constraints.

**Suggested fix:** Add a `cache_invalidate_on_mtime_change` decorator OR drop the cache entirely (broker specs are tiny YAMLs).

---

## MEDIUM (8)

| # | Finding | File:Line | Severity rationale |
|---|---|---|---|
| M1 | Pre-commit hook checks staged file LIST not staged file CONTENT (engine_manifest sync guard) | [tools/hooks/pre-commit:57-77](tools/hooks/pre-commit:57-77) | User can `git add manifest.json` (no-op stage) to satisfy the hook without actually regenerating the manifest. |
| M2 | Indicator warmup defaults to 250 silently on missing INDICATOR_REGISTRY.yaml | [engines/indicator_warmup_resolver.py:43-51](engines/indicator_warmup_resolver.py:43-51) | Strategy may trade on insufficient warm-up bars when registry is corrupt. |
| M3 | `strategy_guard.py:223-229` swallows malformed trade-log rows with `except: pass` | [execution_engine/strategy_guard.py:223](execution_engine/strategy_guard.py:223) | Signal validation silently disabled when input is corrupt. |
| M4 | `audit_compliance.py:114-122` declares "PASS" on CSV exception | [tools/audit_compliance.py:114](tools/audit_compliance.py:114) | Audit claims success when it didn't actually validate anything. |
| M5 | Stem-based substring search corrupts wrong sweep registry entry | [tools/orchestration/pre_execution.py:208](tools/orchestration/pre_execution.py:208) | `if f"directive_name: {strategy_name}" in lines[i]:` matches partial names — sweep registry can be corrupted at the wrong row. |
| M6 | Regime cache len-mismatch logs but falls through to recompute, sometimes silently leaves NaN | [engines/regime_state_machine.py:195-205](engines/regime_state_machine.py:195-205) | Strategy reads NaN regime columns when downstream code expected populated values. |
| M7 | `baseline_freshness_gate.py:289-306` returns None on any of: empty CSV, missing column, OS error | [tools/baseline_freshness_gate.py:289](tools/baseline_freshness_gate.py:289) | Caller cannot distinguish "no trades" from "file corrupt." |
| M8 | `governance/preflight.py:316-320` skips run_state.json that fails to parse | [governance/preflight.py:316](governance/preflight.py:316) | Aborted runs with corrupt state files are invisible to the preflight check. |

All affect **research integrity** primarily. Suggested fixes are mostly: replace `except: pass` with `except: log`, replace silent default with raise, add an explicit "unknown / corrupt" state distinct from "absent / empty."

---

## LOW (6)

| # | Finding | File |
|---|---|---|
| L1 | `vault/root_of_trust.json` claims "human-signed" but contains no actual signature, only a sha256 | vault/root_of_trust.json |
| L2 | Pre-commit hook bypassable via `git commit --no-verify` (well-known) | tools/hooks/pre-commit |
| L3 | `RESEARCH_MEMORY.md` writes via `tools/research_memory_append.py` enforce structure but NOT source-of-call (any orchestrator can call it) | tools/research_memory_append.py |
| L4 | `sys.path.insert(0, str(PROJECT_ROOT))` in [tools/ledger_db.py:32](tools/ledger_db.py:32) depends on PROJECT_ROOT correctness (compounds C1) | tools/ledger_db.py |
| L5 | Append-only invariant of MPS/Master Filter not enforced at writer level (depends on caller discipline) | tools/portfolio/portfolio_ledger_writer.py |
| L6 | Hardcoded threshold values (RATIO_THRESHOLD, MIN_TRADES) duplicated across discovery scripts in `tmp/` and `outputs/` reports — no single source of truth | (multiple) |

---

## Top 5 risks most likely to waste time in the next 90 days

Ranked by probability × time-cost when triggered:

1. **C1 — Worktree state divergence.** Worktree workflow is increasing as a session pattern. The first time anyone runs `python tools/run_pipeline.py --all` from a worktree expecting it to share state with main, **state writes will go to a wrong (or missing) `TradeScan_State` directory.** Likely loss-window: a full sweep silently writing to `worktrees/TradeScan_State/` that gets cleaned up. Probability ≈ 70% in 90 days. Median cost ≈ 2-4 hours.

2. **C2 — Manifest integrity uses mtime, not hash.** Every pipeline run runs this gate. As session work grows, the false-positive (reject due to mtime drift) and false-negative (accept due to manifest-regen) both compound. Already burned us once this session via the analogous approval-marker race. Probability ≈ 60% in 90 days. Median cost ≈ 1-2 hours per incident.

3. **H2 — Encoding cp1252 / utf-8 mismatch on Windows state files.** Already burned us once this session (`pd.to_datetime` mixed-format CSV). Six more landmines remain. Probability ≈ 50% in 90 days. Median cost ≈ 1 hour.

4. **C3/M5 — Direct sweep_registry write (auto-consistency gate) + stem substring search.** Both are the same class as INFRA-NEWS-009 we just closed. The fix protected the API, but two other code paths still bypass it. Probability ≈ 40% (requires concurrent work or specific naming overlap). Median cost ≈ 2 hours debugging "why did the registry get corrupted?".

5. **M7/M8 — Silent corrupt-state skipping in preflight + baseline freshness.** When something goes wrong during a sweep (interrupted run, kill -9, partial CSV), the recovery path silently drops corrupt files instead of surfacing them. We've already lost time this session to "why is this directive not in directive_state?" because of exactly this pattern. Probability ≈ 80% in 90 days for *some* manifestation. Median cost ≈ 30-90 minutes per incident.

Cumulative expected lost time over 90 days from these five: **≈ 12-20 hours.**

---

## Single highest-leverage fix

**C2 — Replace mtime-based manifest guard with sha256-based content guard.**

Why this and not C1:
- C2 is the same class of bug as the framework race we already fixed for approval markers. The pattern (`is_approval_current`) is reusable. The fix is ~10 lines.
- It eliminates not just the documented vulnerability but the entire **mtime-as-integrity** code path. Future infrastructure that relies on the manifest gate becomes hash-correct by default, not symbolically-correct.
- It produces a generalizable pattern: every "is this file unchanged?" check across the codebase becomes a hash check, with a single helper. After landing, you can grep for `st_mtime` and confidently flag every remaining hit as a real bug, not a maybe-bug.
- It gives the system the same guarantee FRAMEWORK_BASELINE gave for strategy approval, but at the tooling layer.

Why not C1: C1 is more dangerous in absolute terms (silent state divergence) but it's also a single-file fix with well-understood scope. C2 is more *generalizable* and unblocks several other findings (M1 also goes away because the pre-commit hook can do hash-sync instead of file-list-sync once the helper exists).

**Estimated cost:** 30-60 minutes implementation + 3-4 regression test cases. Closes C2 directly, partially fixes M1, and produces a reusable helper that makes any remaining mtime-based guards trivial to audit and convert.

---

## What this audit does NOT claim

- Each finding is concrete (file:line + snippet) but I have NOT verified each by actually executing the failure scenario. Severity rankings are informed estimates; they could shift with empirical reproduction.
- The audit covered `tools/`, `engines/`, `governance/`, `tests/`. It did NOT cover `engine_dev/`, `vault/`, `data_root/`, `outputs/` (frozen / data / artifacts), `tmp/`, or `live_runtime/` / `parity_monitor/` (out-of-scope per directive).
- Findings about the live `parity_monitor` and TS_Execution are visible only via their PID interactions (H5); the live runtime itself is not in this repo.
- No infrastructure code was modified. No tests were run. No backtests authored. No registries / manifests / vault files / engine files / YAMLs / strategies / directives changed during this audit.

---

## Anchor

- Pre-audit: `EVENT_READY_BASELINE_2026_05_03` (`167a2d3`) + `5e7da71` (hook routing fix)
- This audit: read-only, no commits, no mutations
