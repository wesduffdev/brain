"""Behavior: the perceived-room frame reaches the sensory-stimulus subsystem
THROUGH the event backbone, behavior-preserving (TICK-EVENT-MIGRATE, ADR 0024/0025).

Today `Simulation._act` hand-feeds each tick's perceived view straight into
`StimulusService.observe(...)` (an inline, synchronous call — TICK-INV #5). This
slice takes the first migration step: when the being is wired to an event bus AND
the `perception.route_via_events` toggle is on, the perceived frame is PUBLISHED as
a `being.perception.taken` domain event at that seam and the StimulusService
CONSUMES it (reacting by advancing motion and raising its stimuli), instead of the
direct call.

It is a config-gated SHADOW/PARALLEL migration: the direct in-tick call and the
via-bus route are two proven-equivalent plumbings of the same responsibility, and
the default (toggle off) keeps the direct call — so the whole pre-migration suite
is untouched. The keystone here is the equivalence proof: two beings, one on each
route, stay byte-identical `state()`-for-`state()` across many ticks. Delivery is
synchronous on the tick thread (single-writer preserved), never a background task.

Every assertion is through the public surface (`Simulation.tick()`/`.state()` and
the events on the in-memory bus). A torch-free fake instinct predictor stands in
for the trained model; no broker, no database.
"""
from __future__ import annotations

import threading
from typing import List

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import Stimulus
from app.policies import MOTION_FEATURE_NAMES
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.services.stimulus_service import PERCEPTION_INPUT_TOPIC, PERCEPTION_TAKEN
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


def _config(*, route_via_events: bool = False, visual_only: bool = True) -> ConfigService:
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
        # The seam under migration: route the perceived frame via the backbone or not.
        "perception": {"route_via_events": route_via_events},
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
            "allow_interrupt": False,
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


def _chain(config: ConfigService):
    bus = InMemoryEventBus()
    sim = Simulation(
        config,
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    )
    return sim, bus


def _recorder(bus: InMemoryEventBus, topic: str) -> List[DomainEvent]:
    seen: List[DomainEvent] = []
    bus.subscribe(topic, seen.append)
    return seen


# --- the toggle defaults to the current (direct) behavior --------------------


def test_perception_routing_is_off_by_default():
    # A config with no `perception` block keeps the pre-migration direct path.
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {"rules": [], "default": "calm"}
    config = ConfigService.from_dict(tick_rates, emotions)
    assert config.perception_routing_policy().route_via_events is False


def test_perception_routing_reads_the_toggle_when_set():
    assert _config(route_via_events=True).perception_routing_policy().route_via_events is True


# --- publish at the seam + the consumer reacts (toggle on, bus wired) --------


def test_perceived_frame_is_published_at_the_seam_and_the_stimulus_consumer_reacts():
    sim, bus = _chain(_config(route_via_events=True))
    frames = _recorder(bus, PERCEPTION_INPUT_TOPIC)

    state = sim.tick()

    # emitted at the seam as a domain event ...
    assert frames, "routing on must publish the perceived frame onto the backbone"
    assert frames[0].event_type == PERCEPTION_TAKEN
    # ... and the StimulusService consumed it, producing this tick's stimuli.
    assert state["stimuli"], "the stimulus consumer must react to the perceived frame"


def test_direct_path_never_touches_the_backbone_for_perception():
    sim, bus = _chain(_config(route_via_events=False))
    frames = _recorder(bus, PERCEPTION_INPUT_TOPIC)

    state = sim.tick()

    assert not frames, "the default direct path must not publish a perceived-frame event"
    assert state["stimuli"], "the direct path still produces stimuli"


def test_routing_on_without_a_bus_falls_back_to_the_direct_path():
    # No publisher/consumer: there is no backbone to route onto, so the being uses
    # the direct call and stays byte-identical to any bus-less being.
    sim = Simulation(_config(route_via_events=True))
    state = sim.tick()
    assert state["stimuli"], "stimulus is still produced via the direct call"


# --- the keystone: the two routes are byte-identical, tick-for-tick ----------


def test_routing_via_events_is_byte_identical_to_the_direct_path():
    direct, direct_bus = _chain(_config(route_via_events=False))
    routed, routed_bus = _chain(_config(route_via_events=True))
    direct_frames = _recorder(direct_bus, PERCEPTION_INPUT_TOPIC)
    routed_frames = _recorder(routed_bus, PERCEPTION_INPUT_TOPIC)

    for _ in range(6):
        a = direct.tick()
        b = routed.tick()
        # every observable field — needs, emotion, decision/currentAction, stimuli,
        # curiosity/surprise, the surfaced reaction — is identical on both routes.
        assert a == b

    # the plumbing genuinely differs: only the routed being used the backbone ...
    assert routed_frames, "the routed being must emit the perceived frame at the seam"
    assert not direct_frames, "the direct being must not touch the backbone"
    # ... yet the instinct chain drained identically on both.
    assert routed.instinct_lag() == direct.instinct_lag() == 0


# --- single-writer: the frame is consumed synchronously on the tick thread ---


def test_perceived_frame_is_consumed_on_the_tick_thread_not_a_background_task():
    sim, bus = _chain(_config(route_via_events=True))
    threads: List[int] = []
    bus.subscribe(PERCEPTION_INPUT_TOPIC, lambda e: threads.append(threading.get_ident()))

    sim.tick()  # synchronous: the frame is consumed before tick() returns

    assert threads == [threading.get_ident()], (
        "the perceived frame must be delivered synchronously on the tick (single-writer) thread"
    )
