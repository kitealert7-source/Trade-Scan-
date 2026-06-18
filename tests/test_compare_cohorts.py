"""Deterministic unit test for tools/compare_cohorts.py (synthetic frame, no MPS, no config import)."""
import pandas as pd

from tools.compare_cohorts import compare_cohorts


def _frame():
    # series -> rows of (pair, test_start, test_end, return_dd_ratio, realized_net%,
    #                     max drawdown %, win_rate, cycles, total_trades)
    data = {
        "REF": [
            ("A/B", "2024-01", "2024-06", 0.10, 5.0, 8.0, 60.0, 10, 20),
            ("C/D", "2024-01", "2024-06", 0.20, 10.0, 6.0, 55.0, 12, 24),
            ("E/F", "2024-01", "2024-06", -0.05, -120.0, 30.0, 40.0, 8, 16),  # a blow-up (< -100)
        ],
        "VAR": [
            ("A/B", "2024-01", "2024-06", 0.12, 6.0, 7.0, 62.0, 10, 10),
            ("C/D", "2024-01", "2024-06", 0.18, 9.0, 6.5, 53.0, 12, 12),
            ("E/F", "2024-01", "2024-06", 0.00, -50.0, 10.0, 45.0, 8, 8),
        ],
    }
    rows = []
    for series, recs in data.items():
        for pair, ts, te, rdd, net, dd, win, cyc, trd in recs:
            rows.append({
                "series": series, "pair": pair, "test_start": ts, "test_end": te,
                "return_dd_ratio": rdd, "realized_net%": net, "max drawdown %": dd,
                "win_rate": win, "cycles": cyc, "total_trades": trd,
            })
    return pd.DataFrame(rows)


def test_matched_pairs_and_corpus():
    res = compare_cohorts(_frame(), "REF", "VAR")
    assert res["matched_pairs"] == 3
    c = res["corpus"]
    assert c["reference_net_pct_sum"] == -105.0   # 5 + 10 - 120
    assert c["variant_net_pct_sum"] == -35.0      # 6 + 9 - 50
    assert c["reference_blowups_lt_minus100"] == 1
    assert c["variant_blowups_lt_minus100"] == 0
    assert c["reference_worst_net_pct"] == -120.0
    assert c["variant_worst_net_pct"] == -50.0
    assert c["reference_total_trades"] == 60      # 20 + 24 + 16
    assert c["variant_total_trades"] == 30        # 10 + 12 + 8
    assert c["variant_trade_freq_pct"] == 50.0


def test_net_pct_median_and_delta():
    net = compare_cohorts(_frame(), "REF", "VAR")["metrics"]["net%"]
    assert net["reference_median"] == 5.0          # median(5, 10, -120)
    assert net["variant_median"] == 6.0            # median(6, 9, -50)
    assert net["median_pair_delta"] == 1.0         # median of per-pair (v-r): 1, -1, 70


def test_no_match_returns_zero():
    res = compare_cohorts(_frame(), "REF", "NOPE")
    assert res["matched_pairs"] == 0
    assert "corpus" not in res


if __name__ == "__main__":
    test_matched_pairs_and_corpus()
    test_net_pct_median_and_delta()
    test_no_match_returns_zero()
    print("OK - all compare_cohorts tests passed")
