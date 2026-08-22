"""Serialize attack artifacts as CandidateSubgraphPackage v0.2."""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Union

import pandas as pd


SUMMARY_MUTATION_FIELDS = (
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _escape_node_part(value: object) -> str:
    return str(value).replace("%", "%25").replace(":", "%3A")


def _node_id(
    dataset_id: str, missing_bank_id: str, account_id: object
) -> str:
    return "::".join(
        (
            _escape_node_part(dataset_id),
            _escape_node_part(missing_bank_id),
            _escape_node_part(account_id),
        )
    )


def _relative_seconds(
    timestamp: object, origin: pd.Timestamp, precision: Decimal
) -> Union[int, float]:
    value = pd.to_datetime(timestamp, utc=True)
    seconds = Decimal(str((value - origin).total_seconds()))
    quantized = seconds.quantize(precision, rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return int(quantized)
    return float(quantized)


def _mutation_ops(attack_type: str) -> list[str]:
    return {
        "temporal_stretch": ["add_delay"],
        "path_extension": ["insert_relay_layer"],
        "amount_perturbation": ["perturb_amount"],
    }[attack_type]


def _validate_consistency(summary: dict, package: dict) -> None:
    mutation = package["mutation"]
    for field in SUMMARY_MUTATION_FIELDS:
        if mutation[field] != summary[field]:
            raise ValueError(f"Summary/Candidate mismatch for field: {field}")
    graph_lineage = {
        edge["edge_id"]: {
            "parent_edge_ids": edge["parent_edge_ids"],
            "mutation_role": edge["mutation_role"],
        }
        for edge in package["graph"]["edges"]
    }
    if graph_lineage != summary["edge_lineage"]:
        raise ValueError("Summary/Candidate edge lineage mismatch")


def build_candidate_package(
    summary: dict,
    baseline: pd.DataFrame,
    mutated: pd.DataFrame,
    output_dir: Path,
    config_path: Path,
    interface_config: dict,
) -> dict:
    """Build a Candidate even when retrieval failed, using mutation scope."""
    dataset_id = interface_config["source_dataset_id"]
    missing_bank_id = interface_config["missing_bank_id"]
    precision = Decimal(str(interface_config["time_precision"])).normalize()
    origin = pd.to_datetime(baseline["timestamp"], utc=True).min()
    time_origin = origin.isoformat().replace("+00:00", "Z")
    lineage = summary["edge_lineage"]

    account_ids = sorted(
        set(mutated["source"].astype(str)) | set(mutated["target"].astype(str))
    )
    nodes = [
        {
            "node_id": _node_id(dataset_id, missing_bank_id, account_id),
            "attrs": {},
        }
        for account_id in account_ids
    ]
    edges = []
    for record in mutated.to_dict(orient="records"):
        edge_id = str(record["transaction_id"])
        edge_lineage = lineage[edge_id]
        edges.append(
            {
                "edge_id": edge_id,
                "src": _node_id(
                    dataset_id, missing_bank_id, record["source"]
                ),
                "dst": _node_id(
                    dataset_id, missing_bank_id, record["target"]
                ),
                "timestamp": _relative_seconds(
                    record["timestamp"], origin, precision
                ),
                "base_amount": float(record["amount"]),
                "base_currency": None,
                "amount_sent": None,
                "sent_currency": None,
                "amount_received": None,
                "receiving_currency": None,
                "transaction_type": None,
                "payment_format": None,
                "scope": "candidate",
                "parent_edge_ids": edge_lineage["parent_edge_ids"],
                "mutation_role": edge_lineage["mutation_role"],
            }
        )

    base_artifact_path = output_dir / "base_transactions.csv"
    base_artifact_id = f"{summary['attack_id']}-base-transactions"
    model_artifact_id = "prototype-scatter-gather-detector-v0.1"
    mutation = {field: summary[field] for field in SUMMARY_MUTATION_FIELDS}
    mutation["candidate_source"] = (
        "retriever" if summary["mutated_retrieved"] else "mutation_scope"
    )

    package = {
        "schema_version": "ccem.candidate_subgraph/v0.2",
        "package_type": "candidate_subgraph",
        "case_id": summary["case_id"],
        "graph": {
            "directed": True,
            "multigraph": True,
            "time_unit": interface_config["time_unit"],
            "time_precision": float(precision),
            "time_origin": time_origin,
            "amount_mode": "base_only",
            "nodes": nodes,
            "edges": edges,
        },
        "analysis_context": {
            "requested_validation_target": "model_behavior",
            "model_artifact": {
                "artifact_id": model_artifact_id,
                "format": "json",
                "uri": f"artifact://{model_artifact_id}",
                "sha256": file_sha256(config_path),
            },
            "outcome_metric": "suspicious_candidate",
            "outcome_metric_type": "boolean",
            "positive_value": True,
            "scoring_direction": "true_is_more_suspicious",
        },
        "mutation": mutation,
        "provenance": {
            "generator": "attack.CandidatePackageBuilder",
            "generator_version": interface_config["generator_version"],
            "parent_motif": summary["source_pattern"],
            "mutation_ops": _mutation_ops(summary["attack_type"]),
            "source_dataset_id": dataset_id,
            "source_artifact_id": base_artifact_id,
            "source_artifact_sha256": file_sha256(base_artifact_path),
            "random_seed": summary["parameters"].get("seed"),
            "time_quantization": interface_config["time_quantization"],
        },
    }
    _validate_consistency(summary, package)
    with (output_dir / "candidate_subgraph.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(package, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    return package


def write_artifact_manifest(output_root: Path, project_root: Path) -> dict:
    """Write logical artifact references with paths relative to the manifest."""
    manifest_path = output_root / "artifact_manifest.json"
    artifacts = {}

    config_path = project_root / "configs" / "attack_config.json"
    model_artifact_id = "prototype-scatter-gather-detector-v0.1"
    artifacts[model_artifact_id] = {
        "path": Path(os.path.relpath(config_path, output_root)).as_posix(),
        "format": "json",
        "sha256": file_sha256(config_path),
    }

    for attack_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        for filename, suffix, file_format in (
            ("base_transactions.csv", "base-transactions", "csv"),
            ("mutated_transactions.csv", "mutated-transactions", "csv"),
            ("attack_summary.json", "attack-summary", "json"),
            ("candidate_subgraph.json", "candidate-subgraph", "json"),
        ):
            path = attack_dir / filename
            if path.exists():
                artifact_id = f"{attack_dir.name}-{suffix}"
                artifacts[artifact_id] = {
                    "path": Path(os.path.relpath(path, output_root)).as_posix(),
                    "format": file_format,
                    "sha256": file_sha256(path),
                }

    profile_path = output_root / "robustness_profile.json"
    if profile_path.exists():
        artifacts["synthetic-sg-001-robustness-profile"] = {
            "path": profile_path.name,
            "format": "json",
            "sha256": file_sha256(profile_path),
        }

    manifest = {
        "schema_version": "ccem.artifact_manifest/v0.1",
        "artifacts": dict(sorted(artifacts.items())),
    }
    with manifest_path.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return manifest
