# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-06-30T17:20:54Z
>
> SESSION SNAPSHOT — regenerated at session **start and end** (`python tools/system_introspection.py`).
> If `Generated:` is >16 h old this file is stale — re-run before trusting the numbers.
> Ephemeral content only. Durable entries (invariant proposals, code-cited decisions) belong in `INVARIANT_PROPOSALS.md`.

## Engine
- **Version:** 1.5.11 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 4 directives

## Ledgers

- **Master Filter:** 33 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 0 rows — no status column
  - **Single-Asset Composites:** 0 rows — no status column

- **Candidates (FPS):** 20 rows — FAIL: 8, WATCH: 12

## Portfolio (TS_Execution)
- **Total entries:** 0 | **Enabled:** 0
- LIVE: 0 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 19 | Latest: `DRY_RUN_2026_06_09__ca6acb78`

## Data Freshness
- Latest bar: **2026-06-26** | Symbols: 221

## Artifacts
- Run directories: 496

## Git Sync
- Remote: IN SYNC (vs `origin/main`)
- Working tree: clean
- Last substantive commit: `037673ba docs(diagnostics): Diagnostic Contract framework-wide design proposal`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- (none — no drift signals exceed threshold this session)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen (system_introspection preserves this block); the auto-detected sections above do not. Keep to ~12 lines (system_introspection warns >12, SESSION STATUS WARNING >20). -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced); promote to BUILD after a gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence, screener block ~3 min/run; promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass; promote to BUILD when a 2nd refresh use-case needs the auth path. First seen 2026-06-07.
- [DRIFT] retire backlog (~330 superseded runs un-retired) — un-actionable until rerun-backtest Phase-C retire tooling is built; defer, not a fire. First seen 2026-06-20.
- [BACKLOG] smaller deferred items: Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, skill-refactor D+F, basket weekend-flatten policy (detail in git history — the 06-06 backlog doc was pruned in `30ec963b`).

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-06-16T08:14:14+00:00 @ ae7e29ae.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Active Charter — (none — PARKED 2026-06-29)

> **No active charter.** The 2026-06-20 infra-freeze charter was fulfilled + PARKED 2026-06-29 (freeze lifted, v1.5.11 Patch A canonical, demo fleet stood down). 2026-06-30: engine compute + ABI consolidations completed (single active engine + single ABI) → the `CURRENT`/`LIVE_ABI` dispatch-convergence follow-up is now largely MOOT (nothing left to select). History → [[project_v1_5_11_patch_a_canonical]] + [[project_engine_consolidation_2026_06_30]]. Set a new charter when the next multi-session focus is chosen.

#### Next-session direction — set 2026-06-30

> **Research (primary — pick fresh):** no active arc. The legacy→fresh-genesis migration path is now *proven* (VOLPULL ideas 73/74/75 ran clean per-symbol) and the `archive/Old directives Archive/` dump (110 files, incl. IDX22-28 / SPX01-04) is a genesis idea-source — continue mining it, or open a new family.
>
> **Infra (queued — only if friction repeats):** Diagnostic Contract **Phase 2** (breadth + auto-fix dispatch; design in `outputs/system_reports/04_governance_and_guardrails/DIAGNOSTIC_CONTRACT_PROPOSAL_2026-06-30.md`). The 2026-06-30 pipeline-friction stress test (old v1.2.1 XAUUSD port) located the next frontier for old-strategy migrations: **VERSION DRIFT** — pipeline/identity/known-gotcha friction is eliminated *everywhere*, but genuinely-old strategies hit indicator-path moves (`price.rsi`→`momentum.rsi`) and indicators lacking `SIGNAL_PRIMITIVE` under the current declare-only-signal contract (`ema_slope`), surfaced as **bare messages** (what, not where/remedy).
>
> **Friction log (carry forward — mechanism only on repeat, per [[feedback_research_throughput_over_infra]]):** `STOP_CONTRACT_VIOLATION` (close-anchored stop vs next_bar_open — hit 2 migrations, nearing mechanism threshold), indicator-path-drift, provisioner-won't-fix-wrong-import, `SIGNAL_PRIMITIVE`-missing.
>
> **Housekeeping:** two OS-locked leftover worktree dirs (`.claude/worktrees/suspicious-greider-aa8e36`, `condescending-payne-9a755a`) — git-deregistered + branches deleted; sweep next session if the dirs still resolve.
