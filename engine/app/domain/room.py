"""Room — the local place the being lives in, as world-truth.

A Room is pure structure: an id, the ids of the objects that share it with the
being, and how clearly things here can be perceived. It holds no perception
logic and the being never reads it directly — the PerceptionService turns a Room
into a *perceived* view (see ADR 0002). For v0 there is exactly one room.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Room:
    """One room. `contains` is the ids of the objects present; `base_confidence`
    (0..1) is how clearly things here can be made out before any environmental
    condition (a dark or loud room — a later slice) erodes recognition.
    """

    room_id: str
    contains: Tuple[str, ...] = ()
    base_confidence: float = 1.0
