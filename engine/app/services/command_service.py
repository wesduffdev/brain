"""CommandService — validates an inbound `player_command` before it can become an
input to the engine (ADR 0004).

The renderer's only outbound message expresses raw player intent. This service is
the gate: it checks the message is a well-formed `player_command`, that its
`command` is in the known v0 vocabulary, and that any required `targetId` names a
known object — rejecting anything unknown or malformed with a CommandError.

It decides NO behavior: an accepted command is returned as a validated
PlayerCommand for the engine's psychology (perception -> decision -> safety) to
act on later, exactly as if the object had appeared any other way. The command
vocabulary lives in `config/commands.yaml`; the known targets are the object
catalog.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from app.domain.player_command import PlayerCommand
from app.policies import CommandSpec

_TYPE = "player_command"


class CommandError(ValueError):
    """An inbound message was not a valid `player_command`: wrong type, unknown
    command, or a missing/unknown required target."""


class CommandService:
    def __init__(self, commands: Mapping[str, CommandSpec], targets: Iterable[str]):
        self._commands = dict(commands)
        self._targets = set(targets)

    def validate(self, message) -> PlayerCommand:
        """Return a validated PlayerCommand for a well-formed, known message, or
        raise CommandError for anything unknown or malformed."""
        if not isinstance(message, Mapping):
            raise CommandError("command must be a player_command object")
        if message.get("type") != _TYPE:
            raise CommandError(f"unexpected message type {message.get('type')!r}")

        name = message.get("command")
        spec = self._commands.get(name)
        if spec is None:
            raise CommandError(f"unknown command {name!r}")

        target = message.get("targetId")
        if spec.requires_target:
            if not target:
                raise CommandError(f"command {name!r} requires a targetId")
            if target not in self._targets:
                raise CommandError(f"unknown target {target!r}")
        else:
            target = None

        return PlayerCommand(command=name, target_id=target)
