"""Behaviors: real SOUND and TOUCH signals now populate the instinct stimulus
(SENSORY-STIM, extends WORLD-MOTION / ADR 0027, feature contract ADR 0026).

A SUDDEN loud/unknown sound (a transition via `change_environment`) becomes a
`being.perception.sound_spike` stimulus carrying a high `sound_spike_intensity`
(the being HEARS it but cannot see it — low visibility, high unexpectedness); an
approaching object REACHING the body becomes a `being.perception.object_contacted`
stimulus carrying a high `touch_intensity`. Both fill the frozen 14-feature vector,
so the existing instinct chain can now select FREEZE (loud/unknown sound) and
WITHDRAW (unexpected contact) — reactions that the motion-only stimulus could
never drive because sound/touch were stubbed 0.0.

Every test drives the public surface: a `Simulation` built from config with an
injected `EventPublisher` (the in-memory bus), ticked, asserting on what lands on
`being.perception.events` and — for the chain tests — a torch-free fake predictor
plus the drained instinct-reaction stream. Sound/touch are world/perception
concerns; they never bend the being's decision.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import Stimulus
from app.policies import MOTION_FEATURE_NAMES
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.services.instinct_service import (
    INSTINCT_REACTIONS_TOPIC,
    REACTION_TRIGGERED,
)
from app.services.stimulus_service import (
    OBJECT_APPROACHED,
    OBJECT_CONTACTED,
    PERCEPTION_TOPIC,
    SOUND_SOURCE_ID,
    SOUND_SPIKE,
)
from app.simulation import Simulation

_TOPIC = PERCEPTION_TOPIC


def _config(
    *,
    position: Tuple[float, float] = (8.0, 0.0),
    velocity: Tuple[float, float] = (-4.0, 0.0),
    size: float = 0.3,
    sound: str = "normal",
    with_instinct_thresholds: bool = False,
):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {"rules": [], "default": "calm"}
    rooms = {
        "room": {
            "id": "room_001",
            "contains": ["obj_mover"],
            "base_confidence": 1.0,
            "sound": sound,
        }
    }
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
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
        "sound": {
            "spike": {
                "loud": {
                    "sound_spike_intensity": 0.8,
                    "unexpectedness": 0.7,
                    "visibility_confidence": 0.2,
                },
                "unknown_sound": {
                    "sound_spike_intensity": 0.95,
                    "unexpectedness": 0.9,
                    "visibility_confidence": 0.1,
                },
            }
        },
        "contact": {
            "contact_distance": 0.5,
            "min_touch_intensity": 0.6,
            "unexpectedness": 0.7,
        },
        "objects": {
            "obj_mover": {"position": list(position), "velocity": list(velocity), "size": size},
        },
    }
    instinct = {
        "feature_order": list(MOTION_FEATURE_NAMES),
        "labels": list(REACTION_LABELS),
    }
    if with_instinct_thresholds:
        instinct["reaction"] = {
            "shadow": True,
            "thresholds": {"flinch": 0.5, "freeze": 0.5, "orient": 0.4, "withdraw": 0.6},
            "cooldowns": {"flinch": 5, "freeze": 5, "orient": 3, "withdraw": 8},
        }
    return ConfigService.from_dict(
        tick_rates, emotions, rooms=rooms, objects=objects, motion=motion, instinct=instinct
    )


class _RuleFakePredictor:
    """A torch-free `InstinctPredictorPort` that imitates the ADR 0026 seed rules
    the trained model learns — so a Simulation test proves MY sourced features
    reach inference and select the right reaction, with no artifact. Loud+unknown
    (unseen) -> freeze; unexpected touch -> withdraw; fast body-bound -> flinch;
    else ignore."""

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        reactions = {label: 0.0 for label in REACTION_LABELS}
        flinch = (
            stimulus.velocity > 0.6
            and stimulus.trajectory_toward_body > 0.6
            and stimulus.time_to_contact < 0.35
        )
        freeze = (
            stimulus.sound_spike_intensity > 0.6
            and stimulus.unexpectedness > 0.5
            and stimulus.visibility_confidence < 0.4
        )
        withdraw = stimulus.touch_intensity > 0.5 and stimulus.unexpectedness > 0.5
        if flinch:
            reactions["flinch"] = 0.9
        if freeze:
            reactions["freeze"] = 0.9
        if withdraw:
            reactions["withdraw"] = 0.9
        if not (flinch or freeze or withdraw):
            reactions["ignore"] = 0.9
        return PortPrediction(reactions=reactions, intensity=max(reactions.values()))


def _events_of(bus_log: List[DomainEvent], event_type: str) -> List[DomainEvent]:
    return [e for e in bus_log if e.event_type == event_type]


def _run(config, *, ticks: int = 1, sound_change=None, change_at: int = 1):
    """Tick `config`'s being with an in-memory publisher, optionally changing the
    room's sound after tick `change_at`. Returns (sim, perception events)."""
    bus = InMemoryEventBus()
    received: List[DomainEvent] = []
    bus.subscribe(_TOPIC, received.append)
    sim = Simulation(config, event_publisher=bus)
    for t in range(1, ticks + 1):
        sim.tick()
        if sound_change is not None and t == change_at:
            sim.change_environment(sound=sound_change)
    return sim, received


# --- SOUND: a sudden loud/unknown sound emits a sound-spike stimulus ----------


