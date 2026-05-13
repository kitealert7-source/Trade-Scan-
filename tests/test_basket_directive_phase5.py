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
    assert result.rule_name == "H2_v7_compression"
    assert result.rule_version == 1
    # Gate closed -> no recycle events
    assert result.recycle_events == []
    assert result.harvested_total_usd == 0.0

    row = result.to_mps_row()
    assert row["execution_mode"] == "basket"
    assert row["basket_id"] == "H2"
    assert len(row["basket_legs"]) == 2


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
