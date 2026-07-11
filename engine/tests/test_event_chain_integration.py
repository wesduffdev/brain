"""Behavior: the event-instinct chain runs END-TO-END inside one being (EVT-VALID).

This is the integration capstone the wave deferred here: on ONE shared event bus,
a moving object drives the whole path in-process ---

    StimulusService  -> being.perception.events (ObjectApproached)
    InstinctService  -> being.instinct.reactions (a shadow reaction)   [via outbox relay]
    ReactionResponseService (Simulation's event_consumer) -> the being reacts

--- so with the INS-ACT activation flags ON the being surfaces the reaction and
biases its derived emotion, and with the flags OFF (the default) the chain is
observed-only and behaviour is byte-identical.

Every assertion is through the public surface: `Simulation.tick()` / `.state()`
and the events on the in-memory bus. A torch-free fake instinct predictor stands
in for the trained model; no broker, no database.
"""
from __future__ import annotations

from typing import List, Tuple

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import Stimulus
from app.policies import MOTION_FEATURE_NAMES
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.services.instinct_service import PERCEPTION_TOPIC, INSTINCT_REACTIONS_TOPIC
from app.services.model_telemetry_service import TELEMETRY_TOPIC
from app.simulation import Simulation


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class FakeInstinctPredictor:
    """Torch-free `InstinctPredictorPort`: the being flinches at a fast, body-bound
    approach — flinch probability and intensity both track velocity*trajectory."""

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        threat = _clamp(stimulus.velocity * stimulus.trajectory_toward_body)
        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = threat
        reactions["ignore"] = 1.0 - threat
        return PortPrediction(reactions=reactions, intensity=threat)


def _config(*, visual_only=False, allow_interrupt=False):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {
        "rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}],
        "default": "calm",
    }
    rooms = {"room": {"id": "room_001", "contains": ["obj_mover"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
    }
    actions = {
        "actions": {
            "observe": {
                "affordance": "look",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a careful look",
            },
        }
    }
    # A fast object heading dead-on at the body (velocity -4 over distance 8).
    motion = {
        "normalization": {
            "max_distance": 10.0,
            "max_speed": 5.0,
            "max_acceleration": 5.0,
            "max_time_to_contact": 10.0,
            "max_size": 1.0,
            "max_size_change_rate": 1.0,
        },
        "approach": {"min_closing_speed": 0.0},
        "objects": {"obj_mover": {"position": [8.0, 0.0], "velocity": [-4.0, 0.0], "size": 0.3}},
    }
    instinct = {
        "feature_order": list(MOTION_FEATURE_NAMES),
        "labels": list(REACTION_LABELS),
        "reaction": {
            "shadow": True,
            "thresholds": {"flinch": 0.5},
            "cooldowns": {"flinch": 0},
            "visual_only": visual_only,
            "allow_interrupt": allow_interrupt,
            "emotion_bias": {"flinch": {"safety": -60}},
            "interrupt": {
                "intensity_threshold": 0.5,
                "interruptible_actions": ["observe"],
                "protective_action": "withdraw",
            },
        },
    }
    return ConfigService.from_dict(
        tick_rates,
        emotions,
        rooms=rooms,
        objects=objects,
        actions=actions,
        safety={"rules": []},
        outcome={"labels": ["pleasant"], "context_features": []},
        instinct=instinct,
        motion=motion,
    )


def _sim(config) -> Tuple[Simulation, InMemoryEventBus]:
    bus = InMemoryEventBus()
    sim = Simulation(
        config,
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    )
    return sim, bus


def _recorder(bus, topic):
    seen: List[DomainEvent] = []
    bus.subscribe(topic, seen.append)
    return seen


# --- the full chain drives a reaction into the being (flags on) ---------------


def test_a_moving_object_drives_a_reaction_the_being_surfaces_and_feels():
    sim, bus = _sim(_config(visual_only=True))
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)

    sim.tick()          # tick 1: stimulus -> instinct reaction, drained onto the bus
    state = sim.tick()  # tick 2: the reaction latched from between-ticks now surfaces

    # the being reacts: the reaction is surfaced for the renderer AND biases the
    # derived emotion toward scared (never assigned — the chain is genuinely wired).
    assert state["reaction"]["type"] == "flinch"
    assert state["emotion"] == "scared"
    # a triggered flinch reaction really travelled the instinct topic
    assert any(r.payload.get("triggered") for r in reactions)


def test_the_chain_emits_model_telemetry_for_the_prediction_and_outcome():
    sim, bus = _sim(_config(visual_only=True))
    telemetry = _recorder(bus, TELEMETRY_TOPIC)

    sim.tick()
    sim.tick()

    assert telemetry, "the chain should record instinct telemetry"
    record = telemetry[0]
    assert record.payload["reaction"] == "flinch"
    assert record.payload["outcome"] == "accepted"
    assert "probability" in record.payload


def test_the_correlation_id_is_preserved_from_the_root_stimulus_to_the_reaction():
    sim, bus = _sim(_config(visual_only=True))
    approaches = _recorder(bus, PERCEPTION_TOPIC)
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)

    sim.tick()

    assert approaches and reactions
    root = approaches[0]
    reaction = reactions[0]
    # the reaction traces back to the exact perception root that caused it
    assert reaction.correlation_id == root.correlation_id
    assert reaction.causation_id == root.event_id


def test_the_consumer_lag_metric_is_surfaced_and_settles_to_zero():
    sim, _ = _sim(_config(visual_only=True))

    sim.tick()
    sim.tick()

    # after each tick's outbox drain, prediction and reaction are paired: no lag
    assert sim.instinct_lag() == 0


# --- default (flags off): the wired chain changes NO behaviour ----------------


def test_with_activation_flags_off_the_wired_chain_is_byte_identical():
    # A being with the whole chain wired but the INS-ACT flags off must behave
    # exactly like a plain being with no instinct predictor at all.
    with_chain, _ = _sim(_config())  # flags default off
    baseline_bus = InMemoryEventBus()
    baseline = Simulation(_config(), event_publisher=baseline_bus)  # no predictor/consumer

    for _ in range(4):
        a = with_chain.tick()
        b = baseline.tick()
        assert a == b
        assert "reaction" not in a
