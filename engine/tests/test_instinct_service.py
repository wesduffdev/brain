"""Behavior of the shadow instinct-inference consumer (INS-RT, extends ADR 0011).

`ObjectApproached` events on `being.perception.events` drive live instinct
inference: the consumer encodes the stimulus, runs an `InstinctPredictorPort`,
persists the prediction + selected reaction, and stages the outgoing
`being.instinct.predictions` / `being.instinct.reactions` events to the outbox —
all in ONE unit of work, published only by the relay (never inside the txn). In
SHADOW (the default) it records and publishes but changes no simulation behavior.

These pin that behavior through the public surface — publish an approach on the
in-memory bus, drain the outbox, observe the published instinct events and the
persisted rows — with a torch-free FAKE predictor (the second
`InstinctPredictorPort` implementation, ADR 0026), no broker, and no database.
"""
from __future__ import annotations

import pytest

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import InstinctFeatureEncoder, InstinctSpec, Stimulus
from app.outbox_relay import drain_outbox
from app.policies import MOTION_FEATURE_NAMES, InstinctRuntimePolicy
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.repositories import (
    InMemoryEventLogRepository,
    InMemoryInstinctPredictionRepository,
    InMemoryInstinctReactionRepository,
    InMemoryOutboxRepository,
)
from app.services.instinct_service import (
    INSTINCT_PREDICTIONS_TOPIC,
    INSTINCT_REACTIONS_TOPIC,
    PERCEPTION_TOPIC,
    PREDICTION_MADE,
    REACTION_SUPPRESSED,
    REACTION_TRIGGERED,
    InstinctService,
)
from app.db.unit_of_work import NullUnitOfWork


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class FakeInstinctPredictor:
    """A torch-free, deterministic `InstinctPredictorPort` stand-in for the INS-RT
    consumer suite (the second implementation ADR 0026 deferred here). Transparent
    on purpose: the being flinches at fast, body-bound approaches — flinch
    probability and reaction intensity both track ``velocity * trajectory_toward_body``
    — so a test drives the consumer's threshold/cooldown/idempotency logic with a
    real `Stimulus` and no artifact."""

    def __init__(self, labels=REACTION_LABELS) -> None:
        self._labels = tuple(labels)

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        threat = _clamp(stimulus.velocity * stimulus.trajectory_toward_body)
        reactions = {label: 0.0 for label in self._labels}
        if "flinch" in reactions:
            reactions["flinch"] = threat
        if "ignore" in reactions:
            reactions["ignore"] = 1.0 - threat
        return PortPrediction(reactions=reactions, intensity=threat)


def _encoder() -> InstinctFeatureEncoder:
    return InstinctFeatureEncoder(
        InstinctSpec(feature_order=MOTION_FEATURE_NAMES, label_vocab=REACTION_LABELS)
    )


def _policy(**overrides) -> InstinctRuntimePolicy:
    defaults = dict(
        thresholds={"flinch": 0.5, "freeze": 0.5, "orient": 0.4, "withdraw": 0.6},
        cooldowns={"flinch": 5, "freeze": 5, "orient": 3, "withdraw": 8},
        shadow=True,
    )
    defaults.update(overrides)
    return InstinctRuntimePolicy(**defaults)


def _service(bus, *, predictor=None, policy=None):
    predictions = InMemoryInstinctPredictionRepository()
    reactions = InMemoryInstinctReactionRepository()
    outbox = InMemoryOutboxRepository()
    service = InstinctService(
        consumer=bus,
        publisher=bus,
        predictor=predictor or FakeInstinctPredictor(),
        encoder=_encoder(),
        policy=policy or _policy(),
        being_id="being_001",
        predictions=predictions,
        reactions=reactions,
        outbox=outbox,
        unit_of_work=NullUnitOfWork(),
    )
    return service, predictions, reactions, outbox


def _recorder(bus, topic):
    seen = []
    bus.subscribe(topic, seen.append)
    return seen


def _approach(*, tick=1, object_id="obj_1", event_id=None, **feature_overrides) -> DomainEvent:
    features = {name: 0.0 for name in MOTION_FEATURE_NAMES}
    features.update(feature_overrides)
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": object_id, "tick": tick, "features": features},
        event_id=event_id,
    )


def _drain(bus, outbox):
    drain_outbox(outbox=outbox, event_log=InMemoryEventLogRepository(), publisher=bus)


# --- reaction selection: trigger, suppress, cooldown --------------------------


def test_a_fast_body_bound_approach_triggers_a_flinch_past_its_threshold():
    bus = InMemoryEventBus()
    reactions_out = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    predictions_out = _recorder(bus, INSTINCT_PREDICTIONS_TOPIC)
    service, _, _, outbox = _service(bus)

    bus.publish(PERCEPTION_TOPIC, _approach(velocity=1.0, trajectory_toward_body=1.0))
    _drain(bus, outbox)

    assert len(predictions_out) == 1
    assert predictions_out[0].event_type == PREDICTION_MADE
    assert len(reactions_out) == 1
    reaction = reactions_out[0]
    assert reaction.event_type == REACTION_TRIGGERED
    assert reaction.payload["reaction"] == "flinch"
    assert reaction.payload["triggered"] is True
    # the published reaction carries an intensity above the fired label's threshold
    assert reaction.payload["intensity"] > 0.5


def test_a_below_threshold_stimulus_is_suppressed():
    bus = InMemoryEventBus()
    reactions_out = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    service, _, _, outbox = _service(bus)

    bus.publish(PERCEPTION_TOPIC, _approach(velocity=0.2, trajectory_toward_body=0.2))
    _drain(bus, outbox)

    assert len(reactions_out) == 1
    reaction = reactions_out[0]
    assert reaction.event_type == REACTION_SUPPRESSED
    assert reaction.payload["triggered"] is False


