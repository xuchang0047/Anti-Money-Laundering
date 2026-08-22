"""Run the complete lightweight scatter-gather robustness prototype."""

import json
from pathlib import Path

import pandas as pd

from baseline_detector import detect_scatter_gather
from candidate_package_builder import (
    build_candidate_package,
    write_artifact_manifest,
)
from candidate_retriever import retrieve_scatter_gather_candidates
from evaluate_attack import evaluate_attack
from feature_extractor import extract_candidate_features
from graph_builder import build_transaction_graph
from mutations import amount_perturbation, path_extension, temporal_stretch
from mutation_artifacts import build_mutation_artifact
from robustness_sweep import print_robustness_profile, run_robustness_sweep
from synthetic_generator import generate_base_scatter_gather


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "attack_config.json"
BASELINE_PATH = PROJECT_ROOT / "data" / "mock" / "base_scatter_gather.csv"
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "attacks"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_or_generate_baseline() -> pd.DataFrame:
    if not BASELINE_PATH.exists():
        return generate_base_scatter_gather(BASELINE_PATH)
    return pd.read_csv(BASELINE_PATH)


def print_results(results: list[dict]) -> None:
    headers = [
        "Attack",
        "Retrieved Before",
        "Retrieved After",
        "Detected Before",
        "Detected After",
        "Failure Stage",
        "Success",
    ]
    rows = []
    for result in results:
        rows.append(
            [
                result["attack_type"],
                str(result["base_retrieved"]),
                str(result["mutated_retrieved"]),
                str(result["old_rule_result"]["before_attack"]),
                str(result["old_rule_result"]["after_attack"]),
                str(result["failure_stage"]),
                str(result["attack_success"]),
            ]
        )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(value.ljust(widths[index]) for index, value in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def main() -> None:
    config = load_config()
    baseline = load_or_generate_baseline()
    base_graph = build_transaction_graph(baseline)
    base_candidates = retrieve_scatter_gather_candidates(
        base_graph, config["retrieval"]
    )
    if not base_candidates:
        raise RuntimeError("Synthetic baseline was not retrieved as a candidate")

    base_candidate = base_candidates[0]
    case_id = str(baseline["pattern_id"].iloc[0])
    base_features = extract_candidate_features(base_candidate, baseline)
    base_detection = detect_scatter_gather(base_features, config["detector"])

    mutations = [
        (
            "temporal_stretch",
            temporal_stretch(baseline, base_candidate, config["mutations"]["temporal_stretch"]),
            dict(config["mutations"]["temporal_stretch"]),
        ),
        (
            "path_extension",
            path_extension(baseline, base_candidate, config["mutations"]["path_extension"]),
            dict(config["mutations"]["path_extension"]),
        ),
        (
            "amount_perturbation",
            amount_perturbation(
                baseline, base_candidate, config["mutations"]["amount_perturbation"]
            ),
            dict(config["mutations"]["amount_perturbation"]),
        ),
    ]

    results = []
    for attack_type, core_mutated_transactions, parameters in mutations:
        attack_id = f"synthetic_sg_001_{attack_type}"
        mutated_transactions, edge_lineage = build_mutation_artifact(
            baseline, core_mutated_transactions, attack_id
        )
        summary = evaluate_attack(
            attack_id=attack_id,
            case_id=case_id,
            attack_type=attack_type,
            parameters=parameters,
            edge_lineage=edge_lineage,
            base_transactions=baseline,
            mutated_transactions=mutated_transactions,
            base_candidate=base_candidate,
            base_features=base_features,
            base_detection=base_detection,
            config=config,
            output_root=OUTPUT_ROOT,
        )
        build_candidate_package(
            summary=summary,
            baseline=baseline,
            mutated=mutated_transactions,
            output_dir=OUTPUT_ROOT / attack_id,
            config_path=CONFIG_PATH,
            interface_config=config["interface"],
        )
        results.append(summary)

    print("Prototype heuristic robustness results (synthetic data only):")
    print_results(results)
    profile = run_robustness_sweep(
        baseline=baseline,
        base_candidate=base_candidate,
        base_features=base_features,
        base_detection=base_detection,
        config=config,
        output_path=OUTPUT_ROOT / "robustness_profile.json",
    )
    print_robustness_profile(profile)
    write_artifact_manifest(OUTPUT_ROOT, PROJECT_ROOT)


if __name__ == "__main__":
    main()
