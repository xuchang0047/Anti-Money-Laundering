from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pattern_evolution.src.evolution_loop import run_evolution
from pattern_evolution.src.matcher import match
from pattern_evolution.src.multignn_adapter import to_multignn_payload, to_torch_tensors
from pattern_evolution.src.proxy_mutator import apply_intervention, causal_roles, make_candidate_proxy, make_validation_report
from pattern_evolution.src.rule_compiler import compile_experience
from pattern_evolution.src.schemas import PackageValidationError, build_validated_package, validate_candidate, validate_validated


class InterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = make_candidate_proxy()
        self.report = make_validation_report(self.candidate)
        self.validated = build_validated_package(self.candidate, self.report, causal_roles(self.candidate))

    def test_candidate_and_validated_are_accepted(self) -> None:
        validate_candidate(self.candidate)
        validate_validated(self.validated)

    def test_candidate_cannot_forge_validation(self) -> None:
        invalid = copy.deepcopy(self.candidate)
        invalid["validation"] = {"accepted": True}
        with self.assertRaises(PackageValidationError):
            validate_candidate(invalid)

    def test_rejected_validated_cannot_compile(self) -> None:
        invalid = copy.deepcopy(self.validated)
        invalid["validation"]["accepted"] = False
        with self.assertRaises(PackageValidationError):
            compile_experience(invalid)

    def test_compiled_experience_has_no_node_id_leak(self) -> None:
        experience = compile_experience(self.validated)
        serialized = json.dumps(experience, sort_keys=True)
        for node in self.validated["graph"]["nodes"]:
            self.assertNotIn(node["node_id"], serialized)

    def test_positive_and_counterfactual_replay(self) -> None:
        experience = compile_experience(self.validated)
        self.assertTrue(match(self.validated["graph"], experience).matched)
        for item in self.report["counterfactuals"]:
            graph = apply_intervention(self.validated["graph"], item["intervention"])
            self.assertFalse(match(graph, experience).matched, item["name"])

    def test_multignn_contract(self) -> None:
        payload = to_multignn_payload(self.validated)
        tensors = to_torch_tensors(self.validated)
        self.assertEqual((2, 9), (len(payload["edge_index"]), len(payload["edge_index"][0])))
        self.assertEqual((9, 4), (len(payload["edge_attr"]), len(payload["edge_attr"][0])))
        self.assertEqual([2, 9], list(tensors["edge_index"].shape))
        self.assertNotIn("y", payload)
        self.assertEqual([], payload["derived_fields"])

    def test_full_evolution_without_optional_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_evolution(Path(directory), api_config=None)
        self.assertEqual("passed", summary["status"])
        self.assertEqual(0, summary["metrics"]["before_evolution"]["proxy_recall"])
        self.assertEqual(1, summary["metrics"]["after_evolution"]["proxy_recall"])
        self.assertEqual(0, summary["metrics"]["counterfactual_false_positive_count"])
        self.assertEqual(0, summary["metrics"]["old_pattern_regression"])


if __name__ == "__main__":
    unittest.main()
