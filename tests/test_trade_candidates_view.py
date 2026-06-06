"""Tests for the pair-level TRADE CANDIDATES projection.

Pure DataFrame -> DataFrame. Guards: the runs>=MIN_QUALIFYING_RUNS gate, pair
grain (one row/pair), loss = net<=0 (break-even is a loss), median Ret/DD over
ALL runs, the badge on zero-loss pairs only, and the loss_rate -> runs ->
median_ret_dd sort.
"""
import pandas as pd

from tools.portfolio.trade_candidates_view import (
    BADGE,
    MIN_QUALIFYING_RUNS,
    TRADE_CANDIDATES_COLUMNS,
    build_trade_candidates_df,
)


def _row(pair_a, pair_b, net_pct, ret_dd=1.0):
    return {
        "run_id": f"{pair_a}{pair_b}_{net_pct}_{ret_dd}",
        "pair_a": pair_a, "pair_b": pair_b,
        "canonical_net_pct": net_pct, "canonical_ret_dd": ret_dd,
    }


def _pair_rows(pair_a, pair_b, nets, ret_dds=None):
    """N rows for one pair, one per net% in `nets` (ret_dd optional, defaults 1)."""
    rds = ret_dds if ret_dds is not None else [1.0] * len(nets)
    return [_row(pair_a, pair_b, n, rd) for n, rd in zip(nets, rds)]


def _raw(rows):
    return pd.DataFrame(rows)


def _strip(pair):
    return pair.replace(BADGE + " ", "")


def test_evaluable_filter_excludes_phantom_runs_from_median():
    """A run with cycles_completed == 0 (entered, never reverted, force-closed at
    the window boundary) carries an inflated Ret/DD on a near-zero realized DD.
    The candidates median must rank on EVALUABLE (cycles>=1) runs ONLY, so those
    phantom runs cannot prop a pair up the shortlist; `Evaluable` reports the real
    count."""
    rows = [
        {"run_id": f"ph{i}", "pair_a": "AAA", "pair_b": "BBB",
         "canonical_net_pct": 1.8, "canonical_ret_dd": 26.0, "cycles_completed": 0}
        for i in range(4)
    ] + [
        {"run_id": "real", "pair_a": "AAA", "pair_b": "BBB",
         "canonical_net_pct": 5.0, "canonical_ret_dd": 1.5, "cycles_completed": 10},
    ]
    out = build_trade_candidates_df(_raw(rows))
    assert len(out) == 1
    r = out.iloc[0]
    assert int(r["Runs"]) == 5
    assert int(r["Evaluable"]) == 1          # only the cycles>=1 run counts as evaluable
    assert r["Median Ret/DD"] == 1.5         # NOT the inflated phantom 26.0


# ---------- qualification gate (runs >= MIN_QUALIFYING_RUNS) ----------

def test_excludes_pairs_below_min_runs():
    out = build_trade_candidates_df(_raw(
        _pair_rows("AA", "AA", [5.0] * (MIN_QUALIFYING_RUNS - 1))
    ))
    assert len(out) == 0
    assert list(out.columns) == TRADE_CANDIDATES_COLUMNS


def test_includes_pairs_at_exactly_min_runs():
    out = build_trade_candidates_df(_raw(
        _pair_rows("AA", "AA", [5.0] * MIN_QUALIFYING_RUNS)
    ))
    assert len(out) == 1
    assert out.iloc[0]["Runs"] == MIN_QUALIFYING_RUNS


def test_thin_perfect_pair_is_excluded_qualified_pair_kept():
    # A thinly-tested perfect pair is universe-explorer noise; a qualified pair
    # with a loss still appears. This is the whole point of the gate.
    out = build_trade_candidates_df(_raw(
        _pair_rows("QUAL", "QUAL", [5.0, 5.0, 5.0, 5.0, -1.0]) +  # 5 runs -> in
        _pair_rows("THIN", "THIN", [9.0, 9.0])                    # 2 runs -> out
    ))
    assert [_strip(p) for p in out["Pair"]] == ["QUAL / QUAL"]


# ---------- shape ----------

def test_empty_returns_columns():
    out = build_trade_candidates_df(pd.DataFrame())
    assert list(out.columns) == TRADE_CANDIDATES_COLUMNS
    assert len(out) == 0


def test_one_row_per_pair():
    out = build_trade_candidates_df(_raw(
        _pair_rows("EURUSD", "GBPUSD", [5.0] * 5) +
        _pair_rows("AUDUSD", "NZDUSD", [2.0] * 5)
    ))
    assert len(out) == 2
    assert list(out.columns) == TRADE_CANDIDATES_COLUMNS


# ---------- counts ----------

def test_runs_and_losses_counts():
    out = build_trade_candidates_df(_raw(
        _pair_rows("EURUSD", "GBPUSD", [5.0, 5.0, 5.0, 2.0, -1.0])
    ))
    row = out.iloc[0]
    assert row["Runs"] == 5
    assert row["Losses"] == 1


def test_break_even_counts_as_loss():
    out = build_trade_candidates_df(_raw(
        _pair_rows("EURUSD", "GBPUSD", [5.0, 5.0, 5.0, 5.0, 0.0])  # 0.0 -> loss
    ))
    assert out.iloc[0]["Losses"] == 1


# ---------- badge ----------

