# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-07-02T15:20:37Z
>
> SESSION SNAPSHOT — regenerated at session **start and end** (`python tools/system_introspection.py`).
> If `Generated:` is >16 h old this file is stale — re-run before trusting the numbers.
> Ephemeral content only. Durable entries (invariant proposals, code-cited decisions) belong in `INVARIANT_PROPOSALS.md`.

## Engine
- **Version:** 1.5.11 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 37 directives

## Ledgers

- **Master Filter:** 93 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 7 rows — FAIL: 7
  - **Single-Asset Composites:** 0 rows — no status column

- **Candidates (FSP):** 72 rows — FAIL: 62, WATCH: 10

## Portfolio (TS_Execution)
- **Total entries:** 0 | **Enabled:** 0
- LIVE: 0 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 19 | Latest: `DRY_RUN_2026_06_09__ca6acb78`

## Data Freshness
- Latest bar: **2026-07-02** | Symbols: 221

## Artifacts
- Run directories: 527

## Git Sync
- Remote: IN SYNC (vs `origin/main`)
- Working tree: clean
- Last substantive commit: `056ee0c1 fix(engine): warmup resolver supports max/min in formulas`

## Deferred Maintenance

> Hygiene tasks deliberately not done this session. NOT problems — see `## Known Issues` below for actual problems. Available to address whenever convenient; nothing here is blocking.

### Auto-detected (regenerated each run)
- (none — no drift signals exceed threshold this session)

### Manual (operator-deferred items)
<!-- Operator-deferred items persist across regen (system_introspection preserves this block); the auto-detected sections above do not. Keep to ~12 lines (system_introspection warns >12, SESSION STATUS WARNING >20). -->
- [MONITOR] conclusion-write-path provenance gate — ungated auto-memory (AGENT.md #31 STOP-doctrine, not mechanically enforced); promote to BUILD after a gate-shakeout session. First seen 2026-05-29.
- [MONITOR] cointegration screener write-volume/runtime — 4h cadence, screener block ~3 min/run; promote when block > 8 min. First seen 2026-06-07.
- [MONITOR] repeat_override_reason refresh-auth debt — `refresh_cointegration.py` reuses the Idea-Gate REPEAT_FAILED bypass; promote to BUILD when a 2nd refresh use-case needs the auth path. First seen 2026-06-07.
- [DRIFT] retire backlog (18 superseded runs un-retired, per `retire_runs.py --drift-check`) — +6 this session: the SPX500 pricing-repair reruns (aa2a6d55/51d49c9b/3344c466/fb181760/328eb0cf/e96fc2fc, quarantined 2026-07-02, superseded by the pricing_units_per_lot fix `c824f223`), Phase-C not run. Un-actionable until rerun-backtest Phase-C retire tooling is built; defer, not a fire. First seen 2026-06-20; count refreshed 2026-07-02.
- [BACKLOG] smaller deferred items: Z-cross Phase-3, market_regime NaN, BASKET_REPORT polish, skill-refactor D+F, basket weekend-flatten policy (detail in git history — the 06-06 backlog doc was pruned in `30ec963b`).

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-06-16T08:14:14+00:00 @ ae7e29ae.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Active Charter — (none — PARKED 2026-06-29)

> **No active charter.** The 2026-06-20 infra-freeze charter was fulfilled + PARKED 2026-06-29 (freeze lifted, v1.5.11 Patch A canonical, demo fleet stood down). 2026-06-30: engine compute + ABI consolidations completed (single active engine + single ABI) → the `CURRENT`/`LIVE_ABI` dispatch-convergence follow-up is now largely MOOT (nothing left to select). History → [[project_v1_5_11_patch_a_canonical]] + [[project_engine_consolidation_2026_06_30]]. Set a new charter when the next multi-session focus is chosen.

#### Next-session direction — set 2026-06-30, updated 2026-07-02

> **Research (primary — HIGH-ROI pick, set 2026-07-02): timeframe-relative minimum trade-count criterion.** The candidate/promote gates apply a flat absolute `trades >= N` threshold, which structurally penalizes higher-timeframe strategies — a daily strategy over a rolling 2yr window *cannot* produce the same trade count as 1h/4h, so a real daily edge FAILs on count alone (SPX500 daily RSIPULL MR: 27 trades, PF 4.99, SQN 3.39 — the FAIL was administrative trade-count, not edge quality). Investigate: scale the min-trades threshold by timeframe (bars-per-year), OR gate on trades-per-year / statistical sufficiency (SQN or a min-N-for-CI) instead of an absolute count. Locate the gate(s) in `filter_strategies.py` `_compute_candidate_status` + any promote-readiness thresholds; audit checker logic before changing (per `feedback_audit_checker_before_ledger`). Distinct from the deployment screening rule (that's a governance gate, not a research ranker — `feedback_screening_rules_for_research`).
>
> **Research (secondary — pick fresh):** legacy→fresh-genesis migration is *proven* (VOLPULL ideas 73/74/75 ran clean per-symbol); the `archive/Old directives Archive/` dump (110 files, incl. IDX22-28 / SPX01-04) + the untracked `backtest_directives/hypotheses/VAULT_RESERVE_2026-07-02/` idea bank (23 StatOasis hypotheses, committed `ff2077c1`) are genesis idea-sources.
>
> **Infra (queued — only if friction repeats):** Diagnostic Contract **Phase 2** (breadth + auto-fix dispatch; design in `outputs/system_reports/04_governance_and_guardrails/DIAGNOSTIC_CONTRACT_PROPOSAL_2026-06-30.md`). The 2026-06-30 pipeline-friction stress test (old v1.2.1 XAUUSD port) located the next frontier for old-strategy migrations: **VERSION DRIFT** — pipeline/identity/known-gotcha friction is eliminated *everywhere*, but genuinely-old strategies hit indicator-path moves (`price.rsi`→`momentum.rsi`) and indicators lacking `SIGNAL_PRIMITIVE` under the current declare-only-signal contract (`ema_slope`), surfaced as **bare messages** (what, not where/remedy).
>
> **Friction log (carry forward — mechanism only on repeat, per [[feedback_research_throughput_over_infra]]):** `STOP_CONTRACT_VIOLATION` (close-anchored stop vs next_bar_open — hit 2 migrations, nearing mechanism threshold), indicator-path-drift, provisioner-won't-fix-wrong-import, `SIGNAL_PRIMITIVE`-missing.
>
> **Housekeeping:** chip-task worktree `awesome-bassi-a5a563` (rerun_backtest fix) merged via cherry-pick `ec28ab6e` + branch deleted + worktree deregistered 2026-07-02; its physical dir under `.claude/worktrees/` was held by a lingering process (`Device or resource busy`) at close — gitignored so it doesn't pollute status; sweep on next `/repo-cleanup-refactor` or reboot. `git worktree list` shows only the main checkout.
