# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-22T07:06:46Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 244 directives

## Ledgers

- **Master Filter:** 1256 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 131 rows — CORE: 4, FAIL: 122, WATCH: 5
  - **Single-Asset Composites:** 81 rows — CORE: 11, FAIL: 65, WATCH: 5

- **Candidates (FPS):** 381 rows — CORE: 14, FAIL: 241, LIVE: 13, RESERVE: 17, WATCH: 96

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- LIVE: 9 | RETIRED: 0 | LEGACY: 0

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-22** | Symbols: 221

## Artifacts
- Run directories: 1592

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last substantive commit: `778106d pine: combine overlay+screener; add PairTradeStrategy`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-05-21T14:12:37+00:00 @ 71d49d99.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

- **Pine PAIRX cross-signal strategy NOT deployable (2026-05-22).** Built combined Pine indicator + Pine `strategy()` script in `Pine Indicators/` to backtest the z-spread cross signal (per-leg z-score of close, then sign-of-(z_A − z_B) with hysteresis deadband, macro-aligned by daily TF z-of-spread). TradingView Strategy Tester on EURUSD with EURUSD/USDJPY source pair, 2002–2026:

  | Chart TF | Trades | Win% | PF | Net | Verdict |
  |---|---|---|---|---|---|
  | 1D | 298 (~12/yr) | 20.1 | 1.58 | +66% | tail-driven, would FAIL Edge Quality Gate |
  | 4H | 1220 (~94/yr) | 20.3 | 1.077 | +11% | edge gone — noise |
  | 1H | 1384 (~460/yr) | 16.6 | 0.971 | −2.25% | losing |

  Classic edge-decay-with-frequency pattern, same shape as ZREV/ZPULL/COINTREV (low WR + thin PF + tail-driven). Daily PF 1.58 reads OK in isolation but ~12 trades/year means a DD takes years to recover — operationally unattractive. Combined indicator (`Pine Indicators/SpreadSmaCrossScreener.txt`) retained as a discretionary screening overlay (plots per-leg normalized z-lines + table of side/macro/sz/corr per combo); strategy form (`Pine Indicators/PairTradeStrategy.txt`) retained for re-tests. **Do NOT re-open this arc without an architectural change** — different signal primitive, different macro context, basket-level harvesting on top, or fundamentally different exit mechanic. Single-lever parameter sweeps (cross_buffer, sz_window, sma_window, macro_tf) on the existing mechanic are exhausted directionally.

<!-- 2026-05-21: All four Phase 5b.3 carry-overs resolved in a dedicated session. Kept for archaeology in `git log`; remove the comment block once a few sessions have passed without regression. Resolution summary:
  • PROFILE_UNRESOLVED on 68_PORT_FX_5M_PORT_S01_V1_P05 — surgical MPS DB upsert via tmp/fix_profile_unresolved_portfolio.py; Step 7 retro-resolved RAW_MIN_LOT_V1; verdict = FAIL (one symbol misses 50-trades/yr density gate by 2).
  • .format_backups YELLOW — one-line dotdir exclusion in tools/system_preflight.py::_check_strategy_drift.
  • 359 stale master_filter rows — batch soft-archive via tmp/soft_archive_stale_master_filter.py; 350 rows flipped is_current=0 with supersede_reason='STATE_LOST'.
  • 13 broader-pytest TDs — fixture .txt restored from git (commit 7383b0a^); _build_row patched to populate verdict_status+enrichment_status; 2 dispatch tests rewritten to assert on ledger.db.basket_sheet (Phase 5b.3 sink) with explicit state pre-cleanup; tests/_fixtures/directives.yaml + new 4th signal in tools/directive_reconciler.py::is_directive_living to prevent re-purge.
-->


