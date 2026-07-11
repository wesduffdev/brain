"""SimilarityService — how alike two objects are by their PERCEIVED properties.

Similarity is the Jaccard overlap of two objects' perceived-property sets: the
share of all the properties involved that both objects show (1.0 when the being
perceives them identically, 0.0 when they share nothing). It rests on perception
alone (ADR 0002) — never a developer label. As the being perceives its world it
records how similar the object it is acting on is to the others around it; the
signal is what lets later slices reach past an exact-property match (curiosity
toward the novel, generalization across near-kin).

The service stages its records through the SimilarityRepository — the Simulation
calls it inside the interaction's unit of work (ADR 0017).
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from app.domain.similarity import ObjectSimilarityRecord
from app.ports.repositories import SimilarityRepository


class SimilarityService:
    def __init__(self, repository: SimilarityRepository):
        self._repository = repository

    def similarity(self, properties_a: Sequence[str], properties_b: Sequence[str]) -> float:
        """The Jaccard similarity of two perceived-property sets, in ``[0, 1]``:
        the size of their intersection over the size of their union. Two objects
        with no shared perceived property score 0.0; identical profiles score 1.0.
        Two empty profiles are treated as unrelated (0.0)."""
        set_a, set_b = set(properties_a), set(properties_b)
        union = set_a | set_b
        if not union:
            return 0.0
        return len(set_a & set_b) / len(union)

    def record(
        self,
        *,
        being_id: str,
        tick: int,
        object_id: str,
        perceived_properties: Sequence[str],
        peers: Iterable[Tuple[str, Sequence[str]]],
    ) -> List[ObjectSimilarityRecord]:
        """Record how similar the object the being is acting on is to each `peer`
        (``(other_object_id, its_perceived_properties)``) it perceives. Returns the
        records laid down (empty when the object is alone)."""
        records: List[ObjectSimilarityRecord] = []
        for other_object_id, other_properties in peers:
            record = ObjectSimilarityRecord(
                being_id=being_id,
                tick=tick,
                object_id=object_id,
                other_object_id=other_object_id,
                similarity=self.similarity(perceived_properties, other_properties),
            )
            self._repository.add(record)
            records.append(record)
        return records
