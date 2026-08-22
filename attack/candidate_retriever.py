"""Retrieve only 2-hop scatter-gather suspicious candidates."""

from collections import defaultdict

import networkx as nx


def _edge_records(graph: nx.MultiDiGraph, source: str, target: str) -> list[dict]:
    edge_map = graph.get_edge_data(source, target, default={})
    return list(edge_map.values())


def retrieve_scatter_gather_candidates(
    graph: nx.MultiDiGraph, config: dict
) -> list[dict]:
    """Generate candidates; this function does not determine laundering."""
    min_fan_out = int(config["min_fan_out"])
    min_converging = int(config["min_converging_intermediates"])
    max_span_hours = float(config["max_time_span_hours"])
    candidates = []

    for source in sorted(graph.nodes, key=str):
        direct_neighbors = {
            str(node) for node in graph.successors(source) if str(node) != str(source)
        }
        if len(direct_neighbors) < min_fan_out:
            continue

        destination_to_intermediates = defaultdict(set)
        for intermediate in direct_neighbors:
            for destination in graph.successors(intermediate):
                destination = str(destination)
                if destination != str(source) and destination not in direct_neighbors:
                    destination_to_intermediates[destination].add(intermediate)

        for destination, intermediate_set in sorted(destination_to_intermediates.items()):
            if len(intermediate_set) < min_converging:
                continue

            intermediates = sorted(intermediate_set)
            transaction_ids = []
            timestamps = []
            for intermediate in intermediates:
                for edge in _edge_records(graph, str(source), intermediate):
                    transaction_ids.append(edge["transaction_id"])
                    timestamps.append(edge["timestamp"])
                for edge in _edge_records(graph, intermediate, destination):
                    transaction_ids.append(edge["transaction_id"])
                    timestamps.append(edge["timestamp"])

            time_span_hours = (
                (max(timestamps) - min(timestamps)).total_seconds() / 3600.0
            )
            if time_span_hours > max_span_hours:
                continue

            candidates.append(
                {
                    "candidate_id": f"sg_{len(candidates) + 1:03d}",
                    "source": str(source),
                    "intermediates": intermediates,
                    "destination": destination,
                    "node_ids": [str(source), *intermediates, destination],
                    "transaction_ids": sorted(set(transaction_ids)),
                }
            )

    return candidates


def retrieve_cycle_candidates(graph: nx.MultiDiGraph, config: dict) -> list[dict]:
    """Reserved interface; cycle retrieval is intentionally not implemented."""
    raise NotImplementedError("Cycle candidate retrieval is outside prototype v0.1")
