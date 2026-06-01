"""Basket reproducibility identity — engine + per-leg data hash in the manifest.

A basket run is reproducible iff its inputs are unchanged: directive + engine +
leg data + leg/rule code. Part A records the code hashes; these helpers add the
engine version + per-leg DATA hash so a re-run can be compared to a prior run
and declared reproducible-or-new-truth (single-strategy parquet_sha256 model).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.basket_provenance import (  # noqa: E402
    basket_input_provenance,
    compare_basket_runs,
    leg_data_sha256,
)


def _df(seed: int, n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-09-02", periods=n, freq="5min")
    base = 1.10 + np.cumsum(rng.normal(0, 0.0005, n))
    return pd.DataFrame({"open": base, "high": base, "low": base,
                         "close": base, "volume": 1000.0}, index=idx)


def _manifest(directive="d1", engine="1.5.8", legs=None, code=None) -> dict:
    return {
        "strategy_hash": directive,
        "engine_version": engine,
        "input_provenance": {"engine_version": engine,
                             "leg_data_sha256": legs or {}},
        "artifacts": {"results_tradelevel.csv": "abc", **(code or {})},
    }


# ── hashing ────────────────────────────────────────────────────────────────


def test_leg_data_sha256_is_deterministic():
    df = _df(1)
    assert leg_data_sha256(df) == leg_data_sha256(df.copy())


def test_leg_data_sha256_detects_change():
    assert leg_data_sha256(_df(1)) != leg_data_sha256(_df(2))


def test_basket_input_provenance_shape():
    prov = basket_input_provenance({"EURUSD": _df(1), "USDJPY": _df(2)}, "1.5.8")
    assert prov["engine_version"] == "1.5.8"
    assert set(prov["leg_data_sha256"]) == {"EURUSD", "USDJPY"}
    assert all(len(h) == 64 for h in prov["leg_data_sha256"].values())


# ── comparison ─────────────────────────────────────────────────────────────


def test_identical_runs_are_reproducible():
    legs = {"EURUSD": "h1", "USDJPY": "h2"}
    code = {"basket_code/recycle_strategies.py": "c1"}
    a = _manifest(legs=legs, code=code)
    b = _manifest(legs=dict(legs), code=dict(code))
    v = compare_basket_runs(a, b)
    assert v["reproducible"] is True and v["changed"] == []


def test_data_change_is_new_truth():
    a = _manifest(legs={"EURUSD": "h1"})
    b = _manifest(legs={"EURUSD": "DIFFERENT"})
    v = compare_basket_runs(a, b)
    assert v["reproducible"] is False
    assert "leg_data:EURUSD" in v["changed"]


def test_engine_change_is_new_truth():
    v = compare_basket_runs(_manifest(engine="1.5.8"), _manifest(engine="1.5.9"))
    assert v["reproducible"] is False
    assert any("engine_version" in c for c in v["changed"])


def test_code_change_is_new_truth():
    a = _manifest(code={"basket_code/recycle_rules/h2_recycle.py": "c1"})
    b = _manifest(code={"basket_code/recycle_rules/h2_recycle.py": "c2"})
    v = compare_basket_runs(a, b)
    assert v["reproducible"] is False
    assert "code:recycle_rules/h2_recycle.py" in v["changed"]
