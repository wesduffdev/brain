"""ConceptService — turns lived interactions into learned CONCEPT SCHEMAS.

Each meaningful interaction the being has is a small lesson: it perceived an
object as having certain properties, took an action, and observed certain
outcomes. This service distils those lessons into generalizations keyed on a
single PERCEIVED property (never a developer label — ADR 0002): pushing a `round`
thing `rolls`; pushing a `heavy` thing `makes_noise`. For every (perceived
property x observed outcome) pair of an interaction it strengthens the matching
concept — nudging its confidence toward certainty by the config-driven
`ConceptLearningPolicy` — and records one piece of append-only evidence linking
the concept to the interaction_event behind it.

Concepts for different perceived features are distinct and coexist: learning that
heavy things resist a push forms its own concept and never erases the belief that
round things roll. The service stages its writes through the ConceptRepository —
the Simulation calls it inside the interaction's unit of work, so a concept
strengthens atomically with the event it learned from (ADR 0017). Like memory,
forming a concept is a side effect of living, not an input to this tick's
decision. `concepts_for` reads the concepts a set of perceived properties + an
action bear on — the surface the BeliefService predicts from.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Sequence

from app.domain.concept import ConceptEvidence, ConceptSchema
from app.policies import ConceptLearningPolicy
from app.ports.repositories import ConceptRepository


def _ordered_unique(items: Sequence[str]) -> List[str]:
    """`items` de-duplicated, order preserved — so a property or outcome that
    appears twice in one interaction reinforces its concept only once."""
    seen: set = set()
    unique: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


class ConceptService:
    def __init__(self, repository: ConceptRepository, policy: ConceptLearningPolicy):
        self._repository = repository
        self._policy = policy

    def observe(
        self,
        *,
        being_id: str,
        tick: int,
        object_id: str,
        action: str,
        perceived_properties: Sequence[str],
        observed_outcomes: Sequence[str],
    ) -> List[ConceptSchema]:
        """Learn from one interaction: for each (perceived property x observed
        outcome), strengthen the matching concept and record its evidence. Returns
        the concepts this interaction formed or reinforced (empty when the action
        produced no outcome)."""
        event_id = f"{being_id}:{tick}"
        touched: List[ConceptSchema] = []
        for feature in _ordered_unique(perceived_properties):
            for outcome in _ordered_unique(observed_outcomes):
                probe = ConceptSchema(
                    being_id=being_id, feature=feature, action=action, outcome=outcome
                )
                existing = self._repository.get(probe.concept_id)
                concept = replace(
                    probe,
                    confidence=self._policy.reinforce(
                        existing.confidence if existing is not None else None
                    ),
                    evidence_count=(existing.evidence_count if existing is not None else 0) + 1,
                )
                self._repository.save(concept)
                self._repository.add_evidence(
                    ConceptEvidence(
                        being_id=being_id,
                        tick=tick,
                        concept_id=concept.concept_id,
                        event_id=event_id,
                        feature=feature,
                        action=action,
                        outcome=outcome,
                    )
                )
                touched.append(concept)
        return touched

    def concepts_for(
        self, *, being_id: str, perceived_properties: Sequence[str], action: str
    ) -> List[ConceptSchema]:
        """The being's concepts that bear on an object perceived to have
        `perceived_properties`, for `action` — every concept whose feature the
        object shows. This is what a never-seen object's expectations are built
        from."""
        features = set(perceived_properties)
        return [
            concept
            for concept in self._repository.all()
            if concept.being_id == being_id
            and concept.action == action
            and concept.feature in features
        ]