def test_a_cooldown_suppresses_a_rapid_second_flinch_for_the_same_label():
    bus = InMemoryEventBus()
    reactions_out = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    service, _, _, outbox = _service(bus)

    # two fast body-bound approaches one tick apart — within flinch's 5-tick cooldown
    bus.publish(PERCEPTION_TOPIC, _approach(tick=1, velocity=1.0, trajectory_toward_body=1.0))
    bus.publish(PERCEPTION_TOPIC, _approach(tick=2, velocity=1.0, trajectory_toward_body=1.0))
    _drain(bus, outbox)

    kinds = [(r.event_type, r.payload["triggered"]) for r in reactions_out]
    assert kinds == [(REACTION_TRIGGERED, True), (REACTION_SUPPRESSED, False)]


def test_a_second_flinch_after_the_cooldown_elapses_triggers_again():
    bus = InMemoryEventBus()
    reactions_out = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    service, _, _, outbox = _service(bus)

    bus.publish(PERCEPTION_TOPIC, _approach(tick=1, velocity=1.0, trajectory_toward_body=1.0))
    bus.publish(PERCEPTION_TOPIC, _approach(tick=7, velocity=1.0, trajectory_toward_body=1.0))
    _drain(bus, outbox)

    kinds = [r.event_type for r in reactions_out]
    assert kinds == [REACTION_TRIGGERED, REACTION_TRIGGERED]


# --- idempotency: a replayed source event yields exactly one reaction ---------


def test_a_replayed_approach_yields_exactly_one_prediction_and_reaction():
    bus = InMemoryEventBus()
    reactions_out = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    service, predictions, reactions, outbox = _service(bus)

    approach = _approach(event_id="evt-dup", velocity=1.0, trajectory_toward_body=1.0)
    bus.publish(PERCEPTION_TOPIC, approach)
    bus.publish(PERCEPTION_TOPIC, approach)  # redelivery of the same event_id
    _drain(bus, outbox)

    assert len(predictions.all()) == 1
    assert len(reactions.all()) == 1
    assert len(reactions_out) == 1


# --- DLQ: a stimulus the consumer cannot process parks off to the side --------


def test_an_unprocessable_approach_routes_to_the_dlq_without_persisting():
    bus = InMemoryEventBus()
    dlq_out = _recorder(bus, PERCEPTION_TOPIC + ".dlq")
    service, predictions, reactions, outbox = _service(bus)

    malformed = DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": "obj_1", "tick": 1},  # no `features` — unprocessable
    )
    bus.publish(PERCEPTION_TOPIC, malformed)  # must not raise (never wedge the bus)
    _drain(bus, outbox)

    assert len(dlq_out) == 1
    assert dlq_out[0].event_id == malformed.event_id
    assert predictions.all() == []
    assert reactions.all() == []


# --- persistence: prediction + reaction rows land through the ports -----------


def test_prediction_and_reaction_rows_are_persisted():
    bus = InMemoryEventBus()
    service, predictions, reactions, outbox = _service(bus)

    bus.publish(PERCEPTION_TOPIC, _approach(tick=3, velocity=1.0, trajectory_toward_body=1.0))

    stored_pred = predictions.all()
    assert len(stored_pred) == 1
    assert stored_pred[0].tick == 3
    assert len(stored_pred[0].features) == 14
    assert len(stored_pred[0].reaction_probabilities) == 5

    stored_reaction = reactions.all()
    assert len(stored_reaction) == 1
    assert stored_reaction[0].reaction == "flinch"
    assert stored_reaction[0].triggered is True
    # the outbox holds exactly the two outgoing events, staged with the writes
    assert {e.topic for e in outbox.all()} == {INSTINCT_PREDICTIONS_TOPIC, INSTINCT_REACTIONS_TOPIC}


def test_a_non_approach_event_on_the_perception_topic_is_ignored():
    bus = InMemoryEventBus()
    service, predictions, reactions, outbox = _service(bus)

    other = DomainEvent.create(
        event_type="being.perception.sudden_sound_detected",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": "obj_1", "tick": 1},
    )
    bus.publish(PERCEPTION_TOPIC, other)

    assert predictions.all() == []
    assert reactions.all() == []
    assert outbox.all() == []


# --- shadow discipline + config plumbing --------------------------------------


def test_the_service_supports_shadow_mode_only():
    bus = InMemoryEventBus()
    with pytest.raises(ValueError):
        _service(bus, policy=_policy(shadow=False))


def test_config_yields_the_runtime_policy_with_shadow_on_by_default():
    config = ConfigService.from_dict(
        tick_rates={"tick": {"duration_ms": 100}, "needs": {}},
        emotions={"rules": [], "default": "calm"},
        instinct={
            "feature_order": list(MOTION_FEATURE_NAMES),
            "labels": list(REACTION_LABELS),
            "reaction": {
                "thresholds": {"flinch": 0.5},
                "cooldowns": {"flinch": 5},
            },
        },
    )
    policy = config.instinct_runtime_policy()
    assert policy.shadow is True
    assert policy.threshold("flinch") == 0.5
    assert policy.cooldown("flinch") == 5


def test_absent_reaction_config_is_shadow_on_with_no_reaction_ever_firing():
    config = ConfigService.from_dict(
        tick_rates={"tick": {"duration_ms": 100}, "needs": {}},
        emotions={"rules": [], "default": "calm"},
    )
    policy = config.instinct_runtime_policy()
    assert policy.shadow is True
    assert policy.thresholded_labels() == ()
