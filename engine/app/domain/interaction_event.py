"""InteractionEvent — the record of one action the being took on one object.

The lasting fact everything learned is later derived from (BRIEF §9): the being
acted on an object, it *expected* some outcomes and *observed* some (both drawn
from the outcome vocabulary in `config/outcome_labels.yaml`), and its dominant
emotion before and after the action. For this slice these events live in memory
only; persisting them to Postgres is a later slice (V0-7).

Expected outcomes come from what the being *perceives* of the object; observed
outcomes from the object's *true* properties — so the two diverge exactly when
perception is imperfect, which is where the learned predictor will earn its keep.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class InteractionEvent:
    being_id: str
    tick: int
    object_id: str
    action: str
    expected_outcome: Tuple[str, ...]
    observed_outcome: Tuple[str, ...]
    emotion_before: str
    emotion_after: str

    def snapshot(self) -> Dict:
        """A plain, serializable view using the stable camelCase keys the brief's
        InteractionEvent uses (BRIEF §9), ready for the wire and, later, the DB."""
        return {
            "beingId": self.being_id,
            "tick": self.tick,
            "objectId": self.object_id,
            "action": self.action,
            "expectedOutcome": list(self.expected_outcome),
            "observedOutcome": list(self.observed_outcome),
            "emotionBefore": self.emotion_before,
            "emotionAfter": self.emotion_after,
        }
