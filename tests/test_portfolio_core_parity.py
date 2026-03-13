import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from tools.portfolio_core import (
    build_run_portfolio_summary,
    compute_concurrency_series,
    compute_drawdown,
    compute_equity_curve,
    deterministic_portfolio_id,
    load_trades_for_portfolio_analysis,
    load_trades_for_portfolio_evaluator,
)


def legacy_load_trades_for_portfolio_analysis(run_ids, project_root: Path):
    all_trades = []
    timeframes = set()

    for run_id in run_ids:
        trade_path = project_root / "runs" / run_id / "data" / "results_tradelevel.csv"
        if not trade_path.exists():
            raise FileNotFoundError(f"Trade file missing for run {run_id}")

        df_trades = pd.read_csv(trade_path)

        if "pnl_usd" in df_trades.columns:
            df_trades.rename(columns={"pnl_usd": "pnl"}, inplace=True)

        for col in ["entry_timestamp", "exit_timestamp", "pnl"]:
            if col not in df_trades.columns:
                raise ValueError(f"Missing column '{col}' in run {run_id}")

        df_trades["entry_timestamp"] = pd.to_datetime(df_trades["entry_timestamp"])
        df_trades["exit_timestamp"] = pd.to_datetime(df_trades["exit_timestamp"])

        meta_path = project_root / "runs" / run_id / "data" / "run_metadata.json"
        strat_name = f"RUN_{run_id}"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                strat_name = meta.get("strategy_name", strat_name)
                tf = meta.get("timeframe") or meta.get("TIMEFRAME")
                if tf:
                    timeframes.add(str(tf))
            except Exception:
                pass

        df_trades["strategy_id"] = strat_name
        df_trades["run_id"] = run_id
        all_trades.append(df_trades)

    trades = pd.concat(all_trades, ignore_index=True)
    trades.sort_values("exit_timestamp", inplace=True)
    trades.reset_index(drop=True, inplace=True)
    return trades, timeframes


def legacy_load_trades_for_portfolio_evaluator(run_ids, project_root: Path):
    all_trades = []
    symbol_trades = {}
    meta_records = {}

    for rid in run_ids:
        run_folder = project_root / "runs" / rid / "data"
        if not run_folder.exists():
            raise ValueError(f"Governance violation: run_data folder missing for {rid}")

        csv_path = run_folder / "results_tradelevel.csv"
        if not csv_path.exists():
            raise ValueError(f"Governance violation: results_tradelevel.csv missing for {rid}")

        strat_name = f"PORTFOLIO_CONSTITUENT_{rid}"
        symbol = f"SYM_{rid}"
        meta_dict = {}

        meta_path = run_folder / "run_metadata.json"
        try:
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    strat_name = meta.get("strategy_name", strat_name)
                    symbol = meta.get("symbol", symbol)
                    meta_dict = meta
        except Exception:
            pass

        meta_records[symbol] = meta_dict

        try:
            df = pd.read_csv(csv_path)
            df["source_run_id"] = rid
            df["strategy_name"] = strat_name
            df["exit_timestamp"] = pd.to_datetime(
                df["exit_timestamp"], errors="coerce", utc=True
            ).dt.tz_convert(None)
            df["entry_timestamp"] = pd.to_datetime(
                df["entry_timestamp"], errors="coerce", utc=True
            ).dt.tz_convert(None)
            df["symbol"] = symbol
            symbol_trades[symbol] = df
            all_trades.append(df)
        except Exception as exc:
            raise ValueError(
                f"Governance violation: failed to load trade data for run_id {rid}: {exc}"
            )

    if not all_trades:
        raise ValueError(f"No valid trade data loaded for run IDs {run_ids}")

    portfolio_df = pd.concat(all_trades, ignore_index=True)
    portfolio_df.sort_values("exit_timestamp", inplace=True)
    portfolio_df.reset_index(drop=True, inplace=True)
    return portfolio_df, symbol_trades, meta_records


