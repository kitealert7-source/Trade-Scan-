# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-22T15:57:31Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 0 directives

## Ledgers

- **Master Filter:** 1257 rows

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
- Run directories: 939

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last substantive commit: `e6fdca5 chore(sync): auto-regen sweep_registry + tools_manifest after chip work`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** clean (0 acknowledged failures). Last refreshed 2026-05-21T14:12:37+00:00 @ 71d49d99.

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### Active Charter — 2026-05-23 — h3_spread_window_c_regime_detector

**Focus:** Build a programmatic Window-C regime detector for the H3_spread@3 EUR/USDJPY 15m + d=8 + e=5.0 + r=1.0 baseline locked 2026-05-22 (see H3_spread@3 entry below). Convert strategy posture from "regime-conditional + manual operator gate" → "regime-tolerant + automated gate" by flagging Window-C-like environments before deployment damage accumulates.

**Why this matters:** H3_spread@3 is deployment-grade on Windows A and B (USD-weakening + USD-strengthening) but catastrophic (−112% Net) on Window C (2018–2020 multi-regime: trade war + Brexit + COVID lead-in). Without a detector, every deployment is an implicit unquantified bet that the next two years resemble A/B more than C. A working detector unlocks confident deployment of an already-proven mechanic; a failed detector caps this strategy at "research peer" status and forces re-allocation to a different family. Cross-pair extensions are already disproven (S11/S12), and single-pair entry/exit axes are exhausted (entry, exit, TF, delay, correlation filter, extreme-z). The detector is the last viable axis on this family — committing weeks of compute here is justified only because the alternative is shelving a 2-of-3-windows winner.

**Goal (measurable):**
- Primary: detector achieves ≥70% precision and ≥60% recall flagging Window-C-like quarters under leave-one-out cross-validation across all three test windows
- Secondary: detector-gated Window C bleed better than −50% Net (vs. current −112%) without sacrificing more than 15pp Net% on Windows A/B

**Hard constraints:**
- EUR/USDJPY only — cross-pair attempts S11/S12 disproven
- @3 base mechanic frozen — `e=5.0` / `r=1.0` / `d=8` / 15m TF locked; detector wraps, does not modify
- Detector inputs limited to: 20-day return correlation, 5m intra-macro coherence, macro-flip frequency
- No entry/exit re-exploration — single-variable axes exhausted (see "All entry-side and exit-side single-variable axes for h3_spread are now EXHAUSTED" entry below)

**Active hypothesis:**
H1: a composite gate on (20-day return corr < −0.45) AND (5m intra-macro coherence ratio > 0.75) AND (macro flip frequency < 1 per 30 days) predicts Window-A/B-like behavior with ≥70% precision and is absent in ≥60% of Window-C months.

**Measurement:**
- Primary: per-quarter detector flag precision/recall on Windows A, B, C
- Pre-promote: [project_promote_quality_gate] — tail concentration, flat periods, edge ratio on detector-gated trade subset
- Data source: per-bar parquet ledgers at `TradeScan_State/backtests/<id>_H2/raw/results_basket_per_bar.parquet` (authoritative per 2026-05-16 RESEARCH_MEMORY entry)

**Decision rules:**
- Continue if: prototype detector hits ≥50% precision on Window C in the first 2–3 design iterations (signal exists, calibration TBD)
- Pivot if: ≥4–5 designs across distinct dimensions (correlation, coherence, flip-frequency, regression, ML) all fail to clear 50% precision — per [feedback_research_positive_iteration]
- Dead if: no signal combination predicts Window-C structure at acceptable precision; fall back to portfolio-level max-DD caps as the only mitigation and re-allocate attention to a different strategy family

**Sessions on this charter:**
- (none yet — charter created 2026-05-23)

---

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