<!-- 2026-05-22: H3_spread V1 directional carry-overs pruned — operator confirmed the V1 BEAR/BULL directional path is retired in favor of the H3_spread@2 bidirectional posture (entry below). Removed entries: (a) BEAR P03 -$20 adverse-stop as leading deployment candidate + -$25/-$30 probe queue; (b) P04 peak-relative trail-stop abandonment forensic; (c) pyramid-2 firing-bar bifurcation feature-predictability audit; (d) slope-gated BEAR+BULL "Revised v2 design" next-move plan. All four are preserved in git log (pre-prune commit). Keep this comment until a few sessions pass without regression. -->

- **H3_spread@2 architectural arc complete; deployment is REGIME-CONDITIONAL not regime-robust (2026-05-19).** Session built and tested H3_spread@2 — a research-validated extension of @1 composing four structural improvements: (1) max_exposure_multiple cap on bidirectional pyramid growth, (2) symmetric harvest scale-out above the cap, (3) harvest_keeps_core (floor=initial_lot, persistent CORE_HOLD), (4) bidirectional cycle direction set from cross_side at basket-open. Committed `7f33a8c feat(h3_spread@2)`.

  **Best variants on 2-window cross-regime test (EUR+USDJPY only, S10 mechanic):**
  - **Window A (2024-05 → 2026-05 USD-weakening):** S08 (1d macro) +184% / DD −24%; **S10 (4h-scaled macro)** +198% / DD −23% / Ret/DD 8.54
  - **Window B (2021-05 → 2023-05 USD-strengthening):** S08 +153% / DD −27%; **S10** +156% / DD −26% / Ret/DD 6.01
  - 1d and 4h-scaled (same daily calendar lookback) deliver equivalent results; 4h sampled finer is marginally better.

  **Two negative-result probes (committed under follow-on S11/S12/S13/S14 directives, NOT in `7f33a8c`):**
  - **Cross-pair fails:** GBPUSD+USDJPY −72%/−152% on A/B; AUDUSD+USDCAD −146%/−80% on A/B. Mechanism does NOT transfer to other pair combinations. GBP/USDJPY has only marginally weaker correlation profile than EUR/JPY but loses anyway (higher 5m vol + Brexit idiosyncratic shocks); AUD/USDCAD has STRONGER inverse correlation but the spread captures commodity-vs-oil dynamics rather than USD direction.
  - **Window C 2018-05 → 2020-05 fails:** −130% Net / −124% DD on the EUR/JPY/S10 mechanic that won the other two windows. Multi-regime period (trade war 2018 + Brexit + Fed pivot 2019 + COVID March 2020). 74% of loss is PRE-COVID (worst single quarter 2019Q1 = −$536 with no COVID involvement). Direction was right 99.7% of cycles; 5m chop within macro-coherent segments + correlation breakdown (25% of days corr > −0.2 vs 5% on Window A) were the proximate drivers.

  **EUR/JPY 20-day return correlation predicts win/loss monotonically across the 3 windows:**
  - Window A: mean corr −0.594, 69% strongly inverse (< −0.5) → **+198% Net**
  - Window B: mean corr −0.408, 36% strongly inverse → **+156% Net**
  - Window C: mean corr −0.342, 24% strongly inverse → **−130% Net**

  **Correlation filter approach TESTED AND DROPPED (S13/S14 directives in completed/, code in basket_data_loader.py with default=off).** Adding `macro_correlation_window + macro_correlation_threshold` params to gate cross_event by daily rolling correlation works directionally (Window C loss reduced 74% at threshold=−0.5, 30% at −0.2) but the cost on Windows A/B is non-trivial (−0.5: lose 62-76% of edge; −0.2: lose 4-41%). No single threshold preserves A/B edge while making Window C profitable — per-cycle PF on Window C stays 0.75-0.78 regardless of threshold, meaning the strategy lacks per-cycle edge on Window C structurally, not just from "broken correlation" entries. **Decision: leave correlation filter OUT of deployment; let portfolio-level max-DD constraints do the risk-management work.** Filter code retained as research diagnostic (default macro_correlation_window=None preserves legacy behavior).

  **Deployment posture (locked, end of session 2026-05-19):**
  - EUR/JPY is the SINGLE deployable pair (cross-pair attempts negative).
  - 2/3 windows positive; 1/3 catastrophically negative. Strategy is regime-conditional, not regime-robust.
  - Required: portfolio-level max-DD discipline to bound the Window-C-like tail when it recurs.
  - Open structural question: how to DETECT regime-condition (correlation health + 5m intra-macro coherence + macro flip frequency) BEFORE deployment damage accumulates. Operator-side review of macro indicators per quarter is the manual baseline.

  **Research artifacts (not yet committed at session-close; will be committed by /session-close):**
  S11 V1 P00/P01 (GBPUSD+USDJPY × A/B), S12 V1 P00/P01 (AUDUSD+USDCAD × A/B), S10 V1 P02 (EUR/JPY × Window C), S13 V1 P00/P01/P02 (corr filter −0.5 × 3 windows), S14 V1 P00/P01/P02 (corr filter −0.2 × 3 windows). Plus correlation-filter code + 6 new tests in `tests/test_basket_data_loader_macro_filter.py`.