def legacy_compute_equity_curve(trades, reference_capital):
    equity = reference_capital
    equity_before_list = []
    equity_after_list = []
    return_list = []

    for _, row in trades.iterrows():
        equity_before_list.append(equity)
        pnl = row["pnl"]
        r = pnl / equity if equity != 0 else 0.0
        equity += pnl
        equity_after_list.append(equity)
        return_list.append(r)

    trades["equity_before_trade"] = equity_before_list
    trades["equity_after_trade"] = equity_after_list
    trades["return_t"] = return_list
    return trades


def legacy_compute_concurrency_series(portfolio_df):
    if portfolio_df.empty:
        return [], 0, 0.0, 0.0, 0.0

    df_sorted = portfolio_df.sort_values("entry_timestamp").copy()
    events = []
    for _, row in df_sorted.iterrows():
        events.append((row["entry_timestamp"], 1))
        events.append((row["exit_timestamp"], -1))
    events.sort(key=lambda x: (x[0], x[1]))

    current_concurrent = 0
    max_concurrent = 0
    weighted_sum = 0.0
    time_deployed = 0.0
    duration_by_count = {}
    last_time = events[0][0]
    total_duration = (events[-1][0] - events[0][0]).total_seconds()
    series = []

    for t, type_ in events:
        delta = (t - last_time).total_seconds()
        if delta > 0:
            weighted_sum += current_concurrent * delta
            duration_by_count[current_concurrent] = duration_by_count.get(current_concurrent, 0.0) + delta
            if current_concurrent > 0:
                time_deployed += delta

        if type_ == 1:
            current_concurrent += 1
            series.append(current_concurrent)
        else:
            current_concurrent -= 1

        if current_concurrent > max_concurrent:
            max_concurrent = current_concurrent

        last_time = t

    avg_concurrent = weighted_sum / total_duration if total_duration > 0 else 0.0
    pct_deployed = (time_deployed / total_duration) if total_duration > 0 else 0.0
    time_at_max = duration_by_count.get(max_concurrent, 0.0)
    pct_at_max = (time_at_max / total_duration) if total_duration > 0 else 0.0
    return series, max_concurrent, avg_concurrent, pct_at_max, pct_deployed


def legacy_compute_drawdown(trades):
    equity = trades["equity_after_trade"]
    rolling_peak = equity.cummax()
    drawdown = equity - rolling_peak

    max_dd = drawdown.min()
    trough_idx = drawdown.idxmin()
    peak_idx = equity.loc[:trough_idx].idxmax()

    peak_time = trades.loc[peak_idx, "exit_timestamp"]
    trough_time = trades.loc[trough_idx, "exit_timestamp"]
    max_dd_pct = max_dd / equity.loc[peak_idx] if equity.loc[peak_idx] != 0 else 0.0
    return max_dd, max_dd_pct, peak_time, trough_time


def legacy_build_run_portfolio_summary(**kwargs):
    return {
        "portfolio_id": kwargs["portfolio_id"],
        "realized_pnl": float(kwargs["trades"]["pnl"].sum()),
        "net_pnl_usd": float(kwargs["trades"]["pnl"].sum()),
        "max_dd_usd": float(kwargs["max_dd"]),
        "max_dd_pct": float(kwargs["max_dd_pct"]),
        "return_dd_ratio": float(kwargs["return_dd_ratio"]),
        "sharpe": float(kwargs["sharpe"]),
        "cagr": float(kwargs["cagr"]),
        "avg_concurrent": float(kwargs["concurrency_data"]["avg_concurrent"]),
        "max_concurrent": int(kwargs["concurrency_data"]["max_concurrent"]),
        "p95_concurrent": float(kwargs["concurrency_data"]["p95_concurrent"]),
        "dd_max_concurrent": int(kwargs["concurrency_data"]["dd_max_concurrent"]),
        "full_load_cluster": bool(kwargs["concurrency_data"]["full_load_cluster"]),
        "peak_capital_deployed": float(kwargs["concurrency_data"]["peak_capital_deployed"]),
        "capital_overextension_ratio": float(kwargs["capital_overextension_ratio"]),
        "avg_pairwise_corr": float(kwargs["avg_pairwise_corr"]),
        "max_pairwise_corr_stress": float(kwargs["max_pairwise_corr_stress"]),
        "reference_capital_usd": kwargs["reference_capital"],
        "total_trades": len(kwargs["trades"]),
        "portfolio_net_profit_low_vol": kwargs["low_pnl"],
        "portfolio_net_profit_normal_vol": kwargs["normal_pnl"],
        "portfolio_net_profit_high_vol": kwargs["high_pnl"],
        "signal_timeframes": kwargs["signal_timeframes_str"],
        "evaluation_timeframe": kwargs["evaluation_timeframe"],
        "k_ratio": float(kwargs["k_ratio"]),
        "win_rate": float(kwargs["win_rate"]),
        "profit_factor": float(kwargs["profit_factor"]),
        "expectancy": float(kwargs["expectancy"]),
        "exposure_pct": float(kwargs["exposure_pct"]),
        "equity_stability_k_ratio": float(kwargs["equity_stability_k_ratio"]),
    }


class TestPortfolioCoreParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_ids = ["RUN_FIXED_001", "RUN_FIXED_002"]
        self._seed_run(
            run_id="RUN_FIXED_001",
            strategy_name="STRAT_FIXED_001",
            symbol="EURUSD",
            timeframe="1D",
            rows=[
                {
                    "entry_timestamp": "2024-01-01 00:00:00",
                    "exit_timestamp": "2024-01-02 00:00:00",
                    "pnl_usd": 100.0,
                    "volatility_regime": "low",
                },
                {
                    "entry_timestamp": "2024-01-01 12:00:00",
                    "exit_timestamp": "2024-01-03 00:00:00",
                    "pnl_usd": -50.0,
                    "volatility_regime": "normal",
                },
            ],
        )
        self._seed_run(
            run_id="RUN_FIXED_002",
            strategy_name="STRAT_FIXED_002",
            symbol="GBPUSD",
            timeframe="4H",
            rows=[
                {
                    "entry_timestamp": "2024-01-02 00:00:00",
                    "exit_timestamp": "2024-01-04 00:00:00",
                    "pnl_usd": 75.0,
                    "volatility_regime": "high",
                },
                {
                    "entry_timestamp": "2024-01-03 00:00:00",
                    "exit_timestamp": "2024-01-05 00:00:00",
                    "pnl_usd": 25.0,
                    "volatility_regime": "normal",
                },
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_run(self, run_id, strategy_name, symbol, timeframe, rows):
        run_data_dir = self.root / "runs" / run_id / "data"
        run_data_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(run_data_dir / "results_tradelevel.csv", index=False)
        metadata = {
            "run_id": run_id,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "signature_hash": "abc123",
            "trend_filter_enabled": True,
            "filter_coverage": 0.3,
            "filtered_bars": 30,
            "total_bars": 100,
        }
        (run_data_dir / "run_metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )

    def test_deterministic_portfolio_id_parity(self):
        self.assertEqual(
            deterministic_portfolio_id(self.run_ids),
            deterministic_portfolio_id(list(reversed(self.run_ids))),
        )
        self.assertEqual(deterministic_portfolio_id(self.run_ids), "PF_1AE543FC87AD")

    def test_trade_loader_parity_for_run_portfolio_analysis(self):
        legacy_trades, legacy_tfs = legacy_load_trades_for_portfolio_analysis(self.run_ids, self.root)
        core_trades, core_tfs = load_trades_for_portfolio_analysis(self.run_ids, self.root)
        assert_frame_equal(legacy_trades, core_trades)
        self.assertEqual(legacy_tfs, core_tfs)

    def test_trade_loader_parity_for_portfolio_evaluator(self):
        legacy_df, legacy_symbol_trades, legacy_meta = legacy_load_trades_for_portfolio_evaluator(
            self.run_ids, self.root
        )
        core_df, core_symbol_trades, core_meta = load_trades_for_portfolio_evaluator(
            self.run_ids, self.root
        )
        assert_frame_equal(legacy_df, core_df)
        self.assertEqual(sorted(legacy_symbol_trades.keys()), sorted(core_symbol_trades.keys()))
        for key in legacy_symbol_trades:
            assert_frame_equal(legacy_symbol_trades[key], core_symbol_trades[key])
        self.assertEqual(legacy_meta, core_meta)

    def test_deterministic_math_and_summary_parity(self):
        base_trades, _ = load_trades_for_portfolio_analysis(self.run_ids, self.root)
        legacy_equity_df = legacy_compute_equity_curve(base_trades.copy(), reference_capital=10000.0)
        core_equity_df = compute_equity_curve(base_trades.copy(), reference_capital=10000.0)
        assert_frame_equal(legacy_equity_df, core_equity_df)

        legacy_conc = legacy_compute_concurrency_series(core_equity_df)
        core_conc = compute_concurrency_series(core_equity_df)
        self.assertEqual(legacy_conc[0], core_conc[0])
        self.assertEqual(legacy_conc[1], core_conc[1])
        self.assertAlmostEqual(legacy_conc[2], core_conc[2], places=12)
        self.assertAlmostEqual(legacy_conc[3], core_conc[3], places=12)
        self.assertAlmostEqual(legacy_conc[4], core_conc[4], places=12)

        legacy_dd = legacy_compute_drawdown(core_equity_df)
        core_dd = compute_drawdown(core_equity_df)
        self.assertEqual(legacy_dd[0], core_dd[0])
        self.assertEqual(legacy_dd[1], core_dd[1])
        self.assertEqual(legacy_dd[2], core_dd[2])
        self.assertEqual(legacy_dd[3], core_dd[3])

        summary_kwargs = {
            "portfolio_id": deterministic_portfolio_id(self.run_ids),
            "trades": core_equity_df,
            "max_dd": core_dd[0],
            "max_dd_pct": core_dd[1],
            "return_dd_ratio": 2.5,
            "sharpe": 1.1,
            "cagr": 0.23,
            "concurrency_data": {
                "avg_concurrent": core_conc[2],
                "max_concurrent": core_conc[1],
                "p95_concurrent": 2.0,
                "dd_max_concurrent": 2,
                "full_load_cluster": False,
                "peak_capital_deployed": 10000.0,
            },
            "capital_overextension_ratio": 1.0,
            "avg_pairwise_corr": 0.2,
            "max_pairwise_corr_stress": 0.5,
            "reference_capital": 10000.0,
            "low_pnl": 100.0,
            "normal_pnl": -25.0,
            "high_pnl": 75.0,
            "signal_timeframes_str": "1D|4H",
            "evaluation_timeframe": "1D",
            "k_ratio": 1.2,
            "win_rate": 50.0,
            "profit_factor": 1.8,
            "expectancy": 37.5,
            "exposure_pct": 80.0,
            "equity_stability_k_ratio": 1.2,
        }
        legacy_summary = legacy_build_run_portfolio_summary(**summary_kwargs)
        core_summary = build_run_portfolio_summary(**summary_kwargs)
        # Compare deterministic metrics only (exclude capital model fields).
        deterministic_keys = [
            "portfolio_id",
            "realized_pnl",
            "net_pnl_usd",
            "max_dd_usd",
            "max_dd_pct",
            "return_dd_ratio",
            "sharpe",
            "cagr",
            "avg_concurrent",
            "max_concurrent",
            "p95_concurrent",
            "dd_max_concurrent",
            "full_load_cluster",
            "avg_pairwise_corr",
            "max_pairwise_corr_stress",
            "reference_capital_usd",
            "total_trades",
            "portfolio_net_profit_low_vol",
            "portfolio_net_profit_normal_vol",
            "portfolio_net_profit_high_vol",
            "signal_timeframes",
            "evaluation_timeframe",
            "k_ratio",
            "win_rate",
            "profit_factor",
            "expectancy",
            "exposure_pct",
            "equity_stability_k_ratio",
        ]
        for k in deterministic_keys:
            self.assertEqual(legacy_summary[k], core_summary[k], k)


if __name__ == "__main__":
    unittest.main()
