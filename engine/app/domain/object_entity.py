"""ObjectEntity — a targetable object as world-truth.

The full, true definition of an object: its id, a human-only `developer_label`,
and the properties and affordances it really has. The being learns from
properties and outcomes, not names, so `developer_label` is metadata for humans
and is deliberately never part of what the being perceives (see ADR 0002).
PerceptionService decides which of these facts become perceived, and with what
confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ObjectEntity:
    object_id: str
    developer_label: str
    properties: Tuple[str, ...] = ()
    affordances: Tuple[str, ...] = ()
