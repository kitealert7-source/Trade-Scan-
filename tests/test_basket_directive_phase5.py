"""Phase 5 acceptance test — first basket directive end-to-end.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5.

Gate per the migration risk table:
  > LOW risk — MPS row matches basket_sim benchmark

Two scopes here:

  (a) Directive admission — the new directive
      `backtest_directives/completed/90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt`
      passes namespace_gate + basket_schema cleanly. Stored under
      completed/ (the tracked specification-record path); INBOX/ is
      gitignored as an ephemeral runtime queue.

  (b) End-to-end run shape — parsing the directive then feeding it to
      basket_pipeline with synthetic per-leg data produces a BasketRunResult
      with the correct shape (basket_id, rule_name@version, MPS row form).

The full 10-window bit-for-bit parity vs `tools/research/basket_sim.py` is
the "live data" gate. It requires loading 10 historical 2y EUR+JPY 5m
datasets with USD_SYNTH compression_5d factor — that data plumbing is
the Phase 5 deliverable on the *runtime* side, separate from this test.
Documenting the deferred gate keeps the architecture green while the data
side is wired in a follow-up session.

Note on recycle semantics: H2CompressionRecycleRule implements the
*harvest-all-at-threshold* variant matching MEMORY.md's H2 spec ($1k
stake, $2k harvest, USD_SYNTH compression_5d gate). basket_sim's
`default_recycle_trigger` is the Variant G "close-winner-add-to-loser"
default; H2's actual research run used a custom recycle_rule callback
with harvest-all semantics. These are distinct strategies despite
sharing the basket_sim simulator.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.basket_pipeline import BasketRunResult, run_basket_pipeline
from tools.basket_schema import is_basket_directive, validate_basket_block
from tools.namespace_gate import validate_namespace
from tools.pipeline_utils import parse_directive


REPO_ROOT = Path(__file__).resolve().parent.parent
DIRECTIVE_PATH = REPO_ROOT / "backtest_directives" / "completed" / "90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt"
RECYCLE_REGISTRY = REPO_ROOT / "governance" / "recycle_rules" / "registry.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _PassthroughStrategy:
    name = "phase5_passthrough"
    timeframe = "5m"

    def prepare_indicators(self, df):
        return df

    def check_entry(self, ctx):
        return None

    def check_exit(self, ctx):
        return False


def _leg_df(seed: int, n: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-09-02", periods=n, freq="5min")
    base = 1.10 + np.cumsum(rng.normal(0.0, 0.0005, n))
    return pd.DataFrame(
        {"open": base, "high": base, "low": base, "close": base,
         "volume": 1000.0, "compression_5d": 5.0},  # gate closed -> no recycle
        index=idx,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_directive_file_exists():
    assert DIRECTIVE_PATH.is_file(), (
        f"Phase 5 deliverable missing: {DIRECTIVE_PATH}"
    )


def test_directive_namespace_validates():
    """namespace_gate must accept the new RECYCLE basket directive."""
    details = validate_namespace(DIRECTIVE_PATH)
    assert details["model"] == "RECYCLE"
    assert details["family"] == "PORT"
    assert details["symbol"] == "H2"          # basket_id encoded in SYMBOL slot
    assert details["timeframe"] == "5M"
    assert details["is_basket"] == "yes"


def test_directive_basket_block_parses():
    parsed = parse_directive(DIRECTIVE_PATH)
    assert is_basket_directive(parsed)
    errors = validate_basket_block(
        parsed,
        recycle_registry_path=RECYCLE_REGISTRY,
        name_symbol_slot="H2",
    )
    assert errors == [], errors


def test_directive_legs_match_h2_spec():
    parsed = parse_directive(DIRECTIVE_PATH)
    legs = parsed["basket"]["legs"]
    by_sym = {l["symbol"]: l for l in legs}
    assert set(by_sym.keys()) == {"EURUSD", "USDJPY"}
    assert by_sym["EURUSD"]["lot"] == 0.02
    assert by_sym["EURUSD"]["direction"] == "long"
    assert by_sym["USDJPY"]["lot"] == 0.01
    assert by_sym["USDJPY"]["direction"] == "short"


def test_directive_runs_through_basket_pipeline_with_synthetic_data():
    """End-to-end: parse directive -> build legs -> run basket_pipeline.

    Synthetic data has gate=5 (below threshold) so the rule never fires.
    The point is to confirm the wiring works and the BasketRunResult has
    the right shape."""
    parsed = parse_directive(DIRECTIVE_PATH)
    leg_data = {"EURUSD": _leg_df(1), "USDJPY": _leg_df(2)}
    leg_strategies = {"EURUSD": _PassthroughStrategy(),
                      "USDJPY": _PassthroughStrategy()}
    result: BasketRunResult = run_basket_pipeline(
        parsed, leg_data, leg_strategies,
        recycle_registry_path=RECYCLE_REGISTRY,
    )
    assert result.basket_id == "H2"
    assert result.rule_name == "H2_recycle"
    assert result.rule_version == 1
    # Gate closed -> no recycle events
    assert result.recycle_events == []
    assert result.harvested_total_usd == 0.0

    row = result.to_mps_row()
    assert row["execution_mode"] == "basket"
    assert row["basket_id"] == "H2"
    assert len(row["basket_legs"]) == 2


def test_basket_dispatch_emits_run_state_and_manifest_phase5b4():
    """Phase 5b.4 regression — `_try_basket_dispatch` must emit run_state.json
    + manifest.json so subsequent startup guardrails do not quarantine the run.

    Scans `TradeScan_State/runs/` for any container whose run_state.json
    declares `metadata.execution_mode == "basket"` and asserts the schema
    invariants on each one. Skips cleanly if no basket runs exist on disk
    (clean checkout).

    Invariants tested:
      run_state.json
        - current_state == "COMPLETE"   (the state walk ran to completion)
        - directive_id present
        - metadata.execution_mode == "basket"
        - metadata.basket_id present
      manifest.json
        - exists in the same run dir
        - run_id matches the folder name
        - execution_mode == "basket"
        - artifacts.results_tradelevel.csv hash is a 64-char hex string
    """
    from config.path_authority import TRADE_SCAN_STATE
    runs_dir = TRADE_SCAN_STATE / "runs"
    if not runs_dir.is_dir():
        pytest.skip("TradeScan_State/runs/ not present")

    basket_runs: list[Path] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir() or len(run_dir.name) != 24:
            continue
        state_file = run_dir / "run_state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (state.get("metadata") or {}).get("execution_mode") == "basket":
            basket_runs.append(run_dir)

    if not basket_runs:
        pytest.skip(
            "No basket runs on disk. Phase 5b.4 schema cannot be regression-"
            "tested without at least one basket run container present. Run "
            "any basket directive through the pipeline to populate."
        )

    hex64 = re.compile(r"^[0-9a-f]{64}$")
    for run_dir in basket_runs:
        run_id = run_dir.name
        # ---- run_state.json ----
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        assert state.get("current_state") == "COMPLETE", (
            f"basket run {run_id} has current_state="
            f"{state.get('current_state')!r}, expected COMPLETE"
        )
        assert state.get("directive_id"), (
            f"basket run {run_id} missing directive_id in run_state.json"
        )
        meta = state.get("metadata") or {}
        assert meta.get("execution_mode") == "basket"
        assert meta.get("basket_id"), (
            f"basket run {run_id} missing metadata.basket_id"
        )
        # ---- manifest.json ----
        manifest_file = run_dir / "manifest.json"
        assert manifest_file.is_file(), (
            f"basket run {run_id} missing manifest.json — Phase 5b.4 fix "
            "regressed; startup guardrail will quarantine this run."
        )
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest.get("run_id") == run_id, (
            f"manifest.run_id {manifest.get('run_id')!r} != folder name {run_id!r}"
        )
        assert manifest.get("execution_mode") == "basket"
        artifacts = manifest.get("artifacts") or {}
        assert "results_tradelevel.csv" in artifacts, (
            f"basket run {run_id} manifest missing results_tradelevel.csv hash"
        )
        h = artifacts["results_tradelevel.csv"]
        assert hex64.match(h), (
            f"basket run {run_id} manifest hash {h!r} is not 64-char hex"
        )


def test_h2_recycle_v3_usd_value_of_ccy():
    """Phase 1 / v3 — generalized currency conversion. USD-anchored pair
    PnL math must collapse cleanly to v1/v2's formulas; cross-pair math
    must compute USD via the appropriate reference rate."""
    from tools.recycle_rules.h2_recycle_v3 import _usd_value_of_ccy, _split_pair

    # USD is the reference — always 1.0
    assert _usd_value_of_ccy("USD", {}) == 1.0

    # EUR: USD per EUR = EURUSD rate (mul case)
    refs = {"EURUSD": 1.10}
    assert abs(_usd_value_of_ccy("EUR", refs) - 1.10) < 1e-9

    # JPY: USD per JPY = 1.0 / USDJPY (div case, because USDJPY is JPY/USD)
    refs = {"USDJPY": 150.0}
    assert abs(_usd_value_of_ccy("JPY", refs) - (1.0 / 150.0)) < 1e-9

    # AUD: USD per AUD = AUDUSD rate
    refs = {"AUDUSD": 0.66}
    assert abs(_usd_value_of_ccy("AUD", refs) - 0.66) < 1e-9

    # Symbol parsing
    assert _split_pair("AUDJPY") == ("AUD", "JPY")
    assert _split_pair("EURUSD") == ("EUR", "USD")
    assert _split_pair("USDJPY") == ("USD", "JPY")
    assert _split_pair("GBPAUD") == ("GBP", "AUD")


def test_h2_recycle_v3_cross_pair_pnl_math():
    """Phase 1 / v3 — cross-pair PnL computation against hand-computed
    AUDJPY and GBPAUD examples."""
    from tools.recycle_rules.h2_recycle_v3 import _leg_pnl_usd
    from tools.basket_runner import BasketLeg
    from engine_abi.v1_5_9 import BarState

    # AUDJPY long 0.01 lot, entry 100, current 102, USDJPY = 150
    #   pnl_jpy = 0.01 × 100000 × (102 − 100) = 2000 JPY
    #   pnl_usd = 2000 / 150 = $13.333...
    idx = pd.date_range("2024-09-02", periods=1, freq="5min")
    df = pd.DataFrame({"close": [102.0]}, index=idx)
    leg = BasketLeg("AUDJPY", lot=0.01, direction=+1, df=df, strategy=None)  # type: ignore
    leg.state = BarState()
    leg.state.in_pos = True
    leg.state.direction = +1
    leg.state.entry_price = 100.0
    ref_closes = {"USDJPY": 150.0, "AUDUSD": 0.66}
    pnl = _leg_pnl_usd(leg, 102.0, ref_closes)
    assert abs(pnl - 13.3333333333) < 1e-6, f"AUDJPY pnl expected ≈$13.33, got ${pnl:.4f}"

    # GBPAUD long 0.01 lot, entry 2.0, current 2.05, AUDUSD = 0.66
    #   pnl_aud = 0.01 × 100000 × (2.05 − 2.00) = 50 AUD
    #   pnl_usd = 50 × 0.66 = $33.00
    df = pd.DataFrame({"close": [2.05]}, index=idx)
    leg = BasketLeg("GBPAUD", lot=0.01, direction=+1, df=df, strategy=None)  # type: ignore
    leg.state = BarState()
    leg.state.in_pos = True
    leg.state.direction = +1
    leg.state.entry_price = 2.0
    ref_closes = {"AUDUSD": 0.66, "GBPUSD": 1.27}
    pnl = _leg_pnl_usd(leg, 2.05, ref_closes)
    assert abs(pnl - 33.0) < 1e-6, f"GBPAUD pnl expected $33, got ${pnl:.4f}"


def test_h2_recycle_v3_usd_anchored_parity_with_v1():
    """Phase 1 / v3 — USD-anchored pair PnL via v3 generalized math must
    match v1's hardcoded formulas byte-identically.
    EURUSD long 0.02 lot, entry 1.10, current 1.11 → expected $20
    USDJPY long 0.01 lot, entry 150, current 151 → expected ≈$6.62
    """
    from tools.recycle_rules.h2_recycle_v3 import _leg_pnl_usd
    from tools.basket_runner import BasketLeg
    from engine_abi.v1_5_9 import BarState

    idx = pd.date_range("2024-09-02", periods=1, freq="5min")
    # EURUSD: pnl = lot × units × (price − entry) = 0.02 × 100000 × 0.01 = $20
    df = pd.DataFrame({"close": [1.11]}, index=idx)
    leg = BasketLeg("EURUSD", lot=0.02, direction=+1, df=df, strategy=None)  # type: ignore
    leg.state = BarState()
    leg.state.in_pos = True
    leg.state.direction = +1
    leg.state.entry_price = 1.10
    ref_closes = {"EURUSD": 1.11}  # self-reference
    pnl = _leg_pnl_usd(leg, 1.11, ref_closes)
    assert abs(pnl - 20.0) < 1e-6, f"EURUSD pnl expected $20, got ${pnl:.4f}"

    # USDJPY: pnl = lot × units × (price − entry) / price = 0.01 × 100000 × 1 / 151 = $6.6225
    df = pd.DataFrame({"close": [151.0]}, index=idx)
    leg = BasketLeg("USDJPY", lot=0.01, direction=+1, df=df, strategy=None)  # type: ignore
    leg.state = BarState()
    leg.state.in_pos = True
    leg.state.direction = +1
    leg.state.entry_price = 150.0
    ref_closes = {"USDJPY": 151.0}
    pnl = _leg_pnl_usd(leg, 151.0, ref_closes)
    assert abs(pnl - (0.01 * 100000 * 1.0 / 151.0)) < 1e-6, (
        f"USDJPY pnl expected ${0.01 * 100000 / 151:.4f}, got ${pnl:.4f}"
    )


def test_compute_basket_telemetry_includes_days_to_exit():
    """Phase 5b.4 / Phase 1 ratio-sweep helper — `_compute_basket_telemetry`
    must compute days_to_exit when start_date is provided, and return -1
    when it cannot (no trades, missing start_date, unparseable timestamps).
    """
    from tools.basket_report import _compute_basket_telemetry

    class _FakeBasketResult:
        recycle_events: list = []
        harvested_total_usd: float = 1002.93
        exit_reason: str = "TARGET"

    # Two trades: 2024-09-02 entry, 2025-10-29 exit (last). Δ = 422 days.
    df = pd.DataFrame({
        "exit_timestamp": ["2024-09-02 10:00:00", "2025-10-29 21:50:00"],
        "pnl_usd": [10.0, 992.93],
    })
    t = _compute_basket_telemetry(_FakeBasketResult(), df, start_date="2024-09-02")
    assert t["days_to_exit"] == 422
    assert t["exit_reason"] == "TARGET"
    assert t["harvested_total_usd"] == 1002.93

    # Without start_date — sentinel
    t_no_start = _compute_basket_telemetry(_FakeBasketResult(), df, start_date=None)
    assert t_no_start["days_to_exit"] == -1

    # Empty trades — sentinel
    t_empty = _compute_basket_telemetry(
        _FakeBasketResult(), pd.DataFrame(columns=["exit_timestamp", "pnl_usd"]),
        start_date="2024-09-02",
    )
    assert t_empty["days_to_exit"] == -1


@pytest.mark.skip(reason="Phase 5 live-data gate: requires 10 historical 2y EUR+JPY 5m datasets + USD_SYNTH features. Deferred until DATA_INGRESS wiring lands.")
def test_basket_pipeline_matches_basket_sim_bit_for_bit_h2_10_windows():
    """The HARD Phase 5 gate per the plan migration risk table.

    Requires:
      - 10 distinct 2-year EUR+JPY 5m datasets
      - USD_SYNTH.compression_5d feature column per dataset
      - basket_sim.simulate() invocation matching the H2 BasketConfig
      - byte-identical equity_curve + events comparison

    Deferred to the follow-up "wire DATA_INGRESS to basket_pipeline" task.
    Keeping the test stub here so the gate is visible in test discovery."""
