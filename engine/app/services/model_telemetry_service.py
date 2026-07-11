"""ModelTelemetryService — the READ-ONLY observability observer of the instinct
chain (EVT-VALID; realizes the v14 observability slot under ADR 0024 — no new ADR).

The instinct path is a fire-and-forget chain of `being.*` events: a perception
`ObjectApproached` causes an `InstinctPredictionMade`, which causes an
`InstinctReactionTriggered`/`Suppressed`. Once it is trusted to run over a broker,
the wave needs to be able to *see* it: whether the model's predictions are being
accepted or suppressed, and whether a consumer is keeping up. This service is that
window, and nothing more.

It subscribes — as a pure consumer — to the three chain topics, and produces three
observability outputs, none of which can bend the being's behaviour:

- **A `being.model.telemetry` stream.** Each prediction is buffered by its
  correlation id; when the matching reaction arrives, one telemetry record is
  published pairing the model's prediction (the selected reaction's probability
  and intensity) with the OBSERVED outcome — ``accepted`` when the reaction fired,
  ``suppressed`` when the selection held it back. The record rides the SAME
  correlation chain, so a prediction-vs-outcome row is traceable to the stimulus
  that produced it.
- **A consumer-lag gauge.** ``lag()`` is how many predictions are still waiting for
  their reaction (the un-paired buffer) — a simple, transport-agnostic "how far
  behind is the observer" reading that settles to zero once the chain drains.
- **A correlation trace.** Every observed hop logs one structured line
  (``being.telemetry.trace``) carrying the event's ``correlation_id`` /
  ``causation_id`` / type, so the whole `root -> prediction -> reaction` chain can
  be followed by correlation id in the logs.

READ-ONLY is the invariant (EVT-VALID guardrail): the only thing this service ever
writes back to the bus is the telemetry topic. It calls nothing on the decision,
emotion, or instinct-SELECTION path, so a telemetry record can no more shape
behaviour than a shadow prediction can — telemetry is observed, never fed back.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from app.domain.event import DomainEvent
from app.ports.events import EventConsumer, EventPublisher
from app.services.instinct_service import (
    INSTINCT_PREDICTIONS_TOPIC,
    INSTINCT_REACTIONS_TOPIC,
    PERCEPTION_TOPIC,
    PREDICTION_MADE,
    REACTION_SUPPRESSED,
    REACTION_TRIGGERED,
)

# The observability stream this service produces (EVT-KAFKA catalogue, ADR 0024:
# `being.model.telemetry`) and the event type it carries. `being.*` throughout.
TELEMETRY_TOPIC = "being.model.telemetry"
TELEMETRY_RECORDED = "being.model.telemetry_recorded"

_SOURCE_SERVICE = "model-telemetry-service"
# The correlation trace logger — one structured line per observed hop.
_TRACE = logging.getLogger("being.telemetry.trace")


class ModelTelemetryService:
    def __init__(
        self,
        *,
        consumer: EventConsumer,
        publisher: EventPublisher,
        being_id: str,
        perception_topic: str = PERCEPTION_TOPIC,
        predictions_topic: str = INSTINCT_PREDICTIONS_TOPIC,
        reactions_topic: str = INSTINCT_REACTIONS_TOPIC,
    ) -> None:
        self._publisher = publisher
        self._being_id = being_id
        # Predictions awaiting their reaction, keyed by the root correlation id. The
        # buffer size IS the consumer-lag gauge; it empties as reactions arrive.
        self._pending: Dict[str, DomainEvent] = {}
        self._emitted = 0
        consumer.subscribe(perception_topic, self._on_perception)
        consumer.subscribe(predictions_topic, self._on_prediction)
        consumer.subscribe(reactions_topic, self._on_reaction)

    # --- surfaced metrics -------------------------------------------------

    def lag(self) -> int:
        """The consumer-lag gauge: predictions seen but not yet paired with their
        reaction. Zero once the chain has drained; positive while the observer is
        behind the prediction stream."""
        return len(self._pending)

    def processed(self) -> int:
        """How many telemetry records have been emitted — one per paired
        prediction/outcome."""
        return self._emitted

    # --- read-only intake: trace every hop, pair prediction with outcome --

    def _on_perception(self, event: DomainEvent) -> None:
        self._trace(event)

    def _on_prediction(self, event: DomainEvent) -> None:
        self._trace(event)
        if event.event_type == PREDICTION_MADE:
            self._pending[event.correlation_id] = event

    def _on_reaction(self, event: DomainEvent) -> None:
        self._trace(event)
        if event.event_type not in (REACTION_TRIGGERED, REACTION_SUPPRESSED):
            return
        prediction = self._pending.pop(event.correlation_id, None)
        if prediction is None:
            return  # a reaction with no buffered prediction — nothing to pair
        self._emit(prediction, event)

    # --- the telemetry record: prediction vs. observed outcome ------------

    def _emit(self, prediction: DomainEvent, reaction: DomainEvent) -> None:
        """Publish one `being.model.telemetry` record pairing the prediction with
        the reaction's observed outcome, on the reaction's correlation chain."""
        label = reaction.payload.get("reaction")
        probabilities = prediction.payload.get("reactions", {}) or {}
        triggered = bool(reaction.payload.get("triggered", False))
        record = reaction.causes(
            event_type=TELEMETRY_RECORDED,
            source_service=_SOURCE_SERVICE,
            payload={
                "objectId": reaction.payload.get("objectId"),
                "tick": reaction.payload.get("tick"),
                "reaction": label,
                "probability": float(probabilities.get(label, 0.0)),
                "intensity": float(reaction.payload.get("intensity", 0.0)),
                # ACCEPTED when the reaction fired, SUPPRESSED when selection held it
                # back — the model's prediction judged against what the being did.
                "outcome": "accepted" if triggered else "suppressed",
            },
        )
        self._publisher.publish(TELEMETRY_TOPIC, record)
        self._emitted += 1

    @staticmethod
    def _trace(event: DomainEvent) -> None:
        """Log one structured correlation-trace line for an observed hop."""
        _TRACE.info(
            "event %s from %s",
            event.event_type,
            event.source_service,
            extra={
                "correlation_id": event.correlation_id,
                "causation_id": event.causation_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "source_service": event.source_service,
            },
        )
