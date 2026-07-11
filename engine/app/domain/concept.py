"""Concept schema — the being's learned generalization about a kind of object.

A ConceptSchema is one line of the being's understanding of the world: "an
object I perceive as `round`, when I `push` it, `rolls`." It keys on a single
PERCEIVED property (the `feature`), the action taken, and the outcome observed —
never on the developer's private label (ADR 0002); the being generalizes from
what it senses, not from an English name it cannot see. Its `confidence` is how
strongly the being holds the generalization; it rises the more the concept is
confirmed (see `ConceptLearningPolicy`), and `evidence_count` is how many
interactions have fed it. Two concepts that key on different features (a `round`
one and a `heavy` one) are distinct and coexist — learning that heavy things
resist a push never erases the belief that round things roll.

A ConceptEvidence is one interaction's contribution to a concept: the append-only
trace linking the concept to the `interaction_event` (`being:tick`) it was
reinforced by, so a concept is always reconcilable to the experiences behind it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ConceptSchema:
    being_id: str
    feature: str
    action: str
    outcome: str
    confidence: float = 0.0
    evidence_count: int = 0

    @property
    def concept_id(self) -> str:
        """Stable identity: one concept per being per (feature, action, outcome).
        Keyed on the perceived feature, so the id never carries a developer label."""
        return f"{self.being_id}|{self.feature}|{self.action}|{self.outcome}"

    @property
    def name(self) -> str:
        """A human-readable name derived purely from the perceived feature and the
        outcome (e.g. ``round_objects_rolls``) — for logs and the wire, never a
        key the being reasons over."""
        return f"{self.feature}_objects_{self.outcome}"

    def snapshot(self) -> Dict:
        """A plain, serializable view with stable camelCase keys. `feature` is a
        perceived property token — there is deliberately no `developerLabel`."""
        return {
            "conceptId": self.concept_id,
            "beingId": self.being_id,
            "feature": self.feature,
            "action": self.action,
            "outcome": self.outcome,
            "name": self.name,
            "confidence": self.confidence,
            "evidenceCount": self.evidence_count,
        }


@dataclass(frozen=True)
class ConceptEvidence:
    being_id: str
    tick: int
    concept_id: str
    event_id: str
    feature: str
    action: str
    outcome: str

    def snapshot(self) -> Dict:
        return {
            "beingId": self.being_id,
            "tick": self.tick,
            "conceptId": self.concept_id,
            "eventId": self.event_id,
            "feature": self.feature,
            "action": self.action,
            "outcome": self.outcome,
        }
