"""InstinctService — the shadow instinct-inference consumer (INS-RT).

This EXTENDS the shadow-mode precedent of ADR 0011 (the outcome predictor's
observational shadow) to the instinct layer of ADR 0026 — there is deliberately
**no new ADR**. It is the integration keystone of the event-instinct wave: it
turns the being's perceived approaches into live protective reactions, observed
but not yet acted on.

The service subscribes as an `EventConsumer` to `being.perception.events`. For
each perception STIMULUS (an object approach, a sudden sound spike, or an object
contact — the frozen 14-feature vector WORLD-MOTION / SENSORY-STIM publish, ADR
0026/0027), it encodes the stimulus (`InstinctFeatureEncoder`), runs
the `InstinctPredictorPort`, selects one protective reaction against the config
`thresholds`/`cooldowns` (or suppresses it), and — in ONE unit of work (ADR
0017) — persists the prediction + reaction (EVT-PERSIST) and STAGES the outgoing
`being.instinct.predictions` / `being.instinct.reactions` events to the outbox.
Publication happens only when the relay drains the outbox (ADR 0028), never
inside the transaction.

Two invariants make the consumer safe on the broker-free bus the suite runs on
(the Kafka adapter provides the same two at the transport layer, so on Kafka this
is belt-and-suspenders):

- **Idempotent** on the source `event_id`: a replayed `ObjectApproached` yields
  exactly one prediction and one reaction.
- **Dead-lettered**: a stimulus the consumer cannot process (a malformed payload,
  a predictor/persistence failure) is routed to the topic's DLQ rather than
  wedging the bus — the failure never propagates back to the publisher.

SHADOW discipline (ADR 0011): this service records and publishes but calls or
mutates NOTHING in the decision / emotion / render path or the being's needs —
it touches no `DecisionService`, `EmotionService`, or renderer, so a learned
instinct score can no more shape behavior than an outcome score can bypass the
safety floor. It runs in shadow only; the active integration (biasing emotion,
interrupting an action through the safety seam) is INS-ACT's, and the service
refuses to construct outside shadow so a misconfiguration cannot silently change
behavior.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Set, Tuple

if TYPE_CHECKING:  # avoid a runtime import cycle — only the duck-typed surface is used
    from app.services.temperament_service import TemperamentService

from app.db.unit_of_work import NullUnitOfWork
from app.domain.event import DomainEvent
from app.domain.instinct import InstinctPrediction, InstinctReaction
from app.domain.outbox import OutboxEntry
from app.ml.instinct_encoder import InstinctFeatureEncoder, Stimulus
from app.policies import InstinctRuntimePolicy
from app.ports.events import EventConsumer, EventPublisher
from app.ports.instinct import InstinctPredictorPort
from app.ports.repositories import (
    InstinctPredictionRepository,
    InstinctReactionRepository,
    OutboxRepository,
    UnitOfWork,
)
from app.services.stimulus_service import (
    OBJECT_APPROACHED,
    OBJECT_CONTACTED,
    PERCEPTION_TOPIC,
    SOUND_SPIKE,
)

# The two topics the instinct layer produces (EVT-KAFKA catalogue, ADR 0024) and
# the event types they carry. `being.*` naming throughout (never `npc.*`).
INSTINCT_PREDICTIONS_TOPIC = "being.instinct.predictions"
INSTINCT_REACTIONS_TOPIC = "being.instinct.reactions"
PREDICTION_MADE = "being.instinct.prediction_made"
REACTION_TRIGGERED = "being.instinct.reaction_triggered"
REACTION_SUPPRESSED = "being.instinct.reaction_suppressed"

_SOURCE_SERVICE = "instinct-service"
# The explicit "no protective reaction" label — recorded suppressed when no
# reaction label is even a candidate (never fires).
_NO_REACTION = "ignore"

# The perception stimuli that drive instinct — an object APPROACH (WORLD-MOTION),
# a sudden SOUND SPIKE, or an object CONTACT (SENSORY-STIM). All three carry the
# same frozen 14-feature payload, so the consumer handles them identically;
# anything else on the topic is ignored.
_STIMULUS_EVENTS = frozenset({OBJECT_APPROACHED, SOUND_SPIKE, OBJECT_CONTACTED})


class InstinctService:
    def __init__(
        self,
        *,
        consumer: EventConsumer,
        publisher: EventPublisher,
        predictor: InstinctPredictorPort,
        encoder: InstinctFeatureEncoder,
        policy: InstinctRuntimePolicy,
        being_id: str,
        predictions: InstinctPredictionRepository,
        reactions: InstinctReactionRepository,
        outbox: OutboxRepository,
        unit_of_work: Optional[UnitOfWork] = None,
        source_topic: str = PERCEPTION_TOPIC,
        dlq_topic: Optional[str] = None,
        temperament: Optional["TemperamentService"] = None,
    ) -> None:
        if not policy.shadow:
            raise ValueError(
                "InstinctService runs in SHADOW only (INS-RT): it records and "
                "publishes but changes no behavior. Active instinct integration — "
                "biasing emotion / interrupting an action through the safety seam — "
                "lands in INS-ACT. Set instinct.reaction.shadow: true."
            )
        self._publisher = publisher
        self._predictor = predictor
        self._encoder = encoder
        self._policy = policy
        self._being_id = being_id
        self._predictions = predictions
        self._reactions = reactions
        self._outbox = outbox
        self._uow = unit_of_work or NullUnitOfWork()
        self._source_topic = source_topic
        self._dlq_topic = dlq_topic or f"{source_topic}.dlq"
        # ADAPTIVE temperament (INS-TEMPERAMENT, ADR 0031): when wired, the being's
        # per-label reaction thresholds DRIFT from experience (habituation /
        # sensitization) and this consumer gates on the drifted EFFECTIVE threshold
        # instead of the static config one. None -> the static baseline (byte-identical).
        self._temperament = temperament
        # In-process idempotency ledger + per-label cooldown clocks. Transient by
        # design (like ADR 0020's familiarity signal): the outbox/event-log carry
        # the durable at-least-once guarantee for the OUTGOING events.
        self._processed: Set[str] = set()
        self._last_triggered: Dict[str, int] = {}
        consumer.subscribe(source_topic, self._on_event)

    # --- the one entry point the bus drives ------------------------------

    def _on_event(self, event: DomainEvent) -> None:
        """Handle one event delivered on the perception topic. Only
        a perception STIMULUS (approach, sound spike, or contact) drives instinct;
        anything else is ignored. Idempotent on
        the source `event_id`, and any failure to process a stimulus routes the
        event to the DLQ rather than propagating back to the publisher."""
        if event.event_type not in _STIMULUS_EVENTS:
            return
        if event.event_id in self._processed:
            return  # idempotent: a replayed approach is dropped
        self._processed.add(event.event_id)
        try:
            self._infer(event)
        except Exception:  # noqa: BLE001 — a poison stimulus dead-letters, never wedges
            self._publisher.publish(self._dlq_topic, event)

    # --- inference + reaction selection + atomic capture -----------------

    def _infer(self, event: DomainEvent) -> None:
        object_id, tick, stimulus = self._stimulus(event)
        prediction = self._predictor.predict_reactions(stimulus)
        intensity = float(prediction.intensity)
        label, triggered = self._select(prediction, tick)

        probabilities = {
            name: float(prediction.reactions.get(name, 0.0))
            for name in self._encoder.label_names()
        }
        record = InstinctPrediction(
            being_id=self._being_id,
            tick=tick,
            event_id=event.event_id,
            features=self._encoder.encode_features(stimulus),
            reaction_probabilities=tuple(probabilities.values()),
            reaction_intensity=intensity,
        )
        reaction = InstinctReaction(
            being_id=self._being_id,
            tick=tick,
            event_id=event.event_id,
            reaction=label,
            intensity=intensity,
            triggered=triggered,
        )
        prediction_event = event.causes(
            event_type=PREDICTION_MADE,
            source_service=_SOURCE_SERVICE,
            payload={
                "objectId": object_id,
                "tick": tick,
                "reactions": probabilities,
                "intensity": intensity,
            },
        )
        reaction_event = event.causes(
            event_type=REACTION_TRIGGERED if triggered else REACTION_SUPPRESSED,
            source_service=_SOURCE_SERVICE,
            payload={
                "objectId": object_id,
                "tick": tick,
                "reaction": label,
                "intensity": intensity,
                "triggered": triggered,
            },
        )
        # ONE unit of work: the prediction, the reaction, and BOTH outbox rows
        # commit together (ADR 0017/0028). Publish happens later, in the relay.
        with self._uow.begin():
            self._predictions.add(record)
            self._reactions.add(reaction)
            self._outbox.add(OutboxEntry(topic=INSTINCT_PREDICTIONS_TOPIC, event=prediction_event))
            self._outbox.add(OutboxEntry(topic=INSTINCT_REACTIONS_TOPIC, event=reaction_event))

        # Start the label's cooldown only once its firing has committed, and note the
        # firing for the adaptive temperament — a harmless startle HABITUATES the being
        # (INS-TEMPERAMENT, ADR 0031); the tick's harm verdict is settled by the caller.
        if triggered:
            self._last_triggered[label] = tick
            if self._temperament is not None:
                self._temperament.record_reaction(label)

    def _select(self, prediction, tick: int) -> Tuple[str, bool]:
        """Pick the being's reaction to a prediction and whether it fires. The
        dominant protective label — highest probability among the thresholded ones
        — is the candidate; it TRIGGERS when its probability clears its threshold
        and the label is not still cooling down from a recent firing, else it is
        SUPPRESSED. Selection touches no decision and never bypasses safety (ADR
        0026)."""
        labels = self._policy.thresholded_labels()
        if not labels:
            return _NO_REACTION, False
        label = max(labels, key=lambda name: prediction.reactions.get(name, 0.0))
        probability = float(prediction.reactions.get(label, 0.0))
        at_threshold = probability >= self._effective_threshold(label)
        triggered = at_threshold and not self._cooling_down(label, tick)
        return label, triggered

    def _effective_threshold(self, label: str) -> float:
        """The threshold `label` must clear to fire: the being's DRIFTED temperament
        threshold when an adaptive temperament is wired (INS-TEMPERAMENT, ADR 0031),
        else the static config baseline. Either way this only gates which REACTION
        fires; it never bypasses the safety floor (ADR 0026)."""
        if self._temperament is not None:
            return self._temperament.threshold(label)
        return self._policy.threshold(label)

    def _cooling_down(self, label: str, tick: int) -> bool:
        last = self._last_triggered.get(label)
        if last is None:
            return False
        return tick - last < self._policy.cooldown(label)

    @staticmethod
    def _stimulus(event: DomainEvent) -> Tuple[str, int, Stimulus]:
        """Rebuild the perceived `Stimulus` from an `ObjectApproached` payload. A
        payload missing `features`/`objectId`/`tick`, or carrying a feature outside
        the frozen contract, raises — and `_on_event` routes it to the DLQ."""
        payload = event.payload
        stimulus = Stimulus(**payload["features"])
        return str(payload["objectId"]), int(payload["tick"]), stimulus
