"""Standalone Candidate -> subgraph recognition -> DoWhy validation pipeline."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from aml_dowhy import CONFOUNDERS, build_panel, rapid_transfer_by_day, run_dowhy
from interface_v03 import (
    REPORT_VERSION,
    VALIDATED_VERSION,
    InterfaceError,
    read_json,
    resolve_artifact,
    sha256_file,
    validate_candidate,
    validate_summary_consistency,
    write_json,
)
from subgraph_patterns import identify_temporal_subgraphs


VALIDATOR_VERSION = "subgraph-dowhy-validator/0.3.0"


@dataclass(frozen=True)
class PipelineConfig:
    treatment: str | None = None
    lookback_days: int = 7
    rapid_hours: float = 1.0
    min_ratio: float = 0.8
    max_ratio: float = 1.2
    motif_hours: float = 1.0
    fan_threshold: int = 3
    motif_min_ratio: float = 0.5
    motif_max_ratio: float = 1.2
    refute_simulations: int = 20
    bootstrap_simulations: int = 50
    seed: int = 42
    expected_direction: str = "positive"
    minimum_effect: float = 0.0
    max_rows: int | None = None


def _candidate_tables(candidate: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    graph = candidate["graph"]
    origin = pd.Timestamp(graph["time_origin"])
    edge_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        timestamp = origin + pd.to_timedelta(int(edge["timestamp"]), unit="s")
        sent = edge.get("amount_sent")
        received = edge.get("amount_received")
        base = float(edge["base_amount"])
        sent = base if sent is None else float(sent)
        received = base if received is None else float(received)
        sent_currency = edge.get("sent_currency") or edge.get("base_currency") or "__UNKNOWN__"
        received_currency = edge.get("receiving_currency") or edge.get("base_currency") or "__UNKNOWN__"
        common = {"date": timestamp.floor("D"), "timestamp": timestamp}
        edge_rows.append({
            **common,
            "source": edge["src"],
            "target": edge["dst"],
            "amount_paid": sent,
            "payment_currency": sent_currency,
            "amount_received": received,
            "receiving_currency": received_currency,
        })
        event_rows.extend([
            {**common, "account_key": edge["src"], "role": "out", "amount": sent,
             "currency": sent_currency},
            {**common, "account_key": edge["dst"], "role": "in", "amount": received,
             "currency": received_currency},
        ])
    return pd.DataFrame(edge_rows), pd.DataFrame(event_rows)


def verify_candidate_treatment(
    candidate: dict[str, Any], treatment: str, config: PipelineConfig
) -> dict[str, Any]:
    edges, events = _candidate_tables(candidate)
    rapid = rapid_transfer_by_day(
        events, config.rapid_hours, config.min_ratio, config.max_ratio
    )
    members, instances = identify_temporal_subgraphs(
        edges,
        rapid,
        motif_hours=config.motif_hours,
        fan_threshold=config.fan_threshold,
        min_ratio=config.motif_min_ratio,
        max_ratio=config.motif_max_ratio,
    )
    if treatment not in members.columns or not bool(members[treatment].eq(1).any()):
        raise InterfaceError(f"Candidate graph does not contain treatment={treatment}")
    return {
        "treatment": treatment,
        "member_count": int(members[treatment].sum()),
        "identified_instance_count": int(len(instances)),
        "identified_types": sorted(instances["type"].unique().tolist())
        if not instances.empty else [],
    }


def _decision(
    causal: dict[str, Any], config: PipelineConfig
) -> tuple[bool, list[str], dict[str, bool]]:
    effect = causal["Causal Effect"]
    validation = causal["Validation"]
    confidence = causal["Confidence"]
    estimate = effect["estimate"]
    ci = effect.get("ci95_cluster_bootstrap")
    if config.expected_direction == "positive":
        direction_ok = estimate > config.minimum_effect
        ci_ok = bool(ci) and ci[0] > config.minimum_effect
    elif config.expected_direction == "negative":
        direction_ok = estimate < config.minimum_effect
        ci_ok = bool(ci) and ci[1] < config.minimum_effect
    else:
        raise InterfaceError("expected_direction must be positive or negative")
    checks = {
        "expected_effect_direction": bool(direction_ok),
        "ci_excludes_threshold": bool(ci_ok),
        "adequate_overlap": validation["propensity_overlap_0.05_0.95"] >= 0.80,
        "acceptable_weights": validation["max_unstabilized_ipw"] <= 20,
        "refuters_stable": all(
            value for key, value in confidence["checks"].items() if key.endswith("_stable")
        ),
        "adequate_group_sample": min(effect["treated_n"], effect["control_n"]) >= 100,
        "adequate_refuter_simulations": config.refute_simulations >= 20,
        "adequate_cluster_bootstrap": effect.get("bootstrap_simulations", 0) >= 50,
    }
    reasons = [name if ok else f"failed:{name}" for name, ok in checks.items()]
    return all(checks.values()), reasons, checks


def build_validation_report(
    candidate: dict[str, Any],
    causal: dict[str, Any],
    membership: dict[str, Any],
    artifact_record: dict[str, Any],
    config: PipelineConfig,
) -> dict[str, Any]:
    accepted, reasons, checks = _decision(causal, config)
    effect = causal["Causal Effect"]
    validation = causal["Validation"]
    return {
        "schema_version": REPORT_VERSION,
        "case_id": candidate["case_id"],
        "attack_id": (candidate.get("mutation") or {}).get("attack_id"),
        "accepted": accepted,
        "decision_rule": "aml-causal-acceptance/v0.3",
        "decision_reasons": reasons,
        "decision_checks": checks,
        "validation_target": "aml_outcome",
        "method": "dowhy.backdoor.propensity_score_weighting",
        "analysis_unit": "account_day",
        "treatment": effect["treatment"],
        "outcome": "next_day_laundering",
        "estimand": "ATE_risk_difference",
        "expected_direction": config.expected_direction,
        "minimum_effect": config.minimum_effect,
        "aggregate": {
            "effect_size": effect["estimate"],
            "ci95_cluster_bootstrap": effect.get("ci95_cluster_bootstrap"),
            "bootstrap_standard_error": effect.get("bootstrap_standard_error"),
            "sample_size": effect["n"],
            "treated_n": effect["treated_n"],
            "control_n": effect["control_n"],
        },
        "adjustment_set": CONFOUNDERS,
        "diagnostics": {
            "propensity_overlap_0.05_0.95": validation["propensity_overlap_0.05_0.95"],
            "max_unstabilized_ipw": validation["max_unstabilized_ipw"],
            "amount_evidence": candidate["graph"]["amount_mode"],
            "candidate_membership": membership,
        },
        "refuters": validation["refuters"],
        "counterfactuals": [],
        "warnings": ["Causal conclusions remain conditional on no unmeasured confounding."],
        "source_artifact": {
            "artifact_id": artifact_record["artifact_id"],
            "format": artifact_record["format"],
            "sha256": artifact_record["sha256"],
        },
        "validator_version": VALIDATOR_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def validated_package(candidate: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    if not report["accepted"]:
        raise InterfaceError("only accepted reports can produce ValidatedSubgraphPackage")
    package = copy.deepcopy(candidate)
    package["schema_version"] = VALIDATED_VERSION
    package["package_type"] = "validated_subgraph"
    package.pop("oracle_ref", None)
    package["validation"] = report
    return package


def run_pipeline(
    candidate_path: Path,
    manifest_path: Path,
    output_dir: Path,
    config: PipelineConfig | None = None,
    attack_summary_path: Path | None = None,
) -> dict[str, Any]:
    config = config or PipelineConfig()
    candidate = read_json(candidate_path)
    validate_candidate(candidate)
    if attack_summary_path is not None:
        validate_summary_consistency(candidate, read_json(attack_summary_path))

    context = candidate["analysis_context"]
    if context["requested_validation_target"] != "aml_outcome":
        raise InterfaceError(
            "this AML causal pipeline only executes aml_outcome; model_behavior is a separate validator"
        )
    population_ref = context["population_artifact"]
    artifact_path, artifact_record = resolve_artifact(
        manifest_path, population_ref["artifact_id"]
    )
    for field in ["format", "sha256"]:
        if population_ref.get(field) != artifact_record.get(field):
            raise InterfaceError(f"population_artifact.{field} differs from manifest")
    outcome_ref = context["outcome_ref"]
    if outcome_ref.get("artifact_id") != population_ref["artifact_id"]:
        raise InterfaceError("demo pipeline requires labels in the population artifact")
    if "CausalValidator" not in outcome_ref.get("allowed_consumers", []):
        raise InterfaceError("outcome_ref does not authorize CausalValidator")

    treatment = config.treatment or context.get("suggested_treatment") or "rapid_transfer"
    membership = verify_candidate_treatment(candidate, treatment, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel_path = output_dir / "account_day_panel.parquet"
    subgraphs_path = output_dir / "identified_subgraphs.parquet"
    causal_path = output_dir / "causal_result.json"
    report_path = output_dir / "validation_report_v03.json"
    validated_path = output_dir / "validated_subgraph_v03.json"

    build_panel(
        artifact_path,
        panel_path,
        subgraphs_path,
        config.lookback_days,
        config.rapid_hours,
        config.min_ratio,
        config.max_ratio,
        config.motif_hours,
        config.fan_threshold,
        config.motif_min_ratio,
        config.motif_max_ratio,
        config.max_rows,
    )
    causal = run_dowhy(
        panel_path,
        causal_path,
        treatment,
        config.refute_simulations,
        config.seed,
        config.bootstrap_simulations,
    )
    report = build_validation_report(candidate, causal, membership, artifact_record, config)
    write_json(report_path, report)
    package = None
    if report["accepted"]:
        package = validated_package(candidate, report)
        write_json(validated_path, package)

    outputs = {
        "panel": str(panel_path),
        "identified_subgraphs": str(subgraphs_path),
        "causal_result": str(causal_path),
        "validation_report": str(report_path),
        "validated_subgraph": str(validated_path) if package else None,
    }
    manifest = {
        "pipeline_version": VALIDATOR_VERSION,
        "case_id": candidate["case_id"],
        "parameters": asdict(config),
        "inputs": {
            "candidate_sha256": sha256_file(candidate_path),
            "artifact_id": artifact_record["artifact_id"],
            "artifact_sha256": artifact_record["sha256"],
        },
        "outputs": outputs,
        "accepted": report["accepted"],
    }
    write_json(output_dir / "run_manifest.json", manifest)
    return {"report": report, "validated_package": package, "outputs": outputs}
