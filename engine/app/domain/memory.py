"""Memory — the durable record of one interaction the being lived through.

Where an InteractionEvent is the raw *fact* the learning loop derives training
data from, a Memory is what the being *keeps*: a single, self-contained trace of
one meaningful interaction, kept so later learning (replay, curiosity, trait
drift) can attend to it. It carries the object as the being PERCEIVED it (its
perceived properties, never the developer's private label — ADR 0002), the
action taken, what was expected vs. observed, the emotion before and after, the
prediction error the moment carried (when a predictor was watching), the tick it
happened on, and a `priority`.

`priority` is the memory's SALIENCE — a config-driven score (see
`MemoryPriorityPolicy`) of how strongly later learning should attend to this
memory. Surprise (a large prediction error) and emotional intensity raise it, so
the moments the being was most wrong or most affected are the ones it holds onto
hardest. It keys on `event_id` (``being:tick``), so a memory is always traceable
to the interaction_event it was formed from.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class Memory:
    being_id: str
    tick: int
    object_id: str
    action: str
    perceived_properties: Tuple[str, ...] = ()
    expected_outcome: Tuple[str, ...] = ()
    observed_outcome: Tuple[str, ...] = ()
    emotion_before: str = ""
    emotion_after: str = ""
    prediction_error: float = 0.0
    priority: float = 0.0

    @property
    def event_id(self) -> str:
        """The interaction_event this memory was formed from (``being:tick``) —
        the being acts at most once per tick, so this names it uniquely."""
        return f"{self.being_id}:{self.tick}"

    def snapshot(self) -> Dict:
        """A plain, serializable view with stable camelCase keys, ready for the
        wire and the `memories` table. `perceivedProperties` is the object as the
        being saw it — there is deliberately no `developerLabel` key (ADR 0002)."""
        return {
            "beingId": self.being_id,
            "tick": self.tick,
            "objectId": self.object_id,
            "action": self.action,
            "perceivedProperties": list(self.perceived_properties),
            "expectedOutcome": list(self.expected_outcome),
            "observedOutcome": list(self.observed_outcome),
            "emotionBefore": self.emotion_before,
            "emotionAfter": self.emotion_after,
            "predictionError": self.prediction_error,
            "priority": self.priority,
        }
