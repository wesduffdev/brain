"""PerceptionService — turns world-truth into the being's *perceived* view.

The being never reads the true world (rooms, object definitions) directly. This
service is the one seam between them (ADR 0002): given the true Room the being
is in and the catalog of true object definitions, it produces a perceived view —
the objects the being can make out, each with a confidence and the
properties/affordances it perceives. It deliberately drops world-truth the being
has no access to, notably each object's human-facing `developer_label`: the
being knows an object by its properties, not its English name.

Confidence is uniform for now (the room's `base_confidence`); the environment
slice will erode it per object as the room goes dark or loud. An id the room
contains but the catalog has no definition for cannot be perceived and is
omitted.
"""
from __future__ import annotations

from typing import Dict, List, Mapping

from app.domain.object_entity import ObjectEntity
from app.domain.room import Room


class PerceptionService:
    def __init__(self, catalog: Mapping[str, ObjectEntity]):
        self._catalog = dict(catalog)

    def perceive(self, room: Room) -> Dict:
        """The being's perceived view of `room`: the objects it can make out, in
        room order, each with a confidence and the properties/affordances it
        perceives. Never leaks the human-only developer label."""
        objects: List[Dict] = []
        for object_id in room.contains:
            entity = self._catalog.get(object_id)
            if entity is None:
                continue
            objects.append(
                {
                    "objectId": entity.object_id,
                    "confidence": room.base_confidence,
                    "properties": list(entity.properties),
                    "affordances": list(entity.affordances),
                }
            )
        return {"objects": objects}
