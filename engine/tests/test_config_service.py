"""Behaviors of ConfigService construction, and the guarantee that
`with_room_contents` copies the WHOLE config — changing only the room's
contents and never silently dropping a section.

This guards the regression that first bit the demo (ADR 0014's V0-SAFE slice):
`with_room_contents` used a manual, positional copy of every section, so a
newly-added section (outcome_effects) could be forgotten and dropped, and the
being would then run with that section missing. The guard asserts, through the
public accessors, that every section survives the copy unchanged.
"""
from __future__ import annotations

import os

from app.config_service import ConfigService

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _shipped() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def test_with_room_contents_changes_only_the_rooms_contents():
    config = _shipped()
    original_room = config.room()

    focused = config.with_room_contents(["obj_red_ball"])
    focused_room = focused.room()

    # the room now holds exactly the requested object ...
    assert focused_room.contains == ("obj_red_ball",)
    # ... and nothing else about the room itself changed.
    assert focused_room.room_id == original_room.room_id
    assert focused_room.light == original_room.light
    assert focused_room.sound == original_room.sound
    assert focused_room.temperature == original_room.temperature
    assert focused_room.base_confidence == original_room.base_confidence


def test_with_room_contents_preserves_every_config_section():
    config = _shipped()
    focused = config.with_room_contents(["obj_red_ball"])

    # Every config section — beyond the room's contents — is carried through
    # unchanged. If the copy drops any section (the original demo-caught bug),
    # exactly one of these comparisons fails, naming the dropped section.
    assert focused.tick_duration_ms() == config.tick_duration_ms()
    assert focused.need_policies() == config.need_policies()
    assert focused.initial_needs() == config.initial_needs()
    assert focused.emotion_rules() == config.emotion_rules()
    assert focused.default_emotion() == config.default_emotion()
    assert focused.object_catalog() == config.object_catalog()
    assert focused.object_property_vocab() == config.object_property_vocab()
    assert focused.object_action_vocab() == config.object_action_vocab()
    assert focused.environment_policy() == config.environment_policy()
    assert focused.render_hints() == config.render_hints()
    assert focused.command_specs() == config.command_specs()
    assert focused.outcome_labels() == config.outcome_labels()
    assert focused.outcome_context_features() == config.outcome_context_features()
    assert focused.prediction_threshold() == config.prediction_threshold()
    assert focused.prediction_policy() == config.prediction_policy()
    assert focused.outcome_training_params() == config.outcome_training_params()
    assert focused.action_policies() == config.action_policies()
    assert focused.safety_rules() == config.safety_rules()
    assert focused.outcome_effects() == config.outcome_effects()
