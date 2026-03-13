import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.orchestration.pre_execution import (
    directive_signature_hash,
    find_directive_path,
    prepare_batch_directives_for_execution,
    prepare_single_directive_for_execution,
    resolve_directive_id_by_signature,
)


def _directive_yaml(directive_id: str) -> str:
    return f"""test:
  name: {directive_id}
  strategy: {directive_id}
  broker: OctaFx
  timeframe: 1d
  start_date: 2015-01-01
  end_date: 2026-01-31
symbols:
  - EURUSD
indicators:
  - indicators.structure.highest_high
execution_rules:
  entry_logic:
    type: volatility_pullback
  exit_logic:
    type: dynamic_or_time
"""


class TestPreExecutionWorkflow(unittest.TestCase):
    def test_find_directive_path(self):
        with tempfile.TemporaryDirectory() as td:
            active = Path(td)
            p = active / "ABC123.txt"
            p.write_text(_directive_yaml("ABC123"), encoding="utf-8")
            self.assertEqual(find_directive_path(active, "ABC123"), p)
            self.assertEqual(find_directive_path(active, "ABC123.txt"), p)
            self.assertIsNone(find_directive_path(active, "MISSING"))

    def test_resolve_by_signature_prefers_namespaced(self):
        with tempfile.TemporaryDirectory() as td:
            active = Path(td)
            legacy = "TEST_PROVISION_ABCDEF12"
            namespaced = "03_TREND_EURUSD_1D_RSIAVG_S01_V1_P00"
            (active / f"{legacy}.txt").write_text(_directive_yaml(legacy), encoding="utf-8")
            (active / f"{namespaced}.txt").write_text(_directive_yaml(namespaced), encoding="utf-8")

            sig = directive_signature_hash(active / f"{legacy}.txt")
            resolved = resolve_directive_id_by_signature(active, sig)
            self.assertEqual(resolved, namespaced)

    def test_prepare_single_directive_finalizes_identity(self):
        with tempfile.TemporaryDirectory() as td:
            active = Path(td)
            legacy = "TEST_PROVISION_ABCDEF12"
            namespaced = "03_TREND_EURUSD_1D_RSIAVG_S01_V1_P00"
            (active / f"{legacy}.txt").write_text(_directive_yaml(legacy), encoding="utf-8")
            (active / f"{namespaced}.txt").write_text(_directive_yaml(namespaced), encoding="utf-8")

            calls = []

            def fake_run(cmd, step_name):
                calls.append((cmd, step_name))
                return True

            final_id = prepare_single_directive_for_execution(
                directive_id=legacy,
                active_dir=active,
                python_exe="python",
                run_command=fake_run,
            )
            self.assertEqual(final_id, namespaced)
            self.assertEqual(len(calls), 1)
            self.assertIn("convert_promoted_directives.py", " ".join(calls[0][0]))
            self.assertEqual(calls[0][1], "Auto Namespace Migration")

    def test_prepare_batch_returns_sorted_directive_paths(self):
        with tempfile.TemporaryDirectory() as td:
            active = Path(td)
            (active / "B.txt").write_text(_directive_yaml("B"), encoding="utf-8")
            (active / "A.txt").write_text(_directive_yaml("A"), encoding="utf-8")

            calls = []

            def fake_run(cmd, step_name):
                calls.append((cmd, step_name))
                return True

            directives = prepare_batch_directives_for_execution(
                active_dir=active,
                python_exe="python",
                run_command=fake_run,
            )
            self.assertEqual([p.name for p in directives], ["A.txt", "B.txt"])
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

