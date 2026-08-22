"""Run small parameter sweeps over the three frozen attack types."""

import json
from pathlib import Path

import networkx as nx
import pandas as pd

from evaluate_attack import evaluate_mutated_case
from graph_builder import build_transaction_graph
from mutations import amount_perturbation, path_extension, temporal_stretch


def _result_fields(evaluation: dict) -> dict:
    return {
        "mutated_retrieved": evaluation["mutated_retrieved"],
        "detected_after": evaluation["after_detected"],
        "failure_stage": evaluation["failure_stage"],
        "failure_type": evaluation["failure_type"],
        "attack_success": evaluation["attack_success"],
    }


def _time_span_hours(transactions: pd.DataFrame, transaction_ids: list[str]) -> float:
    selected = transactions[
        transactions["transaction_id"].astype(str).isin(set(transaction_ids))
    ]
    timestamps = pd.to_datetime(selected["timestamp"], utc=True)
    return round(
        float((timestamps.max() - timestamps.min()).total_seconds() / 3600.0),
        6,
    )


def _apply_path_layers(
    baseline: pd.DataFrame,
    base_candidate: dict,
    mutation_config: dict,
    extra_layers: int,
) -> pd.DataFrame:
    mutated = baseline.copy()
    scope = dict(base_candidate)
    for _ in range(extra_layers):
        mutated = path_extension(mutated, scope, mutation_config)
        relay_intermediates = [
            f"{intermediate}_relay" for intermediate in scope["intermediates"]
        ]
        downstream = mutated[
            mutated["source"].isin(relay_intermediates)
            & (mutated["target"] == scope["destination"])
        ]
        scope = {
            **scope,
            "intermediates": relay_intermediates,
            "transaction_ids": downstream["transaction_id"].astype(str).tolist(),
        }
    return mutated


def run_robustness_sweep(
    baseline: pd.DataFrame,
    base_candidate: dict,
    base_features: dict,
    base_detection: dict,
    config: dict,
    output_path: Path,
) -> dict:
    profiles = {
        "temporal_stretch": [],
        "path_extension": [],
        "amount_perturbation": [],
    }

    for delay_hours in config["sweep"]["temporal_stretch"][
        "downstream_delay_hours"
    ]:
        mutation_config = {"downstream_delay_hours": delay_hours}
        mutated = temporal_stretch(baseline, base_candidate, mutation_config)
        evaluation = evaluate_mutated_case(
            mutated, base_candidate, base_features, base_detection, config
        )
        profiles["temporal_stretch"].append(
            {
                "downstream_delay_hours": delay_hours,
                "observed_time_span_hours": _time_span_hours(
                    mutated, base_candidate["transaction_ids"]
                ),
                **_result_fields(evaluation),
            }
        )

    for extra_layers in config["sweep"]["path_extension"]["extra_layers"]:
        mutated = _apply_path_layers(
            baseline,
            base_candidate,
            config["mutations"]["path_extension"],
            int(extra_layers),
        )
        graph = build_transaction_graph(mutated)
        observed_path_depth = nx.shortest_path_length(
            graph, base_candidate["source"], base_candidate["destination"]
        )
        evaluation = evaluate_mutated_case(
            mutated, base_candidate, base_features, base_detection, config
        )
        profiles["path_extension"].append(
            {
                "extra_layers": extra_layers,
                "observed_path_depth": int(observed_path_depth),
                **_result_fields(evaluation),
            }
        )

    base_amount_config = config["mutations"]["amount_perturbation"]
    for noise_level in config["sweep"]["amount_perturbation"]["noise_levels"]:
        mutation_config = {**base_amount_config, "noise_fraction": noise_level}
        mutated = amount_perturbation(baseline, base_candidate, mutation_config)
        evaluation = evaluate_mutated_case(
            mutated, base_candidate, base_features, base_detection, config
        )
        observed_ratio = evaluation["mutated_case_features"].get(
            "flow_through_ratio"
        )
        profiles["amount_perturbation"].append(
            {
                "noise_level": noise_level,
                "observed_flow_through_ratio": observed_ratio,
                **_result_fields(evaluation),
            }
        )

    profile = {
        "schema_version": "attack.robustness_profile/v0.1",
        "source_pattern": "scatter_gather",
        "prototype_notice": (
            "Thresholds are prototype heuristics; synthetic detection evasion "
            "does not establish a production AML outcome."
        ),
        "profiles": profiles,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(profile, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return profile


def print_robustness_profile(profile: dict) -> None:
    print("\nRobustness sweep (synthetic data, prototype heuristics):")
    print(
        "Attack               Parameter                  Observed   Retrieved  "
        "Detected  Failure Type       Success"
    )
    print(
        "-------------------  -------------------------  ---------  ---------  "
        "--------  -----------------  -------"
    )
    parameter_fields = {
        "temporal_stretch": (
            "downstream_delay_hours",
            "observed_time_span_hours",
        ),
        "path_extension": ("extra_layers", "observed_path_depth"),
        "amount_perturbation": (
            "noise_level",
            "observed_flow_through_ratio",
        ),
    }
    for attack_type, cases in profile["profiles"].items():
        parameter_name, observed_name = parameter_fields[attack_type]
        for case in cases:
            parameter = f"{parameter_name}={case[parameter_name]}"
            print(
                f"{attack_type:<19}  {parameter:<25}  "
                f"{str(case[observed_name]):<9}  "
                f"{str(case['mutated_retrieved']):<9}  "
                f"{str(case['detected_after']):<8}  "
                f"{case['failure_type']:<17}  "
                f"{str(case['attack_success']):<7}"
            )
