"""Add deterministic edge identity and lineage after a core mutation."""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd


FACT_COLUMNS = (
    "timestamp",
    "source",
    "target",
    "amount",
)


def _same_fact(base_row: dict, mutated_row: dict) -> bool:
    for column in FACT_COLUMNS:
        if column == "amount":
            if not math.isclose(
                float(base_row[column]),
                float(mutated_row[column]),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                return False
        elif str(base_row[column]) != str(mutated_row[column]):
            return False
    return True


def _added_parent(edge_id: str, base_edge_ids: list[str]) -> Optional[str]:
    for parent_id in sorted(base_edge_ids, key=len, reverse=True):
        if edge_id.startswith(f"{parent_id}_path_"):
            return parent_id
    return None


def build_mutation_artifact(
    baseline: pd.DataFrame,
    mutated: pd.DataFrame,
    attack_id: str,
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Return factual rows with interface IDs plus complete edge lineage."""
    baseline_records = {
        str(record["transaction_id"]): record
        for record in baseline.to_dict(orient="records")
    }
    base_edge_ids = list(baseline_records)
    artifact = mutated.copy()
    lineage: dict[str, dict] = {}
    operation_index = 0
    new_edge_ids = []

    for record in artifact.to_dict(orient="records"):
        current_id = str(record["transaction_id"])
        if current_id in baseline_records:
            if _same_fact(baseline_records[current_id], record):
                edge_id = current_id
                parent_edge_ids = []
                mutation_role = "preserved"
            else:
                edge_id = (
                    f"{current_id}__mut__{attack_id}__{operation_index:03d}"
                )
                operation_index += 1
                parent_edge_ids = [current_id]
                mutation_role = "modified"
        else:
            parent_id = _added_parent(current_id, base_edge_ids)
            edge_id = f"{attack_id}__add__{operation_index:03d}"
            operation_index += 1
            parent_edge_ids = [parent_id] if parent_id else []
            mutation_role = "added"

        if edge_id in lineage:
            raise ValueError(f"Duplicate mutation edge ID: {edge_id}")
        new_edge_ids.append(edge_id)
        lineage[edge_id] = {
            "parent_edge_ids": parent_edge_ids,
            "mutation_role": mutation_role,
        }

    artifact["transaction_id"] = new_edge_ids
    return artifact, lineage
