"""PreferenceService — the being's learned like/dislike, from what it remembers.

Retrieval says *which* memories bear on the present choice; this turns them into a
PREFERENCE: a signed bias on an action toward an object. Each recalled memory
contributes its relevance times the VALENCE of what it observed — the felt-
consequence net effect (`OutcomeEffectPolicy.net_effect`): a remembered burn
(safety and comfort fell) is negative, something remembered as pleasant is
positive. Summed over the recalled memories and scaled by the config
`PreferencePolicy.weight`, that is the score bias the decision adds to a *safe*
candidate — so a prior negative memory of a similar object lowers a risky action's
score (the hot-lamp generalization), and a fond memory raises an appealing one.

`biases(...)` produces the whole per-(object, action) bias map the decision
consumes in one call, over the objects the being perceives and the actions it might
take. With `weight` at its 0.0 default the map is all zeros — the being forms and
stores memories exactly as before but decides on pure utility (the pre-v6
baseline); only a config that opts in turns the learned preference on.

It holds a `MemoryRetrievalService` as a real collaborator below the seam (like
`BeliefService` over `ConceptService`, ADR 0019); nothing here reads YAML.
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Sequence, Tuple

from app.domain.memory import Memory
from app.policies import OutcomeEffectPolicy, PreferencePolicy
from app.services.memory_retrieval_service import MemoryRetrievalService


class PreferenceService:
    def __init__(
        self,
        retrieval: MemoryRetrievalService,
        outcome_effects: OutcomeEffectPolicy,
        policy: PreferencePolicy,
    ):
        self._retrieval = retrieval
        self._outcome_effects = outcome_effects
        self._policy = policy

    def valence(
        self,
        *,
        object_id: str,
        perceived_properties: Sequence[str],
        action: str,
        memories: Sequence[Memory],
    ) -> float:
        """The being's learned preference for taking `action` on this object — the
        relevance-weighted sum of how good or bad the recalled memories turned out,
        scaled by the config weight. Negative means "what I remember warns me off
        this"; positive means "what I remember draws me to it"; 0.0 when nothing
        relevant is recalled."""
        total = 0.0
        for recalled in self._retrieval.retrieve(
            object_id=object_id,
            perceived_properties=perceived_properties,
            action=action,
            memories=memories,
        ):
            outcome_valence = self._outcome_effects.net_effect(recalled.memory.observed_outcome)
            total += recalled.relevance * float(outcome_valence)
        return self._policy.bias(total)

    def biases(
        self,
        *,
        perceived: Sequence[Mapping],
        actions: Iterable[str],
        memories: Sequence[Memory],
    ) -> Dict[Tuple[str, str], float]:
        """The learned-preference score bias for every (perceived object, action)
        pair, keyed ``(object_id, action)``. A pair the being remembers nothing
        relevant about is left out (an absent key is a zero bias to the decision)."""
        actions = list(actions)
        result: Dict[Tuple[str, str], float] = {}
        for obj in perceived:
            object_id = obj["objectId"]
            properties = obj.get("properties", [])
            for action in actions:
                bias = self.valence(
                    object_id=object_id,
                    perceived_properties=properties,
                    action=action,
                    memories=memories,
                )
                if bias != 0.0:
                    result[(object_id, action)] = bias
        return result
