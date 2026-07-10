"""Room — the local place the being lives in, as world-truth.

A Room is pure structure: an id, the ids of the objects that share it with the
being, how clearly things here can be perceived, and its environmental
conditions (light, sound, temperature). It holds no perception or environment
logic and the being never reads it directly — the PerceptionService turns a Room
into a *perceived* view (ADR 0002) and the EnvironmentService turns its
conditions into pushes on the being's contextual needs (ADR 0006). For v0 there
is exactly one room.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Room:
    """One room. `contains` is the ids of the objects present; `base_confidence`
    (0..1) is how clearly things here can be made out. `light`, `sound`, and
    `temperature` are the room's current environmental conditions — one category
    per dimension (e.g. `dark`, `loud`, `cool`), meaningful only against
    `config/environment.yaml`. Absent (`None`) conditions push nothing.
    """

    room_id: str
    contains: Tuple[str, ...] = ()
    base_confidence: float = 1.0
    light: Optional[str] = None
    sound: Optional[str] = None
    temperature: Optional[str] = None

    def conditions(self) -> dict:
        """The room's current environmental conditions as dimension -> category,
        the shape `EnvironmentPolicy.deltas_for` consumes."""
        return {"light": self.light, "sound": self.sound, "temperature": self.temperature}
