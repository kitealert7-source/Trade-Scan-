# SYSTEM STATE

## SESSION STATUS: WARNING
- WARNING: Working tree 1 uncommitted

> Generated: 2026-05-23T14:46:55Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 6 directives

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
- Latest bar: **2026-05-23** | Symbols: 221

## Artifacts
- Run directories: 945

## Git Sync
- Remote: IN SYNC
- Working tree: 1 uncommitted
- Last substantive commit: `7168f68 session: idea-gate refresh â€” tools_manifest regen for 5 changed tools`

## Known Issues
### Auto-detected (regenerated each run)
- **Broader-pytest baseline:** 13 acknowledged failure(s) (last refreshed 2026-05-23 @ dbfa9c1a). Tests: test_directive_basket_block_parses, test_directive_file_exists, test_directive_legs_match_h2_spec (+10 more). Verify via `python tools/check_broader_pytest_baseline.py` (run by §9b).

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
H1 (revised 2026-05-23): cross-side flip count in a rolling N-bar lookback separates Window C from Windows A/B with ≥70% precision and ≥60% recall on per-quarter classification, for at least one of N ∈ {1000, 2000, 4000} 15m bars (≈ 15 / 30 / 60 calendar days). Halting new cycle initiation AND new pyramid orders when `flips_in_lookback > N_threshold` reduces Window-C Net% bleed below −50% without sacrificing >15pp Net% on Windows A/B.

**Stop/restart spec (locked 2026-05-23):**
- **Stop:** `flips_in_lookback > N_threshold` → block new cycle initiations AND new pyramid orders
- **Restart (R1 pure symmetric):** `flips_in_lookback ≤ N_threshold` → resume both
- **Open cycles during halt:** continue normally (REVERSE_CROSS / EXTREME_Z / ADVERSE_STOP / HARVEST exits all permitted)
- **Cold start:** gate INACTIVE until lookback window is filled (first N bars behave as baseline)
- **Test baseline:** 15m + d=8 + @3 (`e=5.0` / `r=1.0`) — locked cross-window winner; 5m+d=4+@3 disqualified (Window-B catastrophic)

**Measurement:**
- Primary: per-quarter detector flag precision/recall on Windows A, B, C
- Pre-promote: [project_promote_quality_gate] — tail concentration, flat periods, edge ratio on detector-gated trade subset
- Data source: per-bar parquet ledgers at `TradeScan_State/backtests/<id>_H2/raw/results_basket_per_bar.parquet` (authoritative per 2026-05-16 RESEARCH_MEMORY entry)

**Decision rules:**
- Continue if: prototype detector hits ≥50% precision on Window C in the first 2–3 design iterations (signal exists, calibration TBD)
- Pivot if: ≥4–5 designs across distinct dimensions (correlation, coherence, flip-frequency, regression, ML) all fail to clear 50% precision — per [feedback_research_positive_iteration]
- Dead if: no signal combination predicts Window-C structure at acceptable precision; fall back to portfolio-level max-DD caps as the only mitigation and re-allocate attention to a different strategy family

**Sessions on this charter:**
- 2026-05-23: V1 design (binary halt of cycle_init + pyramids when flips > T) NEGATIVE on pipeline test. 6 directives ran (S22 P00-P05). Charter goals NOT met: Window A -244pp / B -153pp / C ~unchanged (+0.4pp). Probe was right that signal differentiates (gate fired 39% on C vs 4-10% on A/B), but per-bar halt is economically correlated with pyramid attempts in healthy regimes — suppresses the buy-the-dip mechanic that drives cycle profit. Charter Decision Rule "signal exists" met → CONTINUE. Five V2-V5 variations documented at [outputs/system_reports/06_strategy_research/H3_SPREAD_REGIME_GATE_V1_2026_05_23.md](outputs/system_reports/06_strategy_research/H3_SPREAD_REGIME_GATE_V1_2026_05_23.md); recommended V3 (soft gate — halve pyramid_add_lot when tripped, not full halt) as next iteration.

---

#### Active deployment baselines (locked references — DO NOT modify without re-approval)

- **H3_spread@3 EUR/USDJPY 15m d=8 e=5.0 r=1.0 — locked 2026-05-22.** Strict Pareto improvement over @2 on Windows A/B (+218% / +226% Net, RetDD 11.7 / 10.9); Window C still −112% Net (regime-conditional, not regime-robust). All @2 mechanics inherited (bidirectional, macro_tf=4h, harvest_keeps_core, cap_mult=3.0, pyramid_step=0.15, adverse_stop=0.020). Deployment requires operator regime gate per quarter — that gate is exactly what the Active Charter above is building.
  - Research-peer alternative (NOT a universal baseline): **5m+d=4+@3** hits +231% on Window A (best ever) but fails Window B (+144% / DD 43% / RetDD 3.3). Deploy selectively only after regime detector distinguishes A-like from B-like.
  - Closed exploration axes for this family (do NOT re-explore): macro filter ✓, correlation filter ✗ dropped, adverse-stop ✓ ($20 Pareto), reverse-cross timing (extreme-z wins), TF (window-dependent), entry-delay (15m+d=8 universal). Remaining axes: (a) Window-C regime detector [active charter], (b) different basket architecture (synthetic spreads, β-weighted cointegration → see COINTREV v1.2 entry below), (c) different pair (naive cross-pair fails — would need transferable mechanic).

#### Cointegration COINTREV v1.2 — handoff for next session (2026-05-23)

- **Design doc locked:** [`outputs/cointegration_screener_v1/v1_2_strategy_design/DESIGN_DOC.md`](outputs/cointegration_screener_v1/v1_2_strategy_design/DESIGN_DOC.md) — base run params (regime_exit_states=["breaking","broken"], no hard stop, no pyramid), one-knob-per-variant doctrine, 8-step implementation order, pre-defined success criteria.
- **Infrastructure ready:** `cointegration_triggers` SQLite table populated with 4,690 trigger events (865 first-crossing after dedupe) across 286 distinct pair-pairs from 1y backfill (2025-05-23 → 2026-05-22).
- **First realized-backtest report:** [`outputs/cointegration_screener_v1/realized_backtest/REPORT_2026-05-23.md`](outputs/cointegration_screener_v1/realized_backtest/REPORT_2026-05-23.md) FALSIFIED v2.1's pessimistic prediction — realized reversion 80-95% (vs v2.1's 25-30%) across all pair_class strata. Stronger empirical motivation for the v1.2 build.
- **Estimated next session:** ~4-6h focused work for strategy class + integration + 10-15 pilot directives + 5-property verification (deterministic reruns, trade count, exit semantics, β sizing, no replay drift). Then evaluate.
- **Daily broker spec refresh chained:** TS_Execution `extract_symbol_specs.py` migrated to DATA_INGRESS post-hook (commit c7bc498). Daily run auto-refreshes Trade_Scan YAMLs at `data_access/broker_specs/OctaFx/`; YAML changes are left uncommitted for operator review.
