#!/usr/bin/env python3
"""Validate Attack outputs at the v0.2 JSON boundary.

This module deliberately imports no Attack implementation. The two components
are coupled only through CandidateSubgraphPackage and the artifact manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pattern_evolution.src.schemas import load_json, validate_candidate


SHARED_MUTATION_FIELDS = (
    "attack_id",
    "attack_type",
    "parameters",
    "attack_success",
    "old_rule_result",
    "base_case_features",
    "mutated_case_features",
    "stable_features",
    "changed_features",
    "failed_rule_conditions",
    "base_retrieved",
    "mutated_retrieved",
    "failure_stage",
    "failure_type",
    "evolution_hint",
    "edge_lineage",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest(output_root: Path) -> dict[str, Any]:
    manifest = load_json(output_root / "artifact_manifest.json")
    if manifest.get("schema_version") != "ccem.artifact_manifest/v0.1":
        raise ValueError("unsupported artifact manifest")
    repository_root = output_root.parents[1].resolve()
    for artifact_id, record in manifest["artifacts"].items():
        path = (output_root / record["path"]).resolve()
        if not path.is_relative_to(repository_root):
            raise ValueError(f"artifact path escapes repository root: {artifact_id}")
        if not path.is_file():
            raise ValueError(f"artifact does not exist: {artifact_id}")
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"artifact hash mismatch: {artifact_id}")
    return manifest


def _validate_summary_consistency(candidate_path: Path, package: dict[str, Any]) -> None:
    summary = load_json(candidate_path.with_name("attack_summary.json"))
    mutation = package["mutation"]
    for field in SHARED_MUTATION_FIELDS:
        if summary[field] != mutation[field]:
            raise ValueError(f"summary/Candidate mismatch: {candidate_path.parent.name}.{field}")
    graph_lineage = {
        edge["edge_id"]: {
            "parent_edge_ids": edge["parent_edge_ids"],
            "mutation_role": edge["mutation_role"],
        }
        for edge in package["graph"]["edges"]
    }
    if graph_lineage != summary["edge_lineage"]:
        raise ValueError(f"summary/Candidate lineage mismatch: {candidate_path.parent.name}")


def validate_attack_outputs(output_root: str | Path) -> dict[str, Any]:
    output_root = Path(output_root)
    manifest = _validate_manifest(output_root)
    candidate_paths = sorted(output_root.glob("*/candidate_subgraph.json"))
    if not candidate_paths:
        raise ValueError(f"no Candidate packages under {output_root}")

    cases = []
    for candidate_path in candidate_paths:
        package = load_json(candidate_path)
        validate_candidate(package)
        _validate_summary_consistency(candidate_path, package)
        cases.append(
            {
                "case_id": package["case_id"],
                "attack_id": package["mutation"]["attack_id"],
                "attack_type": package["mutation"]["attack_type"],
                "attack_success": package["mutation"]["attack_success"],
                "mutated_retrieved": package["mutation"]["mutated_retrieved"],
                "candidate_source": package["mutation"]["candidate_source"],
                "edge_count": len(package["graph"]["edges"]),
            }
        )
    return {
        "status": "passed",
        "schema_version": "ccem.attack_pattern_contract_report/v0.2",
        "candidate_count": len(cases),
        "manifest_artifact_count": len(manifest["artifacts"]),
        "cases": cases,
        "boundary": "Attack emits Candidate; Pattern Evolution accepts only Validated",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs" / "attacks",
    )
    args = parser.parse_args()
    print(json.dumps(validate_attack_outputs(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
