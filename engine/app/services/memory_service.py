"""MemoryService — forms the being's durable memory of one interaction (card v1).

For each meaningful interaction the being has, this turns the InteractionEvent
(and, when a predictor was watching, the shadow-mode PredictionRecord) into one
`Memory`: the object as the being PERCEIVED it, the action, expected vs. observed
outcome, emotion before/after, the prediction error, and a config-driven
`priority` (salience). It stages the memory through the repository port — the
Simulation calls it inside the interaction's unit of work, so the memory commits
atomically with the event it was formed from (ADR 0017). It never reads the
memory back into the being's decision; forming a memory is a side effect of
living, not an input to this tick.

How salient a memory is — how strongly later learning attends to it — is the
`MemoryPriorityPolicy`'s call, config-driven from `learning_rates.yaml`; this
service just asks the policy and records the answer. The object snapshot is
always the being's *perceived* properties, never the developer's private label
(ADR 0002)."""
from __future__ import annotations

from typing import Optional, Sequence

from app.domain.interaction_event import InteractionEvent
from app.domain.memory import Memory
from app.domain.prediction_record import PredictionRecord
from app.policies import MemoryPriorityPolicy
from app.ports.repositories import MemoryRepository


class MemoryService:
    def __init__(self, repository: MemoryRepository, priority: MemoryPriorityPolicy):
        self._repository = repository
        self._priority = priority

    def remember(
        self,
        event: InteractionEvent,
        *,
        perceived_properties: Sequence[str],
        prediction: Optional[PredictionRecord] = None,
    ) -> Memory:
        """Form and store one memory of ``event``. ``perceived_properties`` is the
        object as the being saw it (the memory keys on perception, never the
        developer label). ``prediction`` supplies the prediction error when a
        predictor was watching; absent, the error is 0.0. Returns the stored
        memory, with its config-driven priority already scored."""
        prediction_error = prediction.prediction_error if prediction is not None else 0.0
        priority = self._priority.priority_for(
            prediction_error=prediction_error,
            emotion_before=event.emotion_before,
            emotion_after=event.emotion_after,
        )
        memory = Memory(
            being_id=event.being_id,
            tick=event.tick,
            object_id=event.object_id,
            action=event.action,
            perceived_properties=tuple(perceived_properties),
            expected_outcome=tuple(event.expected_outcome),
            observed_outcome=tuple(event.observed_outcome),
            emotion_before=event.emotion_before,
            emotion_after=event.emotion_after,
            prediction_error=prediction_error,
            priority=priority,
        )
        self._repository.add(memory)
        return memory
