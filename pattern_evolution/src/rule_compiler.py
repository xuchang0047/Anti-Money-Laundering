"""Compile an accepted v0.2 subgraph into a CCEM executable experience."""

from __future__ import annotations

import json
from typing import Any

from .canonicalizer import canonicalize_relay_bridge
from .schemas import RejectedByCausalValidator, stable_hash, validate_validated


def compile_experience(package: dict[str, Any]) -> dict[str, Any]:
    validate_validated(package)
    if package["validation"]["accepted"] is not True:
        raise RejectedByCausalValidator(package["case_id"])

    canonical = canonicalize_relay_bridge(package["graph"])
    fingerprint = canonical["fingerprint"]
    identifier = f"ccem_relay_bridge_gather_scatter_{fingerprint['wl_hash'][:10]}"
    counterfactuals = package["validation"]["counterfactuals"]
    experience = {
        "experience_id": identifier,
        "family": canonical["family"],
        "version": 1,
        "status": "active",
        "matcher_kind": "relay_bridge_gather_scatter/v1",
        "roles": canonical["roles"],
        "required_edges": canonical["required_edges"],
        "constraints": {
            "max_duration_hours": 72.0,
            "flow_ratio": [0.6, 1.4],
            "allow_decoy_edges": True,
            "max_decoy_ratio": 0.25,
        },
        "causal_invariants": [
            {
                "name": item["name"],
                "intervention_type": item["intervention"]["type"],
                "minimum_expected_score_drop": max(0.1, min(1.0, item["result"].get("score_drop", 0.1))),
            }
            for item in counterfactuals
        ],
        "fingerprint": fingerprint,
        "validation_certificate": {
            "validation_target": package["validation"]["validation_target"],
            "method": package["validation"]["method"],
            "effect_size": package["validation"]["aggregate"]["effect_size"],
            "ci95": package["validation"]["aggregate"]["ci95"],
            "q_value": package["validation"]["aggregate"].get("q_value"),
            "decision_rule": package["validation"]["decision_rule"],
            "validator_version": package["validation"]["validator_version"],
            "parameter_hash": package["validation"]["parameter_hash"],
        },
        "lineage": {
            "parent": package["provenance"].get("parent_motif"),
            "round": package["provenance"].get("round"),
            "mutation_ops": package["provenance"].get("mutation_ops", []),
            "generator_version": package["provenance"]["generator_version"],
        },
        "compiler": {
            "name": "ccem_rule_compiler",
            "version": "0.2.0",
            "canonical_observations": canonical["observations"],
        },
    }

    serialized = json.dumps(experience, sort_keys=True)
    leaked_ids = [node["node_id"] for node in package["graph"]["nodes"] if node["node_id"] in serialized]
    if leaked_ids:
        raise RuntimeError(f"node identity leaked into compiled experience: {leaked_ids}")
    experience["experience_hash"] = stable_hash(experience)
    return experience
