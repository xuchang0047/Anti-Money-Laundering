"""End-to-end CCEM self-evolution round."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .canonicalizer import canonicalize_relay_bridge
from .experience_library import DetectorLibrary
from .hypothesis_agent import generate_hypothesis
from .matcher import match
from .multignn_adapter import to_multignn_payload, to_torch_tensors
from .proxy_mutator import (
    apply_intervention,
    causal_roles,
    make_augmented_positive,
    make_base_gather_scatter_graph,
    make_candidate_proxy,
    make_validation_report,
)
from .rule_compiler import compile_experience
from .schemas import build_validated_package, stable_hash, validate_candidate, validate_report, validate_validated, write_json_atomic


def _matched_ids(results: list[Any]) -> list[str]:
    return sorted(result.detector_id for result in results)


def run_evolution(
    output_dir: str | Path,
    *,
    api_config: str | Path | None = None,
    require_api: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    proxy_dir = output_dir / "proxies"
    library_dir = output_dir / "library"
    run_dir = output_dir / "run"

    candidate = make_candidate_proxy()
    report = make_validation_report(candidate)
    validate_candidate(candidate)
    validate_report(report)
    validated = build_validated_package(candidate, report, causal_roles(candidate))
    validate_validated(validated)

    write_json_atomic(proxy_dir / "candidate_subgraph_v0.2.json", candidate)
    write_json_atomic(proxy_dir / "validation_report_v0.2.json", report)
    write_json_atomic(proxy_dir / "validated_subgraph_v0.2.json", validated)

    library = DetectorLibrary()
    library.save(library_dir / "detector_library_v0.json")
    base_graph = make_base_gather_scatter_graph()
    before_proxy = library.detect(validated["graph"])
    before_base = library.detect(base_graph)

    canonical = canonicalize_relay_bridge(validated["graph"])
    hypothesis_result: dict[str, Any] = {"status": "not_requested"}
    if api_config is not None:
        try:
            hypothesis_result = generate_hypothesis(canonical, api_config)
        except Exception as exc:
            if require_api:
                raise
            hypothesis_result = {"status": "failed_non_blocking", "error_type": type(exc).__name__, "message": str(exc)}
    write_json_atomic(run_dir / "hypothesis_agent_result.json", hypothesis_result)

    experience = compile_experience(validated)
    if hypothesis_result.get("status") == "success":
        experience["agent_hypothesis_view"] = {
            "non_executable": True,
            "model": hypothesis_result["model"],
            "content": hypothesis_result["hypothesis"],
        }
        experience["experience_hash"] = stable_hash({key: value for key, value in experience.items() if key != "experience_hash"})

    positive_result = match(validated["graph"], experience)
    augmented_result = match(make_augmented_positive(validated["graph"]), experience)
    counterfactual_results: list[dict[str, Any]] = []
    for item in report["counterfactuals"]:
        counterfactual_graph = apply_intervention(validated["graph"], item["intervention"])
        result = match(counterfactual_graph, experience)
        artifact = {
            "name": item["name"],
            "intervention": item["intervention"],
            "graph": counterfactual_graph,
            "match_result": result.to_dict(),
        }
        counterfactual_results.append(artifact)
        write_json_atomic(proxy_dir / f"counterfactual_{item['name']}.json", artifact)

    replay = {
        "positive_matched": positive_result.matched,
        "augmented_positive_matched": augmented_result.matched,
        "counterfactual_false_positives": sum(item["match_result"]["matched"] for item in counterfactual_results),
        "counterfactual_count": len(counterfactual_results),
        "all_gates_passed": (
            positive_result.matched
            and augmented_result.matched
            and not any(item["match_result"]["matched"] for item in counterfactual_results)
            and bool(before_base)
        ),
        "suggest_specialization": False,
    }
    if not replay["all_gates_passed"]:
        raise RuntimeError(f"experience replay gate failed: {replay}")

    evolution_event = library.evolve(experience, replay)
    library.save(library_dir / f"detector_library_v{library.version}.json")
    after_proxy = library.detect(validated["graph"])
    after_base = library.detect(base_graph)

    adapter_payload = to_multignn_payload(validated)
    tensor_payload = to_torch_tensors(validated)
    adapter_contract = {
        "node_count": len(adapter_payload["x"]),
        "edge_count": len(adapter_payload["edge_attr"]),
        "edge_index_shape": [len(adapter_payload["edge_index"]), len(adapter_payload["edge_index"][0])],
        "edge_attr_shape": [len(adapter_payload["edge_attr"]), len(adapter_payload["edge_attr"][0])],
        "torch_shapes": {
            "x": list(tensor_payload["x"].shape),
            "edge_index": list(tensor_payload["edge_index"].shape),
            "edge_attr": list(tensor_payload["edge_attr"].shape),
            "timestamps": list(tensor_payload["timestamps"].shape),
        },
        "oracle_present": False,
        "derived_fields": adapter_payload["derived_fields"],
        "pyg_runtime_available": _pyg_available(),
    }
    write_json_atomic(run_dir / "multignn_adapter_contract.json", adapter_contract)

    before_proxy_recall = 1 if before_proxy else 0
    after_new_match = experience["experience_id"] in _matched_ids(after_proxy)
    old_detector_id = "ibm_baseline_gather_scatter"
    old_before = old_detector_id in _matched_ids(before_base)
    old_after = old_detector_id in _matched_ids(after_base)
    metrics = {
        "before_evolution": {
            "proxy_recall": before_proxy_recall,
            "proxy_matches": _matched_ids(before_proxy),
            "old_gather_scatter_detected": old_before,
        },
        "after_evolution": {
            "proxy_recall": 1 if after_new_match else 0,
            "proxy_matches": _matched_ids(after_proxy),
            "old_gather_scatter_detected": old_after,
        },
        "counterfactual_false_positive_count": replay["counterfactual_false_positives"],
        "old_pattern_regression": int(old_before and not old_after),
        "positive_replay_passed": positive_result.matched,
        "augmented_replay_passed": augmented_result.matched,
        "library_version": library.version,
        "evolution_operation": evolution_event["operation"],
        "hypothesis_agent_status": hypothesis_result["status"],
    }
    expected = {
        "before_proxy_recall": 0,
        "after_proxy_recall": 1,
        "counterfactual_false_positive_count": 0,
        "old_pattern_regression": 0,
        "library_version": 1,
        "evolution_operation": "ADD",
        "hypothesis_agent_status": "success" if require_api else hypothesis_result["status"],
    }
    actual = {
        "before_proxy_recall": metrics["before_evolution"]["proxy_recall"],
        "after_proxy_recall": metrics["after_evolution"]["proxy_recall"],
        "counterfactual_false_positive_count": metrics["counterfactual_false_positive_count"],
        "old_pattern_regression": metrics["old_pattern_regression"],
        "library_version": metrics["library_version"],
        "evolution_operation": metrics["evolution_operation"],
        "hypothesis_agent_status": metrics["hypothesis_agent_status"],
    }
    summary = {
        "status": "passed" if actual == expected else "failed",
        "pipeline": [
            "CandidateSubgraphPackage",
            "ValidationReport",
            "ValidatedSubgraphPackage",
            "HypothesisGenerationAgent",
            "Canonicalizer",
            "RuleCompiler",
            "CounterfactualReplay",
            "ExperienceLibrary",
            "NextRoundDetection",
            "MultiGNNAdapter",
        ],
        "metrics": metrics,
        "expected": expected,
        "actual": actual,
        "experience_id": experience["experience_id"],
        "experience_hash": experience["experience_hash"],
        "adapter_contract": adapter_contract,
        "artifacts": {
            "candidate": str(proxy_dir / "candidate_subgraph_v0.2.json"),
            "validation_report": str(proxy_dir / "validation_report_v0.2.json"),
            "validated": str(proxy_dir / "validated_subgraph_v0.2.json"),
            "library_v0": str(library_dir / "detector_library_v0.json"),
            "library_v1": str(library_dir / "detector_library_v1.json"),
            "hypothesis": str(run_dir / "hypothesis_agent_result.json"),
        },
    }
    write_json_atomic(run_dir / "latest_summary.json", summary)
    if summary["status"] != "passed":
        raise RuntimeError(f"end-to-end acceptance failed: {actual} != {expected}")
    return summary


def _pyg_available() -> bool:
    try:
        import torch_geometric  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True
