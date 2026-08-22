"""Executable detectors for baseline and evolved AML motifs."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from .canonicalizer import TIME_TO_HOURS, fact_edges


def _json_number(value: float) -> float | None:
    return round(value, 6) if math.isfinite(value) else None


@dataclass
class MatchResult:
    matched: bool
    score: float
    detector_id: str
    role_bindings: dict[str, Any]
    evidence: dict[str, Any]
    failed_constraints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unwrap_graph(value: dict[str, Any]) -> dict[str, Any]:
    return value["graph"] if "graph" in value and "edges" not in value else value


def _adjacency(edges: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["src"]].append(edge)
        incoming[edge["dst"]].append(edge)
    return incoming, outgoing


def match_relay_bridge(graph_value: dict[str, Any], experience: dict[str, Any]) -> MatchResult:
    graph = _unwrap_graph(graph_value)
    edges = fact_edges(graph)
    incoming, outgoing = _adjacency(edges)
    constraints = experience["constraints"]
    source_min = experience["roles"]["sources"]["min_count"]
    sink_min = experience["roles"]["sinks"]["min_count"]
    best: MatchResult | None = None

    for bridge in edges:
        collector, relay = bridge["src"], bridge["dst"]
        gather = [edge for edge in incoming[collector] if edge["src"] != relay]
        scatter = [edge for edge in outgoing[relay] if edge["dst"] != collector]
        sources = sorted({edge["src"] for edge in gather})
        sinks = sorted({edge["dst"] for edge in scatter})
        checks: list[tuple[str, bool]] = [
            ("minimum_sources", len(sources) >= source_min),
            ("minimum_sinks", len(sinks) >= sink_min),
        ]
        if not gather or not scatter:
            checks.extend((name, False) for name in ("temporal_partial_order", "duration", "bridge_input_flow", "output_bridge_flow"))
            duration_hours = float("inf")
            bridge_in_ratio = 0.0
            out_bridge_ratio = float("inf")
        else:
            temporal = max(edge["timestamp"] for edge in gather) <= bridge["timestamp"] <= min(edge["timestamp"] for edge in scatter)
            timestamps = [edge["timestamp"] for edge in gather + [bridge] + scatter]
            duration_hours = (max(timestamps) - min(timestamps)) * TIME_TO_HOURS[graph["time_unit"]]
            incoming_amount = sum(edge["base_amount"] for edge in gather)
            outgoing_amount = sum(edge["base_amount"] for edge in scatter)
            bridge_in_ratio = bridge["base_amount"] / incoming_amount if incoming_amount else 0.0
            out_bridge_ratio = outgoing_amount / bridge["base_amount"] if bridge["base_amount"] else float("inf")
            flow_min, flow_max = constraints["flow_ratio"]
            checks.extend(
                (
                    ("temporal_partial_order", temporal),
                    ("duration", duration_hours <= constraints["max_duration_hours"]),
                    ("bridge_input_flow", flow_min <= bridge_in_ratio <= flow_max),
                    ("output_bridge_flow", flow_min <= out_bridge_ratio <= flow_max),
                )
            )
        context_count = sum(edge.get("scope") == "context" for edge in graph["edges"])
        context_ratio = context_count / len(graph["edges"]) if graph["edges"] else 0.0
        checks.append(("decoy_ratio", context_ratio <= constraints["max_decoy_ratio"]))
        passed = sum(ok for _, ok in checks)
        failed = [name for name, ok in checks if not ok]
        result = MatchResult(
            matched=not failed,
            score=round(passed / len(checks), 6),
            detector_id=experience["experience_id"],
            role_bindings={"sources": sources, "collector": collector, "relay": relay, "sinks": sinks},
            evidence={
                "bridge_edge_id": bridge["edge_id"],
                "duration_hours": _json_number(duration_hours),
                "bridge_in_ratio": _json_number(bridge_in_ratio),
                "out_bridge_ratio": _json_number(out_bridge_ratio),
                "context_edge_ratio": _json_number(context_ratio),
            },
            failed_constraints=failed,
        )
        if best is None or result.score > best.score:
            best = result

    if best is not None:
        return best
    return MatchResult(False, 0.0, experience["experience_id"], {}, {}, ["collector_relay_bridge_missing"])


def match_single_hub(graph_value: dict[str, Any], experience: dict[str, Any]) -> MatchResult:
    graph = _unwrap_graph(graph_value)
    edges = fact_edges(graph)
    incoming, outgoing = _adjacency(edges)
    minimum = experience["constraints"].get("minimum_fan", 3)
    best: MatchResult | None = None
    for hub in {node["node_id"] for node in graph["nodes"]}:
        gather = incoming[hub]
        scatter = outgoing[hub]
        sources = sorted({edge["src"] for edge in gather})
        sinks = sorted({edge["dst"] for edge in scatter})
        checks = [
            ("minimum_sources", len(sources) >= minimum),
            ("minimum_sinks", len(sinks) >= minimum),
            (
                "temporal_partial_order",
                bool(gather and scatter) and max(edge["timestamp"] for edge in gather) <= min(edge["timestamp"] for edge in scatter),
            ),
        ]
        passed = sum(ok for _, ok in checks)
        result = MatchResult(
            not [name for name, ok in checks if not ok],
            round(passed / len(checks), 6),
            experience["experience_id"],
            {"sources": sources, "hub": hub, "sinks": sinks},
            {},
            [name for name, ok in checks if not ok],
        )
        if best is None or result.score > best.score:
            best = result
    return best or MatchResult(False, 0.0, experience["experience_id"], {}, {}, ["empty_graph"])


def match(graph: dict[str, Any], experience: dict[str, Any]) -> MatchResult:
    kind = experience.get("matcher_kind")
    if kind == "relay_bridge_gather_scatter/v1":
        return match_relay_bridge(graph, experience)
    if kind == "single_hub_gather_scatter/v1":
        return match_single_hub(graph, experience)
    return MatchResult(False, 0.0, experience["experience_id"], {}, {}, ["descriptor_only_detector"])
