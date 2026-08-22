"""Node-ID-independent role induction and graph fingerprinting."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any


TIME_TO_HOURS = {
    "millisecond": 1.0 / 3_600_000,
    "second": 1.0 / 3600,
    "minute": 1.0 / 60,
    "hour": 1.0,
    "day": 24.0,
}


def fact_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Return motif-bearing fact edges; context edges remain available as noise."""

    return [edge for edge in graph["edges"] if edge.get("scope", "unknown") != "context"]


def infer_relay_bridge_roles(graph: dict[str, Any]) -> dict[str, Any]:
    edges = fact_edges(graph)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["src"]].append(edge)
        incoming[edge["dst"]].append(edge)

    candidates: list[tuple[tuple[int, float, str, str], dict[str, Any]]] = []
    for bridge in edges:
        collector = bridge["src"]
        relay = bridge["dst"]
        gather = [edge for edge in incoming[collector] if edge["src"] != relay]
        scatter = [edge for edge in outgoing[relay] if edge["dst"] != collector]
        sources = sorted({edge["src"] for edge in gather})
        sinks = sorted({edge["dst"] for edge in scatter})
        if len(sources) < 2 or len(sinks) < 2:
            continue
        temporal_margin = min(edge["timestamp"] for edge in scatter) - max(edge["timestamp"] for edge in gather)
        score = (len(sources) + len(sinks), temporal_margin, collector, relay)
        candidates.append(
            (
                score,
                {
                    "collector": collector,
                    "relay": relay,
                    "sources": sources,
                    "sinks": sinks,
                    "gather_edges": gather,
                    "bridge_edge": bridge,
                    "scatter_edges": scatter,
                },
            )
        )
    if not candidates:
        raise ValueError("no relay-bridge gather-scatter role assignment found")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _wl_hash(graph: dict[str, Any], role_by_node: dict[str, str], rounds: int = 3) -> str:
    edges = fact_edges(graph)
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    nodes = [node["node_id"] for node in graph["nodes"] if node["node_id"] in role_by_node]
    for edge in edges:
        if edge["src"] in role_by_node and edge["dst"] in role_by_node:
            outgoing[edge["src"]].append(edge["dst"])
            incoming[edge["dst"]].append(edge["src"])
    labels = {node: role_by_node[node] for node in nodes}
    for _ in range(rounds):
        next_labels: dict[str, str] = {}
        for node in nodes:
            descriptor = "|".join(
                (
                    labels[node],
                    "I:" + ",".join(sorted(labels[other] for other in incoming[node] if other in labels)),
                    "O:" + ",".join(sorted(labels[other] for other in outgoing[node] if other in labels)),
                )
            )
            next_labels[node] = hashlib.sha256(descriptor.encode("utf-8")).hexdigest()[:16]
        labels = next_labels
    edge_signature = sorted(
        (labels[edge["src"]], labels[edge["dst"]])
        for edge in edges
        if edge["src"] in labels and edge["dst"] in labels
    )
    payload = repr((sorted(labels.values()), edge_signature))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonicalize_relay_bridge(graph: dict[str, Any]) -> dict[str, Any]:
    assignment = infer_relay_bridge_roles(graph)
    role_by_node = {node: "source" for node in assignment["sources"]}
    role_by_node.update({node: "sink" for node in assignment["sinks"]})
    role_by_node[assignment["collector"]] = "collector"
    role_by_node[assignment["relay"]] = "relay"

    gather = assignment["gather_edges"]
    bridge = assignment["bridge_edge"]
    scatter = assignment["scatter_edges"]
    motif_edges = gather + [bridge] + scatter
    timestamps = [edge["timestamp"] for edge in motif_edges]
    duration_hours = (max(timestamps) - min(timestamps)) * TIME_TO_HOURS[graph["time_unit"]]
    temporal_order = (
        "gather<bridge<scatter"
        if max(edge["timestamp"] for edge in gather) <= bridge["timestamp"] <= min(edge["timestamp"] for edge in scatter)
        else "temporal_order_violated"
    )

    incoming_amount = sum(edge["base_amount"] for edge in gather)
    bridge_amount = bridge["base_amount"]
    outgoing_amount = sum(edge["base_amount"] for edge in scatter)
    bridge_in_ratio = bridge_amount / incoming_amount if incoming_amount else 0.0
    out_bridge_ratio = outgoing_amount / bridge_amount if bridge_amount else float("inf")
    context_count = sum(edge.get("scope") == "context" for edge in graph["edges"])
    context_ratio = context_count / len(graph["edges"]) if graph["edges"] else 0.0

    return {
        "family": "relay_bridge_gather_scatter",
        "roles": {
            "sources": {"min_count": min(3, len(assignment["sources"])), "observed_count": len(assignment["sources"])},
            "collector": {"count": 1},
            "relay": {"count": 1},
            "sinks": {"min_count": min(3, len(assignment["sinks"])), "observed_count": len(assignment["sinks"])},
        },
        "required_edges": [
            ["sources", "collector"],
            ["collector", "relay"],
            ["relay", "sinks"],
        ],
        "observations": {
            "duration_hours": round(duration_hours, 6),
            "bridge_in_ratio": round(bridge_in_ratio, 6),
            "out_bridge_ratio": round(out_bridge_ratio, 6),
            "context_edge_ratio": round(context_ratio, 6),
        },
        "fingerprint": {
            "wl_hash": _wl_hash(graph, role_by_node),
            "degree_signature": f"sources:{len(assignment['sources'])}|collector:1|relay:1|sinks:{len(assignment['sinks'])}",
            "temporal_order": temporal_order,
        },
    }
