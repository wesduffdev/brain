"""KnowledgeGraphService — projects the being's learning into a concept graph.

Each interaction the being lives leaves it with concepts, an object it perceived,
outcomes it observed, and a sense of which other objects were alike. This service
projects those into the CONCEPT GRAPH (card v7): it upserts the object / property
/ outcome NODES and lays down the typed EDGES between them —

- ``HAS_PROPERTY`` (object → each perceived property),
- ``PREDICTS`` (each concept's property → its outcome — the concept relationship
  in graph form, read from the concepts the interaction formed),
- ``PRODUCED`` (object → each observed outcome),
- ``SIMILAR_TO`` (object → each peer the being found alike).

An edge is *reinforced* in place, not appended: the service reads the edge's
current confidence, nudges it toward certainty by the config-driven
`GraphEdgePolicy`, increments its evidence count, stamps the tick, and merges in
the `source_memory_ids` of this interaction — so the more evidence an edge
accrues, the more confident it grows, and it stays reconcilable to the memories
(``being:tick``) that formed it (card v1). The service stages its writes through
the GraphRepository; the Simulation calls it inside the interaction's unit of
work, so the graph updates atomically with the event it learned from (ADR 0017).
Like memory and concepts, growing the graph is a side effect of living — never an
input to this tick's decision.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, List, Sequence

from app.domain.concept import ConceptSchema
from app.domain.concept_graph import (
    HAS_PROPERTY,
    OBJECT,
    OUTCOME,
    PREDICTS,
    PRODUCED,
    PROPERTY,
    SIMILAR_TO,
    GraphEdge,
    GraphNode,
)
from app.domain.similarity import ObjectSimilarityRecord
from app.policies import GraphEdgePolicy
from app.ports.repositories import GraphRepository


def _ordered_unique(items: Sequence[str]) -> List[str]:
    """`items` de-duplicated, order preserved — so a property or outcome that
    appears twice in one interaction reinforces its edge only once."""
    seen: set = set()
    unique: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


class KnowledgeGraphService:
    def __init__(self, repository: GraphRepository, policy: GraphEdgePolicy):
        self._repository = repository
        self._policy = policy

    def witness(
        self,
        *,
        being_id: str,
        tick: int,
        object_id: str,
        perceived_properties: Sequence[str],
        observed_outcomes: Sequence[str],
        concepts: Sequence[ConceptSchema],
        similarities: Sequence[ObjectSimilarityRecord],
        source_memory_ids: Sequence[str],
    ) -> None:
        """Project one interaction into the graph: upsert the object/property/
        outcome nodes and reinforce the HAS_PROPERTY, PREDICTS, PRODUCED, and
        SIMILAR_TO edges it evidences, each strengthened and linked back to the
        interaction's source memories."""
        object_node = self._save_node(being_id, OBJECT, object_id)

        for prop in _ordered_unique(perceived_properties):
            property_node = self._save_node(being_id, PROPERTY, prop)
            self._reinforce(being_id, HAS_PROPERTY, object_node, property_node, tick, source_memory_ids)

        for outcome in _ordered_unique(observed_outcomes):
            outcome_node = self._save_node(being_id, OUTCOME, outcome)
            self._reinforce(being_id, PRODUCED, object_node, outcome_node, tick, source_memory_ids)

        # PREDICTS edges are the concept relationships in graph form: a concept
        # keyed on (feature, outcome) becomes a property -> outcome edge.
        for concept in concepts:
            property_node = self._save_node(being_id, PROPERTY, concept.feature)
            outcome_node = self._save_node(being_id, OUTCOME, concept.outcome)
            self._reinforce(being_id, PREDICTS, property_node, outcome_node, tick, source_memory_ids)

        for record in similarities:
            peer_node = self._save_node(being_id, OBJECT, record.other_object_id)
            self._reinforce(being_id, SIMILAR_TO, object_node, peer_node, tick, source_memory_ids)

    def _save_node(self, being_id: str, kind: str, label: str) -> GraphNode:
        node = GraphNode(being_id=being_id, kind=kind, label=label)
        self._repository.save_node(node)
        return node

    def _reinforce(
        self,
        being_id: str,
        kind: str,
        source: GraphNode,
        target: GraphNode,
        tick: int,
        source_memory_ids: Iterable[str],
    ) -> GraphEdge:
        """Strengthen (or first lay down) the edge of `kind` from `source` to
        `target`: nudge its confidence toward certainty, add one to its evidence
        count, stamp the tick, and merge in this interaction's source memories."""
        probe = GraphEdge(
            being_id=being_id, kind=kind, source_id=source.node_id, target_id=target.node_id
        )
        existing = self._repository.get_edge(probe.edge_id)
        edge = replace(
            probe,
            confidence=self._policy.reinforce(
                existing.confidence if existing is not None else None
            ),
            evidence_count=(existing.evidence_count if existing is not None else 0) + 1,
            last_updated_tick=tick,
            source_memory_ids=_merge_memory_ids(
                existing.source_memory_ids if existing is not None else (), source_memory_ids
            ),
        )
        self._repository.save_edge(edge)
        return edge


def _merge_memory_ids(existing: Sequence[str], new: Iterable[str]) -> tuple:
    """The existing source-memory ids plus any new ones, de-duplicated and
    order-preserved — so an edge accumulates the distinct interactions behind it
    without repeating one it has already recorded."""
    return tuple(_ordered_unique([*existing, *new]))
