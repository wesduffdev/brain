"""Object similarity — how alike two objects are by their PERCEIVED properties.

An ObjectSimilarityRecord captures, at one tick, how similar the being finds one
object to another purely from the properties it perceives of each (ADR 0002) —
never from a developer label. Similarity is what lets generalization reach past
an exact-property match: two objects that share most of what the being can sense
are treated as near-kin, so what it learned about one informs its expectations of
the other. The `similarity` is in ``[0, 1]`` (identical perceived profiles = 1).

These are append-only records the being lays down as it perceives its world; the
signal they carry is consumed by later slices (curiosity toward the novel,
generalization across kin).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ObjectSimilarityRecord:
    being_id: str
    tick: int
    object_id: str
    other_object_id: str
    similarity: float

    def snapshot(self) -> Dict:
        return {
            "beingId": self.being_id,
            "tick": self.tick,
            "objectId": self.object_id,
            "otherObjectId": self.other_object_id,
            "similarity": self.similarity,
        }
