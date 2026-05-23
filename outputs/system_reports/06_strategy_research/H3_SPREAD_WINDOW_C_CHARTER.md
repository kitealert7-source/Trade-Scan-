# Active Charter — h3_spread_window_c_regime_detector

**Opened:** 2026-05-23
**Status:** ACTIVE — V1 design negative on pipeline test; V2-V5 variations identified, V3 (soft gate) recommended next.
**Owner:** research-strategy layer
**Related authoritative docs:**
- V1 design + results: [`H3_SPREAD_REGIME_GATE_V1_2026_05_23.md`](H3_SPREAD_REGIME_GATE_V1_2026_05_23.md)
- Baseline strategy: H3_spread@3 (see [`H2_ENGINE_PROMOTION_PLAN.md`](../01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md))

---

## Focus

Build a programmatic Window-C regime detector for the H3_spread@3 EUR/USDJPY 15m + d=8 + e=5.0 + r=1.0 baseline locked 2026-05-22. Convert strategy posture from "regime-conditional + manual operator gate" → "regime-tolerant + automated gate" by flagging Window-C-like environments before deployment damage accumulates.

## Why this matters

H3_spread@3 is deployment-grade on Windows A and B (USD-weakening + USD-strengthening) but catastrophic (−112% Net) on Window C (2018–2020 multi-regime: trade war + Brexit + COVID lead-in). Without a detector, every deployment is an implicit unquantified bet that the next two years resemble A/B more than C.

A working detector unlocks confident deployment of an already-proven mechanic; a failed detector caps this strategy at "research peer" status and forces re-allocation to a different family. Cross-pair extensions are already disproven (S11/S12), and single-pair entry/exit axes are exhausted (entry, exit, TF, delay, correlation filter, extreme-z). The detector is the last viable axis on this family — committing weeks of compute here is justified only because the alternative is shelving a 2-of-3-windows winner.

## Goal (measurable)

- **Primary:** detector achieves ≥70% precision and ≥60% recall flagging Window-C-like quarters under leave-one-out cross-validation across all three test windows.
- **Secondary:** detector-gated Window C bleed better than −50% Net (vs. current −112%) without sacrificing more than 15pp Net% on Windows A/B.

## Hard constraints

- EUR/USDJPY only — cross-pair attempts S11/S12 disproven.
- @3 base mechanic frozen — `e=5.0` / `r=1.0` / `d=8` / 15m TF locked; detector wraps, does not modify.
- Detector inputs limited to: 20-day return correlation, 5m intra-macro coherence, macro-flip frequency.
- No entry/exit re-exploration — single-variable axes exhausted.

## Active hypothesis

**H1 (revised 2026-05-23):** cross-side flip count in a rolling N-bar lookback separates Window C from Windows A/B with ≥70% precision and ≥60% recall on per-quarter classification, for at least one of N ∈ {1000, 2000, 4000} 15m bars (≈ 15 / 30 / 60 calendar days). Halting new cycle initiation AND new pyramid orders when `flips_in_lookback > N_threshold` reduces Window-C Net% bleed below −50% without sacrificing >15pp Net% on Windows A/B.

## Stop/restart spec (locked 2026-05-23)

- **Stop:** `flips_in_lookback > N_threshold` → block new cycle initiations AND new pyramid orders
- **Restart (R1 pure symmetric):** `flips_in_lookback ≤ N_threshold` → resume both
- **Open cycles during halt:** continue normally (REVERSE_CROSS / EXTREME_Z / ADVERSE_STOP / HARVEST exits all permitted)
- **Cold start:** gate INACTIVE until lookback window is filled (first N bars behave as baseline)
- **Test baseline:** 15m + d=8 + @3 (`e=5.0` / `r=1.0`) — locked cross-window winner; 5m+d=4+@3 disqualified (Window-B catastrophic)

## Measurement

- **Primary:** per-quarter detector flag precision/recall on Windows A, B, C
- **Pre-promote:** [project_promote_quality_gate] — tail concentration, flat periods, edge ratio on detector-gated trade subset
- **Data source:** per-bar parquet ledgers at `TradeScan_State/backtests/<id>_H2/raw/results_basket_per_bar.parquet` (authoritative per 2026-05-16 RESEARCH_MEMORY entry)

## Decision rules

- **Continue if:** prototype detector hits ≥50% precision on Window C in the first 2–3 design iterations (signal exists, calibration TBD)
- **Pivot if:** ≥4–5 designs across distinct dimensions (correlation, coherence, flip-frequency, regression, ML) all fail to clear 50% precision — per [feedback_research_positive_iteration]
- **Dead if:** no signal combination predicts Window-C structure at acceptable precision; fall back to portfolio-level max-DD caps as the only mitigation and re-allocate attention to a different strategy family

## Sessions on this charter

- **2026-05-23:** V1 design (binary halt of cycle_init + pyramids when flips > T) NEGATIVE on pipeline test. 6 directives ran (S22 P00-P05). Charter goals NOT met: Window A −244pp / B −153pp / C ~unchanged (+0.4pp). Probe was right that signal differentiates (gate fired 39% on C vs 4-10% on A/B), but per-bar halt is economically correlated with pyramid attempts in healthy regimes — suppresses the buy-the-dip mechanic that drives cycle profit. Charter Decision Rule "signal exists" met → CONTINUE. Five V2-V5 variations documented at [`H3_SPREAD_REGIME_GATE_V1_2026_05_23.md`](H3_SPREAD_REGIME_GATE_V1_2026_05_23.md); recommended V3 (soft gate — halve pyramid_add_lot when tripped, not full halt) as next iteration.