- **Reading list for next session.** Operator will think over the picture. Key strategic questions to consider before next probe:
  1. Accept EUR/JPY-only deployment with manual regime gating + portfolio-level DD?
  2. Build a second filter (5m intra-macro coherence — realized vol within macro-stable segments)?
  3. Search for a different basket structure where the cross-pair mechanism transfers (e.g., truly USD-anchored synthetic spreads, not naive pair-combinations)?
  4. Park the mechanism and pursue a different strategy family?

- **COINTREV v1 retired 2026-05-21 (commit 605317c). Screener universe expanded to XAU/BTC/ETH (commit b8f4251).** The polluted strategy chain (cointegration_meanrev_v1.py + generate_cointrev_directives.py + CointMeanRevLegStrategy + cohort report tool + 48 backtest directives + tradability/corr_504d columns in the Excel viewer) was retired in one commit. Pollution was equal-lot sizing in the strategy + a correlation-based "tradability filter" added at directive-generation time to mask the equal-lot bug — together they made COINTREV correlation-pair-trading dressed in cointegration language. 98 directive admission records quarantined to `TradeScan_State/quarantine/20260521T032947Z_coint_v1_retirement/` with full manifest.

  Clean infrastructure retained: screener (`cointegration_screen.py`), SQLite ingest (`cointegration_db.py`), history matrix (`cointegration_history_matrix.py`), Excel viewer (`cointegration_excel.py`, now strictly cointegration), runtime feature lookup (`indicators/stats/cointegration_state.py`), data-loader `load_cointegration_factor` + `compute_intra_z`, daily runner (`cointegration_daily_runner.py`), event study output (annotated). Output reports POLLUTED-banner annotated (COHORT, CONCURRENCY); EVENT_STUDY annotated with regime-trust caveat (methodology clean, actionable claim re-validation pending).

  **Universe expansion (commit b8f4251):** 18 FX → 21 symbols by adding XAUUSD/BTCUSD/ETHUSD. 153 → 210 pair-pairs. First-run findings (BOTH-window cointegrated cross-asset pairs): **BTCUSD/NZDJPY** (p252=0.0015, p504=0.0210, hl=5.8d/19.4d), **GBPJPY/XAUUSD** (p252=0.0135, p504=0.0437, hl=9.7d/25.4d), **EURJPY/XAUUSD** (p252=0.0165, p504=0.0370, hl=11.7d/25.9d). CHFJPY/XAUUSD one tick from BOTH (504d p=0.0531). Yen-cross / XAU cluster is economically intuitive (risk-off / inflation-hedge drivers); BTC/NZDJPY surprising and warrants follow-up sanity check.

  **Deferred (future sessions):** β-weighted COINTREV v1.2 strategy build (if/when pursued — would test cointegration mean-reversion fairly with β-weighted lots); stocks-universe pivot (cointegration has rich literature on equity pairs but requires new data ingestion + execution path). Today's daily screener continues to run as monitoring infra independent of any strategy.
