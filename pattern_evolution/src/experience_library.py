"""Versioned detector library and its separate motif knowledge graph K_t."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .matcher import MatchResult, match
from .schemas import stable_hash, write_json_atomic


IBM_BASELINE_FAMILIES = (
    "fan_in",
    "fan_out",
    "cycle",
    "bipartite",
    "stack",
    "random",
    "scatter_gather",
    "gather_scatter",
)


def seed_baseline_experiences() -> list[dict[str, Any]]:
    experiences = []
    for family in IBM_BASELINE_FAMILIES:
        experience: dict[str, Any] = {
            "experience_id": f"ibm_baseline_{family}",
            "family": family,
            "version": 1,
            "status": "active",
            "matcher_kind": "descriptor_only/v1",
            "roles": {},
            "constraints": {},
            "fingerprint": {"wl_hash": f"baseline::{family}"},
            "lineage": {"parent": None, "round": 0, "mutation_ops": []},
            "source": "IBM_AMLSim_typology_registry",
        }
        if family == "gather_scatter":
            experience["matcher_kind"] = "single_hub_gather_scatter/v1"
            experience["roles"] = {
                "sources": {"min_count": 3},
                "hub": {"count": 1},
                "sinks": {"min_count": 3},
            }
            experience["constraints"] = {"minimum_fan": 3}
        experiences.append(experience)
    return experiences


class DetectorLibrary:
    def __init__(self, *, experiences: list[dict[str, Any]] | None = None, version: int = 0) -> None:
        self.version = version
        self.experiences = copy.deepcopy(experiences if experiences is not None else seed_baseline_experiences())
        self.history: list[dict[str, Any]] = []
        self.knowledge_edges = self._baseline_knowledge_edges()

    @staticmethod
    def _baseline_knowledge_edges() -> list[dict[str, str]]:
        return [
            {"src": "IBM_AMLSim", "relation": "defines_typology", "dst": f"ibm_baseline_{family}"}
            for family in IBM_BASELINE_FAMILIES
        ]

    def detect(self, graph: dict[str, Any]) -> list[MatchResult]:
        return [
            result
            for experience in self.experiences
            if experience.get("status") == "active"
            for result in [match(graph, experience)]
            if result.matched
        ]

    def evolve(self, experience: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
        exact = next(
            (
                item
                for item in self.experiences
                if item.get("fingerprint", {}).get("wl_hash") == experience["fingerprint"]["wl_hash"]
            ),
            None,
        )
        if exact is not None:
            operation = "MERGE"
            exact.setdefault("supporting_certificates", []).append(experience["validation_certificate"])
            exact["version"] = int(exact.get("version", 1)) + 1
            affected_id = exact["experience_id"]
        else:
            same_family = [item for item in self.experiences if item.get("family") == experience["family"]]
            if same_family and replay.get("suggest_specialization"):
                operation = "SPECIALIZE"
                target = same_family[0]
                target["constraints"].update(experience["constraints"])
                target["version"] = int(target.get("version", 1)) + 1
                affected_id = target["experience_id"]
            else:
                operation = "ADD"
                self.experiences.append(copy.deepcopy(experience))
                affected_id = experience["experience_id"]
                parent = experience.get("lineage", {}).get("parent")
                if parent:
                    self.knowledge_edges.append(
                        {"src": f"ibm_baseline_{parent}", "relation": "parent_of", "dst": affected_id}
                    )
                for role in experience["roles"]:
                    self.knowledge_edges.append(
                        {"src": affected_id, "relation": "requires_role", "dst": role}
                    )
                certificate_node = f"certificate::{experience['experience_hash'][:12]}"
                self.knowledge_edges.append(
                    {"src": affected_id, "relation": "validated_by", "dst": certificate_node}
                )

        self.version += 1
        event = {
            "library_version": self.version,
            "operation": operation,
            "experience_id": affected_id,
            "replay": copy.deepcopy(replay),
        }
        event["event_hash"] = stable_hash(event)
        self.history.append(event)
        return event

    def prune(self, experience_id: str, reason: str) -> dict[str, Any]:
        target = next(item for item in self.experiences if item["experience_id"] == experience_id)
        target["status"] = "pruned"
        self.version += 1
        event = {
            "library_version": self.version,
            "operation": "PRUNE",
            "experience_id": experience_id,
            "reason": reason,
        }
        event["event_hash"] = stable_hash(event)
        self.history.append(event)
        return event

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema_version": "ccem.detector_library/v0.2",
            "library_version": self.version,
            "experiences": self.experiences,
            "knowledge_graph": {
                "design": "G_t_transaction_facts_separate_from_K_t_experiences",
                "edges": self.knowledge_edges,
            },
            "history": self.history,
        }
        body["library_hash"] = stable_hash(body)
        return body

    def save(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_dict())
