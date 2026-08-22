"""Validation and local artifact resolution for the frozen v0.3 interface."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


CANDIDATE_VERSION = "ccem.candidate_subgraph/v0.3"
VALIDATED_VERSION = "ccem.validated_subgraph/v0.3"
REPORT_VERSION = "ccem.validation_report/v0.3"
MANIFEST_VERSION = "ccem.artifact_manifest/v0.1"

class InterfaceError(ValueError):
    """Raised when an interface package violates the frozen contract."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise InterfaceError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def round_half_up_seconds(value: int | float | str | Decimal) -> int:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise InterfaceError("timestamp must be finite and non-negative")
    return int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _required(obj: dict[str, Any], field: str, where: str) -> Any:
    if field not in obj:
        raise InterfaceError(f"missing required field: {where}.{field}")
    return obj[field]


def _utc_iso(value: Any, where: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise InterfaceError(f"{where} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InterfaceError(f"invalid timestamp at {where}: {value}") from exc


def validate_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version") != CANDIDATE_VERSION:
        raise InterfaceError(f"schema_version must be {CANDIDATE_VERSION}")
    if candidate.get("package_type") != "candidate_subgraph":
        raise InterfaceError("package_type must be candidate_subgraph")
    _required(candidate, "case_id", "candidate")
    if "validation" in candidate:
        raise InterfaceError("Candidate must not contain validation")

    graph = _required(candidate, "graph", "candidate")
    if not isinstance(graph, dict):
        raise InterfaceError("graph must be an object")
    if graph.get("directed") is not True or graph.get("multigraph") is not True:
        raise InterfaceError("graph must be directed=true and multigraph=true")
    if graph.get("time_unit") != "second" or graph.get("time_precision") != 1.0:
        raise InterfaceError("v0.3 time must use second with time_precision=1.0")
    if graph.get("time_quantization") != "ROUND_HALF_UP":
        raise InterfaceError("time_quantization must be ROUND_HALF_UP")
    _utc_iso(graph.get("time_origin"), "graph.time_origin")
    if graph.get("amount_mode") not in {"base_only", "dual_endpoint"}:
        raise InterfaceError("graph.amount_mode must be base_only or dual_endpoint")

    nodes = _required(graph, "nodes", "graph")
    if not isinstance(nodes, list) or not nodes:
        raise InterfaceError("graph.nodes must be a non-empty array")
    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        node_id = _required(node, "node_id", f"graph.nodes[{index}]")
        parts = node_id.split("::") if isinstance(node_id, str) else []
        if len(parts) != 3 or not all(parts) or parts[1] == "":
            raise InterfaceError(
                f"node_id must be dataset_id::bank_id::account_id: {node_id!r}"
            )
        if node_id in node_ids:
            raise InterfaceError(f"duplicate node_id: {node_id}")
        node_ids.add(node_id)

    mutation = candidate.get("mutation")
    attack_id = mutation.get("attack_id") if isinstance(mutation, dict) else None
    edges = _required(graph, "edges", "graph")
    if not isinstance(edges, list) or not edges:
        raise InterfaceError("graph.edges must be a non-empty array")
    edge_ids: set[str] = set()
    for index, edge in enumerate(edges):
        where = f"graph.edges[{index}]"
        edge_id = _required(edge, "edge_id", where)
        if edge_id in edge_ids:
            raise InterfaceError(f"duplicate edge_id: {edge_id}")
        edge_ids.add(edge_id)
        if edge.get("src") not in node_ids or edge.get("dst") not in node_ids:
            raise InterfaceError(f"{where} endpoints must reference graph.nodes")
        timestamp = _required(edge, "timestamp", where)
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
            raise InterfaceError(f"{where}.timestamp must be finite and non-negative")
        if float(timestamp) != float(round_half_up_seconds(timestamp)):
            raise InterfaceError(f"{where}.timestamp is not quantized to one second")
        amount = _required(edge, "base_amount", where)
        if not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            raise InterfaceError(f"{where}.base_amount must be finite and non-negative")
        _required(edge, "base_currency", where)
        if edge.get("scope") not in {"candidate", "context"}:
            raise InterfaceError(f"{where}.scope is invalid")
        parents = _required(edge, "parent_edge_ids", where)
        role = _required(edge, "mutation_role", where)
        if not isinstance(parents, list) or role not in {"preserved", "modified", "added"}:
            raise InterfaceError(f"{where} has invalid lineage")
        if mutation is not None:
            if role == "modified":
                expected = (
                    rf"^{re.escape(str(parents[0]))}__mut__"
                    rf"{re.escape(str(attack_id))}__\d+$"
                    if parents else "(?!)"
                )
                if not parents or not re.match(expected, edge_id):
                    raise InterfaceError(f"{where} modified edge_id/parent_edge_ids mismatch")
            elif role == "added":
                expected = rf"^{re.escape(str(attack_id))}__add__\d+$"
                if not re.match(expected, edge_id):
                    raise InterfaceError(f"{where} added edge_id/parent_edge_ids mismatch")
            elif parents:
                raise InterfaceError(f"{where} preserved edge must have parent_edge_ids=[]")
        if "causal_role" in edge:
            raise InterfaceError("Candidate edges must not contain causal_role")

    context = _required(candidate, "analysis_context", "candidate")
    target = context.get("requested_validation_target")
    if target == "aml_outcome":
        _required(context, "population_artifact", "analysis_context")
        _required(context, "outcome_ref", "analysis_context")
    elif target == "model_behavior":
        _required(context, "model_artifact", "analysis_context")
        _required(context, "outcome_metric", "analysis_context")
        metric_type = context.get("outcome_metric_type")
        if metric_type == "boolean":
            _required(context, "positive_value", "analysis_context")
            if context.get("scoring_direction") != "true_is_more_suspicious":
                raise InterfaceError(
                    "boolean model_behavior requires scoring_direction=true_is_more_suspicious"
                )
        elif metric_type == "continuous":
            if context.get("scoring_direction") not in {
                "higher_is_more_suspicious", "lower_is_more_suspicious"
            }:
                raise InterfaceError("continuous model_behavior has invalid scoring_direction")
        else:
            raise InterfaceError("model_behavior outcome_metric_type is invalid")
    else:
        raise InterfaceError("requested_validation_target must be aml_outcome or model_behavior")

    if mutation is not None:
        for field in [
            "attack_id", "attack_type", "attack_success", "base_retrieved",
            "mutated_retrieved", "failure_stage", "candidate_source", "edge_lineage",
        ]:
            _required(mutation, field, "mutation")
        if mutation["candidate_source"] not in {"retrieved_result", "mutation_scope"}:
            raise InterfaceError("mutation.candidate_source is invalid")
        if mutation["mutated_retrieved"] is False and mutation["candidate_source"] != "mutation_scope":
            raise InterfaceError("retrieval failure Candidate must use candidate_source=mutation_scope")

    provenance = _required(candidate, "provenance", "candidate")
    for field in ["source_dataset_id", "generator_version", "created_at"]:
        _required(provenance, field, "provenance")
    _utc_iso(provenance["created_at"], "provenance.created_at")


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise InterfaceError(f"manifest schema_version must be {MANIFEST_VERSION}")
    if not isinstance(manifest.get("artifacts"), dict):
        raise InterfaceError("manifest.artifacts must be an object")
    return manifest


def resolve_artifact(manifest_path: Path, artifact_id: str) -> tuple[Path, dict[str, Any]]:
    manifest = load_manifest(manifest_path)
    try:
        record = manifest["artifacts"][artifact_id]
    except KeyError as exc:
        raise InterfaceError(f"artifact_id not found in manifest: {artifact_id}") from exc
    relative = Path(_required(record, "path", f"artifacts.{artifact_id}"))
    if relative.is_absolute():
        raise InterfaceError("artifact path must be relative to the manifest")
    resolved = (manifest_path.parent / relative).resolve()
    manifest_root = manifest_path.parent.resolve()
    # Parent traversal is permitted because fixtures may reference project data,
    # but the manifest remains the only resolver and the digest is mandatory.
    if not resolved.is_file():
        raise InterfaceError(f"artifact does not exist: {resolved}")
    actual = sha256_file(resolved)
    expected = _required(record, "sha256", f"artifacts.{artifact_id}")
    if actual != expected:
        raise InterfaceError(f"artifact sha256 mismatch for {artifact_id}")
    return resolved, {**record, "artifact_id": artifact_id, "resolved_from": str(manifest_root)}


def validate_summary_consistency(candidate: dict[str, Any], summary: dict[str, Any]) -> None:
    mutation = candidate.get("mutation")
    if mutation is None:
        raise InterfaceError("attack_summary cannot be matched to mutation=null")
    fields = [
        "attack_id", "attack_type", "attack_success", "old_rule_result",
        "failed_rule_conditions", "edge_lineage", "base_retrieved",
        "mutated_retrieved", "failure_stage", "candidate_source",
    ]
    mismatches = [field for field in fields if summary.get(field) != mutation.get(field)]
    if mismatches:
        raise InterfaceError(f"attack_summary/Candidate hard consistency failure: {mismatches}")
