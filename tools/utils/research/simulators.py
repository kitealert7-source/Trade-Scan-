"""
Percent-return path simulators.
Artifact-only: consumes deployable_trade_log.csv columns.
No capital_wrapper dependency.  No Stage1.
"""

import numpy as np
import pandas as pd


# ── helpers ──────────────────────────────────────────────────────────────────

def _trade_pcts(tr_df: pd.DataFrame, start_cap: float) -> np.ndarray:
    """Convert each trade's PnL to a % of equity-at-entry."""
    tr = tr_df.copy()
    tr["entry_timestamp"] = pd.to_datetime(tr["entry_timestamp"])
    tr["exit_timestamp"] = pd.to_datetime(tr["exit_timestamp"])

    events = []
    for pos, row in enumerate(tr.itertuples(index=False)):
        events.append({"time": row.entry_timestamp, "type": "entry", "idx": pos})
        events.append(
            {
                "time": row.exit_timestamp,
                "type": "exit",
                "idx": pos,
                "pnl_usd": float(row.pnl_usd),
            }
        )
    events.sort(key=lambda x: (x["time"], 0 if x["type"] == "exit" else 1))

    equity = start_cap
    entry_equities = np.zeros(len(tr))
    for ev in events:
        if ev["type"] == "entry":
            # Skip if already set by an intra-bar exit-first ordering.
            if entry_equities[ev["idx"]] == 0:
                entry_equities[ev["idx"]] = equity
        else:
            # Intra-bar trade: entry_timestamp == exit_timestamp causes
            # the exit to sort BEFORE its entry. Pre-record the entry
            # equity here using the PRE-exit equity (i.e., current
            # equity before this exit's PnL applies). Without this,
            # entry_equities[idx] gets stamped post-exit and the pct
            # comes out as PnL/(E+PnL) instead of PnL/E — `_simulate`
            # then mis-scales the trade. Companion to the .get()
            # defensive lookup in `_simulate` below.
            if entry_equities[ev["idx"]] == 0:
                entry_equities[ev["idx"]] = equity
            equity += ev["pnl_usd"]

    # guard against any remaining zero-equity entries (defensive — should
    # not trigger after the in-loop pre-recording above, but harmless).
    entry_equities[entry_equities == 0] = start_cap
    return tr["pnl_usd"].values / entry_equities


def _simulate(
    tr_df: pd.DataFrame,
    pcts: np.ndarray,
    start_cap: float,
) -> dict:
    """Run a single equity simulation from trade-percent returns."""
    tr = tr_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(tr["entry_timestamp"]):
        tr["entry_timestamp"] = pd.to_datetime(tr["entry_timestamp"])
        tr["exit_timestamp"] = pd.to_datetime(tr["exit_timestamp"])

    events = []
    for pos, row in enumerate(tr.itertuples(index=False)):
        events.append({"time": row.entry_timestamp, "type": "entry", "idx": pos})
        events.append({"time": row.exit_timestamp, "type": "exit", "idx": pos})
    events.sort(key=lambda x: (x["time"], 0 if x["type"] == "exit" else 1))

    equity = start_cap
    peak = start_cap
    max_dd = 0.0
    loss_streak = 0
    max_loss_streak = 0
    trade_entry_eq: dict = {}

    for ev in events:
        if ev["type"] == "entry":
            trade_entry_eq[ev["idx"]] = equity
        else:
            idx = ev["idx"]
            # Defensive lookup: when a trade has entry_timestamp ==
            # exit_timestamp (intra-bar fill — happens in the data set
            # legitimately on 30M/4H/1D bars and any future tick-fill
            # case), the sort tiebreaker `(time, 0 if exit else 1)`
            # places this exit BEFORE its entry, so the dict slot is
            # still empty. The correct entry equity in that case is
            # the current equity — zero time has passed between the
            # would-be entry and the exit, so they are equal by
            # definition. Use .get(...) with the current equity as
            # fallback to preserve the cross-trade ordering rule
            # (exits-before-entries at the same time still lets prior
            # trades' PnL flow into later entries' equity).
            # Crash predecessor: KeyError when trade #309 of
            # 28_PA_XAUUSD_30M_ENGULF_S02_V1_P00_XAUUSD had
            # entry == exit == 2026-03-31 23:30:00.
            entry_eq = trade_entry_eq.get(idx, equity)
            pnl = entry_eq * pcts[idx]
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if pnl < 0:
                loss_streak += 1
                if loss_streak > max_loss_streak:
                    max_loss_streak = loss_streak
            else:
                loss_streak = 0

    years = (tr["exit_timestamp"].max() - tr["entry_timestamp"].min()).days / 365.25
    if years <= 0:
        years = 1.0
    cagr = (equity / start_cap) ** (1 / years) - 1 if equity > 0 else -1

    return {
        "final_equity": equity,
        "cagr": cagr,
        "max_dd_pct": max_dd * 100,
        "max_loss_streak": max_loss_streak,
    }


# ── public API ───────────────────────────────────────────────────────────────

def simulate_percent_path(tr_df: pd.DataFrame, start_cap: float = 10_000) -> dict:
    """Baseline simulation using original chronological order."""
    pcts = _trade_pcts(tr_df, start_cap)
    return _simulate(tr_df, pcts, start_cap)


def run_reverse_path_test(tr_df: pd.DataFrame, start_cap: float = 10_000) -> dict:
    """Reverse chronological order — tests path dependency."""
    pcts = _trade_pcts(tr_df, start_cap)
    rev_pcts = pcts[::-1]
    return _simulate(tr_df, rev_pcts, start_cap)


