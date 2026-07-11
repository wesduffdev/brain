"""ConceptPathService — walks the concept graph along a template of edge kinds.

Where the KnowledgeGraphService writes the graph, this service reads it: given an
ordered TEMPLATE of edge kinds (e.g. ``HAS_PROPERTY`` then ``PREDICTS``), it finds
every walk through the graph whose consecutive edges match that template — the
``object → property → outcome`` walk that connects a thing to what the being
expects of it. A walk can be pinned to a start node, an end node, or left open at
either end, so the one traversal serves both "explain this specific prediction"
and "every prediction the graph supports".

It is pure graph traversal over the GraphRepository: it builds an adjacency of the
being's edges by kind and source, then extends a frontier of partial walks one
template step at a time. Each result is a `ConceptPath` carrying the nodes it
passed and the edges it crossed, whose aggregate confidence is the weakest edge
along it. The service holds no state; the KnowledgeGraphService's writes are its
only input.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from app.domain.concept_graph import ConceptPath, GraphEdge, GraphNode
from app.ports.repositories import GraphRepository


class ConceptPathService:
    def __init__(self, repository: GraphRepository):
        self._repository = repository

    def paths(
        self,
        *,
        being_id: str,
        via_kinds: Sequence[str],
        source_kind: Optional[str] = None,
        source_label: Optional[str] = None,
        target_kind: Optional[str] = None,
        target_label: Optional[str] = None,
    ) -> List[ConceptPath]:
        """Every walk through `being_id`'s graph whose consecutive edges match
        `via_kinds` in order, optionally pinned to a start node (`source_kind`
        and/or `source_label`) and/or an end node (`target_kind`/`target_label`).
        An empty `via_kinds` yields no walks. Each `ConceptPath` carries the nodes
        it passed and the edges it crossed."""
        if not via_kinds:
            return []

        nodes = {node.node_id: node for node in self._repository.nodes() if node.being_id == being_id}
        adjacency = _adjacency(
            edge for edge in self._repository.edges() if edge.being_id == being_id
        )

        # Seed the frontier from the first template kind, honoring the source pin.
        frontier: List[Tuple[Tuple[GraphNode, ...], Tuple[GraphEdge, ...]]] = []
        for edge in _edges_of(adjacency, via_kinds[0]):
            source_node = nodes.get(edge.source_id)
            target_node = nodes.get(edge.target_id)
            if source_node is None or target_node is None:
                continue
            if not _matches(source_node, source_kind, source_label):
                continue
            frontier.append(((source_node, target_node), (edge,)))

        # Extend one template kind at a time from each partial walk's last node.
        for kind in via_kinds[1:]:
            extended: List[Tuple[Tuple[GraphNode, ...], Tuple[GraphEdge, ...]]] = []
            for walked_nodes, walked_edges in frontier:
                for edge in adjacency.get(kind, {}).get(walked_nodes[-1].node_id, []):
                    next_node = nodes.get(edge.target_id)
                    if next_node is None:
                        continue
                    extended.append((walked_nodes + (next_node,), walked_edges + (edge,)))
            frontier = extended

        results: List[ConceptPath] = []
        for walked_nodes, walked_edges in frontier:
            if not _matches(walked_nodes[-1], target_kind, target_label):
                continue
            results.append(
                ConceptPath(being_id=being_id, nodes=walked_nodes, edges=walked_edges)
            )
        return results


def _adjacency(edges) -> Dict[str, Dict[str, List[GraphEdge]]]:
    """Edges indexed by kind, then by source node id — the traversal's fan-out."""
    by_kind: Dict[str, Dict[str, List[GraphEdge]]] = defaultdict(lambda: defaultdict(list))
    for edge in edges:
        by_kind[edge.kind][edge.source_id].append(edge)
    return by_kind


def _edges_of(adjacency: Dict[str, Dict[str, List[GraphEdge]]], kind: str) -> List[GraphEdge]:
    """Every edge of `kind`, flattened across its source nodes."""
    return [edge for edges in adjacency.get(kind, {}).values() for edge in edges]


def _matches(node: GraphNode, kind: Optional[str], label: Optional[str]) -> bool:
    """Whether `node` satisfies an optional kind pin and an optional label pin.
    An unset pin matches anything."""
    return (kind is None or node.kind == kind) and (label is None or node.label == label)
