"""Validation and construction helpers for Shared Subgraph Package v0.2.

The implementation deliberately uses only the Python standard library so the
interface gate can run before optional GNN or causal-inference dependencies are
installed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


CANDIDATE_SCHEMA = "ccem.candidate_subgraph/v0.2"
VALIDATED_SCHEMA = "ccem.validated_subgraph/v0.2"
REPORT_SCHEMA = "ccem.validation_report/v0.2"

TIME_UNITS = {"second", "millisecond", "minute", "hour", "day"}
AMOUNT_MODES = {"dual_endpoint", "base_only", "receiver_only"}
SCOPES = {"candidate", "context", "unknown"}
MUTATION_ROLES = {"preserved", "modified", "added"}
CAUSAL_ROLES = {"essential", "supporting", "nuisance", "unknown"}
VALIDATION_TARGETS = {"aml_outcome", "model_behavior"}


class PackageValidationError(ValueError):
    """Raised when a package violates the frozen v0.2 contract."""


class RejectedByCausalValidator(PackageValidationError):
    """Raised when an unaccepted package reaches the experience compiler."""


def _require(mapping: Mapping[str, Any], fields: Iterable[str], where: str) -> None:
    for field in fields:
        if field not in mapping:
            raise PackageValidationError(f"{where}.{field} is required")


def _finite_nonnegative(value: Any, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PackageValidationError(f"{where} must be a JSON number")
    if not math.isfinite(float(value)) or value < 0:
        raise PackageValidationError(f"{where} must be finite and non-negative")


def _validate_graph(graph: Mapping[str, Any], *, validated: bool) -> None:
    _require(
        graph,
        (
            "directed",
            "multigraph",
            "time_unit",
            "time_precision",
            "time_origin",
            "amount_mode",
            "nodes",
            "edges",
        ),
        "graph",
    )
    if graph["directed"] is not True or graph["multigraph"] is not True:
        raise PackageValidationError("graph must be a directed multigraph")
    if graph["time_unit"] not in TIME_UNITS:
        raise PackageValidationError(f"unsupported graph.time_unit: {graph['time_unit']}")
    _finite_nonnegative(graph["time_precision"], "graph.time_precision")
    if graph["time_precision"] == 0:
        raise PackageValidationError("graph.time_precision must be greater than zero")
    if graph["amount_mode"] not in AMOUNT_MODES:
        raise PackageValidationError(f"unsupported graph.amount_mode: {graph['amount_mode']}")

    nodes = graph["nodes"]
    edges = graph["edges"]
    if not isinstance(nodes, list) or not nodes:
        raise PackageValidationError("graph.nodes must be a non-empty list")
    if not isinstance(edges, list) or not edges:
        raise PackageValidationError("graph.edges must be a non-empty list")

    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        _require(node, ("node_id", "attrs"), f"graph.nodes[{index}]")
        node_id = node["node_id"]
        if not isinstance(node_id, str) or not node_id:
            raise PackageValidationError(f"graph.nodes[{index}].node_id must be non-empty")
        if node_id in node_ids:
            raise PackageValidationError(f"duplicate node_id: {node_id}")
        node_ids.add(node_id)
        if not isinstance(node["attrs"], dict):
            raise PackageValidationError(f"graph.nodes[{index}].attrs must be an object")
        forbidden_labels = {"is_laundering", "oracle", "label"} & set(node["attrs"])
        if forbidden_labels:
            raise PackageValidationError("Oracle labels are forbidden in node attrs")

    edge_ids: set[str] = set()
    edge_fields = (
        "edge_id",
        "src",
        "dst",
        "timestamp",
        "base_amount",
        "base_currency",
        "amount_sent",
        "sent_currency",
        "amount_received",
        "receiving_currency",
        "transaction_type",
        "payment_format",
        "scope",
        "parent_edge_ids",
        "mutation_role",
    )
    for index, edge in enumerate(edges):
        where = f"graph.edges[{index}]"
        _require(edge, edge_fields, where)
        edge_id = edge["edge_id"]
        if not isinstance(edge_id, str) or not edge_id:
            raise PackageValidationError(f"{where}.edge_id must be non-empty")
        if edge_id in edge_ids:
            raise PackageValidationError(f"duplicate edge_id: {edge_id}")
        edge_ids.add(edge_id)
        if edge["src"] not in node_ids or edge["dst"] not in node_ids:
            raise PackageValidationError(f"{where} references an unknown endpoint")
        _finite_nonnegative(edge["timestamp"], f"{where}.timestamp")
        _finite_nonnegative(edge["base_amount"], f"{where}.base_amount")
        if edge["scope"] not in SCOPES:
            raise PackageValidationError(f"invalid {where}.scope")
        if edge["mutation_role"] not in MUTATION_ROLES:
            raise PackageValidationError(f"invalid {where}.mutation_role")
        if not isinstance(edge["parent_edge_ids"], list):
            raise PackageValidationError(f"{where}.parent_edge_ids must be a list")
        if edge["mutation_role"] == "modified" and not edge["parent_edge_ids"]:
            raise PackageValidationError(f"{where} modified edge requires parent_edge_ids")
        if not validated and "causal_role" in edge:
            raise PackageValidationError("Candidate edges cannot contain causal_role")
        if validated and edge.get("causal_role") not in CAUSAL_ROLES:
            raise PackageValidationError(f"{where}.causal_role is required and must be valid")

        if graph["amount_mode"] == "dual_endpoint":
            for field in ("base_currency", "amount_sent", "sent_currency", "amount_received", "receiving_currency"):
                if edge[field] is None:
                    raise PackageValidationError(f"{where}.{field} cannot be null in dual_endpoint mode")
            _finite_nonnegative(edge["amount_sent"], f"{where}.amount_sent")
            _finite_nonnegative(edge["amount_received"], f"{where}.amount_received")
        elif graph["amount_mode"] == "receiver_only":
            if edge["amount_received"] is None:
                raise PackageValidationError(f"{where}.amount_received is required in receiver_only mode")
            _finite_nonnegative(edge["amount_received"], f"{where}.amount_received")


def validate_candidate(package: Mapping[str, Any]) -> None:
    _require(package, ("schema_version", "package_type", "case_id", "graph", "analysis_context", "mutation", "provenance"), "package")
    if package["schema_version"] != CANDIDATE_SCHEMA or package["package_type"] != "candidate_subgraph":
        raise PackageValidationError("not a CandidateSubgraphPackage v0.2")
    if not package["case_id"]:
        raise PackageValidationError("case_id must be non-empty")
    if "validation" in package:
        raise PackageValidationError("Candidate package cannot contain validation")
    _validate_graph(package["graph"], validated=False)

    context = package["analysis_context"]
    _require(context, ("requested_validation_target",), "analysis_context")
    target = context["requested_validation_target"]
    if target not in VALIDATION_TARGETS:
        raise PackageValidationError(f"unsupported validation target: {target}")
    if target == "aml_outcome":
        _require(context, ("population_artifact", "outcome_ref"), "analysis_context")
    else:
        _require(context, ("model_artifact", "outcome_metric", "scoring_direction"), "analysis_context")

    mutation = package["mutation"]
    if mutation is not None:
        _require(mutation, ("attack_id", "attack_type", "attack_success"), "mutation")
        if not mutation["attack_id"] or not mutation["attack_type"]:
            raise PackageValidationError("mutation identifiers must be non-empty")
        if not isinstance(mutation["attack_success"], bool):
            raise PackageValidationError("mutation.attack_success must be boolean")

    provenance = package["provenance"]
    _require(provenance, ("source_dataset_id", "generator_version"), "provenance")
    if not provenance["source_dataset_id"] or not provenance["generator_version"]:
        raise PackageValidationError("provenance identifiers must be non-empty")


def validate_report(report: Mapping[str, Any]) -> None:
    _require(
        report,
        (
            "schema_version",
            "case_id",
            "attack_id",
            "accepted",
            "decision_rule",
            "decision_reasons",
            "validation_target",
            "method",
            "aggregate",
            "diagnostics",
            "refuters",
            "counterfactuals",
            "validator_version",
            "parameter_hash",
            "created_at",
        ),
        "report",
    )
    if report["schema_version"] != REPORT_SCHEMA:
        raise PackageValidationError("not a ValidationReport v0.2")
    if not isinstance(report["accepted"], bool):
        raise PackageValidationError("report.accepted must be boolean")
    if report["validation_target"] not in VALIDATION_TARGETS:
        raise PackageValidationError("invalid report.validation_target")
    aggregate = report["aggregate"]
    _require(aggregate, ("effect_size", "ci95", "sample_size", "treated_n", "control_n"), "report.aggregate")
    if len(aggregate["ci95"]) != 2 or aggregate["ci95"][0] > aggregate["ci95"][1]:
        raise PackageValidationError("report.aggregate.ci95 must be [lower, upper]")
    for index, counterfactual in enumerate(report["counterfactuals"]):
        if "intervention" not in counterfactual or "result" not in counterfactual:
            raise PackageValidationError(f"counterfactuals[{index}] must contain intervention and result")
        intervention = counterfactual["intervention"]
        if "type" not in intervention:
            raise PackageValidationError(f"counterfactuals[{index}].intervention.type is required")


def validate_validated(package: Mapping[str, Any]) -> None:
    _require(package, ("schema_version", "package_type", "case_id", "graph", "analysis_context", "mutation", "provenance", "validation"), "package")
    if package["schema_version"] != VALIDATED_SCHEMA or package["package_type"] != "validated_subgraph":
        raise PackageValidationError("not a ValidatedSubgraphPackage v0.2")
    if package["validation"].get("accepted") is not True:
        raise RejectedByCausalValidator(str(package.get("case_id")))
    _validate_graph(package["graph"], validated=True)
    report = copy.deepcopy(package["validation"])
    report["schema_version"] = REPORT_SCHEMA
    report["case_id"] = package["case_id"]
    report["attack_id"] = package["mutation"]["attack_id"] if package["mutation"] else None
    validate_report(report)


def build_validated_package(
    candidate: Mapping[str, Any],
    report: Mapping[str, Any],
    causal_roles: Mapping[str, str],
) -> dict[str, Any]:
    """Build a validated package without modifying the candidate fact graph."""

    validate_candidate(candidate)
    validate_report(report)
    attack_id = candidate["mutation"]["attack_id"] if candidate["mutation"] else None
    if candidate["case_id"] != report["case_id"] or attack_id != report["attack_id"]:
        raise PackageValidationError("Candidate and ValidationReport identities differ")
    if report["accepted"] is not True:
        raise RejectedByCausalValidator(candidate["case_id"])

    package = {
        "schema_version": VALIDATED_SCHEMA,
        "package_type": "validated_subgraph",
        "case_id": candidate["case_id"],
        "graph": copy.deepcopy(candidate["graph"]),
        "analysis_context": copy.deepcopy(candidate["analysis_context"]),
        "mutation": copy.deepcopy(candidate["mutation"]),
        "provenance": copy.deepcopy(candidate["provenance"]),
        "validation": {key: copy.deepcopy(value) for key, value in report.items() if key not in {"schema_version", "case_id", "attack_id"}},
    }
    for edge in package["graph"]["edges"]:
        edge["causal_role"] = causal_roles.get(edge["edge_id"], "unknown")
    validate_validated(package)
    return package


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json_atomic(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)