def run_random_sequence_mc(
    tr_df: pd.DataFrame,
    iterations: int = 500,
    start_cap: float = 10_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Random-reshuffle Monte Carlo — shuffles trade outcomes, keeps timestamps."""
    rng = np.random.default_rng(seed)
    pcts = _trade_pcts(tr_df, start_cap)

    rows = []
    for i in range(iterations):
        shuffled = rng.permutation(pcts)
        res = _simulate(tr_df, shuffled, start_cap)
        res["run"] = i + 1
        rows.append(res)
    return pd.DataFrame(rows)


# ── regime-aware block bootstrap ─────────────────────────────────────────────

def _assign_regime_labels(tr_df: pd.DataFrame) -> np.ndarray:
    """Assign HIGH_VOL / NORMAL / LOW_VOL labels to each trade.

    Priority:
        1. Use existing 'volatility_regime' column if present (Stage-1 emitted).
        2. Otherwise, compute rolling std of pnl_usd with adaptive window.
    """
    n = len(tr_df)

    # Priority 1: Stage-1 emitted regime column
    if "volatility_regime" in tr_df.columns:
        raw = tr_df["volatility_regime"].astype(str).str.upper().values
        labels = np.array(["NORMAL"] * n, dtype=object)
        for i, v in enumerate(raw):
            # Numeric handling first (Stage-1 emits 1 / 0 / -1)
            try:
                v_num = float(v)
                if v_num > 0:
                    labels[i] = "HIGH_VOL"
                elif v_num < 0:
                    labels[i] = "LOW_VOL"
                else:
                    labels[i] = "NORMAL"
                continue
            except (ValueError, TypeError):
                pass
            # String handling fallback (legacy labelled data)
            if "HIGH" in v:
                labels[i] = "HIGH_VOL"
            elif "LOW" in v:
                labels[i] = "LOW_VOL"
            else:
                labels[i] = "NORMAL"
        return labels

    # Priority 2: Rolling std fallback
    pnl = tr_df["pnl_usd"].values.astype(float)
    window = max(5, min(30, n // 10))

    # Compute rolling std efficiently with pandas
    rolling_std = pd.Series(pnl).rolling(window).std().to_numpy()

    # Fill leading NaNs with the first valid std
    first_valid_idx = window - 1
    first_valid = rolling_std[first_valid_idx] if first_valid_idx < n else 0.0
    rolling_std[:first_valid_idx] = first_valid

    p30 = np.percentile(rolling_std, 30)
    p70 = np.percentile(rolling_std, 70)

    labels = np.array(["NORMAL"] * n, dtype=object)
    labels[rolling_std > p70] = "HIGH_VOL"
    labels[rolling_std < p30] = "LOW_VOL"

    return labels


def _build_regime_blocks(
    pcts: np.ndarray, labels: np.ndarray
) -> list[dict]:
    """Build contiguous blocks of trades belonging to the same regime.

    Returns list of dicts: {'regime': str, 'pcts': np.ndarray, 'count': int}
    """
    blocks = []
    n = len(labels)
    if n == 0:
        return blocks

    block_start = 0
    current_regime = labels[0]

    for i in range(1, n):
        if labels[i] != current_regime:
            blocks.append({
                "regime": current_regime,
                "pcts": pcts[block_start:i].copy(),
                "count": i - block_start,
            })
            block_start = i
            current_regime = labels[i]

    # Final block
    blocks.append({
        "regime": current_regime,
        "pcts": pcts[block_start:n].copy(),
        "count": n - block_start,
    })

    return blocks


def run_regime_block_mc(
    tr_df: pd.DataFrame,
    iterations: int = 500,
    start_cap: float = 10_000,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict]:
    """Regime-aware block bootstrap Monte Carlo.

    Preserves volatility structure, streak clustering, and regime persistence.
    Samples regime blocks with replacement from the original block distribution
    (no forced proportions). Truncates to original trade count for comparability.

    Returns:
        (mc_results_df, metadata_dict)
    """
    rng = np.random.default_rng(seed)
    n_trades = len(tr_df)

    # Step 1: Compute per-trade percentage returns
    pcts = _trade_pcts(tr_df, start_cap)

    # Step 2: Assign regime labels
    labels = _assign_regime_labels(tr_df)

    # Step 3: Build contiguous regime blocks
    blocks = _build_regime_blocks(pcts, labels)
    n_blocks = len(blocks)

    # Regime distribution metadata
    regime_counts = {}
    for b in blocks:
        regime_counts[b["regime"]] = regime_counts.get(b["regime"], 0) + 1

    # Step 4: Monte Carlo loop
    rows = []
    for i in range(iterations):
        # Sample blocks with replacement from original distribution
        sampled_indices = rng.choice(n_blocks, size=n_blocks, replace=True)

        # Concatenate sampled block pcts
        sampled_pcts = np.concatenate([blocks[idx]["pcts"] for idx in sampled_indices])

        # Truncate to original trade count for comparability
        sampled_pcts = sampled_pcts[:n_trades]

        # If we got fewer trades than original (unlikely but possible), pad with zeros
        if len(sampled_pcts) < n_trades:
            sampled_pcts = np.concatenate([
                sampled_pcts,
                np.zeros(n_trades - len(sampled_pcts))
            ])

        # Run equity simulation using same timestamps
        res = _simulate(tr_df, sampled_pcts, start_cap)
        res["run"] = i + 1
        rows.append(res)

    mc_df = pd.DataFrame(rows)

    metadata = {
        "method": "REGIME_AWARE_BLOCK_BOOTSTRAP",
        "block_definition": "contiguous_regime_segments",
        "total_blocks": n_blocks,
        "regime_distribution": regime_counts,
        "iterations": iterations,
        "seed": seed,
        "original_trade_count": n_trades,
    }

    return mc_df, metadata