def test_a_sudden_unknown_sound_emits_a_sound_spike_with_high_intensity():
    # Baseline normal room on tick 1; then the room turns to an UNKNOWN sound —
    # a sudden, unseen startle. Tick 2 raises one sound-spike stimulus.
    sim, events = _run(_config(sound="normal"), ticks=2, sound_change="unknown_sound", change_at=1)
    spikes = _events_of(events, SOUND_SPIKE)
    assert len(spikes) == 1
    f = spikes[0].payload["features"]
    assert f["sound_spike_intensity"] > 0.6
    assert f["unexpectedness"] > 0.5
    assert f["visibility_confidence"] < 0.4  # a sound has no visible source
    assert spikes[0].payload["objectId"] == SOUND_SOURCE_ID


def test_a_quiet_room_emits_no_sound_spike_and_leaves_the_feature_zero():
    # Nothing changes the sound: no spike is raised, and the motion approach
    # stimulus still reads sound_spike_intensity 0.0 (no spurious signal).
    sim, events = _run(_config(sound="normal"), ticks=2)
    assert _events_of(events, SOUND_SPIKE) == []
    approaches = _events_of(events, OBJECT_APPROACHED)
    assert approaches, "the moving object should still raise approach stimuli"
    assert all(e.payload["features"]["sound_spike_intensity"] == 0.0 for e in approaches)


def test_a_sustained_sound_is_a_single_spike_not_a_repeated_one():
    # A transition INTO loud is one spike; holding loud is not a fresh spike each
    # tick (a startle is the onset, not the steady state).
    sim, events = _run(_config(sound="normal"), ticks=4, sound_change="loud", change_at=1)
    assert len(_events_of(events, SOUND_SPIKE)) == 1


# --- TOUCH: an object reaching the body emits a contact stimulus --------------


def test_an_object_reaching_the_body_emits_a_contact_stimulus_with_high_touch():
    # A slow object crosses into contact range: one contact stimulus with a real
    # (floored) touch intensity and the unexpectedness that makes it a startle.
    sim, events = _run(_config(position=(1.0, 0.0), velocity=(-1.0, 0.0)), ticks=2)
    contacts = _events_of(events, OBJECT_CONTACTED)
    assert len(contacts) == 1
    f = contacts[0].payload["features"]
    assert f["touch_intensity"] > 0.5
    assert f["unexpectedness"] > 0.5
    assert contacts[0].payload["objectId"] == "obj_mover"


def test_an_object_that_never_reaches_the_body_emits_no_contact():
    # Approaching but stopping short (small step, far start) — never crosses the
    # contact threshold within the run, so no contact stimulus, touch stays 0.0.
    sim, events = _run(_config(position=(9.0, 0.0), velocity=(-0.5, 0.0)), ticks=2)
    assert _events_of(events, OBJECT_CONTACTED) == []
    approaches = _events_of(events, OBJECT_APPROACHED)
    assert all(e.payload["features"]["touch_intensity"] == 0.0 for e in approaches)


def test_the_sound_and_contact_stimuli_carry_the_frozen_14_vector_in_order():
    _, sound_events = _run(
        _config(sound="normal"), ticks=2, sound_change="unknown_sound", change_at=1
    )
    _, contact_events = _run(_config(position=(1.0, 0.0), velocity=(-1.0, 0.0)), ticks=2)
    spike = _events_of(sound_events, SOUND_SPIKE)[0]
    contact = _events_of(contact_events, OBJECT_CONTACTED)[0]
    for event in (spike, contact):
        keys = tuple(event.payload["features"].keys())
        assert keys == MOTION_FEATURE_NAMES
        assert len(event.payload["features"]) == 14


# --- CHAIN: the sourced features drive freeze / withdraw through instinct -----


def _chain(config):
    bus = InMemoryEventBus()
    reactions: List[DomainEvent] = []
    bus.subscribe(INSTINCT_REACTIONS_TOPIC, reactions.append)
    sim = Simulation(
        config,
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=_RuleFakePredictor(),
    )
    return sim, reactions


def _triggered(reactions: List[DomainEvent], label: str) -> bool:
    return any(
        e.event_type == REACTION_TRIGGERED and e.payload["reaction"] == label for e in reactions
    )


def test_a_loud_unknown_sound_makes_the_being_freeze():
    sim, reactions = _chain(_config(sound="normal", with_instinct_thresholds=True))
    sim.tick()  # baseline: sound is normal
    sim.change_environment(sound="unknown_sound")
    sim.tick()  # the sudden unknown sound -> freeze
    assert _triggered(reactions, "freeze")


def test_an_unexpected_contact_makes_the_being_withdraw():
    sim, reactions = _chain(
        _config(position=(1.0, 0.0), velocity=(-1.0, 0.0), with_instinct_thresholds=True)
    )
    sim.tick()
    sim.tick()  # the object reaches the body -> withdraw
    assert _triggered(reactions, "withdraw")


def test_a_quiet_room_with_nothing_approaching_triggers_no_reaction():
    # A receding object, normal sound: no sound spike, no contact, no approach —
    # so no reaction fires (no spurious freeze/withdraw from stubbed features).
    sim, reactions = _chain(
        _config(position=(4.0, 0.0), velocity=(3.0, 0.0), with_instinct_thresholds=True)
    )
    sim.tick()
    sim.tick()
    assert not any(e.event_type == REACTION_TRIGGERED for e in reactions)


def test_the_motion_approach_path_still_flinches():
    # No regression: a fast body-bound approach still flinches through the same
    # chain, exactly as before sound/touch were sourced.
    sim, reactions = _chain(
        _config(position=(8.0, 0.0), velocity=(-4.0, 0.0), with_instinct_thresholds=True)
    )
    sim.tick()
    assert _triggered(reactions, "flinch")