- **H3_spread@3 deployment baseline LOCKED (2026-05-22).** New cross-window winner: `90_PORT_EURUSDUSDJPY_15M_PAIRX` with `rule=H3_spread@3`, `extreme_z_threshold=5.0`, `reentry_z_threshold=1.0`, `entry_delay_bars=8`, all @2 mechanics inherited (bidirectional, macro_tf=4h with sma=30/z=360, harvest_keeps_core=true, cap_mult=3.0, pyramid_step=0.15, adverse_stop=0.020). Strict Pareto improvement over prior 5m @2 d=12 baseline on the two favorable regimes:

  | Window | 5m @2 d=12 (prior) | 15m @3 d=8 (NEW) | Δ Net% / Δ DD / Δ Ret/DD |
  |---|---|---|---|
  | A (USD-weakening 2024-05→2026-05) | +198.36% / 23.22% / 8.54 | **+218.21% / 18.71% / 11.66** | +20pp / -4.5pp / +37% |
  | B (USD-strengthening 2021-05→2023-05) | +156.04% / 25.98% / 6.01 | **+225.94% / 20.79% / 10.87** | **+70pp** / -5.2pp / **+81%** |
  | C (multi-regime 2018-05→2020-05) | -129.98% / 124.36% / -1.05 | -112.21% / 107.95% / -1.04 | +17.8pp (less bad) / -16.4pp |

  @3 mechanic = @2 + extreme-z take-profit exit + ARMED-for-reentry phase. Built this session (commits c8e400a + f12abe0 + faecf6b + 6344753 + fa0f18e + ed40845 + 246bb7d + 7166970 + bd33963). Default-off byte-equivalent to @2; all @3 logic gated by `extreme_z_threshold` and `reentry_z_threshold` being non-null. Calibration sweep (S17/S18/S19) confirms e=5.0 is the cross-window robust point; e=4 fails on both windows, e=6 wins A by noise but loses B, e=7 asymptotes to baseline. Entry-delay sweep (S21/S22) confirms d=8 wins at 15m TF; d=4 wins on 5m Window A only but fails Window B (window-conditional).

  Strategy posture: SAME regime-conditional caveat as @2. Window C still requires operator regime gate (correlation health + intra-macro coherence + macro-flip-frequency review per quarter). @3 reduces Window C bleed by 14% (-130 → -112) but doesn't make C profitable. Open question for next session: programmatic regime detector to flip "regime-conditional + manual gate" to "regime-tolerant + automated".

  Reading list (2026-05-19 questions) resolved this session:
    Q1 EUR/JPY-only + portfolio DD → YES (still single deployable pair; cross-pair attempts S11/S12 failed @2 and weren't re-tested @3 — architectural failure expected to hold)
    Q2 5m intra-macro coherence filter → @3 mechanic IS the answer (extreme-z catches over-extension events that proxy for incoherence)
    Q3 Different basket structure → DEFERRED (cross-asset cointegration screener already running daily; β-weighted COINTREV v1.2 pending)
    Q4 Park and pursue different family → NO — @3 deployment-grade improvement justifies continued development of this family

- **5m + d=4 + @3 retained as Window-A-only research peer (2026-05-22).** S21 V1 P00 hit +230.54% / 20.99 DD / RetDD 10.99 on Window A — the highest Net% of any tested config — but fails Window B catastrophically (+144.10% / 43.44 DD / RetDD 3.32). Not deployable as a universal baseline but documents the Window-A peak. If a regime detector later distinguishes A-like from B-like, deploying 5m+d=4 selectively on A-like regimes is a viable second tier.

- **All entry-side and exit-side single-variable axes for h3_spread are now EXHAUSTED for EUR/USDJPY (2026-05-22):** macro filter ✓ (win), correlation filter ✗ (dropped), adverse-stop ✓ ($20=Pareto frontier), reverse-cross timing (unsmoothed=neutral, extreme_z=win), timeframe (window-dependent), entry-delay (15m+d=8 win, 5m has window-conditional sweet spot). Open work for this family limited to: (a) Window C regime detector, (b) different basket pair (cross-pair already failed for naive combinations; would need transferable mechanic), (c) different basket architecture (synthetic spreads, β-weighted cointegration).

- **COINTREV v1 retired 2026-05-21 (commit 605317c). Screener universe expanded to XAU/BTC/ETH (commit b8f4251).** The polluted strategy chain (cointegration_meanrev_v1.py + generate_cointrev_directives.py + CointMeanRevLegStrategy + cohort report tool + 48 backtest directives + tradability/corr_504d columns in the Excel viewer) was retired in one commit. Pollution was equal-lot sizing in the strategy + a correlation-based "tradability filter" added at directive-generation time to mask the equal-lot bug — together they made COINTREV correlation-pair-trading dressed in cointegration language. 98 directive admission records quarantined to `TradeScan_State/quarantine/20260521T032947Z_coint_v1_retirement/` with full manifest.

  Clean infrastructure retained: screener (`cointegration_screen.py`), SQLite ingest (`cointegration_db.py`), history matrix (`cointegration_history_matrix.py`), Excel viewer (`cointegration_excel.py`, now strictly cointegration), runtime feature lookup (`indicators/stats/cointegration_state.py`), data-loader `load_cointegration_factor` + `compute_intra_z`, daily runner (`cointegration_daily_runner.py`), event study output (annotated). Output reports POLLUTED-banner annotated (COHORT, CONCURRENCY); EVENT_STUDY annotated with regime-trust caveat (methodology clean, actionable claim re-validation pending).

  **Universe expansion (commit b8f4251):** 18 FX → 21 symbols by adding XAUUSD/BTCUSD/ETHUSD. 153 → 210 pair-pairs. First-run findings (BOTH-window cointegrated cross-asset pairs): **BTCUSD/NZDJPY** (p252=0.0015, p504=0.0210, hl=5.8d/19.4d), **GBPJPY/XAUUSD** (p252=0.0135, p504=0.0437, hl=9.7d/25.4d), **EURJPY/XAUUSD** (p252=0.0165, p504=0.0370, hl=11.7d/25.9d). CHFJPY/XAUUSD one tick from BOTH (504d p=0.0531). Yen-cross / XAU cluster is economically intuitive (risk-off / inflation-hedge drivers); BTC/NZDJPY surprising and warrants follow-up sanity check.

  **Deferred (future sessions):** β-weighted COINTREV v1.2 strategy build (if/when pursued — would test cointegration mean-reversion fairly with β-weighted lots); stocks-universe pivot (cointegration has rich literature on equity pairs but requires new data ingestion + execution path). Today's daily screener continues to run as monitoring infra independent of any strategy.
