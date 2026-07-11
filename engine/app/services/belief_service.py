"""BeliefService — turns concepts into per-object expectations.

A concept is a general rule; a Belief is that rule applied to one object the
being perceives. Given an object's PERCEIVED properties and an action, this
service asks the ConceptService which concepts bear on it and forms a prediction
for each outcome those concepts foresee, carrying the concept's confidence. So a
never-seen object inherits an expectation purely from what it looks like — a
round object is expected to roll before the being has ever pushed *it*, because
it has pushed other round things.

When more than one perceived feature predicts the same outcome, the strongest
(highest-confidence) concept wins — the being goes with what it is surest of.
Each belief is staged through the BeliefRepository; the Simulation calls this
inside the interaction's unit of work, so a belief persists atomically with the
interaction that prompted it (ADR 0017).
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from app.domain.belief import Belief
from app.ports.repositories import BeliefRepository
from app.services.concept_service import ConceptService


class BeliefService:
    def __init__(self, concepts: ConceptService, repository: BeliefRepository):
        self._concepts = concepts
        self._repository = repository

    def anticipated(
        self, *, being_id: str, perceived_properties: Sequence[str], action: str
    ) -> Dict[str, float]:
        """What the being currently EXPECTS `action` on an object with these
        perceived properties to produce — a map ``outcome -> confidence``, each at
        the strongest supporting concept's confidence (the being goes with what it
        is surest of). READ-ONLY: it forms no persistent belief, so the decision can
        consult the being's expectation every tick without polluting the belief log
        — `believe` is the write path, and reads this same expectation. Empty when
        no concept bears on the object."""
        strongest: Dict[str, float] = {}
        for concept in self._concepts.concepts_for(
            being_id=being_id, perceived_properties=perceived_properties, action=action
        ):
            if concept.confidence > strongest.get(concept.outcome, -1.0):
                strongest[concept.outcome] = concept.confidence
        return strongest

    def believe(
        self,
        *,
        being_id: str,
        tick: int,
        object_id: str,
        perceived_properties: Sequence[str],
        action: str,
    ) -> List[Belief]:
        """Form the being's beliefs about what `action` on `object_id` will do,
        inherited from the concepts its `perceived_properties` bear on. One belief
        per predicted outcome, each at the strongest supporting concept's
        confidence. Returns the beliefs formed (empty when no concept applies)."""
        beliefs: List[Belief] = []
        for outcome, confidence in self.anticipated(
            being_id=being_id, perceived_properties=perceived_properties, action=action
        ).items():
            belief = Belief(
                being_id=being_id,
                tick=tick,
                object_id=object_id,
                action=action,
                outcome=outcome,
                confidence=confidence,
            )
            self._repository.add(belief)
            beliefs.append(belief)
        return beliefs
