import unittest
import shutil
import json
import os
from pathlib import Path
import sys

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_pipeline import enforce_run_schema, detect_strategy_drift, gate_registry_consistency
from tools.orchestration.pipeline_errors import PipelineAdmissionPause

class TestGuardrailsStartup(unittest.TestCase):
    def setUp(self):
        self.test_root = PROJECT_ROOT / "tmp" / "test_guardrails"
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True)
        
        self.runs_dir = self.test_root / "runs"
        self.runs_dir.mkdir()
        
        self.strat_dir = self.test_root / "strategies"
        self.strat_dir.mkdir()
        
        self.quarantine_dir = self.test_root / "quarantine" / "runs"
        
    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_enforce_run_schema_pass(self):
        # Create a valid run
        run_id = "valid_run"
        run_folder = self.runs_dir / run_id
        run_folder.mkdir()
        (run_folder / "data").mkdir()
        (run_folder / "manifest.json").touch()
        (run_folder / "run_state.json").touch()
        
        # Should not raise exception
        enforce_run_schema(self.test_root)
        self.assertTrue(run_folder.exists())

    def test_enforce_run_schema_quarantine(self):
        # Create an invalid run (missing data/)
        run_id = "invalid_run"
        run_folder = self.runs_dir / run_id
        run_folder.mkdir()
        (run_folder / "manifest.json").touch()
        (run_folder / "run_state.json").touch()
        
        with self.assertRaises(PipelineAdmissionPause):
            enforce_run_schema(self.test_root)
            
        # Verify quarantine
        self.assertFalse(run_folder.exists())
        self.assertTrue((self.test_root / "quarantine" / "runs" / run_id).exists())

    def test_detect_strategy_drift_pass(self):
        # Valid portfolio
        p_id = "PF_VALID"
        p_folder = self.strat_dir / p_id
        p_folder.mkdir()
        (p_folder / "portfolio_metadata.json").touch()
        
        # Should not raise
        from tools.run_pipeline import detect_strategy_drift
        detect_strategy_drift(self.test_root)

    def test_detect_strategy_drift_fail(self):
        # Untracked directory (missing metadata)
        drift_id = "DRIFT_DIR"
        drift_folder = self.strat_dir / drift_id
        drift_folder.mkdir()
        
        from tools.run_pipeline import detect_strategy_drift
        with self.assertRaises(PipelineAdmissionPause):
            detect_strategy_drift(self.test_root)

        # Unexpected file
        shutil.rmtree(drift_folder)
        (self.strat_dir / "rogue_file.txt").touch()
        with self.assertRaises(PipelineAdmissionPause):
            detect_strategy_drift(self.test_root)

    def test_verify_manifest_integrity_fail(self):
        # Create a run with a corrupted manifest
        run_id = "corrupt_run"
        run_folder = self.runs_dir / run_id
        run_folder.mkdir()
        data_dir = run_folder / "data"
        data_dir.mkdir()
        
        # Create artifact
        art_file = data_dir / "results_tradelevel.csv"
        art_file.write_text("dummy data")
        
        # Manifest with WRONG hash
        import hashlib
        manifest = {
            "run_id": run_id,
            "artifacts": {
                "results_tradelevel.csv": "WRONG_HASH"
            }
        }
        with open(run_folder / "manifest.json", "w") as f:
            import json
            json.dump(manifest, f)
            
        from tools.run_pipeline import verify_manifest_integrity
        with self.assertRaises(PipelineAdmissionPause):
            verify_manifest_integrity(self.test_root)

    def test_gate_registry_consistency_drift(self):
        # This test is a bit complex because reconcile_registry uses global paths
        # However, we can mock or just verify the printing logic if we had a mock registry.
        # For simplicity, I will verify the logic in run_pipeline.py directly 
        # by checking how it handles results from reconcile_registry.
        
        from tools.run_pipeline import gate_registry_consistency
        from unittest.mock import patch
        
        # Simulate DISK_NOT_IN_REGISTRY
        with patch('tools.run_pipeline.reconcile_registry') as mock_rec:
            mock_rec.return_value = {
                "orphaned_on_disk": ["RUN_DISK_ONLY"],
                "missing_from_disk": [],
                "invalid_in_registry": []
            }
            with self.assertRaises(PipelineAdmissionPause):
                gate_registry_consistency()

        # Simulate REGISTRY_RUN_MISSING_ON_DISK
        with patch('tools.run_pipeline.reconcile_registry') as mock_rec:
            mock_rec.return_value = {
                "orphaned_on_disk": [],
                "missing_from_disk": ["RUN_REG_ONLY"],
                "invalid_in_registry": []
            }
            with self.assertRaises(PipelineAdmissionPause):
                gate_registry_consistency()

if __name__ == "__main__":
    unittest.main()
