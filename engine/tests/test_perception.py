"""Behaviors: what the being perceives of the objects in its one room.

Perception is the seam between world-truth (rooms, object definitions) and what
the being actually experiences (ADR 0002): every test here asserts on the
*perceived* view exposed through `Simulation.state()`, never on true world
state directly.
"""
from __future__ import annotations

import os

import pytest

from app.config_service import ConfigService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _shipped():
    return Simulation(ConfigService.from_files(_CONFIG_ROOT))


def _perceived_objects(sim):
    return sim.state()["perceived"]["objects"]


def test_being_perceives_objects_in_its_room():
    perceived_ids = {obj["objectId"] for obj in _perceived_objects(_shipped())}
    assert {"obj_red_ball", "obj_soft_blanket", "obj_wooden_block"} <= perceived_ids


def test_perception_confidence_is_reported():
    perceived = _perceived_objects(_shipped())
    assert perceived  # the shipped room is not empty
    for obj in perceived:
        assert 0.0 < obj["confidence"] <= 1.0


def test_perceived_view_hides_the_human_only_developer_label():
    # The being knows an object by its properties, not its English name.
    for obj in _perceived_objects(_shipped()):
        assert "developerLabel" not in obj
        assert "developer_label" not in obj
        assert obj["properties"]  # it does perceive real properties, though


def test_state_gains_perceived_without_dropping_prior_keys():
    state = _shipped().state()
    assert {"beingId", "tick", "needs", "emotion", "perceived"} <= set(state)


def _sim_with_room(base_confidence):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {"rules": [], "default": "calm"}
    rooms = {
        "room": {
            "id": "room_001",
            "base_confidence": base_confidence,
            "contains": ["obj_a", "obj_b"],
        }
    }
    objects = {
        "properties": ["round", "soft"],
        "affordances": ["look"],
        "objects": {
            "obj_a": {"developerLabel": "A", "properties": ["round"], "affordances": ["look"]},
            "obj_b": {"developerLabel": "B", "properties": ["soft"], "affordances": ["look"]},
        },
    }
    return Simulation(ConfigService.from_dict(tick_rates, emotions, rooms=rooms, objects=objects))


def test_perception_confidence_is_config_driven():
    # Same code, a hazier room: retuning perceptual clarity is a config change.
    perceived = _perceived_objects(_sim_with_room(0.4))
    assert perceived
    assert all(obj["confidence"] == 0.4 for obj in perceived)


def test_object_claiming_a_property_outside_the_vocabulary_is_rejected():
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {"rules": [], "default": "calm"}
    rooms = {"room": {"id": "room_001", "contains": ["obj_a"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_a": {"developerLabel": "A", "properties": ["sparkly"], "affordances": ["look"]},
        },
    }
    with pytest.raises(ValueError):
        Simulation(ConfigService.from_dict(tick_rates, emotions, rooms=rooms, objects=objects))
