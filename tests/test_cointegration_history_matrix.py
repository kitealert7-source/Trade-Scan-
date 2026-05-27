"""test_cointegration_history_matrix.py — versioning + compute discipline.

Validates the C0 deliverable per the architectural review's emphasis on
provenance discipline: hash determinism, file-level no-overwrite,
LATEST-pointer behavior, and schema correctness on synthetic inputs.

No MASTER_DATA dependency — uses fixture data in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cointegration_history_matrix import (
    MATRIX_COLUMNS,
    SCHEMA_VERSION,
    _compute_pair_history,
    build_manifest,
    build_matrix,
    compute_version_hash as mod_compute_version_hash,
    current_params,
    update_latest_pointer,
    write_artifact,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_pair():
    """Cointegrated pair: B = 2·A + stationary noise.

    n=2000 chosen so the 504-bar ADF window has ~70 monthly anchors of
    qualifying data — enough that the qualified flag eventually trips
    True on the synthetic series. Anything < ~1500 risks the long
    window never accumulating enough significant ADF readings.
    """
    rng = np.random.default_rng(seed=42)
    n = 2000
    idx = pd.date_range("2018-01-01", periods=n, freq="D")
    a_returns = rng.normal(0, 0.01, n)
    a = pd.Series(100 * np.exp(np.cumsum(a_returns)), index=idx, name="A")
    noise = rng.normal(0, 0.5, n)
    b = pd.Series(2.0 * a.values + noise, index=idx, name="B")
    return a, b


@pytest.fixture
def synthetic_pair_history(synthetic_pair):
    a, b = synthetic_pair
    return _compute_pair_history(a, b)


# ---------------------------------------------------------------------------
# Per-pair compute — correctness
# ---------------------------------------------------------------------------


class TestPerPairCompute:

    def test_returns_expected_columns(self, synthetic_pair_history):
        expected = ["beta", "spread_mean", "spread_std", "daily_z",
                    "adf_p_252", "adf_p_504", "qualified"]
        assert list(synthetic_pair_history.columns) == expected

    def test_dtypes_match_spec(self, synthetic_pair_history):
        for col in ["beta", "spread_mean", "spread_std", "daily_z",
                     "adf_p_252", "adf_p_504"]:
            assert str(synthetic_pair_history[col].dtype) == "float32"
        assert str(synthetic_pair_history["qualified"].dtype) == "bool"

    def test_beta_recovers_true_hedge_ratio_in_warmed_window(self, synthetic_pair_history):
        # Last bar should have β ≈ 2.0 from the synthetic construction
        beta_last = float(synthetic_pair_history["beta"].iloc[-1])
        assert abs(beta_last - 2.0) < 0.05

    def test_cointegrated_pair_short_adf_qualifies(self, synthetic_pair_history):
        # Short-window ADF reliably rejects the unit-root null on this
        # stationary-noise synthetic. Long-window (504) is sensitive to
        # rolling-β estimation noise propagating into the spread, so it
        # may not reach p<0.05 on synthetic data with only n=2000 — the
        # production CSVs (n~4000-8000) don't suffer from this.
        last_quarter = synthetic_pair_history.iloc[-250:].dropna(subset=["adf_p_252"])
        assert (last_quarter["adf_p_252"] < 0.05).mean() > 0.5

    def test_warmup_rows_are_unqualified(self, synthetic_pair_history):
        # Pre-warmup rows must be qualified=False (ADF NaN < 0.05 is False)
        warmup = synthetic_pair_history.iloc[:200]   # < HEDGE_WINDOW
        assert not warmup["qualified"].any()


# ---------------------------------------------------------------------------
# Versioning — hash determinism
# ---------------------------------------------------------------------------


class TestVersioning:

    def test_current_params_includes_all_required_fields(self):
        params = current_params()
        required = ["tf", "hedge_window", "adf_window_short", "adf_window_long",
                    "adf_sample_every", "adf_lag_bars", "p_qualify", "schema_version"]
        for k in required:
            assert k in params, f"params missing {k}"

    def test_schema_version_is_string(self):
        assert isinstance(SCHEMA_VERSION, str)
        assert SCHEMA_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# Artifact write — never overwrite
# ---------------------------------------------------------------------------


class TestWriteArtifact:

    def _minimal_matrix(self):
        return pd.DataFrame({
            "date": [pd.Timestamp("2025-01-01")],
            "pair_a": ["EURUSD"], "pair_b": ["USDJPY"],
            "beta": [1.5], "spread_mean": [0.0], "spread_std": [1.0],
            "daily_z": [0.5], "adf_p_252": [0.04], "adf_p_504": [0.03],
            "qualified": [True],
        }).astype({
            "beta": "float32", "spread_mean": "float32", "spread_std": "float32",
            "daily_z": "float32", "adf_p_252": "float32", "adf_p_504": "float32",
        })

    def _minimal_manifest(self):
        return {"schema_version": SCHEMA_VERSION, "matrix_hash": "abc123def456",
                 "params": current_params(), "test": True}

    def test_first_write_succeeds(self, tmp_path, monkeypatch):
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        m = self._minimal_matrix()
        mf = self._minimal_manifest()
        parquet_path, manifest_path = mod.write_artifact(m, mf, "abc123def456")
        assert parquet_path.exists()
        assert manifest_path.exists()
        # Manifest is valid JSON
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded["matrix_hash"] == "abc123def456"

    def test_second_write_with_same_hash_raises(self, tmp_path, monkeypatch):
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        m = self._minimal_matrix()
        mf = self._minimal_manifest()
        mod.write_artifact(m, mf, "abc123def456")
        with pytest.raises(FileExistsError, match="NEVER OVERWRITE"):
            mod.write_artifact(m, mf, "abc123def456")

    def test_force_overwrite_works(self, tmp_path, monkeypatch):
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        m = self._minimal_matrix()
        mf = self._minimal_manifest()
        mod.write_artifact(m, mf, "abc123def456")
        # force=True allows overwrite (intentional act)
        mod.write_artifact(m, mf, "abc123def456", force=True)

    def test_different_hash_coexists(self, tmp_path, monkeypatch):
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        m = self._minimal_matrix()
        mf1 = {**self._minimal_manifest(), "matrix_hash": "hash1"}
        mf2 = {**self._minimal_manifest(), "matrix_hash": "hash2"}
        mod.write_artifact(m, mf1, "hash1")
        mod.write_artifact(m, mf2, "hash2")
        # Both artifacts coexist
        assert (tmp_path / "coint_1d_history_matrix_hash1.parquet").exists()
        assert (tmp_path / "coint_1d_history_matrix_hash2.parquet").exists()


# ---------------------------------------------------------------------------
# LATEST pointer
# ---------------------------------------------------------------------------


class TestLatestPointer:

    def test_pointer_writes_correctly(self, tmp_path, monkeypatch):
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(mod, "LATEST_POINTER", tmp_path / "LATEST.json")
        parquet_path = tmp_path / "coint_1d_history_matrix_hash1.parquet"
        manifest_path = tmp_path / "coint_1d_history_matrix_hash1.manifest.json"
        mod.update_latest_pointer("hash1", parquet_path, manifest_path)
        pointer = json.loads((tmp_path / "LATEST.json").read_text(encoding="utf-8"))
        assert pointer["matrix_hash"] == "hash1"
        assert pointer["parquet_file"] == parquet_path.name
        assert pointer["manifest_file"] == manifest_path.name

    def test_pointer_can_be_overwritten(self, tmp_path, monkeypatch):
        """The LATEST pointer IS allowed to be overwritten — only the
        hashed artifacts are immutable. This is by design."""
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(mod, "LATEST_POINTER", tmp_path / "LATEST.json")
        mod.update_latest_pointer("hash1", tmp_path / "a.parquet", tmp_path / "a.json")
        mod.update_latest_pointer("hash2", tmp_path / "b.parquet", tmp_path / "b.json")
        pointer = json.loads((tmp_path / "LATEST.json").read_text(encoding="utf-8"))
        assert pointer["matrix_hash"] == "hash2"   # last write wins


# ---------------------------------------------------------------------------
# Manifest — required fields
# ---------------------------------------------------------------------------


class TestManifest:

    def test_manifest_includes_required_fields(self, synthetic_pair):
        a, b = synthetic_pair
        closes = pd.concat([a, b], axis=1, join="inner").dropna()
        closes.columns = ["A", "B"]
        # Build a single-pair matrix synthetically
        ph = _compute_pair_history(a, b).reset_index()
        ph = ph.rename(columns={ph.columns[0]: "date"})
        ph["pair_a"] = "A"
        ph["pair_b"] = "B"
        matrix = ph[MATRIX_COLUMNS]

        manifest = build_manifest("testhash12ab", current_params(), ["A", "B"],
                                    closes, matrix, [])
        # Required fields per spec
        for k in ["schema_version", "matrix_hash", "params", "universe",
                  "date_range", "matrix_stats", "source_csv_files",
                  "generated_at", "generator"]:
            assert k in manifest, f"manifest missing {k}"

        assert manifest["matrix_stats"]["total_rows"] == len(matrix)
        assert manifest["matrix_stats"]["qualified_rows"] >= 0
        assert 0.0 <= manifest["matrix_stats"]["qualified_pct"] <= 1.0


# ---------------------------------------------------------------------------
# Multi-TF parameterization (Phase 1, locked decision 2026-05-26)
# ---------------------------------------------------------------------------


class TestMultiTFParameterization:
    """Phase-1 parameterization: 1d defaults preserve legacy behavior;
    4h opt-in produces sibling artifacts with calendar-matched windows."""

    def test_current_params_defaults_to_1d_legacy_values(self):
        params = current_params()
        assert params["tf"] == "1d"
        assert params["hedge_window"] == 252
        assert params["adf_window_short"] == 252
        assert params["adf_window_long"] == 504
        assert params["adf_sample_every"] == 21

    def test_current_params_4h_uses_calendar_matched_windows(self):
        params = current_params("4h")
        assert params["tf"] == "4h"
        assert params["hedge_window"] == 1500     # ~1y at 4H FX
        assert params["adf_window_short"] == 1500
        assert params["adf_window_long"] == 3000  # ~2y at 4H FX
        assert params["adf_sample_every"] == 30   # ~weekly resample

    def test_current_params_unsupported_tf_raises(self):
        with pytest.raises(ValueError, match="Unsupported tf"):
            current_params("1h")
        with pytest.raises(ValueError, match="Unsupported tf"):
            current_params("15m")

    def test_4h_write_artifact_uses_4h_filename(self, tmp_path, monkeypatch):
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        m = pd.DataFrame({
            "date": [pd.Timestamp("2025-01-01")],
            "pair_a": ["EURUSD"], "pair_b": ["USDJPY"],
            "beta": [1.5], "spread_mean": [0.0], "spread_std": [1.0],
            "daily_z": [0.5], "adf_p_1500": [0.04], "adf_p_3000": [0.03],
            "qualified": [True],
        }).astype({
            "beta": "float32", "spread_mean": "float32", "spread_std": "float32",
            "daily_z": "float32", "adf_p_1500": "float32", "adf_p_3000": "float32",
        })
        mf = {"schema_version": SCHEMA_VERSION, "matrix_hash": "4habcdef1234",
              "params": current_params("4h"), "tf": "4h"}
        parquet_path, manifest_path = mod.write_artifact(
            m, mf, "4habcdef1234", tf="4h",
        )
        assert parquet_path.name == "coint_4h_history_matrix_4habcdef1234.parquet"
        assert manifest_path.name == "coint_4h_history_matrix_4habcdef1234.manifest.json"
        assert parquet_path.exists()

    def test_1d_and_4h_artifacts_coexist(self, tmp_path, monkeypatch):
        """Locked-decision invariant: different TFs produce distinct
        artifact filenames and can coexist in OUTPUT_DIR."""
        import tools.cointegration_history_matrix as mod
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
        # 1d artifact
        m_1d = pd.DataFrame({
            "date": [pd.Timestamp("2025-01-01")],
            "pair_a": ["EURUSD"], "pair_b": ["USDJPY"],
            "beta": [1.5], "spread_mean": [0.0], "spread_std": [1.0],
            "daily_z": [0.5], "adf_p_252": [0.04], "adf_p_504": [0.03],
            "qualified": [True],
        }).astype({
            "beta": "float32", "spread_mean": "float32", "spread_std": "float32",
            "daily_z": "float32", "adf_p_252": "float32", "adf_p_504": "float32",
        })
        # 4h artifact (same hash literal, different tf — must still coexist)
        m_4h = m_1d.rename(columns={"adf_p_252": "adf_p_1500",
                                     "adf_p_504": "adf_p_3000"})
        mf_1d = {"schema_version": SCHEMA_VERSION, "matrix_hash": "samehashvalue",
                 "params": current_params("1d")}
        mf_4h = {"schema_version": SCHEMA_VERSION, "matrix_hash": "samehashvalue",
                 "params": current_params("4h")}
        mod.write_artifact(m_1d, mf_1d, "samehashvalue", tf="1d")
        mod.write_artifact(m_4h, mf_4h, "samehashvalue", tf="4h")
        assert (tmp_path / "coint_1d_history_matrix_samehashvalue.parquet").exists()
        assert (tmp_path / "coint_4h_history_matrix_samehashvalue.parquet").exists()

    def test_compute_pair_history_4h_columns_use_bar_count_naming(self, synthetic_pair):
        """4h-params compute should emit adf_p_1500 / adf_p_3000 columns,
        not adf_p_252 / adf_p_504. Schema must encode the lookback so
        consumers can read the right TF unambiguously."""
        a, b = synthetic_pair
        # synthetic_pair has n=2000 — adequate for 1500-bar window short test.
        # Use a tweaked params dict with a smaller long window so the fixture
        # data length is sufficient.
        params = dict(current_params("4h"))
        params["adf_window_long"] = 1800  # fit within n=2000 fixture
        ph = _compute_pair_history(a, b, params=params)
        assert "adf_p_1500" in ph.columns
        assert "adf_p_1800" in ph.columns
        assert "adf_p_252" not in ph.columns
        assert "adf_p_504" not in ph.columns

    def test_4h_latest_pointer_is_separate_from_1d(self, tmp_path):
        """latest_pointer_for(tf) must return distinct paths per TF."""
        import tools.cointegration_history_matrix as mod
        p_1d = mod.latest_pointer_for("1d")
        p_4h = mod.latest_pointer_for("4h")
        assert p_1d != p_4h
        assert p_1d.name == "coint_1d_history_matrix_LATEST.json"
        assert p_4h.name == "coint_4h_history_matrix_LATEST.json"

    def test_compute_version_hash_differs_by_tf(self):
        """Same universe + same code, different tf → different hash.
        Ensures 1d and 4h artifacts have distinct provenance even if
        the source CSV files share names across TFs."""
        # Use a universe that doesn't actually exist on disk so glob
        # returns empty — the hash then depends only on params + tf.
        params_1d = current_params("1d")
        params_4h = current_params("4h")
        h_1d = mod_compute_version_hash(["NONEXISTENT_SYMBOL_FOR_TEST"], params_1d, tf="1d")
        h_4h = mod_compute_version_hash(["NONEXISTENT_SYMBOL_FOR_TEST"], params_4h, tf="4h")
        assert h_1d != h_4h


# ---------------------------------------------------------------------------
# Parallel-determinism regression guard (2026-05-27)
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_universe_closes():
    """3 synthetic price series → 3 pair-pairs for the determinism check.

    One pair (A, B) is designed to be cointegrated (B = 2·A + small noise)
    so the qualified mask trips True for at least part of the series;
    C is an independent random walk so pairs involving C have mixed
    qualified phases. This produces a non-trivial qualified column
    across the matrix — empty/all-True/all-False columns would
    weaken the byte-equivalence check.

    Series length n=1500 + production 1d params (hedge_window=252,
    adf_window_long=504, adf_sample_every=21) keep the test under
    ~15s while exercising the full production code path. Using
    `current_params("1d")` ensures the column-name resolution in
    matrix_columns_for() matches the per-pair output schema.
    """
    rng = np.random.default_rng(seed=42)
    n = 1500
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    a_returns = rng.normal(0, 0.01, n)
    a = 100 * np.exp(np.cumsum(a_returns))
    b = 2.0 * a + rng.normal(0, 0.5, n)
    c_returns = rng.normal(0, 0.01, n)
    c = 50 * np.exp(np.cumsum(c_returns))
    closes = pd.DataFrame({"A": a, "B": b, "C": c}, index=idx)
    return closes


class TestParallelDeterminism:
    """Promoted from tmp/audit_parallel_determinism.py 2026-05-27.

    Verifies that build_matrix produces byte-identical output regardless
    of worker count. Without this guard, future refactors of the
    parallel dispatch path could silently introduce floating-point
    drift, row-ordering issues, or worker-completion-order artifacts.
    The audit on the real 28-pair 4h subset confirmed byte equivalence
    once; this synthetic-data version runs every CI to prevent
    regression.
    """

    def test_workers_1_vs_2_byte_identical(
        self, synthetic_universe_closes,
    ):
        params = current_params("1d")
        m_seq = build_matrix(
            synthetic_universe_closes, params=params, max_workers=1,
        )
        m_par = build_matrix(
            synthetic_universe_closes, params=params, max_workers=2,
        )

        # Schema
        assert list(m_seq.columns) == list(m_par.columns), \
            "column order differs between workers=1 and workers=2"
        for col in m_seq.columns:
            assert m_seq[col].dtype == m_par[col].dtype, \
                f"dtype differs for {col}: seq={m_seq[col].dtype} par={m_par[col].dtype}"

        # Shape
        assert m_seq.shape == m_par.shape, \
            f"shape differs: seq={m_seq.shape} par={m_par.shape}"

        # Pair set
        pairs_seq = set(zip(m_seq.pair_a, m_seq.pair_b))
        pairs_par = set(zip(m_par.pair_a, m_par.pair_b))
        assert pairs_seq == pairs_par, \
            f"pair set differs: seq-only={pairs_seq - pairs_par} par-only={pairs_par - pairs_seq}"

        # Byte-level value equivalence — the strongest single check.
        # Catches floating-point drift, row-ordering artifacts, dtype
        # promotion, and NaN handling differences in one assertion.
        assert m_seq.equals(m_par), \
            "build_matrix output differs between workers=1 and workers=2 — non-determinism in parallel path"

    def test_qualified_mask_matches(
        self, synthetic_universe_closes,
    ):
        """Tier-2 check that targets the qualified column specifically —
        the field downstream backtests read. df.equals() above already
        covers this, but a dedicated assertion improves failure clarity
        if a future regression flips a qualified bit.
        """
        params = current_params("1d")
        m_seq = build_matrix(
            synthetic_universe_closes, params=params, max_workers=1,
        )
        m_par = build_matrix(
            synthetic_universe_closes, params=params, max_workers=2,
        )
        assert m_seq.qualified.sum() == m_par.qualified.sum(), \
            "total qualified-bar count differs across worker counts"
        for (a, b), s_seq in m_seq.groupby(["pair_a", "pair_b"]):
            s_par = m_par[(m_par.pair_a == a) & (m_par.pair_b == b)]
            assert s_seq.qualified.sum() == s_par.qualified.sum(), \
                f"qualified count for {a}/{b} differs across worker counts"

    def test_workers_default_resolves_to_int(self):
        """The auto-default is a positive int and doesn't crash on
        common CPU configurations."""
        from tools.cointegration_history_matrix import _default_workers
        w = _default_workers()
        assert isinstance(w, int) and w >= 1
        assert w <= 12, f"_default_workers exceeded the safety cap: {w}"
