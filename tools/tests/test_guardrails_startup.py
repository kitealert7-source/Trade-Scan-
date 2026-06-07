import unittest
import shutil
import json
from pathlib import Path
import sys
from unittest.mock import patch

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.run_pipeline as rp
from tools.run_pipeline import (
    enforce_run_schema,
    detect_strategy_drift,
    gate_registry_consistency,
    verify_manifest_integrity,
)
from tools.orchestration.pipeline_errors import PipelineAdmissionPause


class TestGuardrailsStartup(unittest.TestCase):
    """Startup guardrail tests.

    The guardrail functions operate on the module-level path globals
    (RUNS_DIR / STRATEGIES_DIR / QUARANTINE_DIR, imported from
    config.state_paths), NOT on their ``project_root`` argument — that
    parameter is vestigial. So each test patches those globals in
    run_pipeline's namespace to point at a disposable temp tree; the
    functions read the names from their own module dict at call time, so the
    redirection takes effect without touching the real TradeScan_State tree.
    """

    def setUp(self):
        self.test_root = PROJECT_ROOT / "tmp" / "test_guardrails"
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True)

        self.runs_dir = self.test_root / "runs"
        self.runs_dir.mkdir()
        self.strat_dir = self.test_root / "strategies"
        self.strat_dir.mkdir()
        self.quarantine_dir = self.test_root / "quarantine"

        # Redirect the guardrails' canonical path globals to the temp tree.
        self._orig_paths = (rp.RUNS_DIR, rp.STRATEGIES_DIR, rp.QUARANTINE_DIR)
        rp.RUNS_DIR = self.runs_dir
        rp.STRATEGIES_DIR = self.strat_dir
        rp.QUARANTINE_DIR = self.quarantine_dir

    def tearDown(self):
        rp.RUNS_DIR, rp.STRATEGIES_DIR, rp.QUARANTINE_DIR = self._orig_paths
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    # --- enforce_run_schema -------------------------------------------------

    def test_enforce_run_schema_pass(self):
        # Valid run container: 24-char id (the canonical run_id length the
        # guard inspects) + run_state.json present.
        run_id = "a" * 24
        run_folder = self.runs_dir / run_id
        run_folder.mkdir()
        (run_folder / "data").mkdir()
        (run_folder / "run_state.json").write_text(
            json.dumps({"run_id": run_id, "current_state": "GENERATED"}),
            encoding="utf-8",
        )

        enforce_run_schema(self.test_root)  # must not raise
        self.assertTrue(run_folder.exists())

    def test_enforce_run_schema_quarantine(self):
        # Corrupt run container: 24-char id MISSING run_state.json (the only
        # startup-required file) -> quarantined + PipelineAdmissionPause.
        run_id = "b" * 24
        run_folder = self.runs_dir / run_id
        run_folder.mkdir()
        (run_folder / "manifest.json").write_text("{}", encoding="utf-8")

        with self.assertRaises(PipelineAdmissionPause):
            enforce_run_schema(self.test_root)

        # Folder moved out of runs/ into quarantine/runs/.
        self.assertFalse(run_folder.exists())
        self.assertTrue((self.quarantine_dir / "runs" / run_id).exists())

    # --- detect_strategy_drift ---------------------------------------------

    def test_detect_strategy_drift_pass(self):
        # Tracked portfolio: carries portfolio_evaluation/portfolio_metadata.json.
        p_eval = self.strat_dir / "PF_VALID" / "portfolio_evaluation"
        p_eval.mkdir(parents=True)
        (p_eval / "portfolio_metadata.json").write_text("{}", encoding="utf-8")

        detect_strategy_drift(self.test_root)  # must not raise

    def test_detect_strategy_drift_fail(self):
        # Untracked directory: no portfolio metadata, no *.py, no deployable/.
        drift_folder = self.strat_dir / "DRIFT_DIR"
        drift_folder.mkdir()
        with self.assertRaises(PipelineAdmissionPause):
            detect_strategy_drift(self.test_root)

        # Unexpected loose file in strategies/ root.
        shutil.rmtree(drift_folder)
        (self.strat_dir / "rogue_file.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(PipelineAdmissionPause):
            detect_strategy_drift(self.test_root)

    # --- verify_manifest_integrity -----------------------------------------

    def test_verify_manifest_integrity_fail(self):
        # Run whose manifest declares a hash that does not match the on-disk
        # artifact at runs/<rid>/data/<name> -> PipelineAdmissionPause.
        run_id = "c" * 24
        run_folder = self.runs_dir / run_id
        data_dir = run_folder / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "results_tradelevel.csv").write_text("dummy data", encoding="utf-8")

        manifest = {
            "run_id": run_id,
            "artifacts": {"results_tradelevel.csv": "WRONG_HASH"},
        }
        (run_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(PipelineAdmissionPause):
            verify_manifest_integrity(self.test_root)

    # --- gate_registry_consistency -----------------------------------------

    def test_gate_registry_consistency_drift(self):
        # Current contract: orphaned-on-disk is AUTO-RECOVERED by the
        # reconciler (sandbox injection) — NOT actionable drift, so the gate
        # must NOT raise. Only registry entries still missing-from-disk after
        # the auto-heal re-check constitute drift -> raise.

        # Scenario 1: orphaned_on_disk only -> no raise.
        with patch("tools.run_pipeline.reconcile_registry") as mock_rec:
            mock_rec.return_value = {
                "orphaned_on_disk": ["RUN_DISK_ONLY"],
                "missing_from_disk": [],
                "invalid_in_registry": [],
            }
            gate_registry_consistency()  # must not raise

        # Scenario 2: missing_from_disk persists across the auto-heal re-check
        # -> drift -> raise. Mock the heal's registry read/write so it stays
        # off the real registry file.
        with patch("tools.run_pipeline.reconcile_registry") as mock_rec, \
                patch("tools.run_pipeline._load_registry", return_value={}), \
                patch("tools.run_pipeline._save_registry_atomic"):
            mock_rec.return_value = {
                "orphaned_on_disk": [],
                "missing_from_disk": ["RUN_REG_ONLY"],
                "invalid_in_registry": [],
            }
            with self.assertRaises(PipelineAdmissionPause):
                gate_registry_consistency()


if __name__ == "__main__":
    unittest.main()
