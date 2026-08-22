"""Extract explainable features from a retrieved transaction candidate."""

import networkx as nx
import numpy as np
import pandas as pd


def extract_candidate_features(candidate: dict, transactions: pd.DataFrame) -> dict:
    transaction_ids = {str(value) for value in candidate["transaction_ids"]}
    frame = transactions.copy()
    frame["transaction_id"] = frame["transaction_id"].astype(str)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="raise")

    candidate_rows = frame[frame["transaction_id"].isin(transaction_ids)].copy()
    if candidate_rows.empty:
        raise ValueError(f"No transactions found for {candidate['candidate_id']}")

    source = candidate["source"]
    destination = candidate["destination"]
    intermediates = set(candidate["intermediates"])
    incoming = candidate_rows[
        (candidate_rows["source"] == source)
        & (candidate_rows["target"].isin(intermediates))
    ]
    all_downstream = frame[frame["source"].isin(intermediates)]
    destination_downstream = all_downstream[
        all_downstream["target"] == destination
    ]

    delays = []
    for intermediate in sorted(intermediates):
        receipts = incoming[incoming["target"] == intermediate]["timestamp"]
        sends = all_downstream[all_downstream["source"] == intermediate]["timestamp"]
        if receipts.empty or sends.empty:
            continue
        receipt_time = receipts.min()
        later_sends = sends[sends >= receipt_time]
        if not later_sends.empty:
            delays.append((later_sends.min() - receipt_time).total_seconds() / 3600.0)

    incoming_amount = float(incoming["amount"].sum())
    downstream_amount = float(all_downstream["amount"].sum())
    destination_amount = float(destination_downstream["amount"].sum())

    # Prototype proxy formula:
    # flow_through_ratio = total amount sent onward by the intermediate accounts
    #                      / total amount those accounts received from the source.
    # It is intentionally not capped at 1 because accounts may contain other funds.
    flow_through_ratio = downstream_amount / incoming_amount if incoming_amount else 0.0
    convergence_ratio = (
        destination_amount / downstream_amount if downstream_amount else 0.0
    )

    topology = nx.DiGraph()
    topology.add_edges_from(candidate_rows[["source", "target"]].itertuples(index=False, name=None))
    path_length = nx.shortest_path_length(topology, source, destination)
    time_span = (
        candidate_rows["timestamp"].max() - candidate_rows["timestamp"].min()
    ).total_seconds() / 3600.0

    return {
        "fan_out_degree": int(incoming["target"].nunique()),
        "fan_in_degree": int(destination_downstream["source"].nunique()),
        "num_intermediates": int(len(intermediates)),
        "time_span_hours": round(float(time_span), 6),
        "median_delay_hours": round(float(np.median(delays)), 6) if delays else 0.0,
        "flow_through_ratio": round(float(flow_through_ratio), 6),
        "convergence_ratio": round(float(convergence_ratio), 6),
        "path_length": int(path_length),
    }
