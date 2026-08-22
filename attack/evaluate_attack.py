"""Rebuild, re-retrieve, and re-evaluate a controlled mutation."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from baseline_detector import detect_scatter_gather
from candidate_retriever import retrieve_scatter_gather_candidates
from feature_extractor import extract_candidate_features
from graph_builder import build_transaction_graph


def _matching_candidate(candidates: list[dict], base_candidate: dict):
    for candidate in candidates:
        if (
            candidate["source"] == base_candidate["source"]
            and candidate["destination"] == base_candidate["destination"]
        ):
            return candidate
    return None


def _feature_delta(before: dict, after: dict) -> tuple[list[str], list[str]]:
    if not after:
        return [], sorted(before)
    stable = []
    changed = []
    for name, value in before.items():
        if np.isclose(value, after[name], equal_nan=True):
            stable.append(name)
        else:
            changed.append(name)
    return stable, changed


def _failure_type(
    before_detected: bool, mutated_retrieved: bool, after_detected: bool
) -> str:
    if not before_detected:
        return "baseline_precondition_failure"
    if not mutated_retrieved:
        return "retrieval_failure"
    if not after_detected:
        return "detection_failure"
    return "no_failure"


def _evolution_hint(
    attack_type: str,
    failure_type: str,
    stable_features: list[str],
    failed_conditions: list[str],
) -> dict:
    """Summarize only evidence observed in this prototype evaluation."""
    if failure_type == "retrieval_failure":
        return {
            "preserve": stable_features,
            "relax_or_reformulate": ["2-hop scatter-gather retrieval constraint"],
            "recommended_direction": (
                "Evaluate bounded multi-hop retrieval before changing detector "
                "conditions; mutated features were unavailable after retrieval failed."
            ),
        }
    if failure_type == "detection_failure":
        direction = (
            "Preserve conditions tied to stable features and review only the "
            "failed prototype conditions against the observed mutation."
        )
        if attack_type == "temporal_stretch":
            direction = (
                "Evaluate a delay-aware temporal condition while preserving the "
                "observed stable structural and flow features."
            )
        return {
            "preserve": stable_features,
            "relax_or_reformulate": failed_conditions,
            "recommended_direction": direction,
        }
    if failure_type == "no_failure":
        return {
            "preserve": stable_features,
            "relax_or_reformulate": [],
            "recommended_direction": (
                "No rule change is supported by this attack result; retain the "
                "current prototype response for the observed mutation level."
            ),
        }
    return {
        "preserve": [],
        "relax_or_reformulate": [],
        "recommended_direction": (
            "Resolve the baseline retrieval/detection precondition before drawing "
            "an evolution conclusion."
        ),
    }


def evaluate_mutated_case(
    mutated_transactions: pd.DataFrame,
    base_candidate: dict,
    base_features: dict,
    base_detection: dict,
    config: dict,
) -> dict:
    """Evaluate a mutation without writing artifacts; shared by runs and sweeps."""
    mutated_graph = build_transaction_graph(mutated_transactions)
    mutated_candidates = retrieve_scatter_gather_candidates(
        mutated_graph, config["retrieval"]
    )
    mutated_candidate = _matching_candidate(mutated_candidates, base_candidate)
    mutated_retrieved = mutated_candidate is not None

    if mutated_retrieved:
        mutated_features = extract_candidate_features(
            mutated_candidate, mutated_transactions
        )
        mutated_detection = detect_scatter_gather(
            mutated_features, config["detector"]
        )
    else:
        mutated_features = {}
        mutated_detection = {
            "suspicious_candidate": False,
            "triggered_conditions": [],
            "failed_conditions": [],
        }

    before_detected = bool(base_detection["suspicious_candidate"])
    after_detected = bool(mutated_detection["suspicious_candidate"])
    attack_success = bool(
        before_detected and (not mutated_retrieved or not after_detected)
    )
    if before_detected and not mutated_retrieved:
        failure_stage = "retrieval"
    elif before_detected and mutated_retrieved and not after_detected:
        failure_stage = "detection"
    else:
        failure_stage = None

    stable_features, changed_features = _feature_delta(
        base_features, mutated_features
    )
    return {
        "mutated_retrieved": mutated_retrieved,
        "mutated_case_features": mutated_features,
        "mutated_detection": mutated_detection,
        "before_detected": before_detected,
        "after_detected": after_detected,
        "stable_features": stable_features,
        "changed_features": changed_features,
        "failure_stage": failure_stage,
        "failure_type": _failure_type(
            before_detected, mutated_retrieved, after_detected
        ),
        "attack_success": attack_success,
    }


def evaluate_attack(
    attack_id: str,
    case_id: str,
    attack_type: str,
    parameters: dict,
    edge_lineage: dict,
    base_transactions: pd.DataFrame,
    mutated_transactions: pd.DataFrame,
    base_candidate: dict,
    base_features: dict,
    base_detection: dict,
    config: dict,
    output_root: Path,
) -> dict:
    evaluation = evaluate_mutated_case(
        mutated_transactions,
        base_candidate,
        base_features,
        base_detection,
        config,
    )
    failed_conditions = evaluation["mutated_detection"]["failed_conditions"]
    summary = {
        "attack_id": attack_id,
        "case_id": case_id,
        "source_pattern": "scatter_gather",
        "attack_type": attack_type,
        "parameters": parameters,
        "base_retrieved": True,
        "mutated_retrieved": evaluation["mutated_retrieved"],
        "base_case_features": base_features,
        "mutated_case_features": evaluation["mutated_case_features"],
        "stable_features": evaluation["stable_features"],
        "changed_features": evaluation["changed_features"],
        "old_rule_result": {
            "before_attack": evaluation["before_detected"],
            "after_attack": evaluation["after_detected"],
        },
        "failed_rule_conditions": failed_conditions,
        "failure_stage": evaluation["failure_stage"],
        "failure_type": evaluation["failure_type"],
        "attack_success": evaluation["attack_success"],
        "evolution_hint": _evolution_hint(
            attack_type,
            evaluation["failure_type"],
            evaluation["stable_features"],
            failed_conditions,
        ),
        "edge_lineage": edge_lineage,
        "prototype_notice": (
            "Synthetic detection-evasion test using prototype heuristics; "
            "not a production AML determination."
        ),
    }

    output_dir = output_root / attack_id
    output_dir.mkdir(parents=True, exist_ok=True)
    base_transactions.to_csv(output_dir / "base_transactions.csv", index=False)
    mutated_transactions.to_csv(
        output_dir / "mutated_transactions.csv", index=False
    )
    with (output_dir / "attack_summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return summary
