"""Belief — the being's prediction about a specific object, drawn from concepts.

Where a `ConceptSchema` is a general rule ("round things roll when pushed"), a
Belief is that rule *applied* to one object the being perceives: "I expect THIS
object, if I push it, to roll — with this confidence." A belief is formed from
the object's PERCEIVED properties alone (ADR 0002), so a never-seen object
inherits an expectation from what it looks like, before the being has ever acted
on it. Its `confidence` is inherited from the concept(s) the prediction rests on.

Beliefs are the observable payoff of concept learning: they are what let the
being anticipate. They are append-only records (one per prediction), traceable to
the tick they were formed on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Belief:
    being_id: str
    tick: int
    object_id: str
    action: str
    outcome: str
    confidence: float = 0.0

    def snapshot(self) -> Dict:
        return {
            "beingId": self.being_id,
            "tick": self.tick,
            "objectId": self.object_id,
            "action": self.action,
            "outcome": self.outcome,
            "confidence": self.confidence,
        }
