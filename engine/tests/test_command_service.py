"""Behaviors of CommandService: validating an inbound `player_command` against
the known command set and object targets (ADR 0004).

Observable through the public `validate()`. It returns a validated PlayerCommand
for a well-formed, known command and raises CommandError for anything unknown or
malformed. It decides NO behavior — a validated command is an input the engine's
psychology consumes later, never a shortcut around it.
"""
from __future__ import annotations

import pytest

from app.config_service import ConfigService
from app.services.command_service import CommandError, CommandService

_COMMANDS = {"commands": {"present_object": {"requires_target": True}}}
_TARGETS = ("obj_red_ball", "obj_soft_blanket")


def _service() -> CommandService:
    specs = ConfigService.from_dict({}, {}, commands=_COMMANDS).command_specs()
    return CommandService(specs, _TARGETS)


def test_a_known_command_with_a_known_target_is_accepted():
    cmd = _service().validate(
        {"type": "player_command", "command": "present_object", "targetId": "obj_red_ball"}
    )

    assert cmd.command == "present_object"
    assert cmd.target_id == "obj_red_ball"


def test_an_unknown_command_is_rejected():
    with pytest.raises(CommandError):
        _service().validate(
            {"type": "player_command", "command": "teleport", "targetId": "obj_red_ball"}
        )


def test_a_command_with_an_unknown_target_is_rejected():
    with pytest.raises(CommandError):
        _service().validate(
            {"type": "player_command", "command": "present_object", "targetId": "obj_dragon"}
        )


def test_a_command_missing_its_required_target_is_rejected():
    with pytest.raises(CommandError):
        _service().validate({"type": "player_command", "command": "present_object"})


def test_a_message_of_the_wrong_type_is_rejected():
    with pytest.raises(CommandError):
        _service().validate(
            {"type": "being_state_update", "command": "present_object", "targetId": "obj_red_ball"}
        )


def test_a_non_object_payload_is_rejected():
    with pytest.raises(CommandError):
        _service().validate("present_object")
