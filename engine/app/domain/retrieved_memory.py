"""RetrievedMemory — a remembered interaction paired with how relevant it is now.

When the being is about to act it recalls the memories that bear on what it now
perceives (`MemoryRetrievalService`). Each recalled memory is wrapped here with a
`relevance` in ``[0, ∞)``: how strongly this past experience should weigh on the
present decision, given how alike the remembered object is to the one now
perceived, whether it was the *same* action, and how salient (emotional /
surprising) the memory was. A relevance of 0.0 means "recalled but bears nothing
on this choice"; larger means "this is the experience the being should heed".

This is the value object that crosses from `MemoryRetrievalService` (which finds
and scores the memories) to `PreferenceService` (which turns them into a learned
like/dislike). It carries the `Memory` itself unchanged, so the consumer still
reads the object as PERCEIVED, the observed outcome, and the emotion (ADR 0002).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.memory import Memory


@dataclass(frozen=True)
class RetrievedMemory:
    memory: Memory
    relevance: float
