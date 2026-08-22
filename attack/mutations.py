"""Controlled mutations for synthetic robustness testing."""

from datetime import timedelta

import numpy as np
import pandas as pd


def temporal_stretch(df: pd.DataFrame, candidate: dict, config: dict) -> pd.DataFrame:
    """Delay downstream transactions while preserving topology and amounts."""
    mutated = df.copy()
    downstream_ids = set(candidate["transaction_ids"])
    mask = (
        mutated["transaction_id"].astype(str).isin(downstream_ids)
        & mutated["source"].isin(candidate["intermediates"])
    )
    timestamps = pd.to_datetime(mutated.loc[mask, "timestamp"], utc=True)
    delay = timedelta(hours=float(config["downstream_delay_hours"]))
    mutated.loc[mask, "timestamp"] = (timestamps + delay).map(
        lambda value: value.isoformat().replace("+00:00", "Z")
    )
    return mutated


def path_extension(df: pd.DataFrame, candidate: dict, config: dict) -> pd.DataFrame:
    """Replace each intermediate→destination edge with a two-edge relay path."""
    relay_delay = timedelta(hours=float(config["relay_delay_hours"]))
    candidate_ids = set(candidate["transaction_ids"])
    rows = []

    for record in df.to_dict(orient="records"):
        is_downstream = (
            str(record["transaction_id"]) in candidate_ids
            and record["source"] in candidate["intermediates"]
            and record["target"] == candidate["destination"]
        )
        if not is_downstream:
            rows.append(record)
            continue

        original_id = str(record["transaction_id"])
        relay = f"{record['source']}_relay"
        first = dict(record)
        second = dict(record)
        first["transaction_id"] = f"{original_id}_path_1"
        first["target"] = relay
        second["transaction_id"] = f"{original_id}_path_2"
        second["source"] = relay
        timestamp = pd.to_datetime(record["timestamp"], utc=True)
        second["timestamp"] = (timestamp + relay_delay).isoformat().replace(
            "+00:00", "Z"
        )
        rows.extend([first, second])

    return pd.DataFrame(rows, columns=df.columns)


def amount_perturbation(
    df: pd.DataFrame, candidate: dict, config: dict
) -> pd.DataFrame:
    """Apply seeded independent amount noise without changing graph topology."""
    mutated = df.copy()
    candidate_ids = set(candidate["transaction_ids"])
    # Candidate membership, not synthetic/oracle labels, defines mutation scope.
    mask = mutated["transaction_id"].astype(str).isin(candidate_ids)
    rng = np.random.default_rng(int(config["seed"]))
    noise_fraction = float(config["noise_fraction"])
    factors = rng.uniform(1.0 - noise_fraction, 1.0 + noise_fraction, mask.sum())
    amounts = pd.to_numeric(mutated.loc[mask, "amount"], errors="raise").to_numpy()
    mutated.loc[mask, "amount"] = np.maximum(
        float(config["minimum_amount"]), amounts * factors
    ).round(2)
    return mutated
