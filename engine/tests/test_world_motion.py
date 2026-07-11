"""Behaviors: objects can MOVE, and perception derives an APPROACH STIMULUS —
publishing an `ObjectApproached` domain event carrying the frozen 14-feature
instinct vector (WORLD-MOTION, ADR 0027, feature contract ADR 0026).

Every test drives the public surface: it builds a `Simulation` from config (with
a `motion` section) and an injected `EventPublisher` (the in-memory bus), ticks,
and asserts on what lands on `being.perception.events` and on `Simulation.state()`.
Motion is a world/perception concern — it never bends the being's decision.
"""
from __future__ import annotations

from typing import List, Tuple

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.policies import MOTION_FEATURE_NAMES
from app.simulation import Simulation

_TOPIC = "being.perception.events"


def _config(
    *,
    position: Tuple[float, float] = (8.0, 0.0),
    velocity: Tuple[float, float] = (-4.0, 0.0),
    size: float = 0.3,
    with_motion: bool = True,
):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {"rules": [], "default": "calm"}
    rooms = {"room": {"id": "room_001", "contains": ["obj_mover"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
    }
    motion = None
    if with_motion:
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
            "objects": {
                "obj_mover": {
                    "position": list(position),
                    "velocity": list(velocity),
                    "size": size,
                }
            },
        }
    return ConfigService.from_dict(
        tick_rates, emotions, rooms=rooms, objects=objects, motion=motion
    )


def _run_once(config) -> Tuple[Simulation, List[DomainEvent]]:
    bus = InMemoryEventBus()
    received: List[DomainEvent] = []
    bus.subscribe(_TOPIC, received.append)
    sim = Simulation(config, event_publisher=bus)
    sim.tick()
    return sim, received


# --- a moving object produces an ObjectApproached stimulus ------------------


def test_a_fast_body_bound_object_reads_as_high_trajectory_and_low_time_to_contact():
    # Straight at the body, fast: heading dead-on (trajectory ~1) and about to
    # arrive (time-to-contact small).
    _, events = _run_once(_config(position=(8.0, 0.0), velocity=(-4.0, 0.0)))

    assert len(events) == 1
    features = events[0].payload["features"]
    assert features["trajectory_toward_body"] > 0.9
    assert features["time_to_contact"] < 0.25
    assert features["velocity"] > 0.5


def test_a_slow_approaching_object_reads_as_low_velocity_and_high_time_to_contact():
    # Same heading, but crawling: still toward the body, yet slow and far from
    # contact — the being should read it as far less pressing than the fast one.
    _, fast = _run_once(_config(position=(8.0, 0.0), velocity=(-4.0, 0.0)))
    _, slow = _run_once(_config(position=(8.0, 0.0), velocity=(-0.5, 0.0)))

    assert len(slow) == 1
    slow_f = slow[0].payload["features"]
    fast_f = fast[0].payload["features"]
    assert slow_f["velocity"] < fast_f["velocity"]
    assert slow_f["time_to_contact"] > fast_f["time_to_contact"]


def test_an_object_moving_away_emits_no_object_approached():
    # Receding from the body — not an approach — so no stimulus is published.
    _, events = _run_once(_config(position=(4.0, 0.0), velocity=(3.0, 0.0)))
    assert events == []


def test_a_static_world_emits_no_object_approached():
    # Nothing moves: the object sits still, so perception raises no approach.
    _, events = _run_once(_config(velocity=(0.0, 0.0)))
    assert events == []


def test_a_world_with_no_motion_configured_emits_no_object_approached():
    # No motion section at all — the pre-motion world — is silent on the bus.
    _, events = _run_once(_config(with_motion=False))
    assert events == []


# --- the payload carries the frozen 14-feature instinct vector, in order ----


def test_object_approached_payload_carries_all_fourteen_features_in_order():
    _, events = _run_once(_config())

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "being.perception.object_approached"
    features = event.payload["features"]
    # Exactly the ADR 0026 frozen vector, exact keys, exact order.
    assert tuple(features.keys()) == MOTION_FEATURE_NAMES
    assert len(features) == 14
    for name, value in features.items():
        assert isinstance(value, float), name


def test_object_approached_reports_the_moving_object():
    _, events = _run_once(_config())
    assert events[0].payload["objectId"] == "obj_mover"


# --- visible in state() -----------------------------------------------------


def test_state_exposes_the_current_approach_stimuli():
    sim, _ = _run_once(_config())
    stimuli = sim.state()["stimuli"]
    assert len(stimuli) == 1
    assert stimuli[0]["objectId"] == "obj_mover"
    assert tuple(stimuli[0]["features"].keys()) == MOTION_FEATURE_NAMES


def test_state_stimuli_do_not_alias_internal_state():
    sim, _ = _run_once(_config())
    snapshot = sim.state()
    snapshot["stimuli"][0]["features"]["distance"] = 999.0
    assert sim.state()["stimuli"][0]["features"]["distance"] != 999.0


# --- motion never runs without a publisher, and never bends behavior --------


def test_a_moving_world_runs_without_a_publisher():
    # No publisher injected: the being still ticks and perceives, and its state
    # simply carries no stimuli-published events (motion advances silently).
    sim = Simulation(_config())
    sim.tick()
    # It exposes the stimulus in state() but published nothing (no bus).
    assert "stimuli" in sim.state()


def test_a_moving_object_outside_the_room_raises_no_stimulus():
    # A stimulus is a PERCEPTION: an object the being cannot make out (not in its
    # room, ADR 0002) raises none, even while its world motion advances.
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {"rules": [], "default": "calm"}
    rooms = {"room": {"id": "room_001", "contains": []}}  # the being is alone
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
    }
    motion = {
        "approach": {"min_closing_speed": 0.0},
        "objects": {"obj_mover": {"position": [8.0, 0.0], "velocity": [-4.0, 0.0], "size": 0.3}},
    }
    config = ConfigService.from_dict(
        tick_rates, emotions, rooms=rooms, objects=objects, motion=motion
    )
    _, events = _run_once(config)
    assert events == []
