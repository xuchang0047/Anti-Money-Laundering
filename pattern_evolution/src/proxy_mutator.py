"""Deterministic proxy graphs for the first self-evolution round."""

from __future__ import annotations

import copy
from typing import Any

from .schemas import REPORT_SCHEMA, stable_hash


def _node(name: str) -> dict[str, Any]:
    return {"node_id": f"IBM-HI-Proxy::B00::{name}", "attrs": {}}


def _edge(
    edge_id: str,
    src: str,
    dst: str,
    timestamp: float,
    amount: float,
    *,
    scope: str = "candidate",
    mutation_role: str = "modified",
    parents: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "src": f"IBM-HI-Proxy::B00::{src}",
        "dst": f"IBM-HI-Proxy::B00::{dst}",
        "timestamp": timestamp,
        "base_amount": amount,
        "base_currency": "USD",
        "amount_sent": amount,
        "sent_currency": "USD",
        "amount_received": amount,
        "receiving_currency": "USD",
        "transaction_type": "TRANSFER",
        "payment_format": "ACH",
        "scope": scope,
        "parent_edge_ids": parents or [],
        "mutation_role": mutation_role,
    }


def make_candidate_proxy() -> dict[str, Any]:
    """Create a relay-bridge gather-scatter Candidate v0.2 package.

    The IDs intentionally resemble IBM-style scoped identifiers, but the
    compiler must remove them from the resulting experience.
    """

    nodes = [_node(name) for name in ("s1", "s2", "s3", "collector", "relay", "d1", "d2", "d3", "normal")]
    edges = [
        _edge("mut_e01", "s1", "collector", 0, 1000, parents=["base_e01"]),
        _edge("mut_e02", "s2", "collector", 60, 1100, parents=["base_e02"]),
        _edge("mut_e03", "s3", "collector", 120, 900, parents=["base_e03"]),
        _edge("mut_e04", "collector", "relay", 3600, 2850, mutation_role="added", parents=["base_hub_split"]),
        _edge("mut_e05", "relay", "d1", 3900, 900, parents=["base_e04"]),
        _edge("mut_e06", "relay", "d2", 3960, 850, parents=["base_e05"]),
        _edge("mut_e07", "relay", "d3", 4020, 950, parents=["base_e06"]),
        _edge("mut_e08", "collector", "normal", 1800, 120, scope="context", mutation_role="added", parents=["base_decoy_seed"]),
        _edge("mut_e09", "normal", "relay", 3300, 100, scope="context", mutation_role="added", parents=["base_decoy_seed"]),
    ]
    return {
        "schema_version": "ccem.candidate_subgraph/v0.2",
        "package_type": "candidate_subgraph",
        "case_id": "proxy_relay_bridge_0001",
        "graph": {
            "directed": True,
            "multigraph": True,
            "time_unit": "second",
            "time_precision": 1.0,
            "time_origin": "2022-09-01T00:00:00Z",
            "amount_mode": "dual_endpoint",
            "nodes": nodes,
            "edges": edges,
        },
        "analysis_context": {
            "requested_validation_target": "model_behavior",
            "suggested_treatment": "relay_bridge_member",
            "analysis_unit": "subgraph",
            "anchor_time": "2022-09-15T00:00:00Z",
            "lookback_days": 7,
            "outcome_days": 1,
            "model_artifact": {
                "artifact_id": "baseline-rule-library-v0",
                "format": "json",
                "uri": "artifact://baseline-rule-library-v0",
                "sha256": "proxy-demo-no-external-model",
            },
            "outcome_metric": "old_rule_detection",
            "scoring_direction": "decrease_is_attack_success",
        },
        "mutation": {
            "attack_id": "attack_proxy_0001",
            "attack_type": "path_extension",
            "parameters": {"inserted_relays": 1, "delay_seconds": 3480, "decoy_edges": 2},
            "attack_success": True,
            "old_rule_result": {"before_attack": True, "after_attack": False},
            "base_case_features": {"hub_count": 1},
            "mutated_case_features": {"hub_count": 2},
            "stable_features": ["three_sources", "three_sinks", "flow_conservation"],
            "changed_features": ["path_length", "holding_time", "context_edge_ratio"],
            "failed_rule_conditions": ["single_hub_required"],
        },
        "provenance": {
            "round": 1,
            "generator": "proxy_mutator/v0.2",
            "parent_motif": "gather_scatter",
            "mutation_ops": ["split_hub", "add_delay", "inject_decoy_edges"],
            "source_dataset_id": "IBM-HI-Proxy",
            "source_artifact_sha256": "proxy-demo-deterministic-fixture",
            "generator_version": "0.2.0",
            "created_at": "2026-08-22T12:00:00Z",
            "random_seed": 42,
        },
    }


