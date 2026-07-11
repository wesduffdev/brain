"""Concept graph — the being's learned knowledge as a network of nodes and edges.

Where a `ConceptSchema` is one line of the being's understanding and a `Belief`
is that line applied to one object, the CONCEPT GRAPH is the whole understanding
laid out as a graph the being can *walk*: OBJECT, PROPERTY, and OUTCOME nodes
joined by typed EDGES —

- ``HAS_PROPERTY`` (OBJECT → PROPERTY): the being perceives an object to have a
  property (``obj_ball → round``);
- ``PREDICTS`` (PROPERTY → OUTCOME): a property foretells an outcome, the concept
  relationship in graph form (``round → rolls``);
- ``PRODUCED`` (OBJECT → OUTCOME): an object actually produced an outcome the
  being observed (``obj_ball → rolls``);
- ``SIMILAR_TO`` (OBJECT → OBJECT): two objects the being finds alike.

Every EDGE carries a `confidence` that strengthens as evidence accrues, an
`evidence_count`, the `last_updated_tick`, and the `source_memory_ids` linking it
back to the interactions (``being:tick``) that produced it (card v1). Nodes and
edges are keyed on PERCEIVED tokens (property/outcome labels, perception-scoped
object ids) — never a developer label (ADR 0002).

The payoff is the EXPLANATION PATH: a prediction the being makes about an object
comes with the ``object → property → outcome`` walk through the graph that
justifies it. A `ConceptPath` is a raw graph walk (its nodes + the edges between
them); an `ExplanationPath` is that walk turned toward a prediction — the object,
the mediating property, the predicted outcome, and the path's aggregate
confidence — ready for the wire.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

# Node kinds ------------------------------------------------------------------
OBJECT = "OBJECT"
PROPERTY = "PROPERTY"
OUTCOME = "OUTCOME"

# Edge kinds ------------------------------------------------------------------
HAS_PROPERTY = "HAS_PROPERTY"  # OBJECT   -> PROPERTY
PREDICTS = "PREDICTS"          # PROPERTY -> OUTCOME
PRODUCED = "PRODUCED"          # OBJECT   -> OUTCOME
SIMILAR_TO = "SIMILAR_TO"      # OBJECT   -> OBJECT


@dataclass(frozen=True)
class GraphNode:
    """One node in the concept graph: a `kind` (OBJECT/PROPERTY/OUTCOME) and the
    perceived `label` it stands for. Upserted by `node_id`, so a node the being
    meets again is the same node, not a duplicate."""

    being_id: str
    kind: str
    label: str

    @property
    def node_id(self) -> str:
        """Stable identity: one node per being per (kind, label). Keyed on a
        perceived token, so the id never carries a developer label."""
        return f"{self.being_id}|{self.kind}|{self.label}"

    def snapshot(self) -> Dict:
        return {
            "nodeId": self.node_id,
            "beingId": self.being_id,
            "kind": self.kind,
            "label": self.label,
        }


@dataclass(frozen=True)
class GraphEdge:
    """One typed, directed edge between two nodes. Its `confidence` rises the more
    evidence confirms it (`GraphEdgePolicy`), `evidence_count` counts the
    confirmations, `last_updated_tick` is when it last strengthened, and
    `source_memory_ids` names the interactions (``being:tick``) behind it, so an
    edge is always reconcilable to the lived experiences that formed it. Upserted
    by `edge_id`, so an edge strengthens in place rather than duplicating."""

    being_id: str
    kind: str
    source_id: str  # a GraphNode.node_id
    target_id: str  # a GraphNode.node_id
    confidence: float = 0.0
    evidence_count: int = 0
    last_updated_tick: int = 0
    source_memory_ids: Tuple[str, ...] = ()

    @property
    def edge_id(self) -> str:
        """Stable identity: one edge per being per (kind, source, target)."""
        return f"{self.being_id}|{self.kind}|{self.source_id}|{self.target_id}"

    def snapshot(self) -> Dict:
        return {
            "edgeId": self.edge_id,
            "beingId": self.being_id,
            "kind": self.kind,
            "sourceId": self.source_id,
            "targetId": self.target_id,
            "confidence": self.confidence,
            "evidenceCount": self.evidence_count,
            "lastUpdatedTick": self.last_updated_tick,
            "sourceMemoryIds": list(self.source_memory_ids),
        }


@dataclass(frozen=True)
class ConceptPath:
    """A raw walk through the graph: the ordered nodes it passes and the edges it
    crosses. Its `confidence` is the weakest link along the way (the least
    confident edge), so a chain is only as sure as its shakiest step."""

    being_id: str
    nodes: Tuple[GraphNode, ...]
    edges: Tuple[GraphEdge, ...]

    @property
    def labels(self) -> Tuple[str, ...]:
        """The perceived labels of the nodes along the walk, in order."""
        return tuple(node.label for node in self.nodes)

    @property
    def confidence(self) -> float:
        """The walk's aggregate confidence — the minimum edge confidence along it
        (a chain is only as strong as its weakest link). An edgeless walk is
        certain of nothing (0.0)."""
        if not self.edges:
            return 0.0
        return min(edge.confidence for edge in self.edges)


@dataclass(frozen=True)
class ExplanationPath:
    """A prediction with the graph walk that justifies it: the object, the
    perceived `property` that bridges it to the predicted `outcome`, the ordered
    `path` (``object → property → outcome``), and the walk's aggregate
    `confidence`."""

    being_id: str
    object_id: str
    property: str
    outcome: str
    confidence: float
    path: Tuple[str, ...]

    def snapshot(self) -> Dict:
        return {
            "beingId": self.being_id,
            "objectId": self.object_id,
            "property": self.property,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "path": list(self.path),
        }
