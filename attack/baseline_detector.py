"""A transparent prototype heuristic, not a production AML detector."""


def detect_scatter_gather(features: dict, config: dict) -> dict:
    checks = [
        (
            "fan_out_degree",
            features["fan_out_degree"] >= config["min_fan_out"],
            ">=",
            config["min_fan_out"],
        ),
        (
            "fan_in_degree",
            features["fan_in_degree"] >= config["min_fan_in"],
            ">=",
            config["min_fan_in"],
        ),
        (
            "time_span_hours",
            features["time_span_hours"] <= config["max_time_span_hours"],
            "<=",
            config["max_time_span_hours"],
        ),
        (
            "flow_through_ratio",
            features["flow_through_ratio"] >= config["min_flow_through_ratio"],
            ">=",
            config["min_flow_through_ratio"],
        ),
    ]

    triggered = []
    failed = []
    for feature_name, passed, operator, threshold in checks:
        description = (
            f"{feature_name} {operator} {threshold} "
            f"(observed={features[feature_name]}) [prototype heuristic]"
        )
        (triggered if passed else failed).append(description)

    return {
        "suspicious_candidate": all(passed for _, passed, _, _ in checks),
        "triggered_conditions": triggered,
        "failed_conditions": failed,
    }