def make_validation_report(candidate: dict[str, Any]) -> dict[str, Any]:
    """Represent the already-completed upstream causal/model validation."""

    counterfactuals = [
        {
            "name": "bridge_removal",
            "intervention": {"type": "remove_edges", "edge_ids": ["mut_e04"]},
            "result": {"matched_after": False, "score_drop": 1.0},
        },
        {
            "name": "degree_preserving_rewire",
            "intervention": {
                "type": "rewire_edges",
                "rewires": [{"edge_id": "mut_e04", "new_src": "IBM-HI-Proxy::B00::collector", "new_dst": "IBM-HI-Proxy::B00::normal"}],
            },
            "result": {"matched_after": False, "score_drop": 1.0},
        },
        {
            "name": "temporal_reversal",
            "intervention": {
                "type": "shuffle_timestamps",
                "random_seed": 42,
                "timestamp_mapping": {"mut_e05": 3000, "mut_e06": 3060, "mut_e07": 3120, "mut_e04": 3600},
            },
            "result": {"matched_after": False, "score_drop": 0.75},
        },
        {
            "name": "amount_permutation",
            "intervention": {
                "type": "permute_amounts",
                "random_seed": 42,
                "amount_mapping": {"mut_e04": {"base_amount": 120.0}, "mut_e08": {"base_amount": 2850.0}},
            },
            "result": {"matched_after": False, "score_drop": 0.65},
        },
    ]
    decision_parameters = {
        "minimum_effect": 0.2,
        "minimum_counterfactual_score_drop": 0.1,
        "required_refuters": 3,
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "case_id": candidate["case_id"],
        "attack_id": candidate["mutation"]["attack_id"],
        "accepted": True,
        "decision_rule": "model-behavior-counterfactual-acceptance/v0.2",
        "decision_reasons": ["positive_effect", "counterfactuals_break_pattern", "refuters_stable"],
        "validation_target": "model_behavior",
        "method": "deterministic.counterfactual_replay",
        "analysis_unit": "subgraph",
        "treatment": "relay_bridge_member",
        "outcome": "compiled_detector_score",
        "estimand": "score_difference",
        "expected_direction": "positive",
        "minimum_effect": 0.2,
        "aggregate": {
            "effect_size": 0.31,
            "ci95": [0.18, 0.44],
            "p_value": 0.008,
            "q_value": 0.012,
            "sample_size": 128,
            "treated_n": 64,
            "control_n": 64,
        },
        "adjustment_set": ["edge_count", "duration", "total_amount"],
        "diagnostics": {
            "propensity_overlap": 1.0,
            "max_unstabilized_ipw": 1.0,
            "effective_sample_size": 128,
            "amount_evidence": "dual_endpoint",
        },
        "refuters": {
            "placebo_treatment": {"passed": True},
            "random_common_cause": {"passed": True},
            "data_subset": {"passed": True},
        },
        "counterfactuals": counterfactuals,
        "validator_version": "0.2.0",
        "parameter_hash": stable_hash(decision_parameters),
        "created_at": "2026-08-22T12:10:00Z",
    }


def causal_roles(candidate: dict[str, Any]) -> dict[str, str]:
    roles = {edge["edge_id"]: "supporting" for edge in candidate["graph"]["edges"]}
    roles["mut_e04"] = "essential"
    roles["mut_e08"] = "nuisance"
    roles["mut_e09"] = "nuisance"
    return roles


def make_base_gather_scatter_graph() -> dict[str, Any]:
    """A standard single-hub pattern used for the regression check."""

    nodes = [_node(name) for name in ("bs1", "bs2", "bs3", "hub", "bd1", "bd2", "bd3")]
    edges = [
        _edge("base_gs01", "bs1", "hub", 0, 1000, mutation_role="preserved"),
        _edge("base_gs02", "bs2", "hub", 60, 1000, mutation_role="preserved"),
        _edge("base_gs03", "bs3", "hub", 120, 1000, mutation_role="preserved"),
        _edge("base_gs04", "hub", "bd1", 600, 900, mutation_role="preserved"),
        _edge("base_gs05", "hub", "bd2", 660, 950, mutation_role="preserved"),
        _edge("base_gs06", "hub", "bd3", 720, 1000, mutation_role="preserved"),
    ]
    return {
        "directed": True,
        "multigraph": True,
        "time_unit": "second",
        "time_precision": 1.0,
        "time_origin": "2022-09-01T00:00:00Z",
        "amount_mode": "dual_endpoint",
        "nodes": nodes,
        "edges": edges,
    }


def apply_intervention(graph: dict[str, Any], intervention: dict[str, Any]) -> dict[str, Any]:
    """Apply the resolved v0.2 counterfactual payload deterministically."""

    result = copy.deepcopy(graph)
    edge_by_id = {edge["edge_id"]: edge for edge in result["edges"]}
    kind = intervention["type"]
    if kind == "remove_edges":
        removed = set(intervention["edge_ids"])
        result["edges"] = [edge for edge in result["edges"] if edge["edge_id"] not in removed]
    elif kind == "rewire_edges":
        for rewire in intervention["rewires"]:
            edge = edge_by_id[rewire["edge_id"]]
            if "new_src" in rewire:
                edge["src"] = rewire["new_src"]
            if "new_dst" in rewire:
                edge["dst"] = rewire["new_dst"]
    elif kind == "shuffle_timestamps":
        for edge_id, timestamp in intervention["timestamp_mapping"].items():
            edge_by_id[edge_id]["timestamp"] = timestamp
    elif kind == "permute_amounts":
        for edge_id, values in intervention["amount_mapping"].items():
            edge = edge_by_id[edge_id]
            for field, value in values.items():
                edge[field] = value
                if field == "base_amount":
                    edge["amount_sent"] = value
                    edge["amount_received"] = value
    elif kind == "add_edges":
        result["edges"].extend(copy.deepcopy(intervention["edges"]))
    elif kind == "replace_nodes":
        mapping = intervention["node_mapping"]
        for edge in result["edges"]:
            edge["src"] = mapping.get(edge["src"], edge["src"])
            edge["dst"] = mapping.get(edge["dst"], edge["dst"])
    else:
        raise ValueError(f"unsupported intervention: {kind}")
    return result


def make_augmented_positive(graph: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(graph)
    for edge in result["edges"]:
        edge["timestamp"] += 30
        if edge["scope"] == "candidate":
            edge["base_amount"] *= 1.02
            edge["amount_sent"] *= 1.02
            edge["amount_received"] *= 1.02
    return result
