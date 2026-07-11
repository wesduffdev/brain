"""MemoryRetrievalService — recalls the memories that bear on the present choice.

Before the being acts it does not reason from the present alone: it RETRIEVES the
memories relevant to the object it now perceives and the action it is weighing.
Given the object's id, its perceived properties, and a candidate action, this
scores every stored memory for RELEVANCE — how strongly that past experience
should weigh on this decision — and returns the ones that bear on it, each wrapped
as a `RetrievedMemory`.

Relevance (config-driven, `RetrievalPolicy`) fuses the signals the being cares
about: the same object recalls itself; a SIMILAR object recalls it too — the
`SimilarityService` Jaccard overlap of perceived properties (ADR 0019) is what lets
a burn learned from one hot thing be recalled for a *new* hot thing (the hot-lamp
generalization); the same action weighs where a different one does not; and a
high-salience memory (emotional or surprising — its `priority`) is recalled more
strongly. A memory that connects to the present choice by nothing scores 0.0 and is
filtered out.

It reads the memories it is handed — the caller pulls them from the
`MemoryRepository` (the in-memory fake in tests, the Postgres adapter at runtime),
so this service stays a pure recall-and-rank function over whatever store backs the
being. It holds a `SimilarityService` as a real collaborator below the seam; nothing
here reads YAML — the weights arrive as a typed `RetrievalPolicy`.
"""
from __future__ import annotations

from typing import List, Sequence

from app.domain.memory import Memory
from app.domain.retrieved_memory import RetrievedMemory
from app.policies import RetrievalPolicy
from app.services.similarity_service import SimilarityService


class MemoryRetrievalService:
    def __init__(self, similarity: SimilarityService, policy: RetrievalPolicy):
        self._similarity = similarity
        self._policy = policy

    def retrieve(
        self,
        *,
        object_id: str,
        perceived_properties: Sequence[str],
        action: str,
        memories: Sequence[Memory],
    ) -> List[RetrievedMemory]:
        """The memories relevant to taking `action` on the object `object_id`
        perceived as `perceived_properties`, each paired with its relevance, most
        relevant first. Memories that bear nothing on this choice (relevance 0.0) are
        left out, so the caller sees only what the being would actually heed."""
        retrieved: List[RetrievedMemory] = []
        for memory in memories:
            relevance = self._policy.relevance(
                similarity=self._similarity.similarity(
                    perceived_properties, memory.perceived_properties
                ),
                same_object=memory.object_id == object_id,
                same_action=memory.action == action,
                priority=memory.priority,
            )
            if relevance > 0.0:
                retrieved.append(RetrievedMemory(memory=memory, relevance=relevance))
        retrieved.sort(key=lambda rm: rm.relevance, reverse=True)
        return retrieved
