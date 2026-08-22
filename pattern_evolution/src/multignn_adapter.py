"""Contract adapter from Shared Subgraph Package v0.2 to Multi-GNN inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class VocabularyEncoder:
    values: dict[str, int]
    unknown: int = 0

    def encode_or_unknown(self, value: str | None) -> int:
        return self.values.get(value or "", self.unknown)


def to_multignn_payload(
    package: dict[str, Any],
    *,
    currency_encoder: VocabularyEncoder | None = None,
    transaction_encoder: VocabularyEncoder | None = None,
) -> dict[str, Any]:
    """Produce the exact pre-tensor columns used by Multi-GNN data_loading.py.

    Oracle labels, causal roles, reverse edges, ports and normalized features are
    deliberately excluded.
    """

    graph = package["graph"] if "graph" in package and "edges" not in package else package
    currency_encoder = currency_encoder or VocabularyEncoder({"USD": 1, "EUR": 2})
    transaction_encoder = transaction_encoder or VocabularyEncoder({"TRANSFER": 1, "CASH": 2})
    node_ids = [node["node_id"] for node in graph["nodes"]]
    local_id = {node_id: index for index, node_id in enumerate(node_ids)}
    edges = graph["edges"]
    return {
        "x": [[1.0] for _ in node_ids],
        "edge_index": [
            [local_id[edge["src"]] for edge in edges],
            [local_id[edge["dst"]] for edge in edges],
        ],
        "edge_attr": [
            [
                float(edge["timestamp"]),
                float(edge["base_amount"]),
                float(currency_encoder.encode_or_unknown(edge["base_currency"])),
                float(transaction_encoder.encode_or_unknown(edge["transaction_type"])),
            ]
            for edge in edges
        ],
        "timestamps": [float(edge["timestamp"]) for edge in edges],
        "edge_ids": [edge["edge_id"] for edge in edges],
        "local_node_id_by_stable_id": local_id,
        "derived_fields": [],
        "feature_contract": ["timestamp", "base_amount", "base_currency", "transaction_type"],
    }


def to_torch_tensors(package: dict[str, Any]) -> dict[str, Any]:
    import torch

    payload = to_multignn_payload(package)
    return {
        "x": torch.tensor(payload["x"], dtype=torch.float32),
        "edge_index": torch.tensor(payload["edge_index"], dtype=torch.long),
        "edge_attr": torch.tensor(payload["edge_attr"], dtype=torch.float32),
        "timestamps": torch.tensor(payload["timestamps"], dtype=torch.float32),
        "edge_ids": payload["edge_ids"],
        "local_node_id_by_stable_id": payload["local_node_id_by_stable_id"],
    }


def to_pyg(package: dict[str, Any], graph_data_factory: Callable[..., Any] | None = None) -> Any:
    tensors = to_torch_tensors(package)
    if graph_data_factory is None:
        try:
            from torch_geometric.data import Data
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "torch_geometric is not installed; to_multignn_payload() and to_torch_tensors() remain usable"
            ) from exc
        graph_data_factory = Data
    return graph_data_factory(
        x=tensors["x"],
        edge_index=tensors["edge_index"],
        edge_attr=tensors["edge_attr"],
        timestamps=tensors["timestamps"],
    )
