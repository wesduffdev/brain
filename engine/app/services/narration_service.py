"""NarrationService — turns a state snapshot into a readable, NON-authoritative
narration (card v9, BRIEF §17; wired to a surface by S1, ADR 0032).

This is the "narrate" half of the language layer. Given a `Simulation.state()`
snapshot, it serializes the being's present situation — the emotion it feels and
the objects it perceives (by their properties, never a developer label, ADR
0002) — into a single present-state FACT-LINE and asks the language model to
phrase it. The narration is a description laid *on top* of the sim: it is derived
strictly from the snapshot it is handed, and it never feeds back — nothing here
mutates the being or the world. It reads a plain dict, so the `Simulation` stays
a black box; running narration over a state leaves that state exactly as it was.

Where `MemorySummaryService` looks back over what the being has DONE, this
describes what IS. `SelfReportService` uses it as the grounded fallback when the
being has no memories yet: asked what it has done, a being that has done nothing
truthfully describes the present instead of inventing a past.

The present fact-line — no `action`, which is how the narrator tells it from a
memory fact — is::

    - felt=scared perceives=hot,hard objects=obj_hot_lamp

Because the line is built only from the passed-in snapshot, the narration
reflects state rather than inventing or overriding it — language sits on top,
never in control.
"""
from __future__ import annotations

from typing import List, Mapping

from app.ports.language_model import LanguageModelPort


class NarrationService:
    def __init__(self, model: LanguageModelPort):
        self._model = model

    def narrate(self, snapshot: Mapping) -> str:
        """Return a readable, non-authoritative narration of ``snapshot``.
        Read-only: derives its prompt from the snapshot and mutates nothing."""
        return self._model.complete(self._prompt(snapshot)).strip()

    @staticmethod
    def _prompt(snapshot: Mapping) -> str:
        emotion = snapshot.get("emotion", "")
        perceived = (snapshot.get("perceived", {}) or {}).get("objects", []) or []

        properties: List[str] = []
        for obj in perceived:
            for prop in (obj.get("properties") or []):
                if prop not in properties:
                    properties.append(str(prop))
        object_ids = ",".join(str(obj.get("objectId")) for obj in perceived)

        return "\n".join(
            [
                "Describe, in one or two plain first-person sentences, what the "
                "being is experiencing right now. Narrate only these facts; do "
                "not invent actions, objects, or feelings.",
                f"- felt={emotion} perceives={','.join(properties)} objects={object_ids}",
            ]
        )
