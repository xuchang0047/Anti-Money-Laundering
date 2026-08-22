import tempfile
import unittest
from pathlib import Path

from pipeline import PipelineConfig, run_pipeline


ROOT = Path(__file__).resolve().parents[1]


class PipelineEndToEndTest(unittest.TestCase):
    def test_candidate_to_validated_subgraph(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
            result = run_pipeline(
                ROOT / "fixtures" / "candidate_rapid_transfer_v03.json",
                ROOT / "fixtures" / "artifact_manifest_v01.json",
                Path(temporary),
                PipelineConfig(refute_simulations=20, bootstrap_simulations=50, seed=42),
                ROOT / "fixtures" / "attack_summary_v03.json",
            )
            report = result["report"]
            self.assertEqual(report["schema_version"], "ccem.validation_report/v0.3")
            self.assertEqual(report["diagnostics"]["candidate_membership"]["treatment"], "rapid_transfer")
            self.assertTrue(report["accepted"], report["decision_reasons"])
            self.assertIsNotNone(result["validated_package"])
            self.assertTrue(Path(result["outputs"]["validated_subgraph"]).is_file())


if __name__ == "__main__":
    unittest.main()