def test_badge_on_zero_loss_pair_only():
    out = build_trade_candidates_df(_raw(
        _pair_rows("EURUSD", "GBPUSD", [5.0] * 5) +                  # perfect
        _pair_rows("AUDUSD", "NZDUSD", [5.0, 5.0, 5.0, 5.0, -2.0])   # has a loss
    ))
    byp = {_strip(p): p for p in out["Pair"]}
    assert byp["EURUSD / GBPUSD"].startswith(BADGE)
    assert not byp["AUDUSD / NZDUSD"].startswith(BADGE)


# ---------- median Ret/DD ----------

def test_median_ret_dd_over_all_runs_not_mean():
    # median([1, 2, 2, 9, 9]) = 2 (incl. the high outliers); mean would be 4.6.
    out = build_trade_candidates_df(_raw(
        _pair_rows("EURUSD", "GBPUSD", [5.0] * 5,
                   ret_dds=[1.0, 2.0, 2.0, 9.0, 9.0])
    ))
    assert out.iloc[0]["Median Ret/DD"] == 2.0


def test_median_includes_losing_runs():
    # Losers participate: median([4,4,0,0,0]) = 0; excluding losers it'd be 4.
    out = build_trade_candidates_df(_raw(
        _pair_rows("EURUSD", "GBPUSD", [5.0, 5.0, -1.0, -1.0, -1.0],
                   ret_dds=[4.0, 4.0, 0.0, 0.0, 0.0])
    ))
    assert out.iloc[0]["Median Ret/DD"] == 0.0


# ---------- sort: loss_rate -> median_ret_dd -> runs (Option B) ----------

def test_sort_loss_rate_is_primary():
    # Tier 1 = reliability: a lower loss-rate pair outranks a higher-quality
    # lossy one. Quality never jumps the loss-rate gate.
    rows = (
        _pair_rows("CLEAN", "PAIR", [5.0] * 5, ret_dds=[1.0] * 5) +        # rate 0, med 1.0
        _pair_rows("LOSSY", "PAIR", [5.0, 5.0, 5.0, 5.0, -1.0],
                   ret_dds=[9.0] * 5)                                      # rate .2, med 9.0
    )
    out = build_trade_candidates_df(_raw(rows))
    assert _strip(out.iloc[0]["Pair"]) == "CLEAN / PAIR"


def test_median_beats_more_runs_within_same_loss_rate():
    # Tier 2 = median: once loss_rate ties, higher quality wins even with FEWER
    # runs. This is the whole point of Option B (was the opposite under A).
    rows = (
        _pair_rows("MANY", "RUNS", [5.0] * 12, ret_dds=[1.0] * 12) +   # rate 0, 12 runs, med 1.0
        _pair_rows("FEW", "HIQ", [5.0] * 5, ret_dds=[4.0] * 5)         # rate 0, 5 runs, med 4.0
    )
    out = build_trade_candidates_df(_raw(rows))
    assert [_strip(p) for p in out["Pair"]] == ["FEW / HIQ", "MANY / RUNS"]


def test_runs_is_final_tiebreak():
    # Tier 3 = runs: only when loss_rate AND median tie does the more-tested
    # pair win.
    rows = (
        _pair_rows("X", "X", [5.0] * 10, ret_dds=[2.0] * 10) +   # rate 0, med 2.0, 10 runs
        _pair_rows("Y", "Y", [5.0] * 5, ret_dds=[2.0] * 5)       # rate 0, med 2.0, 5 runs
    )
    out = build_trade_candidates_df(_raw(rows))
    assert _strip(out.iloc[0]["Pair"]) == "X / X"


# ---------- Coint Status (252d) column (regime_map injection) ----------

def test_status_blank_without_regime_map():
    # No screener data supplied -> column present, every value blank.
    out = build_trade_candidates_df(_raw(_pair_rows("EURUSD", "GBPUSD", [5.0] * 5)))
    assert "Coint Status (252d)" in out.columns
    assert out.iloc[0]["Coint Status (252d)"] == ""


def test_status_populated_from_regime_map():
    out = build_trade_candidates_df(
        _raw(_pair_rows("EURUSD", "GBPUSD", [5.0] * 5)),
        regime_map={("EURUSD", "GBPUSD"): "cointegrated"},
    )
    assert out.iloc[0]["Coint Status (252d)"] == "cointegrated"


def test_status_blank_for_pair_absent_from_map():
    # A qualifying pair not in the current screen renders blank, not an error.
    out = build_trade_candidates_df(
        _raw(
            _pair_rows("EURUSD", "GBPUSD", [5.0] * 5) +
            _pair_rows("AUDUSD", "NZDUSD", [5.0] * 5)
        ),
        regime_map={("EURUSD", "GBPUSD"): "broken"},
    )
    byp = {_strip(p): s for p, s in zip(out["Pair"], out["Coint Status (252d)"])}
    assert byp["EURUSD / GBPUSD"] == "broken"
    assert byp["AUDUSD / NZDUSD"] == ""


def test_status_column_is_second_after_pair():
    out = build_trade_candidates_df(
        _raw(_pair_rows("EURUSD", "GBPUSD", [5.0] * 5)),
        regime_map={("EURUSD", "GBPUSD"): "breaking"},
    )
    assert list(out.columns) == TRADE_CANDIDATES_COLUMNS
    assert list(out.columns).index("Coint Status (252d)") == 1
