import copy
import unittest
from pathlib import Path

from interface_v03 import (
    InterfaceError,
    read_json,
    resolve_artifact,
    round_half_up_seconds,
    validate_candidate,
    validate_summary_consistency,
)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "fixtures" / "candidate_rapid_transfer_v03.json"
SUMMARY = ROOT / "fixtures" / "attack_summary_v03.json"
MANIFEST = ROOT / "fixtures" / "artifact_manifest_v01.json"


class InterfaceV03Test(unittest.TestCase):
    def setUp(self):
        self.candidate = read_json(CANDIDATE)

    def test_valid_retrieval_failure_candidate_and_manifest(self):
        validate_candidate(self.candidate)
        self.assertFalse(self.candidate["mutation"]["mutated_retrieved"])
        self.assertEqual(self.candidate["mutation"]["candidate_source"], "mutation_scope")
        path, record = resolve_artifact(MANIFEST, "demo-ibm-aml-v03")
        self.assertTrue(path.is_file())
        self.assertEqual(record["format"], "csv")

    def test_summary_candidate_consistency(self):
        validate_summary_consistency(self.candidate, read_json(SUMMARY))
        invalid = read_json(SUMMARY)
        invalid["attack_success"] = False
        with self.assertRaisesRegex(InterfaceError, "hard consistency failure"):
            validate_summary_consistency(self.candidate, invalid)

    def test_round_half_up_not_bankers_rounding(self):
        self.assertEqual(round_half_up_seconds("1.5"), 2)
        self.assertEqual(round_half_up_seconds("2.5"), 3)

    def test_candidate_forbids_validation_and_bad_node_ids(self):
        invalid = copy.deepcopy(self.candidate)
        invalid["validation"] = {"accepted": True}
        with self.assertRaisesRegex(InterfaceError, "must not contain validation"):
            validate_candidate(invalid)
        invalid = copy.deepcopy(self.candidate)
        invalid["graph"]["nodes"][0]["node_id"] = "only-two::parts"
        with self.assertRaisesRegex(InterfaceError, "three-part|dataset_id"):
            validate_candidate(invalid)


if __name__ == "__main__":
    unittest.main()
