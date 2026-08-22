from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from pattern_evolution.src.rule_compiler import compile_experience
from pattern_evolution.src.schemas import PackageValidationError, load_json
from pattern_evolution.validate_attack_contract import validate_attack_outputs


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ATTACK_OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "attacks"


class AttackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, "main.py"],
            cwd=REPOSITORY_ROOT / "attack",
            check=True,
            capture_output=True,
            text=True,
        )

    def test_all_attack_candidates_satisfy_v02(self) -> None:
        report = validate_attack_outputs(ATTACK_OUTPUT_ROOT)
        self.assertEqual("passed", report["status"])
        self.assertEqual(3, report["candidate_count"])

    def test_retrieval_failure_is_exported_from_mutation_scope(self) -> None:
        report = validate_attack_outputs(ATTACK_OUTPUT_ROOT)
        path_extension = next(case for case in report["cases"] if case["attack_type"] == "path_extension")
        self.assertFalse(path_extension["mutated_retrieved"])
        self.assertEqual("mutation_scope", path_extension["candidate_source"])

    def test_candidate_cannot_enter_validated_compiler(self) -> None:
        candidate = load_json(
            ATTACK_OUTPUT_ROOT / "synthetic_sg_001_path_extension" / "candidate_subgraph.json"
        )
        with self.assertRaises(PackageValidationError):
            compile_experience(candidate)


if __name__ == "__main__":
    unittest.main()
