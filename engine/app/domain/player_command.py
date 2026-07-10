"""PlayerCommand — a validated inbound player intent.

The renderer's raw `player_command` (ADR 0004) once CommandService has checked it
against the known command set and targets. It is the being's world receiving an
input — e.g. an object being presented for the being to perceive — never a
decision about what the being does; the engine's psychology decides that later.
`target_id` is None for a command that needs no target.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PlayerCommand:
    command: str
    target_id: Optional[str] = None
